"""This module contains the Flask app and SocketIO initialization."""
import argparse
import hashlib
import logging
import os
import secrets
import socket
import time
from typing import Optional
from flask import Flask, request, send_from_directory
from flask_socketio import SocketIO
from .config import REACT_BUILD_DIR
from .config_store import ConfigStore
from ._version import __version__ as ELAB_VERSION

logger = logging.getLogger(__name__)

# Session-based unique visitor tracking for the /api/visitors counter.
# Maps a hash of (IP, User-Agent) to the timestamp it was last seen; repeat
# visits within SESSION_TIMEOUT are not counted again as a new visitor.
_recent_visitors: dict[str, float] = {}
SESSION_TIMEOUT = 30 * 60  # 30 minutes


def _is_new_visitor(remote_addr: Optional[str], user_agent: str) -> bool:
    """Returns True if this visitor should be counted, tracking it either way.

    Known bots/crawlers are never counted. Purges stale entries opportunistically
    so ``_recent_visitors`` does not grow unbounded.
    """
    if 'bot' in user_agent.lower() or 'crawler' in user_agent.lower():
        return False

    visitor_hash = hashlib.sha256(f"{remote_addr}-{user_agent}".encode('utf-8')).hexdigest()
    now = time.time()

    stale = [h for h, last_seen in _recent_visitors.items() if now - last_seen > SESSION_TIMEOUT]
    for h in stale:
        del _recent_visitors[h]

    last_seen = _recent_visitors.get(visitor_hash, 0)
    is_new = (now - last_seen) > SESSION_TIMEOUT
    _recent_visitors[visitor_hash] = now
    return is_new

# CLI ARGUMENTS PARSING
parser = argparse.ArgumentParser(description='E-Lab Dispatcher Server')
parser.add_argument('-d', '--dispatcher-only', action='store_true',
                    help='Start only the API/WebSocket server without serving the React frontend')
parser.add_argument('--plugin-origins', default='',
                    help='Comma-separated list of trusted plugin-script origins '
                         '(e.g. "http://192.168.1.50:8080,http://127.0.0.1:*"). '
                         'Merged with ELAB_PLUGIN_ORIGINS env var.')
args, unknown = parser.parse_known_args()

SERVE_FRONTEND = not args.dispatcher_only

# Merge CLI --plugin-origins with env ELAB_PLUGIN_ORIGINS (CLI takes precedence).
# Must happen before _helpers.py imports _PLUGIN_ORIGIN_ALLOWLIST from os.environ.
if args.plugin_origins.strip():
    existing = os.environ.get('ELAB_PLUGIN_ORIGINS', '').strip()
    cli_origins = args.plugin_origins.strip()
    merged = ','.join(filter(None, [existing, cli_origins]))
    os.environ['ELAB_PLUGIN_ORIGINS'] = merged
    logger.info("Plugin origins: %s (merged from env + CLI args)", merged)

# Flask App
static_folder_path = REACT_BUILD_DIR if SERVE_FRONTEND else None
app = Flask(__name__, static_folder=static_folder_path, static_url_path='')

# SECRET_KEY: prefer ELAB_SECRET_KEY env var; fall back to an ephemeral
# random key for local LAN/dev use. Sessions will not survive a restart in
# that case, which is the safer default for a multi-user lab deployment.
_secret = os.environ.get('ELAB_SECRET_KEY')
if not _secret:
    _secret = secrets.token_hex(32)
    logger.warning(
        "ELAB_SECRET_KEY not set; using an ephemeral random key. "
        "Set ELAB_SECRET_KEY for stable sessions in production."
    )
app.config['SECRET_KEY'] = _secret

# CORS: comma-separated list of allowed origins via ELAB_CORS_ORIGINS.
# Defaults to '*' for the typical single-LAN-laboratory setup.
_cors = os.environ.get('ELAB_CORS_ORIGINS', '*').strip()
if _cors == '*':
    CORS_ALLOWED: object = '*'
    logger.info(
        "Socket.IO CORS allows ALL origins. Restrict via ELAB_CORS_ORIGINS "
        "in production."
    )
else:
    CORS_ALLOWED = [o.strip() for o in _cors.split(',') if o.strip()]
    logger.info("Socket.IO CORS restricted to: %s", CORS_ALLOWED)

# Socket.IO
socketio = SocketIO(
    app,
    cors_allowed_origins=CORS_ALLOWED,
    async_mode='gevent',
    logger=False,
    engineio_logger=False
)

