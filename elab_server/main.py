"""Main entry point for the E-Lab server."""
import os
import signal
import sys
import threading
import time
import logging

try:
    import gevent.signal as gevent_signal  # type: ignore[import-not-found]
except ImportError:
    gevent_signal = None

from .app import app, socketio, get_ip_addresses, SERVE_FRONTEND, register_routes
from .config import SESSION_DIR, WEB_PORT, UDP_PORT, REACT_BUILD_DIR
from .state import SystemState
from .config_store import ConfigStore
from .recorder import SessionRecorder
from .replayer import SessionReplayer
from .process_manager import ClientProcessManager
from .discovery import udp_discovery_service, shutdown_event as discovery_shutdown
from .sockets import register_socket_handlers
from ._version import __version__ as ELAB_VERSION

logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
_shutdown_event = threading.Event()

# pylint: disable=C0301


def _is_debugger_attached():
    """Check if a Python debugger (e.g. VS Code debugpy) is attached.

    ``sys.gettrace()`` alone is unreliable for debugpy on Windows because the
    trace function is only installed while actively stepping. We therefore
    also check whether ``debugpy``/``pydevd`` has been imported into the
    running interpreter, which is the case when VS Code launches via F5.
    """
    if getattr(sys, 'gettrace', lambda: None)() is not None:
        return True
    if 'debugpy' in sys.modules or 'pydevd' in sys.modules:
        return True
    return False


def _shutdown_handler(signum, _frame):
    """Handle shutdown signals gracefully."""
    logger.info("Received signal %d, initiating graceful shutdown...", signum)
    _shutdown_event.set()
    discovery_shutdown.set()
    # Best-effort: ask socketio to stop. May raise if not yet running.
    try:
        socketio.stop()
    except (RuntimeError, OSError) as exc:
        logger.debug("socketio.stop() during shutdown: %s", exc)


def main():
    """Initializes and starts the E-Lab server."""
    debugger_attached = _is_debugger_attached()

    # Register signal handlers for graceful shutdown.
    # SIGTERM always uses the regular shutdown handler. SIGINT depends on
    # whether a debugger is attached:
    #   * No debugger -> let socketio.run() handle Ctrl-C itself (default
    #     Python handler). Installing our own handler here would race with
    #     gevent's SIGINT watcher on Windows and produce spurious shutdowns.
    #   * Debugger attached -> install a SIGINT handler that swallows the
    #     spurious CTRL_C_EVENT debugpy injects ~2-3 s after startup. Real
    #     Ctrl-C presses after the startup window are forwarded to the
    #     normal shutdown handler.
    try:
        signal.signal(signal.SIGTERM, _shutdown_handler)
    except (ValueError, OSError, AttributeError):
        pass

    if debugger_attached:
        startup_ts = time.monotonic()

        def _debug_sigint_handler(signum, frame):
            elapsed = time.monotonic() - startup_ts
            if elapsed < 10 and not _shutdown_event.is_set():
                logger.debug(
                    "Ignoring spurious SIGINT from debugpy attach (after %.1fs)",
                    elapsed,
                )
                return
            _shutdown_handler(signum, frame)

        # Override BOTH the stdlib and (if available) gevent SIGINT
        # handlers. On Windows the two layers are distinct and only
        # overriding one is not enough.
        try:
            signal.signal(signal.SIGINT, _debug_sigint_handler)
        except (ValueError, OSError, AttributeError):
            logger.debug("Could not install stdlib SIGINT handler for debugger mode")
        try:
            if gevent_signal is not None:
                gevent_signal.signal(signal.SIGINT, _debug_sigint_handler)  # pyright: ignore[reportAttributeAccessIssue]
        except (ValueError, OSError, AttributeError):
            logger.debug("Could not install gevent SIGINT handler for debugger mode")

    os.makedirs(SESSION_DIR, exist_ok=True)
    print(r"="*60)
    print(r"          _         _        ")
    print(r"  ___    | |   __ _| |_      ")
    print(r" / _ \   | | / _ ` | '_ \    ")
    print(r"|  __/   |__| (_|  | |_) |   ")
    print(r" \___/___|____\__,_|_.__/    ")
    print(r"="*60)
    available_ips = get_ip_addresses()
    print(f"🚀 Dispatcher v{ELAB_VERSION} running.")
    if SERVE_FRONTEND:
        print("🌍 Web UI available at:")
        for host_ip in available_ips:
            print(f"   👉 http://{host_ip}:{WEB_PORT}")
    else:
        print("🔌 API endpoint listening. Connect clients to:")
        for host_ip in available_ips:
            print(f"   👉 {host_ip}:{WEB_PORT}")
    print("-" * 60)
    mode_label = (
        'Dispatcher Only (-d)' if not SERVE_FRONTEND else 'Full Server (API + Frontend)'
    )
    print(f"🔧 Mode: {mode_label}")
    if SERVE_FRONTEND:
        print(f"📁 Frontend: Served from {REACT_BUILD_DIR}")
    print(f"📡 Discovery: UDP Port {UDP_PORT}")
    print(f"💾 Recording to SQLite in: {SESSION_DIR}")
    print("🔧 Mode: Gevent (High Performance)")
    print("="*60)

    # Initialization of components
    config_store = ConfigStore()
    state = SystemState(socketio, config_store=config_store)
    register_routes(state)
    recorder = SessionRecorder(state, socketio)
    replayer = SessionReplayer(socketio)
    replayer.start()
    client_manager = ClientProcessManager()

    # Register all socket handlers
    register_socket_handlers(socketio, state, recorder, replayer, client_manager)

    # Start background threads
    discovery_thread = threading.Thread(target=udp_discovery_service, daemon=True)
    discovery_thread.start()

    # Start the server.
    # When debugpy attaches on Windows it injects a CTRL_C_EVENT into the
    # process (~2-3 s after start). The debugger-aware SIGINT handler above
    # normally swallows it; as an additional safety net we retry the loop
    # once if a KeyboardInterrupt still arrives during the startup window.
    def _run_server():
        socketio.run(app, host='0.0.0.0', port=WEB_PORT, debug=False)

    try:
        start_time = time.monotonic()
        try:
            _run_server()
        except KeyboardInterrupt:
            elapsed = time.monotonic() - start_time
            if debugger_attached and elapsed < 10 and not _shutdown_event.is_set():
                logger.warning(
                    "Spurious KeyboardInterrupt from debugpy attach after %.2fs; restarting server loop",
                    elapsed,
                )
                _run_server()
            else:
                raise
    except KeyboardInterrupt:
        logger.info("Server interrupted, shutting down gracefully...")
    except OSError as e:
        if "10048" in str(e) or "EADDRINUSE" in str(e).upper():
            logger.error("Port %d is already in use. Is another server instance running?", WEB_PORT)
        else:
            logger.error("Failed to start server: %s", e)
    finally:
        # Best-effort cleanup of background services and child processes.
        _shutdown_event.set()
        discovery_shutdown.set()
        try:
            client_manager.shutdown()
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Error while shutting down client processes: %s", exc)
        logger.info("Server stopped.")

if __name__ == '__main__':
    main()
