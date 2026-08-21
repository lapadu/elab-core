"""Shared lock and dependencies for the split state stores."""
import threading
from typing import Optional

from ..config_store import ConfigStore


class StateContext:
    """Holds the single re-entrant lock and shared dependencies.

    Every store receives the *same* ``StateContext`` instance so they all
    serialize on one ``RLock``. This preserves the cross-store atomicity the
    original ``SystemState`` guaranteed through a single ``atomic_update``
    block, while letting each store own only its own data.
    """

    def __init__(self, socketio, config_store: Optional[ConfigStore] = None):
        # Re-entrant so helper methods may be called from within an already
        # locked block without deadlocking.
        self.lock = threading.RLock()
        self.socketio = socketio
        self.config_store: Optional[ConfigStore] = config_store
