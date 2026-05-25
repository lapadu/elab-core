"""This module contains the Socket.IO event handlers."""
from __future__ import annotations

import time
import os
import math
import json
import base64
import shutil
import sqlite3
import logging
import threading
from urllib.parse import urlparse
from typing import TYPE_CHECKING

from flask import request
from flask_socketio import emit, join_room

from ._version import __version__ as ELAB_VERSION
from .config import SESSION_DIR
from .session_utils import list_recorded_sessions

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)

# Per-source clock offset (server_ms - client_ms). Protected by _time_offsets_lock
# because Socket.IO handlers may run in parallel under gevent/threading.
_time_offsets: dict = {}
_time_offsets_lock = threading.Lock()

# Hard cap on a single inbound binary payload (per data_stream frame).
# Protects the dispatcher from a misbehaving ESP32 sending oversized buffers.
# Override via the ELAB_MAX_BINARY_PAYLOAD env var (bytes).
_MAX_BINARY_PAYLOAD = int(os.environ.get('ELAB_MAX_BINARY_PAYLOAD', 64 * 1024))

# Optional comma-separated allow-list of additional plugin origins
# (e.g. "http://internal-cdn.lab:8080"). Provider-supplied URLs that don't
# resolve to either the registering provider's own client IP or one of these
# origins are stripped from the manifest before it reaches the workbench.
_PLUGIN_ORIGIN_ALLOWLIST = {
    o.strip().rstrip('/').lower()
    for o in os.environ.get('ELAB_PLUGIN_ORIGINS', '').split(',')
    if o.strip()
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Return finite float(value) or *default* for invalid input."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return f


def _pick_observed_value(payload: dict) -> float:
    """Pick a representative value from a data_stream payload."""
    val = payload.get('value')
    if isinstance(val, (int, float)) and math.isfinite(float(val)):
        return float(val)
    vals = payload.get('values')
    if isinstance(vals, list):
        for raw in reversed(vals):
            if isinstance(raw, (int, float)) and math.isfinite(float(raw)):
                return float(raw)
    return 0.0


def _get_task_for_source(state: Any, source_id: str) -> dict | None:
    """Return task manifest dict for a source id, if currently registered."""
    with state.atomic_update():
        for provider_list in state.providers.values():
            for provider in provider_list:
                for task in provider.get('tasks', []) or []:
                    if task.get('id') == source_id:
                        return task
    return None


def _resolve_digit_step(accuracy: dict, decoder: Any) -> float:
    """Resolve one-digit step in decoded units for the configured reference."""
    ref = accuracy.get('digitReference', 'ui_lsd')
    if ref == 'ui_lsd':
        return abs(_safe_float(accuracy.get('displayStep'), 0.0))
    if ref == 'explicit_step':
        return abs(_safe_float(accuracy.get('digitStep'), 0.0))
    if ref == 'adc_lsb':
        if decoder and hasattr(decoder, 'adc_lsb_decoded'):
            try:
                return abs(float(decoder.adc_lsb_decoded()))
            except (TypeError, ValueError):
                return 0.0
        return 0.0
    return 0.0


def _uncertainty_from_accuracy(accuracy: dict | None, value: float, decoder: Any) -> dict | None:
    """Build decoded-domain uncertainty from the accuracy object."""
    if not isinstance(accuracy, dict):
        return None

    model = accuracy.get('model')
    if not isinstance(model, str):
        return None

    abs_v = abs(_safe_float(value, 0.0))
    systematic_abs = 0.0
    random_sigma = 0.0

    if model == 'percent_reading':
        systematic_abs = abs_v * _safe_float(accuracy.get('relativePctReading'), 0.0) / 100.0
    elif model == 'absolute':
        systematic_abs = abs(_safe_float(accuracy.get('absoluteOffset'), 0.0))
    elif model == 'percent_reading_plus_absolute':
        systematic_abs = (
            abs_v * _safe_float(accuracy.get('relativePctReading'), 0.0) / 100.0
            + abs(_safe_float(accuracy.get('absoluteOffset'), 0.0))
        )
    elif model == 'percent_reading_plus_digits':
        digit_step = _resolve_digit_step(accuracy, decoder)
        systematic_abs = (
            abs_v * _safe_float(accuracy.get('relativePctReading'), 0.0) / 100.0
            + abs(_safe_float(accuracy.get('digits'), 0.0)) * digit_step
            + abs(_safe_float(accuracy.get('absoluteOffset'), 0.0))
        )
    elif model == 'adc_quantization_only':
        adc_step = _resolve_digit_step({'digitReference': 'adc_lsb'}, decoder)
        random_sigma = adc_step / math.sqrt(12.0) if adc_step > 0.0 else 0.0
    elif model == 'combined':
        sys_part = _uncertainty_from_accuracy(accuracy.get('systematic'), value, decoder) or {}
        rnd_part = _uncertainty_from_accuracy(accuracy.get('random'), value, decoder) or {}
        systematic_abs = abs(_safe_float(sys_part.get('systematicAbs'), 0.0))
        random_sigma = abs(_safe_float(rnd_part.get('randomSigma'), 0.0))
    elif model == 'random_sigma':
        random_sigma = abs(_safe_float(accuracy.get('randomSigma'), 0.0))
    else:
        return None

    return {
        'domain': 'decoded',
        'model': 'combined',
        'systematicAbs': systematic_abs,
        'randomSigma': random_sigma,
        'confidenceK': _safe_float(accuracy.get('confidenceK'), 2.0),
        'source': 'manifest_accuracy',
    }


def _merge_uncertainty(base: dict | None, extra: dict | None) -> dict | None:
    """Merge two uncertainty objects in decoded domain."""
    if not isinstance(base, dict) and not isinstance(extra, dict):
        return None
    if not isinstance(base, dict):
        out = dict(extra)
        out['domain'] = 'decoded'
        return out
    if not isinstance(extra, dict):
        out = dict(base)
        out['domain'] = 'decoded'
        return out

    out = dict(base)
    out['domain'] = 'decoded'
    out['model'] = 'combined'
    out['systematicAbs'] = (
        abs(_safe_float(base.get('systematicAbs'), 0.0))
        + abs(_safe_float(extra.get('systematicAbs'), 0.0))
    )
    out['randomSigma'] = math.sqrt(
        _safe_float(base.get('randomSigma'), 0.0) ** 2
        + _safe_float(extra.get('randomSigma'), 0.0) ** 2
    )
    out['confidenceK'] = _safe_float(base.get('confidenceK'), _safe_float(extra.get('confidenceK'), 2.0))
    return out


def _is_plugin_url_allowed(url: str, client_ip: str) -> bool:
    """Return True if *url* may be loaded into the workbench.

    The plugin script must come from either the provider's own client IP or
    from an explicitly whitelisted origin. This stops a hijacked manifest
    from pointing the browser at an arbitrary attacker host.
    """
    if not isinstance(url, str) or not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ('http', 'https'):
        return False
    if not parsed.hostname:
        return False
    if client_ip and parsed.hostname.lower() == client_ip.lower():
        return True
    origin = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        origin = f"{origin}:{parsed.port}"
    return origin.lower() in _PLUGIN_ORIGIN_ALLOWLIST


def _sanitize_plugin_urls(manifest: dict, client_ip: str) -> None:
    """Strip ui.url/ui.integrity from any task whose URL is not allow-listed.

    Mutates *manifest* in place.
    """
    for task in manifest.get('tasks', []) or []:
        ui = task.get('ui') if isinstance(task, dict) else None
        if not isinstance(ui, dict):
            continue
        url = ui.get('url')
        if not url:
            continue
        if not _is_plugin_url_allowed(url, client_ip):
            logger.warning(
                "Stripped untrusted plugin URL %s from task %s (client_ip=%s)",
                url, task.get('id'), client_ip,
            )
            ui.pop('url', None)
            ui.pop('integrity', None)
            # Fall back to generic UI so the workbench still renders something.
            ui['mode'] = 'generic'


def _drop_time_offsets_for(source_ids) -> None:
    """Remove cached offsets for a set of source ids (called on disconnect)."""
    if not source_ids:
        return
    with _time_offsets_lock:
        for sid in source_ids:
            _time_offsets.pop(sid, None)


def _get_offset(source_id: str, client_ts_ms: float, now_ms: float) -> float:
    """Return a stable client->server clock offset; recompute if it drifts."""
    with _time_offsets_lock:
        offset = _time_offsets.get(source_id)
        if offset is None or abs((client_ts_ms + offset) - now_ms) > 2000:
            offset = now_ms - client_ts_ms
            _time_offsets[source_id] = offset
        return offset


# pylint: disable=too-many-locals, too-many-statements, C0301
def register_socket_handlers(socketio, state, recorder, replayer, client_manager):
    """Registers all Socket.IO event handlers."""
    @socketio.on('connect')
    def handle_connect():
        """Handles a new Socket.IO client connection.

        Logs the connection and emits the current session status to the client.
        """
        client_id: str = request.sid  # type: ignore[attr-defined]
        logger.debug("🔌 Client connected: %s", client_id)
        emit('connection_established', {
            'client_id': client_id,
            'server_version': ELAB_VERSION,
            'timestamp': time.time(),
            'session_active': state.recording,
            'session_id': state.current_session_id
        })

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handles client disconnection.

        If a hardware provider disconnects, it's removed from the state and UI clients are notified.
        If a UI client disconnects, it's removed from the clients list.
        """
        sid: str = request.sid  # type: ignore[attr-defined]
        if sid in state.providers:
            provider_list = state.providers.get(sid, [])
            # Collect every source id that belonged to this provider so we can
            # drop their cached time offsets and avoid an unbounded memory leak.
            stale_source_ids = []
            for provider in provider_list:
                pid = provider.get('id')
                if pid:
                    stale_source_ids.append(pid)
                for task in provider.get('tasks', []) or []:
                    tid = task.get('id')
                    if tid:
                        stale_source_ids.append(tid)

            state.remove_provider(sid)
            _drop_time_offsets_for(stale_source_ids)

            for provider in provider_list:
                socketio.emit('provider_offline', {
                    'provider_id': provider.get('id'),
                    'reason': 'disconnect',
                    'timestamp': time.time()
                }, room='ui_clients')
            socketio.emit('available_providers', {
                'providers': state.get_providers_list(),
                'timestamp': time.time()
            }, room='ui_clients')
        if sid in state.clients:
            client_info = state.clients.pop(sid)
            logger.debug("Client disconnected: %s (Type: %s)",
                        sid, client_info.get('type'))

            # If this was the last UI client, the dispatcher no longer has
            # anyone observing the slot grid. Clear the slot assignments so
            # the next UI session starts from a clean state instead of
            # tripping group-exclusivity checks against ghost assignments.
            remaining_ui = sum(
                1 for info in state.clients.values()
                if info.get('type') == 'ui'
            )
            if remaining_ui == 0 and state.active_tasks_by_slot:
                with state.atomic_update():
                    cleared = dict(state.active_tasks_by_slot)
                    state.active_tasks_by_slot.clear()
                logger.info(
                    "🧹 Last UI client disconnected; cleared %d slot assignment(s): %s",
                    len(cleared), list(cleared.values()),
                )

    @socketio.on('register_client')
    def handle_register_client(_data):
        """Registers a new UI client.

        Joins the client to the 'ui_clients' room and sends the current system state,
        including available providers, scripts, and session replay status.
        """
        client_id: str = request.sid  # type: ignore[attr-defined]
        join_room('ui_clients')
        state.clients[client_id] = {'type': 'ui', 'connected_at': time.time()}
        logger.debug("✅ Client registered: %s", client_id)
        emit('available_providers', {'providers': state.get_providers_list()})
        emit('available_scripts', client_manager.scan_scripts())
        # Sync current slot assignments so a newly connected UI tab matches
        # the dispatcher's view of the world.
        with state.atomic_update():
            active_snapshot = dict(state.active_tasks_by_slot)
        if active_snapshot:
            emit('active_tasks_snapshot', {'slots': active_snapshot})
        if replayer.running:
            emit(
                'replay_status',
                {
                    'state': 'paused' if replayer.paused else 'playing',
                    'session_id': replayer.active_session_path,
                },
            )

    @socketio.on('register_provider')
    def handle_register_provider(manifest):
        """Registers a hardware provider and its tasks.

        Args:
            manifest (dict): Validated manifest according to ManifestSchema.json.

        Emits:
            'registration_error' if validation fails.
            'provider_registered' and 'available_providers' on success.
        """
        # Defensive shape check first - never trust client structure.
        if not isinstance(manifest, dict):
            logger.warning(
                "register_provider: payload is not a dict (%s) from %s",
                type(manifest).__name__, request.sid,  # type: ignore[attr-defined]
            )
            emit('registration_error', {'message': 'Manifest must be a JSON object'})
            return

        provider_id: str = request.sid  # type: ignore[attr-defined]
        manifest_id = manifest.get('id')
        if not isinstance(manifest_id, str) or not manifest_id:
            logger.warning("register_provider: missing/invalid 'id' from %s", provider_id)
            emit('registration_error', {'message': "Manifest field 'id' missing or invalid"})
            return

        # Store the provider's current client IP in the manifest.
        client_ip = request.remote_addr or 'unknown'
        manifest['client_ip'] = client_ip

        # Sanitize plugin URLs against allow-list before they propagate to the UI.
        _sanitize_plugin_urls(manifest, client_ip)

        ghost_sids = []

        # Detect duplicates: the same manifest ID from another session is renamed,
        # while the same ID from the same session is treated as a re-registration.
        with state.atomic_update():
            # Count how often the same base ID already exists so duplicates can
            # be numbered deterministically across sessions.
            existing_count = 0
            is_reregister = False
            for sid, p_list in state.providers.items():
                for existing in p_list:
                    if existing.get('id') == manifest_id:
                        if sid == provider_id:
                            is_reregister = True
                        elif existing.get('client_ip') == client_ip:
                            # Same ID and same IP usually means the device restarted
                            # without performing a clean disconnect.
                            ghost_sids.append(sid)
                        else:
                            existing_count += 1

            # If this is a duplicate from another session, assign a unique
            # suffix to the provider and all of its task IDs.
            if existing_count > 0 and not is_reregister:
                suffix = f"_{existing_count + 1:03d}"
                manifest['id'] = f"{manifest_id}{suffix}"
                manifest['name'] = f"{manifest.get('name', '')}{suffix}"
                # Update task IDs as well so every task remains unique.
                for task in manifest.get('tasks', []):
                    task['id'] = f"{task['id']}{suffix}"
                logger.warning(
                    "🔢 Duplicate provider detected, renaming to: %s [%s]",
                    manifest.get('name'), manifest.get('id'),
                )
            elif is_reregister:
                # Replace the previous registration from the same session.
                state.providers[provider_id] = [
                    p for p in state.providers.get(provider_id, [])
                    if p['id'] != manifest_id
                ]
                logger.info(
                    "🔄 Manifest refreshed via re-registration: %s [%s] from SID %s",
                    manifest.get('name'),
                    manifest_id,
                    provider_id,
                )

        # Disconnect stale ghost sessions outside the state lock.
        for ghost_sid in ghost_sids:
            logger.warning("👻 Ghost session detected for %s from IP %s. Disconnecting old SID %s", manifest_id, client_ip, ghost_sid)
            try:
                socketio.server.disconnect(ghost_sid)
            except (OSError, RuntimeError, ValueError) as e:
                logger.error("Could not disconnect ghost session %s: %s", ghost_sid, e)

        if not state.add_provider(provider_id, manifest):
            emit('registration_error', {'message': 'Invalid manifest'})
            return

        # Apply stored configuration (alias, color) from the config store
        # for providers that do NOT self-persist.
        state.apply_stored_config(manifest)

        logger.info(
            "🔧 Provider registered: %s [%s]",
            manifest.get('name'),
            manifest.get('id'),
        )
        socketio.emit('provider_registered', {
                      'provider': manifest}, room='ui_clients')
        socketio.emit(
            'available_providers',
            {'providers': state.get_providers_list()},
            room='ui_clients',
        )

    @socketio.on('data_stream')
    def handle_data_stream(payload):
        """Handles incoming measurement data from a provider.

        Applies decoding if configured, writes the data to the current recording session,
        and broadcasts it to all UI clients.

        Args:
            payload (dict): Must contain 'sourceId' and either 'value', 'raw_bytes',
                            'binary_payload', or 'binary_payload_b64'.
        """
        # Defensive shape check - clients can send anything.
        if not isinstance(payload, dict):
            return

        # Backward compatibility: accept both sourceId (canonical) and source_id.
        source_id = payload.get('sourceId') or payload.get('source_id')
        if not isinstance(source_id, str) or not source_id:
            return

        # Normalize for downstream consumers and recorded payload shape.
        payload['sourceId'] = source_id
        payload.pop('source_id', None)

        now_ms = time.time() * 1000.0
        distribution = payload.get('distribution')

        # Normalize client-local timestamps to server wall-clock.
        # This keeps recorded sessions consistent even if devices send millis() values.
        # A stable offset per source prevents jitter in continuous distributions.
        if distribution == 'linear':
            start_time = payload.get('startTime')
            end_time = payload.get('endTime')
            if (
                isinstance(start_time, (int, float))
                and isinstance(end_time, (int, float))
                and math.isfinite(float(start_time))
                and math.isfinite(float(end_time))
            ):
                end_f = float(end_time)
                if end_f < 1e11:
                    offset = _get_offset(source_id, end_f, now_ms)
                    payload['startTime'] = float(start_time) + offset
                    payload['endTime'] = end_f + offset
        else:
            ts = payload.get('timestamp')
            if isinstance(ts, (int, float)) and math.isfinite(float(ts)) and float(ts) < 1e11:
                offset = _get_offset(source_id, float(ts), now_ms)
                payload['timestamp'] = float(ts) + offset

            ts_array = payload.get('timestamps')
            if isinstance(ts_array, list) and ts_array:
                numeric = [
                    t for t in ts_array
                    if isinstance(t, (int, float)) and math.isfinite(float(t))
                ]
                if len(numeric) == len(ts_array):
                    first_ts = float(numeric[0])
                    if first_ts < 1e11:
                        offset = _get_offset(source_id, first_ts, now_ms)
                        payload['timestamps'] = [float(t) + offset for t in numeric]
                        payload['timestamp'] = payload['timestamps'][0]

        # Apply an optional decoder before the payload reaches the UI.
        decoder = state.decoders.get(source_id)

        # Support multiple binary payload formats, for example from the ESP32.
        binary_data = None
        if 'raw_bytes' in payload:
            # Byte buffer sent directly as a JSON integer array.
            raw = payload.pop('raw_bytes', None)
            if isinstance(raw, (list, tuple)) and len(raw) > _MAX_BINARY_PAYLOAD:
                logger.warning(
                    "raw_bytes from %s exceeds limit (%d > %d), dropping frame.",
                    source_id, len(raw), _MAX_BINARY_PAYLOAD,
                )
                return
            try:
                binary_data = bytes(raw) if raw is not None else None
            except (TypeError, ValueError) as e:
                logger.error("raw_bytes decode error for %s: %s", source_id, e)
        elif 'binary_payload' in payload:
            binary_data = payload.pop('binary_payload', None)
            if isinstance(binary_data, (bytes, bytearray)) and len(binary_data) > _MAX_BINARY_PAYLOAD:
                logger.warning(
                    "binary_payload from %s exceeds limit (%d > %d), dropping frame.",
                    source_id, len(binary_data), _MAX_BINARY_PAYLOAD,
                )
                return
        elif 'binary_payload_b64' in payload:
            b64 = payload.pop('binary_payload_b64', None)
            # base64 expands ~4/3; cap the encoded length too.
            if isinstance(b64, str) and len(b64) > _MAX_BINARY_PAYLOAD * 2:
                logger.warning(
                    "binary_payload_b64 from %s exceeds limit (%d chars), dropping frame.",
                    source_id, len(b64),
                )
                return
            try:
                binary_data = base64.b64decode(b64) if b64 else None
                if binary_data and len(binary_data) > _MAX_BINARY_PAYLOAD:
                    logger.warning(
                        "decoded binary_payload_b64 from %s exceeds limit (%d > %d), dropping frame.",
                        source_id, len(binary_data), _MAX_BINARY_PAYLOAD,
                    )
                    return
            except (TypeError, ValueError) as e:
                logger.error("Base64 decode error for %s: %s", source_id, e)

        if decoder and binary_data:
            try:
                # Decode the byte payload into normalized float values.
                decoded_floats = decoder.decode(binary_data)

                # Rewrite the payload as if the client had sent floats directly.
                payload['values'] = decoded_floats
                payload['value'] = decoded_floats[-1] if decoded_floats else 0

                # If provider supplied raw-domain uncertainty, map it through
                # the decoder transfer function into decoded units.
                raw_unc = payload.get('uncertainty')
                if isinstance(raw_unc, dict) and hasattr(decoder, 'map_uncertainty'):
                    mapped_unc = decoder.map_uncertainty(raw_unc)
                    if isinstance(mapped_unc, dict):
                        payload['uncertainty'] = mapped_unc

            except (TypeError, ValueError, OSError, RuntimeError) as e:
                logger.error("Error decoding payload for %s: %s", source_id, e)
                return
        # Decoder step finished.

        # Enrich/derive uncertainty from manifest-level accuracy specification.
        task = _get_task_for_source(state, source_id)
        accuracy = None
        if isinstance(task, dict):
            cfg = task.get('config')
            if isinstance(cfg, dict):
                accuracy = cfg.get('accuracy')
        observed_value = _pick_observed_value(payload)
        derived_unc = _uncertainty_from_accuracy(accuracy, observed_value, decoder)
        payload_unc = payload.get('uncertainty') if isinstance(payload.get('uncertainty'), dict) else None
        merged_unc = _merge_uncertainty(payload_unc, derived_unc)
        if merged_unc is not None:
            payload['uncertainty'] = merged_unc

        # --- Selective Recording ---
        is_task_active = False
        with state.atomic_update():
            # Check if the sourceId corresponds to an active task
            # It could be the main task ID or an original ID for recorded tasks
            active_ids = list(state.active_tasks_by_slot.values())
            if source_id in active_ids:
                is_task_active = True
        if state.recording and is_task_active:
            binary_blob = None
            db_payload = payload
            if 'image_b64' in payload:
                try:
                    image_data = payload['image_b64']
                    if ',' in image_data:
                        _, encoded = image_data.split(",", 1)
                    else:
                        encoded = image_data
                    binary_blob = base64.b64decode(encoded)
                    db_payload = payload.copy()
                    del db_payload['image_b64']
                    db_payload['has_binary'] = True
                    db_payload['binary_size'] = len(binary_blob)
                except (TypeError, ValueError) as e:
                    logger.error("Image decode error in stream: %s", e)

            recorder.write({
                'type': 'DATA_STREAM',
                'payload': db_payload
            }, binary_blob=binary_blob)

        # Forward all data to UI clients, regardless of recording state
        socketio.emit('data_stream', payload, room='ui_clients')

    @socketio.on('task_request')
    def handle_task_request(request_data):
        """Forwards a task request to a specific provider.

        Args:
            request_data (dict): Must contain 'provider_id'.
        """
        # This is now mostly for virtual tasks or specific one-off commands
        provider_id = request_data.get('provider_id')
        provider_sid = state.find_provider_sid(provider_id)
        if provider_sid:
            socketio.emit('execute_task', request_data, room=provider_sid)
        else:
            logger.warning("Provider %s not found for task request", provider_id)

    @socketio.on('task_assigned')
    def handle_task_assigned(data):
        """Registers a task as active when dropped into a UI slot.

        Args:
            data (dict): Contains 'slot' index and 'taskId'.

        Emits:
            'task_rejected' if the task group exclusivity rule is violated.
        """
        slot = data.get('slot')
        task_id = data.get('taskId')
        if slot is not None and task_id:
            # Enforce task group exclusivity before accepting the assignment.
            allowed, reason = state.check_group_exclusivity(task_id)
            if not allowed:
                logger.warning("Task assignment rejected: %s", reason)
                emit('task_rejected', {
                    'taskId': task_id,
                    'slot': slot,
                    'reason': reason
                })
                return

            with state.atomic_update():
                state.active_tasks_by_slot[slot] = task_id

            # Add the task manifest to the active recording as soon as it is assigned.
            recorder.add_manifest_if_recording(task_id)

            logger.debug("Task %s assigned to slot %s. Active tasks: %s",
                        task_id, slot, state.active_tasks_by_slot)

    @socketio.on('task_unassigned')
    def handle_task_unassigned(data):
        """Removes a task from the active state when removed from a UI slot.

        Args:
            data (dict): Contains 'slot' index.
        """
        slot = data.get('slot')
        if slot is not None and slot in state.active_tasks_by_slot:
            with state.atomic_update():
                removed_task_id = state.active_tasks_by_slot.pop(slot, None)
            if removed_task_id:
                logger.debug("Task %s unassigned from slot %s. Active tasks: %s",
                            removed_task_id, slot, state.active_tasks_by_slot)

    @socketio.on('cmd_control')
    def handle_control_command(cmd):
        """Forwards a control command to a specific provider.

        Args:
            cmd (dict): Must contain 'provider_id' (e.g. 'prov_esp32_voltmeter').
        """
        provider_id_with_prefix = cmd.get('provider_id')
        if not provider_id_with_prefix:
            return

        provider_id = provider_id_with_prefix.replace('prov_', '')

        if state.recording:
            recorder.write({'type': 'CONTROL_CMD', 'payload': cmd})

        sid = state.find_provider_sid(provider_id)
        if sid:
            socketio.emit('execute_command', cmd, room=sid)
        else:
            # Maybe it's a virtual provider on the client, broadcast to all UIs
            logger.warning("SID for %s not found, broadcasting to UIs", provider_id)
            socketio.emit('execute_command', cmd, room='ui_clients')

    @socketio.on('provider_meta_changed')
    def handle_provider_meta_changed(data):
        """A provider has changed its own metadata, update state and broadcast to all UIs."""
        task_id = data.get('task_id')
        changes = data.get('changes', {})
        if task_id and changes:
            state.update_task_meta(task_id, changes)
        logger.debug("📢 Provider meta changed, broadcasting to UIs: %s", data)
        socketio.emit('provider_meta_changed', data, room='ui_clients')

    # --- REPLAY & SESSION MANAGEMENT ---
    @socketio.on('session_start')
    def cmd_session_start(data):
        """Starts recording a new data session.

        Args:
            data (dict): Contains 'session_id'.

        Emits:
            'session_start_result' with success/failure status.
        """
        if replayer.running:
            replayer.control('stop')
            time.sleep(0.2)
        result = recorder.start(data.get('session_id'))
        emit('session_start_result', result)

    @socketio.on('session_stop')
    def cmd_session_stop(_data):
        """Stops the currently active recording session.

        Emits:
            'session_stop_result' with success/failure status.
        """
        result = recorder.stop()
        emit('session_stop_result', result)

    @socketio.on('get_sessions')
    def on_get_sessions():
        """Retrieves a list of available recorded sessions.

        Emits:
            'session_list' with an array of session names.
        """
        sessions = list_recorded_sessions(SESSION_DIR)
        emit('session_list', sessions)

    @socketio.on('replay_load')
    def on_replay_load(data):
        """Loads a recorded session for playback.

        Args:
            data (dict): Contains 'session_id'.

        Emits:
            'replay_loaded' with the session metadata and total duration.
        """
        session_id = data.get('session_id')
        if state.recording:
            cmd_session_stop({})
            time.sleep(0.2)
        success, msg = replayer.load_session(session_id)
        duration = 0

        if success:
            db_path = os.path.join(SESSION_DIR, session_id, "session.sqlite")
            try:
                conn = sqlite3.connect(db_path)
                conn.execute("PRAGMA journal_mode=WAL;")
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT MIN(event_time_ms), MAX(event_time_ms) FROM session_log WHERE type = 'DATA_STREAM'")
                result = cursor.fetchone()
                if result and result[0] is not None and result[1] is not None:
                    duration = result[1] - result[0]
                conn.close()
            except sqlite3.Error as e:
                logger.error(
                    "Could not read session duration for %s: %s", session_id, e)

        emit('replay_loaded', {
            'success': success,
            'message': msg,
            'session_id': session_id,
            'duration': duration
        })

    @socketio.on('replay_action')
    def on_replay_action(data):
        """Controls the session replayer.

        Args:
            data (dict): Contains 'action' ('play', 'pause', 'stop', 'seek', 'unload', 'speed')
                         and an optional 'value'.
        """
        if not isinstance(data, dict):
            return
        action = data.get('action')
        value = data.get('value')
        if action in ('play', 'pause', 'stop', 'unload'):
            replayer.control(action, value)
        elif action == 'seek':
            try:
                seek_val = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                logger.warning("replay_action seek: invalid value %r", value)
                return
            if not math.isfinite(seek_val) or seek_val < 0:
                logger.warning("replay_action seek: out-of-range value %r", value)
                return
            replayer.control(action, seek_val)
        elif action == 'speed':
            try:
                speed = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                logger.warning("replay_action speed: invalid value %r", value)
                return
            # Clamp to a sane range so a stray UI slider can't run replay at NaN/inf.
            if not math.isfinite(speed):
                return
            replayer.speed = max(0.1, min(speed, 10.0))

    @socketio.on('delete_session')
    def on_delete_session(data):
        """Deletes a recorded session from the disk.

        Args:
            data (dict): Contains 'session_id'.
        """
        session_id = data.get('session_id')
        if not session_id:
            return

        # --- Security Check ---
        # Ensure the session_id is a simple directory name, no '..' or '/' or '\'
        if '..' in session_id or '/' in session_id or '\\' in session_id:
            logger.warning(
                "Attempted path traversal on session delete: %s", session_id)
            return

        session_path = os.path.join(SESSION_DIR, session_id)
        if not os.path.isdir(session_path):
            logger.warning(
                "Attempted to delete non-existent session: %s", session_id)
            return

        try:
            shutil.rmtree(session_path)
            logger.info("🗑️ Deleted session: %s", session_id)
            # Refresh the list for all clients
            on_get_sessions()
        except OSError as e:
            logger.error("Error deleting session %s: %s", session_id, e)

    @socketio.on('get_recorded_providers')
    def on_get_recorded_providers(data):
        """Retrieves the provider manifests for a recorded session.

        Args:
            data (dict): Contains 'session_id'.

        Emits:
            'recorded_providers' with a list of manifests modified for replay mode.
        """
        session_id = data.get('session_id')
        db_path = os.path.join(SESSION_DIR, session_id, "session.sqlite")
        if not os.path.exists(db_path):
            emit('recorded_providers', {'providers': []})
            return

        providers = []
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            cursor = conn.cursor()

            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='manifests'")
            if cursor.fetchone() is None:
                logger.warning(
                    "Manifests table not found in %s. Cannot load rec_tasks.",
                    session_id,
                )
                emit('recorded_providers', {'providers': []})
                conn.close()
                return

            # Only include tasks with recorded data in the replay list.
            cursor.execute(
                "SELECT DISTINCT source_id FROM session_log WHERE type = 'DATA_STREAM'")
            recorded_task_ids = {row[0] for row in cursor.fetchall()}
            if not recorded_task_ids:
                logger.warning(
                    "No data streams found in session %s. No rec_tasks will be generated.", session_id)

            cursor.execute("SELECT manifest FROM manifests")
            rows = cursor.fetchall()
            for row in rows:
                manifest = json.loads(row[0])
                original_provider_id = manifest.get('id')

                rec_provider = manifest.copy()

                # Avoid adding the recorded prefix twice.
                rec_provider_id = original_provider_id
                if not original_provider_id.startswith('rec_'):
                    rec_provider_id = f"rec_{original_provider_id}"
                rec_provider['name'] = f"[REC] {manifest.get('name', 'Unknown')}"
                rec_provider['id'] = rec_provider_id
                rec_provider['originalId'] = original_provider_id
                rec_provider['is_recorded'] = True

                # Preserve the provider-level UI but drop remote URLs that may
                # no longer be reachable during replay.
                prov_ui = dict(manifest.get('ui') or {})
                if prov_ui.get('mode') == 'custom':
                    prov_ui['mode'] = 'generic'
                    prov_ui.pop('url', None)
                    prov_ui.pop('integrity', None)
                rec_provider['ui'] = prov_ui

                if 'tasks' in rec_provider and isinstance(rec_provider['tasks'], list):
                    rec_provider['tasks'] = []
                    for task in manifest.get('tasks', []):
                        original_task_id = task.get('id')

                        if original_task_id not in recorded_task_ids:
                            continue

                        rec_task = task.copy()

                        rec_task_id = original_task_id
                        if not original_task_id.startswith('rec_'):
                            rec_task_id = f"rec_{original_task_id}"

                        rec_task['id'] = rec_task_id
                        rec_task['originalId'] = original_task_id
                        rec_task['name'] = f"[REC] {task.get('name', 'Unknown Task')}"
                        rec_task['is_recorded'] = True

                        # Keep the original task UI (views / template) so the
                        # recorded widget looks like the live one. Remote
                        # custom widgets are downgraded to generic because the
                        # provider URL may be unavailable during replay.
                        task_ui = dict(task.get('ui') or {})
                        if task_ui.get('mode') == 'custom':
                            task_ui['mode'] = 'generic'
                            task_ui.pop('url', None)
                            task_ui.pop('integrity', None)
                        rec_task['ui'] = task_ui
                        rec_provider['tasks'].append(rec_task)

                if rec_provider.get('tasks'):
                    providers.append(rec_provider)

        except sqlite3.Error as e:
            logger.error(
                "Error reading recorded providers from '%s': %s", session_id, e)
            providers = []
        finally:
            if 'conn' in locals() and conn:
                conn.close()

        logger.debug(
            "Emitting %d recorded providers for session %s.",
            len(providers),
            session_id,
        )
        emit('recorded_providers', {'providers': providers})

    # --- PROCESS MANAGEMENT ---
    @socketio.on('get_available_scripts')
    def handle_get_scripts():
        """Scans the clients directory for available Python scripts.

        Emits:
            'available_scripts' with an array of filenames.
        """
        emit('available_scripts', client_manager.scan_scripts())

    @socketio.on('start_client_script')
    def handle_start_script(data):
        """Starts a Python client script in a new process.

        Args:
            data (dict): Contains 'filename'.
        """
        filename = data.get('filename')
        success, msg = client_manager.start_script(filename)
        if success:
            emit('available_scripts',
                 client_manager.scan_scripts(), broadcast=True)
        else:
            logger.error("Failed to start script %s: %s", filename, msg)

    @socketio.on('stop_client_script')
    def handle_stop_script(data):
        """Stops a running Python client script.

        Args:
            data (dict): Contains 'filename'.
        """
        filename = data.get('filename')
        client_manager.stop_script(filename)
        emit('available_scripts', client_manager.scan_scripts(), broadcast=True)

    # --- TASK CONFIGURATION (ALIAS & COLOR) ---
    @socketio.on('set_task_alias')
    def handle_set_task_alias(data):
        """Sets a user-defined alias for a task.

        Args:
            data (dict): Contains 'task_id' and 'alias' (string or null to clear).

        Emits:
            'task_config_changed' to all UI clients with the updated config.
        """
        if not isinstance(data, dict):
            return
        task_id = data.get('task_id')
        alias = data.get('alias')
        if not isinstance(task_id, str) or not task_id:
            return
        if alias is not None and not isinstance(alias, str):
            return

        if state.set_task_alias(task_id, alias):
            socketio.emit('task_config_changed', {
                'task_id': task_id,
                'changes': {'alias': alias},
                'timestamp': time.time()
            }, room='ui_clients')
            logger.debug("Alias for task %s set to %r", task_id, alias)

    @socketio.on('set_task_color')
    def handle_set_task_color(data):
        """Sets a color override for a task, with upstream propagation.

        Args:
            data (dict): Contains 'task_id', 'color' (hex string or null),
                         and optionally 'propagate' (bool, default true).

        Color propagation rules:
        - A color change at a sink propagates upstream to the nearest source.
        - MATH modules act as color boundaries; propagation stops there.
        - The frontend is responsible for resolving the signal chain and
          applying propagation visually.

        Emits:
            'task_config_changed' to all UI clients with the updated config.
        """
        if not isinstance(data, dict):
            return
        task_id = data.get('task_id')
        color = data.get('color')
        if not isinstance(task_id, str) or not task_id:
            return
        if color is not None and not isinstance(color, str):
            return

        if state.set_task_color(task_id, color):
            socketio.emit('task_config_changed', {
                'task_id': task_id,
                'changes': {'color': color},
                'propagate': data.get('propagate', True),
                'timestamp': time.time()
            }, room='ui_clients')
            logger.debug("Color for task %s set to %r", task_id, color)

    @socketio.on('get_task_config')
    def handle_get_task_config(data):
        """Returns the stored configuration (alias, color) for a task.

        Args:
            data (dict): Contains 'task_id'.

        Emits:
            'task_config' with the stored config dict.
        """
        if not isinstance(data, dict):
            return
        task_id = data.get('task_id')
        if not isinstance(task_id, str) or not task_id:
            return
        config = {}
        if state.config_store:
            config = state.config_store.get_task_config(task_id)
        emit('task_config', {'task_id': task_id, 'config': config})
