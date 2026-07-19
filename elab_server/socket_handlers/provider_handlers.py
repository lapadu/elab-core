"""Socket.IO handlers for the provider data path and task lifecycle.

Handles: ``data_stream``, ``task_request``, ``task_assigned``,
``task_unassigned``, ``cmd_control``, ``provider_meta_changed``,
``set_task_alias``, ``set_task_color``, ``get_task_config``.

The provider-config events (alias / color / get_task_config) live here
because they are conceptually part of "what a provider/task looks like",
not session bookkeeping.
"""
from __future__ import annotations

import base64
import logging
import math
import threading
import time

from flask import request
from flask_socketio import emit

from ..auth import is_auth_required, verify_payload
from ._helpers import (
    _MAX_BINARY_PAYLOAD,
    _get_offset,
    _get_task_for_source,
    _merge_uncertainty,
    _pick_observed_value,
    _uncertainty_from_accuracy,
)


logger = logging.getLogger(__name__)


# Per source→actuator route: monotonic timestamp of the last forwarded command.
# Used to honour an actuator's declared ``maxRateHz`` so constrained targets
# (e.g. an ESP32) are not flooded by a generator's full-rate chunk stream.
_actuator_route_ts: dict[tuple[str, str], float] = {}
_actuator_route_lock = threading.Lock()


def _actuator_delivery_prefs(task: dict | None) -> tuple[bool, float]:
    """Derive delivery constraints from an actuator task's config.

    Returns ``(scalar_only, min_interval_s)``:

    - ``scalar_only``: the actuator declared ``accepts`` without any array/stream
      capability (e.g. ``["scalar"]``), so it cannot process ``values`` arrays.
    - ``min_interval_s``: ``1 / maxRateHz`` when a positive ``maxRateHz`` is
      declared, else ``0`` (no throttling).

    Actuators that declare neither field keep the previous behaviour (full
    payload, no throttle) for backward compatibility.
    """
    scalar_only = False
    min_interval = 0.0
    if isinstance(task, dict):
        config = task.get('config') or {}
        accepts = config.get('accepts')
        if isinstance(accepts, list) and accepts:
            lowered = {str(a).lower() for a in accepts}
            scalar_only = not lowered & {'array', 'values', 'stream'}
        rate = config.get('maxRateHz')
        try:
            rate_hz = float(rate)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            rate_hz = 0.0
        if rate_hz > 0.0:
            min_interval = 1.0 / rate_hz
    return scalar_only, min_interval


def _resolve_actuator_task(state, actuator_id: str) -> dict | None:
    """Resolve the actuator task carrying the delivery config.

    ``actuator_id`` from an ``actuator_link`` is usually the provider manifest
    id (the ``prov_`` prefix stripped), while the ``accepts`` / ``maxRateHz``
    config lives on a task inside that manifest. Match a task by id first, then
    fall back to the provider's sole/first task.
    """
    manifest = state.get_provider_manifest(actuator_id)
    if not isinstance(manifest, dict):
        return None
    tasks = manifest.get('tasks') or []
    for task in tasks:
        if isinstance(task, dict) and task.get('id') == actuator_id:
            return task
    for task in tasks:
        if isinstance(task, dict):
            return task
    return None


def _route_to_actuators(socketio, state, source_id, payload):
    """Deliver a source's stream directly to any linked actuator providers.

    This is the server-side source→actuator route: instead of the UI polling a
    stream and echoing scalar control commands back, the dispatcher forwards the
    payload straight to each linked actuator's session.

    Each actuator's manifest config governs what it receives: ``maxRateHz`` caps
    the forward rate, and ``accepts`` (when it lists no array capability)
    down-converts the chunk to a single scalar. This keeps low-power actuators
    from drowning in a high-rate generator stream (which otherwise saturates the
    device's receive loop and triggers a watchdog reset).
    """
    targets = state.get_actuator_links(source_id)
    if not targets:
        return

    now = time.monotonic()
    for actuator_id in targets:
        sid = state.find_provider_sid(actuator_id)
        if not sid:
            continue

        scalar_only, min_interval = _actuator_delivery_prefs(
            _resolve_actuator_task(state, actuator_id)
        )

        # Rate-limit per route to the actuator's declared maxRateHz.
        if min_interval > 0.0:
            key = (source_id, actuator_id)
            with _actuator_route_lock:
                last = _actuator_route_ts.get(key, 0.0)
                if now - last < min_interval:
                    continue
                _actuator_route_ts[key] = now

        if scalar_only:
            # Actuator can't handle arrays: send the chunk's representative
            # scalar (last finite sample) only.
            command_payload = {
                'value': _pick_observed_value(payload),
                'timestamp': payload.get('timestamp'),
            }
        else:
            command_payload = {
                'value': payload.get('value'),
                'values': payload.get('values'),
                'startTime': payload.get('startTime'),
                'endTime': payload.get('endTime'),
                'timestamp': payload.get('timestamp'),
            }

        socketio.emit('execute_command', {
            'provider_id': f'prov_{actuator_id}',
            'command': {'action': 'set_value', 'payload': command_payload},
        }, room=sid)


