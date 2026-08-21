"""Task metadata: aliases, colors, decimals and stored-config application."""
import logging
from typing import Any, Dict, Optional

from .context import StateContext
from .provider_registry import ProviderRegistry

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
                            return bool(provider.get('persistConfig', False))
        return False

    def set_task_alias(self, task_id: str, alias: Optional[str]) -> bool:
        """Set a user-defined alias for a task.

        If the provider self-persists, the alias is forwarded to the provider.
        Otherwise, the dispatcher stores it in its ConfigStore.
        Returns True if the task was found and the alias applied.
        """
        with self._ctx.lock:
            for p_list in self._providers.providers.values():
                for provider in p_list:
                    for task in provider.get('tasks', []):
                        if task.get('id') == task_id:
                            task['alias'] = alias
                            if provider.get('persistConfig', False):
                                # Forward to the provider to persist
                                sid = provider.get('sid')
                                if sid:
                                    self._ctx.socketio.emit('persist_config', {
                                        'task_id': task_id,
                                        'alias': alias
                                    }, room=sid)
                            elif self._ctx.config_store:
                                self._ctx.config_store.set_task_alias(task_id, alias)
                            return True
        return False

    def set_task_color(self, task_id: str, color: Optional[str]) -> bool:
        """Set a color override for a task.

        If the provider self-persists, the color is forwarded to the provider.
        Otherwise, the dispatcher stores it in its ConfigStore.
        Returns True if the task was found and the color applied.
        """
        with self._ctx.lock:
            for p_list in self._providers.providers.values():
                for provider in p_list:
                    for task in provider.get('tasks', []):
                        if task.get('id') == task_id:
                            task['color'] = color
                            if provider.get('persistConfig', False):
                                sid = provider.get('sid')
                                if sid:
                                    self._ctx.socketio.emit('persist_config', {
                                        'task_id': task_id,
                                        'color': color
                                    }, room=sid)
                            elif self._ctx.config_store:
                                self._ctx.config_store.set_task_color(task_id, color)
                            return True
        return False

    def set_task_decimals(self, task_id: str, decimals: Optional[int]) -> bool:
        """Set a decimal places (precision) override for a task.

        Returns True if the task was found and decimals applied.
        """
        with self._ctx.lock:
            for p_list in self._providers.providers.values():
                for provider in p_list:
                    for task in provider.get('tasks', []):
                        if task.get('id') == task_id:
                            task['decimals'] = decimals
                            if self._ctx.config_store:
                                self._ctx.config_store.set_task_decimals(task_id, decimals)
                            return True
        return False

    def apply_stored_config(self, manifest: Dict[str, Any]) -> None:
        """Apply stored configuration (alias, color, decimals) to a manifest on registration.

        Only applies if the provider does NOT self-persist (persistConfig == false).
        """
        if not self._ctx.config_store:
            return
        if manifest.get('persistConfig', False):
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
