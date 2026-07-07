"""Socket.IO event handler facade.

The actual handler implementations live in
:mod:`elab_server.socket_handlers`, split by domain (auth, provider,
session, plugin).  This module exposes a single
``register_socket_handlers`` entry point used by ``elab_server.main``
and re-exports a few helpers kept for backward compatibility with the
integration tests.
"""
from __future__ import annotations

from .socket_handlers import (
    auth_handlers,
    plugin_handlers,
    provider_handlers,
    session_handlers,
)
from .config import SESSION_DIR  # re-exported for tests that monkeypatch elab_server.sockets.SESSION_DIR
from .socket_handlers._helpers import (
    _is_plugin_url_allowed,
    _sanitize_plugin_urls,
)


def register_socket_handlers(socketio, state, recorder, replayer, client_manager):
    """Register all Socket.IO event handlers on the given ``socketio`` server."""
    auth_handlers.register(socketio, state, recorder, replayer, client_manager)
    provider_handlers.register(socketio, state, recorder, replayer, client_manager)
    session_handlers.register(socketio, state, recorder, replayer, client_manager)
    plugin_handlers.register(socketio, state, recorder, replayer, client_manager)


__all__ = [
    "register_socket_handlers",
    "SESSION_DIR",
    "_is_plugin_url_allowed",
    "_sanitize_plugin_urls",
]