# --- STATIC FILE SERVING ---
if SERVE_FRONTEND:
    @app.route('/')
    def serve_index():
        """Serves the index.html file."""
        index_path = os.path.join(REACT_BUILD_DIR, "index.html")
        if os.path.exists(index_path):
            config_store = app.config.get('CONFIG_STORE')
            if config_store is not None and _is_new_visitor(request.remote_addr, request.headers.get('User-Agent', '')):
                config_store.increment_metric('page_views')
            return send_from_directory(REACT_BUILD_DIR, 'index.html')
        return f"Build not found: {REACT_BUILD_DIR}<br>Please run 'npm run build'!", 404

    @app.route('/<path:path>')
    def serve_static(path):
        """Serves static files from the build directory."""
        file_path = os.path.join(REACT_BUILD_DIR, path)
        if os.path.exists(file_path):
            return send_from_directory(REACT_BUILD_DIR, path)
        return send_from_directory(REACT_BUILD_DIR, 'index.html')
else:
    @app.route('/')
    def serve_api_info():
        """Returns API info when frontend serving is disabled."""
        return "<h1>E-Lab Dispatcher Mode</h1><p>Frontend serving is disabled (-d flag active).</p>"

def register_routes(state, config_store: Optional[ConfigStore] = None):
    """Registers the API routes."""
    app.config['CONFIG_STORE'] = config_store
    @app.route('/api/health')
    def health_check():
        """Returns the health status of the server.

        Returns:
            dict: JSON object containing server status, version, connection counts, and recording state.
        """
        return {
            'status': 'online',
            'version': ELAB_VERSION,
            'providers': len(state.get_providers_list()),
            'clients': len(state.clients),
            'recording': state.recording,
            'session_id': state.current_session_id,
            'uptime': time.time(),
        }

    @app.route('/api/visitors')
    def visitor_count():
        """Returns the number of page views since the counter was created."""
        store = app.config.get('CONFIG_STORE')
        return {'visitors': store.get_metric('page_views') if store is not None else 0}

    @app.route('/api/providers')
    def get_providers():
        """Returns the list of available providers.

        Returns:
            dict: JSON object containing a 'providers' list.
        """
        return {'providers': state.get_providers_list()}

    @app.route('/schemas/ManifestSchema.json')
    def get_manifest_schema():
        """Returns the JSON schema used to validate manifests.

        Returns:
            file: The ManifestSchema.json file.
        """
        schema_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'schemas'))
        return send_from_directory(schema_dir, 'ManifestSchema.json')

    @app.route('/api/discovery/disable', methods=['POST'])
    def disable_discovery():
        """Disables the UDP discovery service."""
        from .discovery import stop_discovery_service
        stop_discovery_service()
        return {'status': 'disabled', 'enabled': False}
        
    @app.route('/api/discovery/enable', methods=['POST'])
    def enable_discovery():
        """Enables the UDP discovery service."""
        from .discovery import start_discovery_service
        start_discovery_service()
        return {'status': 'enabled', 'enabled': True}

    @app.route('/api/discovery/status', methods=['GET'])
    def discovery_status():
        """Returns the status of the UDP discovery service."""
        from .discovery import shutdown_event
        return {'enabled': not shutdown_event.is_set()}

# --- IP ADDRESS MANAGEMENT ---

def get_ip_addresses():
    """Returns all IP addresses under which the server is reachable."""
    ips = set()
    try:
        hostname = socket.gethostname()
        # Use getaddrinfo to retrieve IPs as it is more robust on Windows
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for item in addr_info:
            addr = item[4][0]
            if not addr.startswith("127."):
                ips.add(addr)
    except (socket.gaierror, OSError):
        pass

    # Fallback to gethostbyname_ex if getaddrinfo had issues or returned nothing
    if not ips:
        try:
            hostname = socket.gethostname()
            _, _, ip_list = socket.gethostbyname_ex(hostname)
            for addr in ip_list:
                if not addr.startswith("127."):
                    ips.add(addr)
        except (socket.gaierror, OSError):
            pass

    primary_ip = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip:
            ips.add(primary_ip)
    except OSError:
        pass

    sorted_ips = []
    if primary_ip:
        sorted_ips.append(primary_ip)

    for addr in sorted(list(ips)):
        if addr != primary_ip:
            sorted_ips.append(addr)

    sorted_ips.append("127.0.0.1")
    return sorted_ips