# pylint: disable=too-many-locals, too-many-statements, too-many-branches
def register(socketio, state, recorder, replayer, client_manager):
    """Register provider-side Socket.IO event handlers."""
    del replayer, client_manager  # not used here

    @socketio.on('data_stream')
    def handle_data_stream(payload):
        """Handles incoming measurement data from a provider."""
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

        # --- HMAC authentication gate --------------------------------------
        # Drop any packet that doesn't carry a valid signature for an approved
        # provider. The secret is looked up by ``source_id`` so multiplexed
        # bridges (one Socket.IO session forwarding many providers) work too.
        # UI-internal virtual providers (in-browser simulators) bypass HMAC:
        # they originate from an already-trusted UI socket and cannot exchange
        # a shared secret through the same channel they would sign with.
        if is_auth_required() and source_id not in state.ui_internal_sources:
            sender_sid: str = request.sid  # type: ignore[attr-defined]
            secret_hex = state.get_secret_for_source(source_id)
            if secret_hex is None:
                # Unknown source, pending provider, or revoked credential.
                return
            ok, reason = verify_payload(payload, secret_hex, server_time=time.time())
            if not ok:
                logger.warning(
                    "data_stream HMAC verify failed for source=%s sid=%s: %s",
                    source_id, sender_sid, reason,
                )
                return
            # Strip auth block before forwarding / recording.
            payload.pop('auth', None)

        now_ms = time.time() * 1000.0
        distribution = payload.get('distribution')

        # Normalize client-local timestamps to server wall-clock so recorded
        # sessions stay consistent even if devices send millis() values.
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
            # Could be the main task ID or an original ID for recorded tasks.
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

        # Forward all data to UI clients, regardless of recording state.
        socketio.emit('data_stream', payload, room='ui_clients')

        # Server-side source→actuator routing (no UI round-trip): deliver the
        # same stream directly to any actuator linked to this source.
        _route_to_actuators(socketio, state, source_id, payload)

    @socketio.on('task_request')
    def handle_task_request(request_data):
        """Forwards a task request to a specific provider."""
        # This is now mostly for virtual tasks or specific one-off commands.
        provider_id = request_data.get('provider_id')
        provider_sid = state.find_provider_sid(provider_id)
        if provider_sid:
            socketio.emit('execute_task', request_data, room=provider_sid)
        else:
            logger.warning("Provider %s not found for task request", provider_id)

    @socketio.on('task_assigned')
    def handle_task_assigned(data):
        """Registers a task as active when dropped into a UI slot."""
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

            logger.debug(
                "Task %s assigned to slot %s. Active tasks: %s",
                task_id, slot, state.active_tasks_by_slot,
            )

    @socketio.on('task_unassigned')
    def handle_task_unassigned(data):
        """Removes a task from the active state when removed from a UI slot."""
        slot = data.get('slot')
        if slot is not None and slot in state.active_tasks_by_slot:
            with state.atomic_update():
                removed_task_id = state.active_tasks_by_slot.pop(slot, None)
            if removed_task_id:
                logger.debug(
                    "Task %s unassigned from slot %s. Active tasks: %s",
                    removed_task_id, slot, state.active_tasks_by_slot,
                )

    @socketio.on('cmd_control')
    def handle_control_command(cmd):
        """Forwards a control command to a specific provider."""
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
            # Maybe it's a virtual provider on the client, broadcast to all UIs.
            logger.warning("SID for %s not found, broadcasting to UIs", provider_id)
            socketio.emit('execute_command', cmd, room='ui_clients')

    @socketio.on('link_source')
    def handle_link_source(data):
        """Bind a data source to an actuator; dispatcher routes it directly."""
        if not isinstance(data, dict):
            return
        source_id = data.get('source_id') or data.get('sourceId')
        actuator_id = (data.get('actuator_id') or '').replace('prov_', '')
        if not source_id or not actuator_id:
            return
        state.add_actuator_link(source_id, actuator_id)
        logger.info("Linked source %s -> actuator %s", source_id, actuator_id)

    @socketio.on('unlink_source')
    def handle_unlink_source(data):
        """Remove a source→actuator route."""
        if not isinstance(data, dict):
            return
        source_id = data.get('source_id') or data.get('sourceId')
        actuator_id = (data.get('actuator_id') or '').replace('prov_', '')
        if not source_id or not actuator_id:
            return
        state.remove_actuator_link(source_id, actuator_id)
        logger.info("Unlinked source %s -> actuator %s", source_id, actuator_id)

    @socketio.on('provider_meta_changed')
    def handle_provider_meta_changed(data):
        """A provider has changed its own metadata; update state and broadcast."""
        task_id = data.get('task_id')
        changes = data.get('changes', {})
        if task_id and changes:
            state.update_task_meta(task_id, changes)
        logger.debug("📢 Provider meta changed, broadcasting to UIs: %s", data)
        socketio.emit('provider_meta_changed', data, room='ui_clients')

    # --- TASK CONFIGURATION (ALIAS & COLOR) -----------------------------
    @socketio.on('set_task_alias')
    def handle_set_task_alias(data):
        """Sets a user-defined alias for a task."""
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

        Color propagation rules:
        - A color change at a sink propagates upstream to the nearest source.
        - MATH modules act as color boundaries; propagation stops there.
        - The frontend is responsible for resolving the signal chain and
          applying propagation visually.
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
        """Returns the stored configuration (alias, color) for a task."""
        if not isinstance(data, dict):
            return
        task_id = data.get('task_id')
        if not isinstance(task_id, str) or not task_id:
            return
        config = {}
        if state.config_store:
            config = state.config_store.get_task_config(task_id)
        emit('task_config', {'task_id': task_id, 'config': config})

    _ = (
        handle_data_stream, handle_task_request, handle_task_assigned,
        handle_task_unassigned, handle_control_command,
        handle_provider_meta_changed, handle_set_task_alias,
        handle_set_task_color, handle_get_task_config,
    )
