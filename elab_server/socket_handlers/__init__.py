"""Socket.IO event handler subpackage.

The dispatcher's Socket.IO surface used to live in a single 1200+ line
``sockets.py``.  It is now split by domain:

* :mod:`auth_handlers` – connect / disconnect, provider TOFU pairing,
  approve / revoke / delete credential.
* :mod:`provider_handlers` – the live data path: ``data_stream``,
  task assignment, control commands, plus the small task-config helpers
  (alias / color / get_task_config) which logically belong to providers.
* :mod:`session_handlers` – recording, replay and session housekeeping.
* :mod:`plugin_handlers` – script start/stop and the plugin URL allow-list
  helpers (re-exported from :mod:`_helpers`).
* :mod:`_helpers` – stateless utilities, module-level caches and constants
  shared between the handler groups.

The umbrella :mod:`elab_server.sockets` module still exposes the public
``register_socket_handlers`` entrypoint and the historical helper symbols
``_is_plugin_url_allowed`` / ``_sanitize_plugin_urls`` so existing
imports (and the integration test suite) keep working unchanged.
"""

from . import auth_handlers, plugin_handlers, provider_handlers, session_handlers

__all__ = [
    "auth_handlers",
    "plugin_handlers",
    "provider_handlers",
    "session_handlers",
]
