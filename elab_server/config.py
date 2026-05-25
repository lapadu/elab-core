"""Configuration for the E-Lab server."""
import os
import json
import logging

# --- CONFIGURATION ---
UDP_PORT = 5005
WEB_PORT = 5000
SESSION_DIR = "sessions"
UDP_TTL = 1  # Time To Live for UDP broadcasts (number of hops)

# Logging Setup
# Guideline for Log Levels:
# - DEBUG: For development and detailed error analysis.
# - INFO: For normal production operation (start, stop, important status changes).
# - WARNING: For anomalies and unexpected behavior that does not directly stop the operation.
# - ERROR: For errors and exceptions that impair a function.

log_level_str = os.environ.get("ELAB_LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logging.basicConfig(
    level=log_level,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("e_Lab_Dispatcher")
# Suppress noisy gevent-websocket logs.
logging.getLogger('geventwebsocket.handler').setLevel(logging.WARNING)


# Load the schema once at startup. Set ELAB_REQUIRE_SCHEMA=1 to refuse to
# start without a schema (recommended for production deployments). Otherwise
# the server logs a loud error and runs with validation disabled.
_REQUIRE_SCHEMA = os.environ.get("ELAB_REQUIRE_SCHEMA", "").lower() in ("1", "true", "yes")
_SCHEMA_PATH = os.environ.get(
    "ELAB_MANIFEST_SCHEMA",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schemas", "ManifestSchema.json"),
)

try:
    with open(_SCHEMA_PATH, 'r', encoding='utf-8') as f:
        MANIFEST_SCHEMA = json.load(f)
except FileNotFoundError as exc:
    if _REQUIRE_SCHEMA:
        raise RuntimeError(
            f"ManifestSchema.json not found at {_SCHEMA_PATH} and "
            "ELAB_REQUIRE_SCHEMA is set."
        ) from exc
    MANIFEST_SCHEMA = {}
    logger.error(
        "ManifestSchema.json NOT FOUND at %s - manifest validation is DISABLED. "
        "Set ELAB_REQUIRE_SCHEMA=1 to refuse to start without a schema.",
        _SCHEMA_PATH,
    )
except (OSError, json.JSONDecodeError) as exc:
    if _REQUIRE_SCHEMA:
        raise RuntimeError(f"Failed to load ManifestSchema.json: {exc}") from exc
    MANIFEST_SCHEMA = {}
    logger.error("Failed to load ManifestSchema.json (%s); validation disabled.", exc)


# React Build Directory
REACT_BUILD_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",  # Go up one level from elab_server.
    "elab_workbench",
    "dist"
))
