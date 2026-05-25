"""Tests for elab_server.discovery helper functions."""
import ipaddress
import json
import socket
import threading
from unittest.mock import patch, MagicMock

from elab_server.discovery import get_broadcast_addresses, udp_discovery_service


class TestGetBroadcastAddresses:
    """Tests for broadcast address calculation."""

    def test_includes_global_broadcast(self):
        """Result must always include 255.255.255.255."""
        with patch('elab_server.discovery.get_ip_addresses', return_value=['192.168.1.100']):
            addrs = get_broadcast_addresses()
        assert "255.255.255.255" in addrs

    def test_computes_subnet_broadcast(self):
        """A /24 subnet for 192.168.1.100 should yield 192.168.1.255."""
        with patch('elab_server.discovery.get_ip_addresses', return_value=['192.168.1.100']):
            addrs = get_broadcast_addresses()
        assert "192.168.1.255" in addrs

    def test_multiple_ips(self):
        """Multiple local IPs should produce multiple broadcast addresses."""
        with patch('elab_server.discovery.get_ip_addresses', return_value=['10.0.0.5', '172.16.2.10']):
            addrs = get_broadcast_addresses()
        assert "10.0.0.255" in addrs
        assert "172.16.2.255" in addrs
        assert "255.255.255.255" in addrs

    def test_no_duplicates(self):
        """Duplicate entries should be eliminated (uses set internally)."""
        with patch('elab_server.discovery.get_ip_addresses', return_value=['192.168.1.1', '192.168.1.2']):
            addrs = get_broadcast_addresses()
        # Both yield same broadcast: 192.168.1.255
        assert addrs.count("192.168.1.255") == 1

    def test_empty_ip_list(self):
        """No IPs should still return global broadcast."""
        with patch('elab_server.discovery.get_ip_addresses', return_value=[]):
            addrs = get_broadcast_addresses()
        assert addrs == ["255.255.255.255"]

    def test_all_results_are_valid_ipv4(self):
        """All returned addresses must be valid IPv4."""
        with patch('elab_server.discovery.get_ip_addresses', return_value=['192.168.0.1']):
            addrs = get_broadcast_addresses()
        for addr in addrs:
            ipaddress.IPv4Address(addr)  # raises if invalid

    def test_invalid_ip_is_skipped(self):
        """Non-IPv4 strings should be silently skipped."""
        with patch('elab_server.discovery.get_ip_addresses', return_value=['not-an-ip', '10.0.0.1']):
            addrs = get_broadcast_addresses()
        assert "10.0.0.255" in addrs
        assert "255.255.255.255" in addrs


class TestUdpDiscoveryService:
    """Tests for the UDP beacon loop."""

    def test_sends_beacon_and_stops_on_event(self):
        """Service should send at least one beacon and stop when event is set."""
        stop = threading.Event()
        sent_packets = []

        mock_sock = MagicMock(spec=socket.socket)
        def fake_sendto(data, addr):
            sent_packets.append((data, addr))
            # Stop after first broadcast round
            stop.set()
        mock_sock.sendto.side_effect = fake_sendto

        with patch('elab_server.discovery.socket.socket', return_value=mock_sock), \
             patch('elab_server.discovery.get_ip_addresses', return_value=['192.168.1.10']):
            udp_discovery_service(stop_event=stop)

        assert len(sent_packets) > 0
        payload = json.loads(sent_packets[0][0].decode('utf-8'))
        assert payload['service'] == 'elab-dispatcher'
        assert payload['protocol'] == 'socketio'
        assert '192.168.1.10' in payload['ips']
        mock_sock.close.assert_called_once()

    def test_beacon_contains_version_and_port(self):
        """Beacon payload must include version and web port."""
        stop = threading.Event()

        mock_sock = MagicMock(spec=socket.socket)
        def capture_and_stop(data, addr):
            stop.set()
        mock_sock.sendto.side_effect = capture_and_stop

        with patch('elab_server.discovery.socket.socket', return_value=mock_sock), \
             patch('elab_server.discovery.get_ip_addresses', return_value=['10.0.0.1']):
            udp_discovery_service(stop_event=stop)

        payload = json.loads(mock_sock.sendto.call_args_list[0][0][0].decode('utf-8'))
        assert 'version' in payload
        assert 'port' in payload
        assert isinstance(payload['port'], int)

    def test_os_error_during_send_continues(self):
        """An OSError during sendto should not crash the service."""
        stop = threading.Event()
        call_count = 0

        mock_sock = MagicMock(spec=socket.socket)
        def flaky_sendto(data, addr):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Network unreachable")
            stop.set()
        mock_sock.sendto.side_effect = flaky_sendto

        # Patch stop_event.wait to return quickly instead of waiting 5s
        original_wait = threading.Event.wait
        def fast_wait(self_evt, timeout=None):
            return self_evt.is_set()

        with patch('elab_server.discovery.socket.socket', return_value=mock_sock), \
             patch('elab_server.discovery.get_ip_addresses', return_value=['10.0.0.1']), \
             patch.object(threading.Event, 'wait', fast_wait):
            udp_discovery_service(stop_event=stop)

        # Service recovered and sent again
        assert call_count >= 2
        mock_sock.close.assert_called_once()

    def test_uses_default_shutdown_event_when_none(self):
        """When no stop_event is given, the module-level shutdown_event is used."""
        from elab_server.discovery import shutdown_event
        shutdown_event.set()  # pre-set so loop exits immediately

        mock_sock = MagicMock(spec=socket.socket)
        with patch('elab_server.discovery.socket.socket', return_value=mock_sock), \
             patch('elab_server.discovery.get_ip_addresses', return_value=['10.0.0.1']):
            udp_discovery_service(stop_event=None)

        mock_sock.close.assert_called_once()
        shutdown_event.clear()  # cleanup

    def test_socket_close_oserror_suppressed(self):
        """OSError during socket.close() should be suppressed."""
        stop = threading.Event()
        stop.set()

        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.close.side_effect = OSError("close failed")

        with patch('elab_server.discovery.socket.socket', return_value=mock_sock), \
             patch('elab_server.discovery.get_ip_addresses', return_value=['10.0.0.1']):
            # Should not raise
            udp_discovery_service(stop_event=stop)

    def test_socket_options_are_set(self):
        """Socket must have SO_BROADCAST and IP_TTL configured."""
        stop = threading.Event()
        stop.set()

        mock_sock = MagicMock(spec=socket.socket)
        with patch('elab_server.discovery.socket.socket', return_value=mock_sock), \
             patch('elab_server.discovery.get_ip_addresses', return_value=['10.0.0.1']):
            udp_discovery_service(stop_event=stop)

        mock_sock.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        mock_sock.setsockopt.assert_any_call(socket.IPPROTO_IP, socket.IP_TTL, 1)
