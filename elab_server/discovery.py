"""UDP discovery service to broadcast server information."""
import socket
import json
import logging
import ipaddress
import threading
from typing import Optional
from .config import UDP_PORT, WEB_PORT, UDP_TTL
from .app import get_ip_addresses
from ._version import __version__ as ELAB_VERSION

logger = logging.getLogger(__name__)

# Module-level shutdown signal so main.py can request a clean stop.
shutdown_event = threading.Event()
_discovery_thread: Optional[threading.Thread] = None

def get_broadcast_addresses():
    """Calculates broadcast addresses for all local IP addresses."""
    broadcast_addrs = set()
    local_ips = get_ip_addresses()

    for ip_str in local_ips:
        try:
            ip = ipaddress.IPv4Address(ip_str)
            # Calculate the /24 subnet, which is typical for local networks.
            network = ipaddress.IPv4Network(f"{ip}/24", strict=False)
            broadcast_addrs.add(str(network.broadcast_address))
        except ipaddress.AddressValueError:
            # Skip invalid IPs.
            continue

    # Always include the global broadcast address as well.
    broadcast_addrs.add("255.255.255.255")

    return list(broadcast_addrs)

def start_discovery_service():
    """Starts the UDP discovery service if not already running."""
    global _discovery_thread
    if _discovery_thread and _discovery_thread.is_alive():
        return
    shutdown_event.clear()
    _discovery_thread = threading.Thread(target=udp_discovery_service, daemon=True)
    _discovery_thread.start()

def stop_discovery_service():
    """Signals the UDP discovery service to stop."""
    shutdown_event.set()

def udp_discovery_service(stop_event: Optional[threading.Event] = None) -> None:
    """Broadcasts server information via UDP until *stop_event* is set."""
    stop_event = stop_event or shutdown_event

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, UDP_TTL)

    local_ips = get_ip_addresses()
    broadcast_addrs = get_broadcast_addresses()
    logger.info("📡 Discovery active on UDP %d (IPs: %s, Broadcasts: %s, TTL: %d)",
                UDP_PORT, ', '.join(local_ips), ', '.join(broadcast_addrs), UDP_TTL)

    beacon = json.dumps({
        "service": "elab-dispatcher",
        "version": ELAB_VERSION,
        "ips": local_ips,
        "port": WEB_PORT,
        "protocol": "socketio",
    }).encode('utf-8')

    try:
        while not stop_event.is_set():
            try:
                for broadcast_addr in broadcast_addrs:
                    sock.sendto(beacon, (broadcast_addr, UDP_PORT))
            except OSError as e:
                logger.error("Discovery error: %s", e)
                # Wait longer after an error before retrying.
                if stop_event.wait(5):
                    break
                continue
            # Interruptible sleep so shutdown is fast.
            if stop_event.wait(3):
                break
    finally:
        try:
            sock.close()
        except OSError:
            pass
        logger.info("📡 Discovery service stopped.")
