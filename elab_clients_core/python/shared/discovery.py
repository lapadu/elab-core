"""Shared UDP discovery helpers for Python clients."""

from __future__ import annotations

import json
import socket
from typing import Any


def get_local_ips() -> set[str]:
    """Return a set of IP addresses bound to this machine."""
    local_ips: set[str] = set()
    try:
        hostname = socket.gethostname()
        _, _, ip_list = socket.gethostbyname_ex(hostname)
        local_ips.update(ip_list)
    except (socket.gaierror, OSError):
        pass

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(('8.8.8.8', 80))
        local_ips.add(sock.getsockname()[0])
        sock.close()
    except OSError:
        pass

    local_ips.add('127.0.0.1')
    return local_ips


def _candidate_ips(beacon: dict[str, Any], prefer_non_loopback: bool) -> list[str]:
    ips = [ip for ip in beacon.get('ips', [beacon.get('ip')]) if ip]
    if prefer_non_loopback:
        return sorted(ips, key=lambda ip: ip.startswith('127.'))
    return ips


def _probe_url(ip: str, port: int, local_ips: set[str]) -> tuple[str, bool]:
    effective_ip = '127.0.0.1' if ip in local_ips else ip
    url = f"http://{effective_ip}:{port}"
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(1.0)
        is_reachable = probe.connect_ex((effective_ip, port)) == 0
        probe.close()
        return url, is_reachable
    except OSError:
        return url, False


def discover_dispatcher(
    udp_port: int,
    logger: Any,
    max_attempts: int = 5,
    timeout_sec: float = 2.0,
    prefer_non_loopback: bool = False,
) -> str | None:
    """Discover dispatcher via UDP beacons and return its HTTP base URL."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.bind(('', udp_port))
        sock.settimeout(timeout_sec)

        for attempt in range(max_attempts):
            logger.info(
                "🔍 Searching for dispatcher on UDP port %s (attempt %d/%d)...",
                udp_port,
                attempt + 1,
                max_attempts,
            )
            try:
                data, addr = sock.recvfrom(1024)
                beacon = json.loads(data.decode('utf-8'))
                if beacon.get('service') != 'elab-dispatcher':
                    continue

                ips = _candidate_ips(beacon, prefer_non_loopback)
                port = beacon.get('port', 5000)
                local_ips = get_local_ips()

                for ip in ips:
                    url, is_reachable = _probe_url(ip, port, local_ips)
                    logger.info("✅ Dispatcher found at: %s", url)
                    if is_reachable:
                        return url
                    logger.warning("❌ IP %s unreachable, trying next candidate...", ip)

                if ips:
                    fallback_ip = ips[0]
                    effective_ip = '127.0.0.1' if fallback_ip in local_ips else fallback_ip
                    return f"http://{effective_ip}:{port}"
                return f"http://{addr[0]}:{port}"

            except socket.timeout:
                continue
            except json.JSONDecodeError:
                continue

        logger.error("❌ No server found. Is server.py running?")
        return None

    except socket.error as exc:
        logger.error("❌ Discovery error: %s", exc)
        return None
    finally:
        sock.close()
