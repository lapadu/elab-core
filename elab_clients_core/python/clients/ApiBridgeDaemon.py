# pylint: disable=invalid-name
"""
E-Lab Local API Bridge Daemon.

Bridges external Python scripts (connected via ZeroMQ/Shared Memory) into the
E-Lab ecosystem. Start this daemon from the Library panel, then launch external
scripts (e.g. fir_filter_node.py) that connect via elab_api.LocalNode.
"""
import os
import sys
import logging
import signal
import argparse

# Add project root to path for imports
project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, project_root)

# Add the client directory as an import root for the shared-module fallback.
_clients_dir = os.path.dirname(os.path.abspath(__file__))
if _clients_dir not in sys.path:
    sys.path.insert(0, _clients_dir)

try:
    from elab_clients_core.python.shared.discovery import discover_dispatcher
except ImportError:
    def discover_dispatcher(*_args, **_kwargs):
        return None

from elab_bridge.bridge_daemon import BridgeDaemon

# --- CONFIGURATION ---
UDP_PORT = 5005
FALLBACK_URL = "http://127.0.0.1:5000"

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("API-Bridge")


def main() -> None:
    """Start the Bridge Daemon, auto-discovering the dispatcher."""
    parser = argparse.ArgumentParser(description="E-Lab Local API Bridge")
    parser.add_argument(
        "--dispatcher-url",
        default=os.environ.get("ELAB_DISPATCHER_URL"),
        help="Dispatcher URL (auto-discovered if omitted)",
    )
    parser.add_argument(
        "--control-port", type=int, default=5580,
        help="ZMQ control port (default: 5580)",
    )
    parser.add_argument(
        "--notify-port", type=int, default=5581,
        help="ZMQ notify port (default: 5581)",
    )
    args = parser.parse_args()

    # Discover dispatcher (same mechanism as other clients)
    dispatcher_url = args.dispatcher_url
    if not dispatcher_url:
        logger.info("Searching for E-Lab dispatcher via UDP discovery...")
        discovered = discover_dispatcher(udp_port=UDP_PORT, logger=logger, max_attempts=3)
        if discovered:
            dispatcher_url = discovered
            logger.info("Dispatcher found: %s", dispatcher_url)
        else:
            dispatcher_url = FALLBACK_URL
            logger.warning(
                "Discovery failed, using fallback: %s", dispatcher_url
            )

    daemon = BridgeDaemon(
        dispatcher_url=dispatcher_url,
        control_port=args.control_port,
        notify_port=args.notify_port,
    )

    signal.signal(signal.SIGINT, lambda *_: daemon.stop())
    signal.signal(signal.SIGTERM, lambda *_: daemon.stop())

    logger.info("Starting Local API Bridge → %s", dispatcher_url)
    logger.info("  Control Port: %d / Notify Port: %d", args.control_port, args.notify_port)
    logger.info("  External scripts can now connect via elab_api.LocalNode")
    daemon.run_forever()


if __name__ == "__main__":
    main()
