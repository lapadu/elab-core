"""This module contains the SystemState class."""
import threading
import time
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from jsonschema import validate, ValidationError
from .config import MANIFEST_SCHEMA
from .config_store import ConfigStore
from .decoders import DecoderRegistry

logger = logging.getLogger(__name__)


class SystemState:
    """Thread-safe central registry."""
    def __init__(self, socketio, config_store: Optional[ConfigStore] = None):
        self.providers: Dict[str, List[Dict[str, Any]]] = {}    # sid -> [manifests]
        self.clients: Dict[str, Dict[str, Any]] = {}            # sid -> client info
        self.recording: bool = False
        self.current_session_id: Optional[str] = None
        self.active_tasks_by_slot: Dict[Any, str] = {}          # slot_idx -> task_id
        # Re-entrant lock so helper methods may be called from within an
        # already-locked atomic_update block without deadlocking.
        self._lock = threading.RLock()
        self.socketio = socketio
        self.decoders: Dict[str, Any] = {}                      # source_id -> decoder instance
        # O(1) lookup indices kept in sync with self.providers under the lock.
        self._provider_sid_index: Dict[str, str] = {}           # provider_id / task_id -> sid
        # Configuration store for tasks whose provider does NOT self-persist.
        self.config_store: Optional[ConfigStore] = config_store
        # --- Authentication / pairing state ---
        # Providers awaiting operator approval. sid -> {device_id, manifest,
        # manifest_hash, client_ip, first_seen_at}. Kept separate from
        # ``self.providers`` so unapproved devices never appear to the UI as
        # active data sources, while still being visible in the registration view.
        self.pending_providers: Dict[str, Dict[str, Any]] = {}
        # Active approved providers: device_id -> secret_hex (in-memory cache for
        # fast HMAC verification on the data_stream hot path).
        self.approved_secrets: Dict[str, str] = {}
        # sid -> device_id mapping for approved sessions.
        self.sid_to_device: Dict[str, str] = {}
        # One-shot auto-approval tokens issued to locally-spawned scripts via
        # ProcessManager. Consumed on first register_provider use.
        self.auto_approve_tokens: Dict[str, Dict[str, Any]] = {}  # token -> {issued_at, script}
        # Source IDs (provider + task ids) belonging to UI-internal virtual
        # providers (e.g. in-browser simulators registered from the workbench).
        # These bypass TOFU/HMAC because the originating socket is already a
        # trusted UI client; the provider effectively is the UI.
        self.ui_internal_sources: set[str] = set()

    @contextmanager
    def atomic_update(self):
        """Context manager for atomic updates of state data."""
        with self._lock:
            yield self

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _index_manifest(self, sid: str, manifest: Dict[str, Any]) -> None:
        """Register provider and task ids in the sid lookup index."""
        pid = manifest.get('id')
        if pid:
            self._provider_sid_index[pid] = sid
        for task in manifest.get('tasks', []) or []:
            tid = task.get('id')
            if tid:
                self._provider_sid_index[tid] = sid

    def _unindex_manifest(self, manifest: Dict[str, Any]) -> None:
        """Remove a provider's ids from the sid lookup index."""
        pid = manifest.get('id')
        if pid and self._provider_sid_index.get(pid):
            self._provider_sid_index.pop(pid, None)
        for task in manifest.get('tasks', []) or []:
            tid = task.get('id')
            if tid:
                self._provider_sid_index.pop(tid, None)

    @staticmethod
    def _build_decoders(manifest: Dict[str, Any]) -> Dict[str, Any]:
        """Build decoders for a manifest's tasks. Faulty decoders are skipped.

        Runs OUTSIDE any state lock so a misbehaving decoder cannot stall
        other socket handlers.
        """
        result: Dict[str, Any] = {}
        for task in manifest.get('tasks', []) or []:
            decoder_config = task.get('decoder')
            if not isinstance(decoder_config, dict):
                continue
            dec_type = decoder_config.get('type')
            dec_params = decoder_config.get('parameters', {}) or {}
            if not isinstance(dec_type, str):
                continue
            decoder_class = DecoderRegistry.get_decoder(dec_type)
            if not decoder_class:
                if dec_type:
                    logger.warning(
                        "Unknown decoder type '%s' requested by task %s; skipped.",
                        dec_type, task.get('id'),
                    )
                continue
            task_id = task.get('id')
            if not task_id:
                continue
            try:
                result[task_id] = decoder_class(dec_params)
                logger.debug("Decoder '%s' activated for %s.", dec_type, task_id)
            except Exception as exc:  # pylint: disable=broad-except
                # Never let a buggy decoder break provider registration.
                logger.error(
                    "Failed to instantiate decoder '%s' for task %s: %s",
                    dec_type, task_id, exc,
                )
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def add_provider(self, sid: str, manifest: Dict[str, Any]) -> bool:
        """Adds a provider to the state."""
        if not isinstance(manifest, dict):
            logger.warning("add_provider: manifest is not a dict (%s)", type(manifest).__name__)
            return False

        if MANIFEST_SCHEMA:
            try:
                validate(instance=manifest, schema=MANIFEST_SCHEMA)
            except ValidationError as e:
                logger.warning("Invalid manifest: %s", e.message)
                return False

        # Build decoders outside the lock so a slow / faulty decoder ctor
        # cannot block other state operations.
        new_decoders = self._build_decoders(manifest)

        with self.atomic_update():
            manifest['sid'] = sid
            manifest['connected_at'] = time.time()
            if sid not in self.providers:
                self.providers[sid] = []

            # Drop any previous registration of the same provider id from this sid
            # and clean up its index/decoders before reinserting.
            replaced = [p for p in self.providers[sid] if p.get('id') == manifest.get('id')]
            for old in replaced:
                self._unindex_manifest(old)
                for task in old.get('tasks', []) or []:
                    if isinstance(task, dict):
                        self.decoders.pop(task.get('id'), None)
            self.providers[sid] = [
                p for p in self.providers[sid] if p.get('id') != manifest.get('id')
            ]
            self.providers[sid].append(manifest)

            self._index_manifest(sid, manifest)
            self.decoders.update(new_decoders)

        return True

    def remove_provider(self, sid: str) -> None:
        """Removes a provider from the state."""
        with self.atomic_update():
            providers = self.providers.pop(sid, [])
            for manifest in providers:
                self._unindex_manifest(manifest)
                for task in manifest.get('tasks', []) or []:
                    if isinstance(task, dict):
                        self.decoders.pop(task.get('id'), None)
                # Drop any UI-internal source-id registrations.
                pid = manifest.get('id')
                if pid:
                    self.ui_internal_sources.discard(pid)
                for task in manifest.get('tasks', []) or []:
                    if not isinstance(task, dict):
                        continue
                    tid = task.get('id')
                    if tid:
                        self.ui_internal_sources.discard(tid)

        for provider in providers:
            logger.info("Provider removed: %s (%s)",
                        provider.get('name'), sid)
            self.socketio.emit('provider_disconnected', {
                'provider_id': provider.get('id'),
                'timestamp': time.time()
            }, room='ui_clients')

    def get_providers_list(self):
        """Returns a list of all available providers."""
        with self.atomic_update():
            all_providers = []
            for p_list in self.providers.values():
                all_providers.extend(p_list)
            return all_providers

    def find_provider_sid(self, provider_id: str) -> Optional[str]:
        """Finds the session ID of a provider or one of its tasks (O(1))."""
        if not provider_id:
            return None
        with self.atomic_update():
            return self._provider_sid_index.get(provider_id)

    def get_provider_manifest(self, provider_id):
        """Returns the manifest of a provider."""
        with self.atomic_update():
            for p_list in self.providers.values():
                for p in p_list:
                    if p.get('id') == provider_id:
                        return p
                    if 'tasks' in p:
                        for task in p.get('tasks', []):
                            if task.get('id') == provider_id:
                                # Return the main provider manifest
                                return p
        return None

    def update_task_meta(self, task_id, changes):
        """Updates task metadata such as color, name, and config in state."""
        with self.atomic_update():
            for p_list in self.providers.values():
                for provider in p_list:
                    for task in provider.get('tasks', []):
                        if task.get('id') == task_id:
                            if 'color' in changes:
                                task['color'] = changes['color']
                            if 'name' in changes:
                                task['name'] = changes['name']
                            if 'config' in changes:
                                task.setdefault('config', {}).update(changes['config'])
                            logger.debug("State updated for task %s: %s", task_id, changes)
                            return True
        logger.warning("Task %s not found in state for meta update", task_id)
        return False

    def _provider_persists(self, task_id: str) -> bool:
        """Check if the provider owning *task_id* handles its own persistence."""
        with self.atomic_update():
            for p_list in self.providers.values():
                for provider in p_list:
                    for task in provider.get('tasks', []):
                        if task.get('id') == task_id:
                            return bool(provider.get('persistConfig', False))
        return False

    def set_task_alias(self, task_id: str, alias: Optional[str]) -> bool:
        """Set a user-defined alias for a task.

        If the provider self-persists, the alias is forwarded to the provider.
        Otherwise, the dispatcher stores it in its ConfigStore.
        Returns True if the task was found and the alias applied.
        """
        with self.atomic_update():
            for p_list in self.providers.values():
                for provider in p_list:
                    for task in provider.get('tasks', []):
                        if task.get('id') == task_id:
                            task['alias'] = alias
                            if provider.get('persistConfig', False):
                                # Forward to the provider to persist
                                sid = provider.get('sid')
                                if sid:
                                    self.socketio.emit('persist_config', {
                                        'task_id': task_id,
                                        'alias': alias
                                    }, room=sid)
                            elif self.config_store:
                                self.config_store.set_task_alias(task_id, alias)
                            return True
        return False

    def set_task_color(self, task_id: str, color: Optional[str]) -> bool:
        """Set a color override for a task.

        If the provider self-persists, the color is forwarded to the provider.
        Otherwise, the dispatcher stores it in its ConfigStore.
        Returns True if the task was found and the color applied.
        """
        with self.atomic_update():
            for p_list in self.providers.values():
                for provider in p_list:
                    for task in provider.get('tasks', []):
                        if task.get('id') == task_id:
                            task['color'] = color
                            if provider.get('persistConfig', False):
                                sid = provider.get('sid')
                                if sid:
                                    self.socketio.emit('persist_config', {
                                        'task_id': task_id,
                                        'color': color
                                    }, room=sid)
                            elif self.config_store:
                                self.config_store.set_task_color(task_id, color)
                            return True
        return False

    def apply_stored_config(self, manifest: Dict[str, Any]) -> None:
        """Apply stored configuration (alias, color) to a manifest on registration.

        Only applies if the provider does NOT self-persist (persistConfig == false).
        """
        if not self.config_store:
            return
        if manifest.get('persistConfig', False):
            return
        for task in manifest.get('tasks', []) or []:
            task_id = task.get('id')
            if not task_id:
                continue
            stored = self.config_store.get_task_config(task_id)
            if 'alias' in stored:
                task['alias'] = stored['alias']
            if 'color' in stored:
                task['color'] = stored['color']

    def find_upstream_source(self, task_id: str) -> Optional[str]:
        """Find the nearest upstream source task for color propagation.

        Color changes at a sink propagate back to the nearest upstream source
        but NOT beyond intermediate processing modules (MATH).
        Returns the task_id of the nearest upstream source, or None.
        """
        # In the current architecture, tasks don't have explicit wiring info
        # in the manifest. Color propagation is handled by the frontend based
        # on the signal chain. This method provides a server-side helper for
        # the case where the backend needs to resolve it.
        # For now, the frontend handles propagation via the slot/wiring state.
        return None

    def check_group_exclusivity(self, task_id):
        """Check whether dispatching *task_id* is allowed given the active tasks.

        Returns ``(allowed, reason)`` where *reason* is ``None`` when allowed
        or a human-readable rejection message otherwise.

        Rules:
        * Tasks within the **same group** of a provider can be dispatched in
          parallel.
        * Tasks in **different groups** of the same provider are mutually
          exclusive – only one group may be active at a time.
        * When **no** task in a provider carries a ``group`` field every task
          is treated as belonging to one implicit group (always allowed).
        """
        with self.atomic_update():
            # 1. Locate the provider manifest that owns the requested task.
            owner_manifest = None
            requested_task = None
            for p_list in self.providers.values():
                for manifest in p_list:
                    for task in manifest.get('tasks', []):
                        if task.get('id') == task_id:
                            owner_manifest = manifest
                            requested_task = task
                            break
                    if owner_manifest:
                        break
                if owner_manifest:
                    break

            if not owner_manifest:
                # Task not found – let the caller decide how to handle this.
                return True, None

            # 2. Determine whether the provider uses groups at all.
            tasks = owner_manifest.get('tasks', [])
            has_groups = any(t.get('group') for t in tasks)
            if not has_groups:
                # No groups defined → all tasks are implicitly in one group.
                return True, None

            # 3. Resolve the group of the requested task (fall back to a
            #    default so ungrouped tasks are treated as one group).
            default_group = '__default__'
            assert requested_task is not None  # guaranteed by owner_manifest guard above
            requested_group = requested_task.get('group') or default_group

            # 4. Collect the IDs of all tasks belonging to this provider.
            provider_task_ids = {t['id'] for t in tasks}

            # 5. Check every currently active task.
            for active_task_id in self.active_tasks_by_slot.values():
                if active_task_id not in provider_task_ids:
                    continue  # Different provider – irrelevant.
                # Find the active task's group.
                for t in tasks:
                    if t['id'] == active_task_id:
                        active_group = t.get('group') or default_group
                        if active_group != requested_group:
                            return False, (
                                f"Task '{task_id}' (group '{requested_group}') "
                                f"conflicts with active task '{active_task_id}' "
                                f"(group '{active_group}') on the same provider."
                            )
                        break  # Same group – allowed, continue checking.

            return True, None

    # ------------------------------------------------------------------
    # Pending / authentication helpers
    # ------------------------------------------------------------------
    def add_pending_provider(
        self,
        sid: str,
        device_id: str,
        manifest: Dict[str, Any],
        manifest_hash: str,
        client_ip: Optional[str] = None,
    ) -> None:
        """Register a provider as awaiting approval (does NOT enter ``providers``)."""
        with self.atomic_update():
            self.pending_providers[sid] = {
                "device_id": device_id,
                "manifest": manifest,
                "manifest_hash": manifest_hash,
                "client_ip": client_ip,
                "first_seen_at": time.time(),
            }

    def remove_pending_provider(self, sid: str) -> Optional[Dict[str, Any]]:
        """Pop a pending entry by sid."""
        with self.atomic_update():
            return self.pending_providers.pop(sid, None)

    def get_pending_list(self) -> List[Dict[str, Any]]:
        """Return a serializable snapshot of all pending providers."""
        with self.atomic_update():
            return [
                {
                    "device_id": entry["device_id"],
                    "manifest": entry["manifest"],
                    "manifest_hash": entry["manifest_hash"],
                    "client_ip": entry.get("client_ip"),
                    "first_seen_at": entry.get("first_seen_at"),
                    "sid": sid,
                }
                for sid, entry in self.pending_providers.items()
            ]

    def find_pending_sid_by_device(self, device_id: str) -> Optional[str]:
        """Return the sid of the pending provider with given device_id, if any."""
        with self.atomic_update():
            for sid, entry in self.pending_providers.items():
                if entry.get("device_id") == device_id:
                    return sid
        return None

    def register_approved_secret(self, sid: str, device_id: str, secret_hex: str) -> None:
        """Cache an approved provider's secret in memory for fast HMAC verify."""
        with self.atomic_update():
            self.approved_secrets[device_id] = secret_hex
            self.sid_to_device[sid] = device_id

    def get_secret_for_sid(self, sid: str) -> Optional[str]:
        """Return the cached secret for a session, or ``None`` if not approved."""
        with self.atomic_update():
            device_id = self.sid_to_device.get(sid)
            if device_id is None:
                return None
            return self.approved_secrets.get(device_id)

    def get_secret_for_source(self, source_id: str) -> Optional[str]:
        """Return the cached secret responsible for a given source / task id.

        Looks up the owning provider's manifest by ``source_id`` (which may be
        the provider id itself or any of its task ids) and returns the secret
        keyed by ``device_id`` (= manifest['id']). This works correctly even
        when several providers are multiplexed through one Socket.IO session
        (e.g. via the bridge daemon).
        """
        with self.atomic_update():
            for p_list in self.providers.values():
                for provider in p_list:
                    if provider.get('id') == source_id:
                        return self.approved_secrets.get(provider['id'])
                    for task in provider.get('tasks', []) or []:
                        if task.get('id') == source_id:
                            pid = provider.get('id')
                            if pid:
                                return self.approved_secrets.get(pid)
                            return None
        return None

    def drop_session_auth(self, sid: str) -> Optional[str]:
        """Remove session-level auth state on disconnect. Returns device_id if any."""
        with self.atomic_update():
            device_id = self.sid_to_device.pop(sid, None)
            # Keep ``approved_secrets`` intact across reconnects (TOFU persists).
            return device_id



    def issue_auto_approve_token(self, token: str, script: Optional[str] = None) -> None:
        """Register a one-shot auto-approval token (used by ProcessManager)."""
        with self.atomic_update():
            self.auto_approve_tokens[token] = {
                "issued_at": time.time(),
                "script": script,
            }

    def consume_auto_approve_token(self, token: Optional[str]) -> bool:
        """Atomically consume an auto-approval token. Returns True if valid."""
        if not isinstance(token, str) or not token:
            return False
        with self.atomic_update():
            return self.auto_approve_tokens.pop(token, None) is not None
