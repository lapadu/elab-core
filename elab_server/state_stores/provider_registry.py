"""Provider registry: manifests, the sid lookup index and per-task decoders."""
import logging
import time
from typing import Any, Dict, List, Optional

from jsonschema import validate, ValidationError

from ..config import MANIFEST_SCHEMA
from ..decoders import DecoderRegistry
from .context import StateContext

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Owns registered provider manifests and their derived indices."""

    def __init__(self, ctx: StateContext):
        self._ctx = ctx
        self.providers: Dict[str, List[Dict[str, Any]]] = {}    # sid -> [manifests]
        self.decoders: Dict[str, Any] = {}                      # source_id -> decoder instance
        # O(1) lookup indices kept in sync with self.providers under the lock.
        # Provider ids and task ids live in separate namespaces so a task id
        # can never shadow another provider's id.
        self._provider_sid_index: Dict[str, str] = {}           # provider_id -> sid
        self._task_sid_index: Dict[str, str] = {}               # task_id -> sid

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _index_manifest(self, sid: str, manifest: Dict[str, Any]) -> None:
        """Register provider and task ids in the sid lookup indices."""
        pid = manifest.get('id')
        if pid:
            self._provider_sid_index[pid] = sid
        for task in manifest.get('tasks', []) or []:
            tid = task.get('id')
            if tid:
                self._task_sid_index[tid] = sid

    def _unindex_manifest(self, manifest: Dict[str, Any]) -> None:
        """Remove a provider's ids from the sid lookup indices.

        Only index entries that still point at *this manifest's own sid* are
        removed. A device that reconnects with a new sid (e.g. after a
        RAW-capture WiFi teardown) re-registers and remaps the index to the
        fresh sid. If the delayed disconnect of the stale sid arrives later, it
        must not clobber those remapped entries — doing so would break
        ``find_provider_sid`` routing and leave the widget stuck offline with
        no data until the task is re-dragged.
        """
        owner_sid = manifest.get('sid')
        pid = manifest.get('id')
        if pid and self._provider_sid_index.get(pid) == owner_sid:
            self._provider_sid_index.pop(pid, None)
        for task in manifest.get('tasks', []) or []:
            tid = task.get('id')
            if tid and self._task_sid_index.get(tid) == owner_sid:
                self._task_sid_index.pop(tid, None)

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
    def find_id_conflicts(self, sid: str, manifest: Dict[str, Any]) -> List[str]:
        """Return ids of *manifest* that are already owned by a different sid.

        Provider ids and task ids are indexed separately but share one global
        name space: ``find_provider_sid`` and the HMAC gate both accept either
        kind, so an id claimed as a task by one device and as a provider by
        another would route ambiguously. Reporting the clash lets the caller
        reject the registration instead of silently renaming it, which would
        decouple the manifest from its pairing credential.
        """
        conflicts: List[str] = []
        with self._ctx.lock:
            candidates = [manifest.get('id')]
            candidates.extend(
                task.get('id')
                for task in manifest.get('tasks', []) or []
                if isinstance(task, dict)
            )
            for candidate in candidates:
                if not candidate:
                    continue
                owner = (
                    self._provider_sid_index.get(candidate)
                    or self._task_sid_index.get(candidate)
                )
                if owner is not None and owner != sid:
                    conflicts.append(candidate)
        return conflicts

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

        task_ids = [
            task.get('id')
            for task in manifest.get('tasks', []) or []
            if isinstance(task, dict) and task.get('id')
        ]
        if len(set(task_ids)) != len(task_ids):
            logger.warning(
                "Provider %s declares duplicate task ids; registration refused.",
                manifest.get('id'),
            )
            return False

        conflicts = self.find_id_conflicts(sid, manifest)
        if conflicts:
            logger.warning(
                "Provider %s claims ids already owned by another session: %s",
                manifest.get('id'), ", ".join(conflicts),
            )
            return False

        # Build decoders outside the lock so a slow / faulty decoder ctor
        # cannot block other state operations.
        new_decoders = self._build_decoders(manifest)

        with self._ctx.lock:
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
                    if isinstance(task, dict) and task.get('id'):
                        self.decoders.pop(task['id'], None)
            self.providers[sid] = [
                p for p in self.providers[sid] if p.get('id') != manifest.get('id')
            ]
            self.providers[sid].append(manifest)

            self._index_manifest(sid, manifest)
            self.decoders.update(new_decoders)

        return True

    def pop_provider(self, sid: str) -> List[Dict[str, Any]]:
        """Remove all manifests for a sid, clean index/decoders, return them.

        Cross-store cleanup (actuator links, pending-auth sources) and the
        ``provider_disconnected`` emit are orchestrated by the facade under the
        same shared lock.
        """
        with self._ctx.lock:
            providers = self.providers.pop(sid, [])
            for manifest in providers:
                self._unindex_manifest(manifest)
                for task in manifest.get('tasks', []) or []:
                    if isinstance(task, dict) and task.get('id'):
                        self.decoders.pop(task['id'], None)
            return providers

    def get_providers_list(self) -> List[Dict[str, Any]]:
        """Returns a list of all available providers."""
        with self._ctx.lock:
            all_providers = []
            for p_list in self.providers.values():
                all_providers.extend(p_list)
            return all_providers

    def find_provider_sid(self, provider_id: str) -> Optional[str]:
        """Finds the session ID of a provider or one of its tasks (O(1))."""
        if not provider_id:
            return None
        with self._ctx.lock:
            sid = self._provider_sid_index.get(provider_id)
            if sid is not None:
                return sid
            return self._task_sid_index.get(provider_id)

    def has_sid(self, sid: str) -> bool:
        """Whether any provider is registered under *sid*."""
        with self._ctx.lock:
            return sid in self.providers

    def get_for_sid(self, sid: str) -> List[Dict[str, Any]]:
        """Return a shallow copy of the manifests registered under *sid*."""
        with self._ctx.lock:
            return list(self.providers.get(sid, []))

    def snapshot_items(self) -> List[tuple]:
        """Return a ``(sid, manifests)`` snapshot for read-only iteration.

        Manifest dicts are shared by reference; callers must hold the shared
        lock (via ``atomic_update``) if they mutate based on the snapshot.
        """
        with self._ctx.lock:
            return [(sid, list(mlist)) for sid, mlist in self.providers.items()]

    def drop_manifest(self, sid: str, manifest_id: str) -> None:
        """Remove manifests with *manifest_id* from *sid*'s list (re-register path)."""
        self.pop_manifest(sid, manifest_id)

    def pop_manifest(self, sid: str, manifest_id: str) -> List[Dict[str, Any]]:
        """Remove and return manifests with *manifest_id* from a session."""
        with self._ctx.lock:
            if sid in self.providers:
                dropped = [
                    p for p in self.providers.get(sid, []) if p.get('id') == manifest_id
                ]
                for manifest in dropped:
                    self._unindex_manifest(manifest)
                    for task in manifest.get('tasks', []) or []:
                        if isinstance(task, dict) and task.get('id'):
                            self.decoders.pop(task['id'], None)
                self.providers[sid] = [
                    p for p in self.providers.get(sid, []) if p.get('id') != manifest_id
                ]
                return dropped
        return []

    def get_decoder(self, source_id: str) -> Any:
        """Return the active decoder for *source_id*, or ``None``."""
        with self._ctx.lock:
            return self.decoders.get(source_id)

    def get_task(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Return the task manifest for *source_id*, if currently registered."""
        with self._ctx.lock:
            for provider_list in self.providers.values():
                for provider in provider_list:
                    for task in provider.get('tasks', []) or []:
                        if task.get('id') == source_id:
                            return task
        return None

    def get_provider_manifest(self, provider_id):
        """Returns the manifest of a provider."""
        with self._ctx.lock:
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

    def update_provider_manifest(self, sid: str, manifest: Dict[str, Any]) -> bool:
        """Replace the registered manifest for a provider sid."""
        from ..auth import is_persist_capable  # local import avoids a cycle

        with self._ctx.lock:
            if sid in self.providers:
                old_list = self.providers[sid]
                if old_list:
                    new_id = manifest.get('id')
                    for idx, old_manifest in enumerate(old_list):
                        if old_manifest.get('id') == new_id:
                            manifest['sid'] = sid
                            manifest['connected_at'] = old_manifest.get('connected_at', time.time())
                            # Devices that persist their own configuration ship the
                            # authoritative values inside the manifest; never
                            # overwrite them from the dispatcher's cache.
                            if not is_persist_capable(manifest):
                                for task in manifest.get('tasks', []) or []:
                                    tid = task.get('id')
                                    if tid:
                                        stored = (
                                            self._ctx.config_store.get_task_config(tid)
                                            if self._ctx.config_store else {}
                                        )
                                        if 'alias' in stored:
                                            task['alias'] = stored['alias']
                                        if 'color' in stored:
                                            task['color'] = stored['color']
                                        if 'decimals' in stored:
                                            task['decimals'] = stored['decimals']
                            self._unindex_manifest(old_manifest)
                            self._index_manifest(sid, manifest)
                            old_list[idx] = manifest
                            return True
        return False
