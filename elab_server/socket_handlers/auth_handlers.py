"""Socket.IO handlers covering connection lifecycle and TOFU pairing.

Handles: ``connect``, ``disconnect``, ``register_client``,
``register_provider``, ``get_pending_devices``, ``approve_pending_device``,
``revoke_device``, ``delete_device_credential``.
"""
from __future__ import annotations

import logging
import time

import jsonschema
from flask import request
from flask_socketio import emit, join_room

from .._version import __version__ as ELAB_VERSION
from ..auth import (
    compute_manifest_hash,
    generate_secret,
    is_auth_required,
    resolve_device_anchor,
    resolve_device_id,
)
from ..config import MANIFEST_SCHEMA
from .provider_handlers import _drop_actuator_routes_for, _drop_sid_emit_lock
from ._helpers import (
    _PLUGIN_ORIGIN_ALLOWLIST,
    _drop_time_offsets_for,
    _sanitize_plugin_urls,
)


logger = logging.getLogger(__name__)


# pylint: disable=too-many-locals, too-many-statements
def register(socketio, state, recorder, replayer, client_manager):
    """Register auth-related Socket.IO event handlers."""
    del recorder  # not used here, kept for uniform registrar signature

    @socketio.on('connect')
    def handle_connect():
        """Handles a new Socket.IO client connection."""
        client_id: str = request.sid  # type: ignore[attr-defined]
        logger.debug("🔌 Client connected: %s", client_id)
        emit('connection_established', {
            'client_id': client_id,
            'server_version': ELAB_VERSION,
            'timestamp': time.time(),
            'session_active': state.recording,
            'session_id': state.current_session_id,
            # Publish the configured plugin allow-list so the workbench can
            # enforce the same origin policy in the browser. The server still
            # strips disallowed URLs out of incoming manifests; this is a
            # second line of defence against a tampered build.
            'plugin_origins': sorted(_PLUGIN_ORIGIN_ALLOWLIST),
        })

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handles client disconnection.

        If a hardware provider disconnects, it's removed from the state and
        UI clients are notified. If a UI client disconnects, it's removed
        from the clients list.
        """
        sid: str = request.sid  # type: ignore[attr-defined]
        _drop_sid_emit_lock(sid)
        if state.has_provider_sid(sid):
            provider_list = state.get_providers_for_sid(sid)
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
            state.drop_session_auth(sid)
            _drop_time_offsets_for(stale_source_ids)
            _drop_actuator_routes_for(stale_source_ids)

            for provider in provider_list:
                pid = provider.get('id')
                # A device that reconnected under a new sid (e.g. after a
                # RAW-capture WiFi teardown) may already own this id again. Only
                # report it offline when no live session currently owns it, so a
                # delayed stale disconnect does not mark a re-registered
                # provider offline and leave its widget stuck.
                if pid and state.find_provider_sid(pid) is not None:
                    continue
                socketio.emit('provider_offline', {
                    'provider_id': pid,
                    'reason': 'disconnect',
                    'timestamp': time.time()
                }, room='ui_clients')
            socketio.emit('available_providers', {
                'providers': state.get_providers_list(),
                'timestamp': time.time()
            }, room='ui_clients')
        # Drop any pending registration belonging to this sid, then refresh UI.
        if state.remove_pending_provider(sid) is not None:
            socketio.emit('pending_devices', {
                'devices': state.get_pending_list(),
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
        """Registers a new UI client."""
        client_id: str = request.sid  # type: ignore[attr-defined]
        join_room('ui_clients')
        state.clients[client_id] = {'type': 'ui', 'connected_at': time.time()}
        logger.debug("✅ Client registered: %s", client_id)
        emit('available_providers', {'providers': state.get_providers_list()})
        emit('available_scripts', client_manager.scan_scripts())
        emit('pending_devices', {'devices': state.get_pending_list()})
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
        """Registers a hardware provider and its tasks."""
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

        # Validate before the TOFU flow so a malformed manifest never creates a
        # credential row that the operator would have to clean up by hand.
        if MANIFEST_SCHEMA:
            try:
                jsonschema.validate(instance=manifest, schema=MANIFEST_SCHEMA)
            except jsonschema.ValidationError as exc:
                logger.warning(
                    "register_provider: schema validation failed for %s: %s",
                    manifest_id, exc.message,
                )
                emit('registration_error', {
                    'code': 'invalid_manifest',
                    'message': f"Manifest validation failed: {exc.message}",
                })
                return

        # --- Authentication / TOFU pairing ---------------------------------
        # Extract optional pairing fields BEFORE computing the manifest hash so
        # they don't pollute the canonical projection.
        auto_approve_token = manifest.pop('auto_approve_token', None)
        if not isinstance(auto_approve_token, str):
            auto_approve_token = None

        manifest_hash = compute_manifest_hash(manifest)
        device_id = resolve_device_id(manifest)
        device_anchor = resolve_device_anchor(manifest)
        if not device_id:
            emit('registration_error', {'message': "Manifest field 'device.id' missing or invalid"})
            return

        # UI-internal virtual providers (e.g. in-browser simulators registered
        # from the workbench itself) share their fate with the originating UI
        # socket. They are implicitly trusted because the sender is already a
        # connected UI client, so we skip the TOFU/HMAC flow for them.
        is_ui_internal = bool(manifest.get('isUiInstance')) and (
            state.clients.get(provider_id, {}).get('type') == 'ui'
        )

        auth_required = is_auth_required() and not is_ui_internal
        is_ephemeral = device_anchor == 'ephemeral'
        credential = (
            state.get_ephemeral_credential(device_id)
            if is_ephemeral else
            (state.config_store.get_credential(device_id) if state.config_store else None)
        )
        is_newly_paired = False
        issued_secret: 'str | None' = None

        if auth_required and (state.config_store is not None or is_ephemeral):
            if credential is None:
                # Unknown device → create a pending credential
                new_secret = generate_secret()
                credential = (
                    state.set_ephemeral_credential(device_id, new_secret, manifest_hash)
                    if is_ephemeral else
                    state.config_store.upsert_pending_credential(
                        device_id=device_id, secret_hex=new_secret,
                        manifest_hash=manifest_hash, client_ip=client_ip,
                    )
                )
                # Auto-approve if a valid one-shot token was supplied by a
                # locally-spawned script via ProcessManager.
                if state.consume_auto_approve_token(auto_approve_token):
                    if is_ephemeral:
                        state.approve_ephemeral_credential(device_id, manifest_hash)
                    else:
                        state.config_store.approve_credential(device_id, manifest_hash)
                    credential = (
                        state.get_ephemeral_credential(device_id)
                        if is_ephemeral else state.config_store.get_credential(device_id)
                    )
                    is_newly_paired = True
                    issued_secret = new_secret
                    logger.info("🔓 Auto-approved provider %s via one-shot token", device_id)
            else:
                stored_hash = credential.get('manifest_hash')
                stored_status = credential.get('status')
                if stored_status == 'revoked':
                    emit('registration_pending', {
                        'deviceId': device_id,
                        'reason': 'revoked',
                    })
                    state.add_pending_provider(provider_id, device_id, manifest, manifest_hash, client_ip)
                    socketio.emit('pending_devices', {
                        'devices': state.get_pending_list(),
                    }, room='ui_clients')
                    logger.warning("Provider %s attempted to reconnect after revoke", device_id)
                    return
                if stored_hash != manifest_hash:
                    # Manifest changed since approval → force re-pending with new secret.
                    new_secret = generate_secret()
                    credential = (
                        state.set_ephemeral_credential(device_id, new_secret, manifest_hash)
                        if is_ephemeral else
                        state.config_store.upsert_pending_credential(
                            device_id=device_id, secret_hex=new_secret,
                            manifest_hash=manifest_hash, client_ip=client_ip,
                        )
                    )
                    if state.consume_auto_approve_token(auto_approve_token):
                        if is_ephemeral:
                            state.approve_ephemeral_credential(device_id, manifest_hash)
                        else:
                            state.config_store.approve_credential(device_id, manifest_hash)
                        credential = (
                            state.get_ephemeral_credential(device_id)
                            if is_ephemeral else state.config_store.get_credential(device_id)
                        )
                        is_newly_paired = True
                        issued_secret = new_secret
                        logger.info(
                            "🔓 Auto-re-approved provider %s (manifest changed) via one-shot token",
                            device_id,
                        )
                    else:
                        logger.info("🔄 Manifest hash changed for %s, re-pending approval", device_id)

            assert credential is not None  # populated above for auth_required path
            if credential.get('status') != 'approved':
                # Park as pending and inform both client and UI.
                state.add_pending_provider(provider_id, device_id, manifest, manifest_hash, client_ip)
                emit('registration_pending', {
                    'deviceId': device_id,
                    'manifestHash': manifest_hash,
                    'reason': 'awaiting_approval',
                })
                socketio.emit('pending_devices', {
                    'devices': state.get_pending_list(),
                }, room='ui_clients')
                logger.info(
                    "⏳ Provider %s [%s] pending operator approval (sid=%s, ip=%s)",
                    manifest.get('name'), device_id, provider_id, client_ip,
                )
                return

        # --- Proceed with activation ---------------------------------------
        ghost_sids = []

        # Duplicate handling. A second session claiming ids that are already
        # registered is refused outright: silently renaming it would decouple
        # the manifest from the credential its secret is stored under, and the
        # device's data_stream packets would then fail the HMAC gate.
        with state.atomic_update():
            is_reregister = False
            for sid, p_list in state.snapshot_provider_items():
                for existing in p_list:
                    if existing.get('id') != manifest_id:
                        continue
                    if sid == provider_id:
                        is_reregister = True
                    elif (
                        existing.get('client_ip') == client_ip
                        or resolve_device_id(existing) == device_id
                    ):
                        # Same ID from the same physical device (matched by IP
                        # or, more reliably, by its stable hardware anchor)
                        # usually means the device restarted without a clean
                        # disconnect. The IP can change across a RAW-capture
                        # WiFi teardown/reconnect, so matching on the anchor is
                        # what stops the fresh session from being refused as a
                        # duplicate id while the ghost lingers.
                        ghost_sids.append(sid)

            if is_reregister:
                state.drop_manifest_from_sid(provider_id, manifest_id)
                logger.info(
                    "🔄 Manifest refreshed via re-registration: %s [%s] from SID %s",
                    manifest.get('name'),
                    manifest_id,
                    provider_id,
                )

        # Disconnect stale ghost sessions outside the state lock.
        for ghost_sid in ghost_sids:
            logger.warning(
                "👻 Ghost session detected for %s from IP %s. Disconnecting old SID %s",
                manifest_id, client_ip, ghost_sid,
            )
            try:
                socketio.server.disconnect(ghost_sid)
            except (OSError, RuntimeError, ValueError) as e:
                logger.error("Could not disconnect ghost session %s: %s", ghost_sid, e)
            state.remove_provider(ghost_sid)

        conflicts = state.find_id_conflicts(provider_id, manifest)
        if conflicts:
            logger.warning(
                "🚫 Refusing %s [%s] from %s: id(s) already in use by another device: %s",
                manifest.get('name'), manifest_id, client_ip, ", ".join(conflicts),
            )
            emit('registration_error', {
                'code': 'duplicate_id',
                'deviceId': device_id,
                'conflictingIds': conflicts,
                'message': (
                    "Provider or task ids are already registered by another device: "
                    f"{', '.join(conflicts)}. Derive them from a hardware anchor "
                    "(MAC, serial number) so identical firmware stays distinguishable."
                ),
            })
            return

        if not state.add_provider(provider_id, manifest):
            emit('registration_error', {'message': 'Invalid manifest'})
            return

        # Cache the approved secret for fast HMAC verification on data_stream.
        if auth_required and credential is not None:
            state.register_approved_secret(provider_id, device_id, credential['secret_hex'])

        # Tag UI-internal source IDs so the data_stream auth gate lets their
        # packets through without HMAC.
        if is_ui_internal:
            with state.atomic_update():
                pid = manifest.get('id')
                if pid:
                    state.mark_ui_internal_source(pid)
                for task in manifest.get('tasks', []) or []:
                    tid = task.get('id')
                    if tid:
                        state.mark_ui_internal_source(tid)

        # Apply stored configuration (alias, color) from the config store
        # for providers that do NOT self-persist.
        state.apply_stored_config(manifest)
        state.apply_stored_device_config(manifest)

        logger.info(
            "🔧 Provider registered: %s [%s] on device %s (anchor=%s)",
            manifest.get('name'),
            manifest.get('id'),
            device_id,
            device_anchor,
        )

        # If this connection just transitioned from pending→approved (auto-pair)
        # send the one-shot secret to the client so it can sign future packets.
        if is_newly_paired and issued_secret is not None:
            emit('registration_approved', {
                'deviceId': device_id,
                'secret': issued_secret,
                'manifestHash': manifest_hash,
            })

        socketio.emit('provider_registered', {
                      'provider': manifest}, room='ui_clients')
        socketio.emit(
            'available_providers',
            {'providers': state.get_providers_list()},
            room='ui_clients',
        )

    @socketio.on('get_pending_devices')
    def handle_get_pending_devices(_data=None):
        """Return the current snapshot of pending devices to the requesting UI."""
        emit('pending_devices', {'devices': state.get_pending_list()})

    @socketio.on('approve_pending_device')
    def handle_approve_pending_device(data):
        """Approve a pending device. Triggered by a UI operator."""
        if not isinstance(data, dict):
            return
        device_id = data.get('deviceId') or data.get('device_id')
        manifest_hash = data.get('manifestHash') or data.get('manifest_hash')
        if not isinstance(device_id, str) or not isinstance(manifest_hash, str):
            emit('approval_error', {'message': 'deviceId and manifestHash are required'})
            return
        pending_entry = state._pairing.ephemeral_credentials.get(device_id)  # pylint: disable=protected-access
        is_ephemeral = pending_entry is not None
        if state.config_store is None and not is_ephemeral:
            emit('approval_error', {'message': 'ConfigStore unavailable'})
            return

        approved = (
            state.approve_ephemeral_credential(device_id, manifest_hash)
            if is_ephemeral else
            state.config_store.approve_credential(device_id, manifest_hash)
        )
        if not approved:
            emit('approval_error', {
                'deviceId': device_id,
                'message': 'unknown device or manifest hash mismatch',
            })
            return

        credential = (
            state.get_ephemeral_credential(device_id)
            if is_ephemeral else state.config_store.get_credential(device_id)
        )
        if credential is None:
            emit('approval_error', {'deviceId': device_id, 'message': 'credential vanished'})
            return

        # Locate the still-connected pending session for this device, if any.
        pending_sid = state.find_pending_sid_by_device(device_id)
        if pending_sid is not None:
            entry = state.remove_pending_provider(pending_sid)
            if entry is not None:
                # Notify the device with its one-shot secret so it can sign
                # subsequent data_stream packets.
                socketio.emit('registration_approved', {
                    'deviceId': device_id,
                    'secret': credential['secret_hex'],
                    'manifestHash': manifest_hash,
                }, room=pending_sid)
                # Now actually activate the provider.
                manifest = entry['manifest']
                if state.add_provider(pending_sid, manifest):
                    state.register_approved_secret(pending_sid, device_id, credential['secret_hex'])
                    state.apply_stored_config(manifest)
                    state.apply_stored_device_config(manifest)
                    socketio.emit('provider_registered',
                                  {'provider': manifest}, room='ui_clients')
                    socketio.emit('available_providers',
                                  {'providers': state.get_providers_list()},
                                  room='ui_clients')
                    logger.info("✅ Operator approved & activated provider %s", device_id)

        socketio.emit('pending_devices', {'devices': state.get_pending_list()}, room='ui_clients')

    @socketio.on('revoke_device')
    def handle_revoke_device(data):
        """Revoke an approved device. Forces it back to pending on next connect."""
        if not isinstance(data, dict):
            return
        device_id = data.get('deviceId') or data.get('device_id')
        if not isinstance(device_id, str):
            return
        if state.config_store is None:
            return
        if not state.config_store.revoke_credential(device_id):
            return
        # Drop the in-memory secret too, otherwise the device keeps streaming
        # until it happens to reconnect.
        state.forget_secret(device_id)
        logger.info("⛔ Revoked credential for device %s", device_id)

        # If currently connected & approved, let it disconnect itself.
        sid = state.find_provider_sid(device_id)
        if sid is not None:
            # Inform the device so it can wipe its local secret and disconnect cleanly.
            socketio.emit('registration_revoked', {'deviceId': device_id}, room=sid)

        # Refresh views.
        socketio.emit('available_providers',
                      {'providers': state.get_providers_list()},
                      room='ui_clients')
        socketio.emit('pending_devices',
                      {'devices': state.get_pending_list()},
                      room='ui_clients')

    @socketio.on('delete_device_credential')
    def handle_delete_device_credential(data):
        """Remove a credential entry completely (forces fresh pairing next time)."""
        if not isinstance(data, dict):
            return
        device_id = data.get('deviceId') or data.get('device_id')
        if not isinstance(device_id, str):
            return
        if state.config_store is None:
            return
        state.config_store.delete_credential(device_id)
        state.forget_secret(device_id)
        removed = state.config_store.delete_device_config(device_id)
        logger.info(
            "🗑️ Deleted credential for device %s (%d task config rows removed)",
            device_id, removed,
        )
        socketio.emit('pending_devices',
                      {'devices': state.get_pending_list()},
                      room='ui_clients')

    # Avoid 'unused' lint for handler closures registered via decorator.
    _ = (
        handle_connect, handle_disconnect, handle_register_client,
        handle_register_provider, handle_get_pending_devices,
        handle_approve_pending_device, handle_revoke_device,
        handle_delete_device_credential,
    )
