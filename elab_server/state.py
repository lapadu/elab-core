"""This module contains the SystemState class.

``SystemState`` is a thin facade over focused stores (provider registry,
actuator link registry, pairing/auth store, task-metadata store). The stores
share one re-entrant lock via :class:`~elab_server.state_stores.StateContext`
so operations spanning several of them stay atomic. The facade keeps the
original public method surface and exposes the underlying dicts as properties
so existing socket handlers, the recorder and tests keep working unchanged.
"""
import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from .config_store import ConfigStore
from .state_stores import (
    ActuatorLinkRegistry,
    PairingStore,
    ProviderRegistry,
    StateContext,
    TaskMetaStore,
)

logger = logging.getLogger(__name__)


class SystemState:
    """Thread-safe central registry."""

    def __init__(self, socketio, config_store: Optional[ConfigStore] = None):
        self._ctx = StateContext(socketio, config_store)
        # Focused stores sharing the context's single re-entrant lock.
        self._providers = ProviderRegistry(self._ctx)
        self._actuators = ActuatorLinkRegistry(self._ctx)
        self._pairing = PairingStore(self._ctx, self._providers)
        self._meta = TaskMetaStore(self._ctx, self._providers)

        # Runtime / session fields mutated directly by handlers and recorder.
        self.socketio = socketio
        self.clients: Dict[str, Dict[str, Any]] = {}            # sid -> client info
        self.recording: bool = False
        self.current_session_id: Optional[str] = None
        self.active_tasks_by_slot: Dict[Any, str] = {}          # slot_idx -> task_id

    @contextmanager
    def atomic_update(self):
        """Context manager for atomic updates of state data."""
        with self._ctx.lock:
            yield self

    # ------------------------------------------------------------------
    # Backward-compatible attribute access (delegates to the stores)
    # ------------------------------------------------------------------
    @property
    def config_store(self) -> Optional[ConfigStore]:
        """The dispatcher's persistent config store, if configured."""
        return self._ctx.config_store

    @property
    def providers(self) -> Dict[str, List[Dict[str, Any]]]:
        """Registered provider manifests keyed by sid (low-level/test seam)."""
        return self._providers.providers

    @property
    def decoders(self) -> Dict[str, Any]:
        """Active source_id -> decoder cache (low-level/test seam)."""
        return self._providers.decoders

    @property
    def _provider_sid_index(self) -> Dict[str, str]:
        """O(1) provider/task id -> sid lookup index (low-level/test seam)."""
        return self._providers._provider_sid_index  # pylint: disable=protected-access

    @property
    def approved_secrets(self) -> Dict[str, str]:
        """Approved device_id -> secret_hex cache (low-level/test seam)."""
        return self._pairing.approved_secrets

    # ------------------------------------------------------------------
    # Provider registry (delegated)
    # ------------------------------------------------------------------
    def add_provider(self, sid: str, manifest: Dict[str, Any]) -> bool:
        """Adds a provider to the state."""
        return self._providers.add_provider(sid, manifest)

    def remove_provider(self, sid: str) -> None:
        """Removes a provider from the state and cleans up dependent state."""
        with self._ctx.lock:
            providers = self._providers.pop_provider(sid)
            # Drop UI-internal source-id registrations for the removed providers.
            self._pairing.forget_sources(providers)
            # Drop source->actuator routes that referenced this provider,
            # whether it was the source or the actuator target.
            self._actuators.purge_for(providers)

        for provider in providers:
            logger.info("Provider removed: %s (%s)",
                        provider.get('name'), sid)
            self.socketio.emit('provider_disconnected', {
                'provider_id': provider.get('id'),
                'timestamp': time.time()
            }, room='ui_clients')

    def get_providers_list(self) -> List[Dict[str, Any]]:
        """Returns a list of all available providers."""
        return self._providers.get_providers_list()

    def find_provider_sid(self, provider_id: str) -> Optional[str]:
        """Finds the session ID of a provider or one of its tasks (O(1))."""
        return self._providers.find_provider_sid(provider_id)

    def has_provider_sid(self, sid: str) -> bool:
        """Whether any provider is registered under *sid*."""
        return self._providers.has_sid(sid)

    def get_providers_for_sid(self, sid: str) -> List[Dict[str, Any]]:
        """Return a shallow copy of the manifests registered under *sid*."""
        return self._providers.get_for_sid(sid)

    def snapshot_provider_items(self) -> List[tuple]:
        """Return a ``(sid, manifests)`` snapshot for read-only iteration."""
        return self._providers.snapshot_items()

    def drop_manifest_from_sid(self, sid: str, manifest_id: str) -> None:
        """Remove manifests with *manifest_id* from *sid*'s list (re-register path)."""
        self._providers.drop_manifest(sid, manifest_id)

    def get_decoder(self, source_id: str) -> Any:
        """Return the active decoder for *source_id*, or ``None``."""
        return self._providers.get_decoder(source_id)

    def get_task(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Return the task manifest for *source_id*, if currently registered."""
        return self._providers.get_task(source_id)

    def get_provider_manifest(self, provider_id):
        """Returns the manifest of a provider."""
        return self._providers.get_provider_manifest(provider_id)

    def update_provider_manifest(self, sid: str, manifest: Dict[str, Any]) -> bool:
        """Replace the registered manifest for a provider sid."""
        return self._providers.update_provider_manifest(sid, manifest)

    # ------------------------------------------------------------------
    # Actuator links (delegated)
    # ------------------------------------------------------------------
    def add_actuator_link(self, source_id: str, actuator_id: str) -> None:
        """Route a data source directly to an actuator provider."""
        self._actuators.add_actuator_link(source_id, actuator_id)

    def remove_actuator_link(self, source_id: str, actuator_id: str) -> None:
        """Remove a single source->actuator route."""
        self._actuators.remove_actuator_link(source_id, actuator_id)

    def get_actuator_links(self, source_id: str) -> List[str]:
        """Return a copy of the actuator ids linked to a source."""
        return self._actuators.get_actuator_links(source_id)

    # ------------------------------------------------------------------
    # Task metadata (delegated)
    # ------------------------------------------------------------------
    def update_task_meta(self, task_id, changes):
        """Updates task metadata such as color, name, and config in state."""
        return self._meta.update_task_meta(task_id, changes)

    def _provider_persists(self, task_id: str) -> bool:
        """Check if the provider owning *task_id* handles its own persistence."""
        return self._meta._provider_persists(task_id)  # pylint: disable=protected-access

    def set_task_alias(self, task_id: str, alias: Optional[str]) -> bool:
        """Set a user-defined alias for a task."""
        return self._meta.set_task_alias(task_id, alias)

    def set_task_color(self, task_id: str, color: Optional[str]) -> bool:
        """Set a color override for a task."""
        return self._meta.set_task_color(task_id, color)

    def set_task_decimals(self, task_id: str, decimals: Optional[int]) -> bool:
        """Set a decimal places (precision) override for a task."""
        return self._meta.set_task_decimals(task_id, decimals)

    def apply_stored_config(self, manifest: Dict[str, Any]) -> None:
        """Apply stored configuration (alias, color, decimals) on registration."""
        self._meta.apply_stored_config(manifest)

    def find_upstream_source(self, task_id: str) -> Optional[str]:
        """Find the nearest upstream source task for color propagation."""
        return self._meta.find_upstream_source(task_id)

    # ------------------------------------------------------------------
    # Pairing / authentication (delegated)
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
        self._pairing.add_pending_provider(sid, device_id, manifest, manifest_hash, client_ip)

    def remove_pending_provider(self, sid: str) -> Optional[Dict[str, Any]]:
        """Pop a pending entry by sid."""
        return self._pairing.remove_pending_provider(sid)

    def get_pending_list(self) -> List[Dict[str, Any]]:
        """Return a serializable snapshot of all pending providers."""
        return self._pairing.get_pending_list()

    def find_pending_sid_by_device(self, device_id: str) -> Optional[str]:
        """Return the sid of the pending provider with given device_id, if any."""
        return self._pairing.find_pending_sid_by_device(device_id)

    def register_approved_secret(self, sid: str, device_id: str, secret_hex: str) -> None:
        """Cache an approved provider's secret in memory for fast HMAC verify."""
        self._pairing.register_approved_secret(sid, device_id, secret_hex)

    def get_secret_for_sid(self, sid: str) -> Optional[str]:
        """Return the cached secret for a session, or ``None`` if not approved."""
        return self._pairing.get_secret_for_sid(sid)

    def get_secret_for_source(self, source_id: str) -> Optional[str]:
        """Return the cached secret responsible for a given source / task id."""
        return self._pairing.get_secret_for_source(source_id)

    def drop_session_auth(self, sid: str) -> Optional[str]:
        """Remove session-level auth state on disconnect. Returns device_id if any."""
        return self._pairing.drop_session_auth(sid)

    def issue_auto_approve_token(self, token: str, script: Optional[str] = None) -> None:
        """Register a one-shot auto-approval token (used by ProcessManager)."""
        self._pairing.issue_auto_approve_token(token, script)

    def consume_auto_approve_token(self, token: Optional[str]) -> bool:
        """Atomically consume an auto-approval token. Returns True if valid."""
        return self._pairing.consume_auto_approve_token(token)

    def mark_ui_internal_source(self, source_id: str) -> None:
        """Tag a source id as belonging to a trusted UI-internal provider."""
        self._pairing.mark_ui_internal(source_id)

    def is_ui_internal_source(self, source_id: str) -> bool:
        """Whether *source_id* bypasses TOFU/HMAC as a UI-internal source."""
        return self._pairing.is_ui_internal(source_id)

    # ------------------------------------------------------------------
    # Group exclusivity policy (reads providers + runtime slots)
    # ------------------------------------------------------------------
    def check_group_exclusivity(self, task_id):
        """Check whether dispatching *task_id* is allowed given the active tasks.

        Returns ``(allowed, reason)`` where *reason* is ``None`` when allowed
        or a human-readable rejection message otherwise.

        Rules:
        * Tasks within the **same group** of a provider can be dispatched in
          parallel.
        * Tasks in **different groups** of the same provider are mutually
          exclusive - only one group may be active at a time.
        * When **no** task in a provider carries a ``group`` field every task
          is treated as belonging to one implicit group (always allowed).
        """
        with self._ctx.lock:
            # 1. Locate the provider manifest that owns the requested task.
            owner_manifest = None
            requested_task = None
            for p_list in self._providers.providers.values():
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
                # Task not found - let the caller decide how to handle this.
                return True, None

            # 2. Determine whether the provider uses groups at all.
            tasks = owner_manifest.get('tasks', [])
            has_groups = any(t.get('group') for t in tasks)
            if not has_groups:
                # No groups defined -> all tasks are implicitly in one group.
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
                    continue  # Different provider - irrelevant.
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
                        break  # Same group - allowed, continue checking.

            return True, None
