"""Server-side source -> actuator routing table."""
from typing import Any, Dict, List

from .context import StateContext


class ActuatorLinkRegistry:
    """Maps a data ``source_id`` to the actuator provider ids it feeds.

    The stream is delivered to those actuators directly as ``execute_command``
    without a UI round-trip. Populated by the UI when a source is linked to an
    actuator widget.
    """

    def __init__(self, ctx: StateContext):
        self._ctx = ctx
        self.actuator_links: Dict[str, set] = {}

    def add_actuator_link(self, source_id: str, actuator_id: str) -> None:
        """Route a data source directly to an actuator provider."""
        if not source_id or not actuator_id:
            return
        with self._ctx.lock:
            self.actuator_links.setdefault(source_id, set()).add(actuator_id)

    def remove_actuator_link(self, source_id: str, actuator_id: str) -> None:
        """Remove a single source->actuator route."""
        with self._ctx.lock:
            targets = self.actuator_links.get(source_id)
            if targets:
                targets.discard(actuator_id)
                if not targets:
                    self.actuator_links.pop(source_id, None)

    def get_actuator_links(self, source_id: str) -> List[str]:
        """Return a copy of the actuator ids linked to a source."""
        with self._ctx.lock:
            targets = self.actuator_links.get(source_id)
            return list(targets) if targets else []

    def purge_for(self, providers: List[Dict[str, Any]]) -> None:
        """Remove source->actuator routes referencing the removed providers.

        Called from within the facade's ``remove_provider`` lock; the shared
        RLock is reentrant so nested acquisition here is safe.
        """
        gone: set = set()
        for manifest in providers:
            if manifest.get('id'):
                gone.add(manifest['id'])
            for task in manifest.get('tasks', []) or []:
                if isinstance(task, dict) and task.get('id'):
                    gone.add(task['id'])
        with self._ctx.lock:
            for gid in gone:
                self.actuator_links.pop(gid, None)
            for src, targets in list(self.actuator_links.items()):
                targets -= gone
                if not targets:
                    self.actuator_links.pop(src, None)
