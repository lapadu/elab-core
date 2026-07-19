"""This module contains the Flask app and SocketIO initialization."""
import argparse
import logging
import os
import secrets
import socket
import time
from flask import Flask, send_from_directory
from flask_socketio import SocketIO
from .config import REACT_BUILD_DIR
from ._version import __version__ as ELAB_VERSION

logger = logging.getLogger(__name__)

# CLI ARGUMENTS PARSING
parser = argparse.ArgumentParser(description='E-Lab Dispatcher Server')
parser.add_argument('-d', '--dispatcher-only', action='store_true',
                    help='Start only the API/WebSocket server without serving the React frontend')
args, unknown = parser.parse_known_args()

SERVE_FRONTEND = not args.dispatcher_only

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

def register_routes(state):
    """Registers the API routes."""
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

