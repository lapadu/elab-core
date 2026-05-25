"""Tests for elab_clients_core.python.shared.discovery."""

# Helper stubs intentionally call private helpers of the module under test.
# pylint: disable=missing-function-docstring,protected-access

import json
import socket as std_socket
from unittest.mock import MagicMock

from elab_clients_core.python.shared import discovery


def _empty_local_ips():
    return set()


class _FakeUDPSocket:
    def __init__(self, recv_events=None, bind_exc=None):
        self._recv_events = list(recv_events or [])
        self._bind_exc = bind_exc
        self.closed = False

    def setsockopt(self, *_args, **_kwargs):
        return None

    def bind(self, _addr):
        if self._bind_exc is not None:
            raise self._bind_exc

    def settimeout(self, _timeout):
        return None

    def recvfrom(self, _size):
        if not self._recv_events:
            raise std_socket.timeout()
        event = self._recv_events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event

    def connect(self, _addr):
        return None

    def getsockname(self):
        return ("10.0.0.99", 1234)

    def close(self):
        self.closed = True


class _FakeTCPSocket:
    def __init__(self, connect_result=0, raise_on_connect=False):
        self._connect_result = connect_result
        self._raise_on_connect = raise_on_connect
        self.closed = False

    def settimeout(self, _timeout):
        return None

    def connect_ex(self, _addr):
        if self._raise_on_connect:
            raise OSError("connect failed")
        return self._connect_result

    def close(self):
        self.closed = True


def test_get_local_ips_includes_loopback_and_detected_ip(monkeypatch):
    """get_local_ips should include localhost and resolved local addresses."""
    monkeypatch.setattr(discovery.socket, "gethostname", lambda: "host")
    monkeypatch.setattr(
        discovery.socket,
        "gethostbyname_ex",
        lambda _h: ("host", [], ["192.168.1.20", "10.1.1.5"]),
    )

    fake_udp = _FakeUDPSocket()
    monkeypatch.setattr(discovery.socket, "socket", lambda *_a, **_k: fake_udp)

    ips = discovery.get_local_ips()

    assert "127.0.0.1" in ips
    assert "192.168.1.20" in ips
    assert "10.1.1.5" in ips
    assert "10.0.0.99" in ips


def test_candidate_ips_prefers_non_loopback():
    """When requested, loopback addresses should be sorted after normal IPs."""
    beacon = {"ips": ["127.0.0.1", "192.168.0.10", "10.0.0.2"]}
    out = discovery._candidate_ips(beacon, prefer_non_loopback=True)
    assert out[:2] == ["192.168.0.10", "10.0.0.2"]
    assert out[-1] == "127.0.0.1"


def test_probe_url_maps_local_to_loopback_and_reports_reachability(monkeypatch):
    """_probe_url should map local IP to localhost and report probe result."""
    monkeypatch.setattr(discovery.socket, "socket", lambda *_a, **_k: _FakeTCPSocket(0))
    url, ok = discovery._probe_url("192.168.0.7", 5000, {"192.168.0.7"})
    assert url == "http://127.0.0.1:5000"
    assert ok is True


def test_discover_dispatcher_returns_reachable_url(monkeypatch):
    """discover_dispatcher should return the first reachable dispatcher URL."""
    beacon = {"service": "elab-dispatcher", "ips": ["10.0.0.8"], "port": 6000}
    recv = [(json.dumps(beacon).encode("utf-8"), ("10.0.0.8", 5005))]
    udp = _FakeUDPSocket(recv_events=recv)

    def fake_socket(_family, sock_type):
        if sock_type == discovery.socket.SOCK_DGRAM:
            return udp
        return _FakeTCPSocket(connect_result=0)

    monkeypatch.setattr(discovery.socket, "socket", fake_socket)
    monkeypatch.setattr(discovery, "get_local_ips", _empty_local_ips)

    logger = MagicMock()
    url = discovery.discover_dispatcher(5005, logger, max_attempts=1)

    assert url == "http://10.0.0.8:6000"
    assert udp.closed is True


def test_discover_dispatcher_fallback_to_sender_addr_when_no_ips(monkeypatch):
    """If beacon has no IP list, sender address should be used as fallback."""
    beacon = {"service": "elab-dispatcher", "port": 7000}
    recv = [(json.dumps(beacon).encode("utf-8"), ("172.16.1.9", 5005))]
    udp = _FakeUDPSocket(recv_events=recv)

    monkeypatch.setattr(
        discovery.socket,
        "socket",
        lambda _f, sock_type: udp if sock_type == discovery.socket.SOCK_DGRAM else _FakeTCPSocket(1),
    )
    monkeypatch.setattr(discovery, "get_local_ips", _empty_local_ips)

    logger = MagicMock()
    url = discovery.discover_dispatcher(5005, logger, max_attempts=1)

    assert url == "http://172.16.1.9:7000"


def test_discover_dispatcher_returns_none_after_timeouts(monkeypatch):
    """Timeout-only discovery cycles should end with None and an error log."""
    udp = _FakeUDPSocket(recv_events=[std_socket.timeout(), std_socket.timeout()])

    monkeypatch.setattr(
        discovery.socket,
        "socket",
        lambda _f, sock_type: udp if sock_type == discovery.socket.SOCK_DGRAM else _FakeTCPSocket(1),
    )

    logger = MagicMock()
    url = discovery.discover_dispatcher(5005, logger, max_attempts=2)

    assert url is None
    logger.error.assert_called()


def test_discover_dispatcher_returns_none_on_bind_error(monkeypatch):
    """Socket setup errors should be handled and return None."""
    udp = _FakeUDPSocket(bind_exc=std_socket.error("bind failed"))
    monkeypatch.setattr(
        discovery.socket,
        "socket",
        lambda _f, sock_type: udp if sock_type == discovery.socket.SOCK_DGRAM else _FakeTCPSocket(0),
    )

    logger = MagicMock()
    assert discovery.discover_dispatcher(5005, logger, max_attempts=1) is None
    logger.error.assert_called()
