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
                    self.decoders.pop(task.get('id'), None)

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
