"""Task metadata: aliases, colors, decimals and stored-config application."""
import logging
from typing import Any, Dict, Optional

from .context import StateContext
from .provider_registry import ProviderRegistry
from ..auth import is_persist_capable, resolve_device_id

logger = logging.getLogger(__name__)


class TaskMetaStore:
    """Reads provider manifests (via :class:`ProviderRegistry`) and applies
    user-defined task metadata, persisting through the provider itself or the
    dispatcher's ``ConfigStore`` depending on ``persistConfig``."""

    def __init__(self, ctx: StateContext, providers: ProviderRegistry):
        self._ctx = ctx
        self._providers = providers

    def update_task_meta(self, task_id, changes) -> bool:
        """Updates task metadata such as color, name, and config in state."""
        with self._ctx.lock:
            for p_list in self._providers.providers.values():
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
        with self._ctx.lock:
            for p_list in self._providers.providers.values():
                for provider in p_list:
                    for task in provider.get('tasks', []):
                        if task.get('id') == task_id:
                            return is_persist_capable(provider)
        return False

    def _find_task(self, task_id: str):
        """Return ``(provider, task)`` for *task_id*, or ``(None, None)``."""
        for p_list in self._providers.providers.values():
            for provider in p_list:
                for task in provider.get('tasks', []):
                    if task.get('id') == task_id:
                        return provider, task
        return None, None

    def _set_meta_field(self, task_id: str, field: str, value: Any) -> bool:
        """Apply a meta field and persist it where the device model dictates.

        Devices that can store configuration themselves receive a
        ``persist_config`` push and stay the single source of truth, so their
        settings travel with the hardware. For everything else the dispatcher
        keeps the value on the device's behalf.
        """
        with self._ctx.lock:
            provider, task = self._find_task(task_id)
            if provider is None or task is None:
                return False
            task[field] = value
            if is_persist_capable(provider):
                sid = provider.get('sid')
                if sid:
                    self._ctx.socketio.emit(
                        'persist_config', {'task_id': task_id, field: value}, room=sid
                    )
            elif self._ctx.config_store:
                setter = getattr(self._ctx.config_store, f'set_task_{field}')
                setter(task_id, value, resolve_device_id(provider))
            return True

    def set_task_alias(self, task_id: str, alias: Optional[str]) -> bool:
        """Set a user-defined alias for a task (e.g. 'Eingang Vorstufe')."""
        return self._set_meta_field(task_id, 'alias', alias)

    def set_task_color(self, task_id: str, color: Optional[str]) -> bool:
        """Set a color override for a task."""
        return self._set_meta_field(task_id, 'color', color)

    def set_task_decimals(self, task_id: str, decimals: Optional[int]) -> bool:
        """Set a decimal places (precision) override for a task."""
        return self._set_meta_field(task_id, 'decimals', decimals)

    def apply_stored_config(self, manifest: Dict[str, Any]) -> None:
        """Apply stored configuration (alias, color, decimals) to a manifest on registration.

        Skipped for devices that persist their own configuration - their
        manifest already carries the authoritative values.
        """
        if not self._ctx.config_store:
            return
        if is_persist_capable(manifest):
            return
        for task in manifest.get('tasks', []) or []:
            task_id = task.get('id')
            if not task_id:
                continue
            stored = self._ctx.config_store.get_task_config(task_id)
            if 'alias' in stored:
                task['alias'] = stored['alias']
            if 'color' in stored:
                task['color'] = stored['color']
            if 'decimals' in stored:
                task['decimals'] = stored['decimals']

    def find_upstream_source(self, task_id: str) -> Optional[str]:  # pylint: disable=unused-argument
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
