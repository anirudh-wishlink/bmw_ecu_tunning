"""Tests for interface discovery and the ENET transport.

The transport tests run against a local TCP echo server on the loopback
interface. That exercises real socket behaviour, timeouts, and disconnect
handling without a vehicle. It proves the transport works; it proves nothing
about BMW protocol behaviour, and no BMW bytes appear anywhere in this file.
"""

from __future__ import annotations

import socket
import threading

import pytest

from f10diag.config import ENETConfig
from f10diag.exceptions import (
    ConnectionFailedError,
    ConnectionLostError,
    InterfaceNotFoundError,
    InterfaceUnavailableError,
    NotConnectedError,
    TransportTimeoutError,
    UnverifiedParameterError,
)
from f10diag.status import CommsLevel
from f10diag.transport.base import ConnectionState
from f10diag.transport.enet import ENETTransport, probe_tcp
from f10diag.transport.ethernet import (
    IPv4Address,
    NetworkInterface,
    ethernet_interfaces,
    list_interfaces,
    parse_hardware_ports,
    parse_ifconfig,
    rank_candidates,
)

IFCONFIG_SAMPLE = """\
lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\toptions=1203<RXCSUM,TXCSUM,TXSTATUS,SW_TIMESTAMP>
\tinet 127.0.0.1 netmask 0xff000000
\tinet6 ::1 prefixlen 128
\tnd6 options=201<PERFORMNUD,DAD>
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether a1:b2:c3:d4:e5:f6
\tinet6 fe80::1%en0 prefixlen 64 secured scopeid 0xb
\tinet 192.168.1.42 netmask 0xffffff00 broadcast 192.168.1.255
\tmedia: autoselect
\tstatus: active
en7: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether 11:22:33:44:55:66
\tinet 169.254.10.20 netmask 0xffff0000 broadcast 169.254.255.255
\tmedia: autoselect (1000baseT <full-duplex>)
\tstatus: active
en8: flags=8863<UP,BROADCAST,SMART,SIMPLEX,MULTICAST> mtu 1500
\tether 77:88:99:aa:bb:cc
\tmedia: autoselect (none)
\tstatus: inactive
utun0: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380
\tinet6 fe80::2%utun0 prefixlen 64 scopeid 0x10
"""

NETWORKSETUP_SAMPLE = """\
Hardware Port: Wi-Fi
Device: en0
Ethernet Address: a1:b2:c3:d4:e5:f6

Hardware Port: USB 10/100/1000 LAN
Device: en7
Ethernet Address: 11:22:33:44:55:66

Hardware Port: Thunderbolt Ethernet Slot 0
Device: en8
Ethernet Address: 77:88:99:aa:bb:cc

VLAN Configurations
===================
"""


def _sample_interfaces() -> list[NetworkInterface]:
    ports = parse_hardware_ports(NETWORKSETUP_SAMPLE)
    return [
        NetworkInterface(
            name=iface.name,
            flags=iface.flags,
            mtu=iface.mtu,
            mac=iface.mac,
            ipv4=iface.ipv4,
            ipv6=iface.ipv6,
            status=iface.status,
            media=iface.media,
            hardware_port=ports.get(iface.name),
        )
        for iface in parse_ifconfig(IFCONFIG_SAMPLE)
    ]


class TestIfconfigParsing:
    def test_finds_every_interface(self):
        names = [iface.name for iface in parse_ifconfig(IFCONFIG_SAMPLE)]
        assert names == ["lo0", "en0", "en7", "en8", "utun0"]

    def test_parses_addresses_and_mac(self):
        en7 = next(i for i in parse_ifconfig(IFCONFIG_SAMPLE) if i.name == "en7")
        assert en7.mac == "11:22:33:44:55:66"
        assert en7.ipv4[0].address == "169.254.10.20"
        assert en7.ipv4[0].netmask == "255.255.0.0"
        assert en7.status == "active"
        assert en7.mtu == 1500

    def test_converts_hex_netmask_to_dotted_quad(self):
        en0 = next(i for i in parse_ifconfig(IFCONFIG_SAMPLE) if i.name == "en0")
        assert en0.ipv4[0].netmask == "255.255.255.0"

    def test_flags_are_captured(self):
        lo0 = next(i for i in parse_ifconfig(IFCONFIG_SAMPLE) if i.name == "lo0")
        assert lo0.is_loopback
        assert lo0.is_up

    def test_interface_without_address_has_no_ipv4(self):
        en8 = next(i for i in parse_ifconfig(IFCONFIG_SAMPLE) if i.name == "en8")
        assert en8.ipv4 == ()
        assert not en8.has_link

    def test_unknown_lines_are_ignored(self):
        assert parse_ifconfig("garbage\nmore garbage\n") == []

    def test_empty_input_yields_nothing(self):
        assert parse_ifconfig("") == []


class TestHardwarePortParsing:
    def test_maps_device_to_port_name(self):
        ports = parse_hardware_ports(NETWORKSETUP_SAMPLE)
        assert ports["en0"] == "Wi-Fi"
        assert ports["en7"] == "USB 10/100/1000 LAN"

    def test_trailing_sections_are_ignored(self):
        assert "VLAN Configurations" not in parse_hardware_ports(NETWORKSETUP_SAMPLE)


class TestClassification:
    def test_wifi_is_not_ethernet_like(self):
        en0 = next(i for i in _sample_interfaces() if i.name == "en0")
        assert en0.is_wireless
        assert not en0.is_ethernet_like

    def test_usb_adapter_is_ethernet_like(self):
        en7 = next(i for i in _sample_interfaces() if i.name == "en7")
        assert en7.is_ethernet_like

    def test_loopback_and_tunnels_are_excluded(self):
        names = [i.name for i in ethernet_interfaces(_sample_interfaces())]
        assert "lo0" not in names
        assert "utun0" not in names

    def test_link_local_address_is_detected(self):
        en7 = next(i for i in _sample_interfaces() if i.name == "en7")
        assert en7.link_local_ipv4 is not None
        assert en7.link_local_ipv4.address == "169.254.10.20"

    def test_routable_address_is_not_link_local(self):
        assert not IPv4Address("192.168.1.42").is_link_local


class TestRanking:
    def test_active_link_local_adapter_ranks_first(self):
        ranked = rank_candidates(_sample_interfaces())
        assert ranked[0].interface.name == "en7"

    def test_inactive_adapter_is_ranked_but_warned_about(self):
        ranked = rank_candidates(_sample_interfaces())
        en8 = next(c for c in ranked if c.interface.name == "en8")
        assert any("no link" in warning for warning in en8.warnings)

    def test_ranking_explains_itself(self):
        top = rank_candidates(_sample_interfaces())[0]
        assert top.reasons, "a ranked candidate must say why it was ranked"

    def test_no_ethernet_interfaces_yields_no_candidates(self):
        wifi_only = [i for i in _sample_interfaces() if i.name == "en0"]
        assert rank_candidates(wifi_only) == []


class TestENETConfigValidation:
    def test_missing_host_and_port_is_rejected(self):
        with pytest.raises(UnverifiedParameterError) as excinfo:
            ENETConfig().validate_for_connection()
        # The message must explain the refusal, not silently pick a default.
        assert "UNVERIFIED" in str(excinfo.value)

    def test_missing_port_alone_is_rejected(self):
        with pytest.raises(UnverifiedParameterError, match="port"):
            ENETConfig(host="127.0.0.1").validate_for_connection()

    def test_complete_config_is_accepted(self):
        ENETConfig(host="127.0.0.1", port=1234).validate_for_connection()

    def test_transport_refuses_to_connect_without_host(self):
        with pytest.raises(UnverifiedParameterError):
            ENETTransport(ENETConfig(interface="lo0")).connect()


# --------------------------------------------------------------------------
# Local echo server fixtures
# --------------------------------------------------------------------------


class EchoServer:
    """A minimal TCP server on the loopback interface.

    Args:
        echo: Send received bytes back.
        drop_immediately: Close each connection as soon as it is accepted.
        greeting: Bytes to send once, right after accepting.
    """

    def __init__(
        self,
        *,
        echo: bool = True,
        drop_immediately: bool = False,
        greeting: bytes | None = None,
    ) -> None:
        self._echo = echo
        self._drop = drop_immediately
        self._greeting = greeting
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(1)
        self.host, self.port = self._socket.getsockname()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self._socket.settimeout(0.2)
        while not self._stop.is_set():
            try:
                connection, _ = self._socket.accept()
            except (socket.timeout, OSError):
                continue
            with connection:
                if self._drop:
                    continue
                connection.settimeout(0.5)
                if self._greeting:
                    connection.sendall(self._greeting)
                while not self._stop.is_set():
                    try:
                        data = connection.recv(4096)
                    except (socket.timeout, OSError):
                        break
                    if not data:
                        break
                    if self._echo:
                        connection.sendall(data)

    def close(self) -> None:
        self._stop.set()
        self._socket.close()
        self._thread.join(timeout=2)


def _loopback_interface_name() -> str | None:
    for iface in list_interfaces():
        if iface.is_loopback:
            return iface.name
    return None


@pytest.fixture
def loopback() -> str:
    name = _loopback_interface_name()
    if name is None:
        pytest.skip("no loopback interface reported by this host")
    return name


@pytest.fixture
def echo_server():
    server = EchoServer()
    yield server
    server.close()


def _config(server: EchoServer, interface: str, **overrides) -> ENETConfig:
    values = {
        "interface": interface,
        "host": server.host,
        "port": server.port,
        "connect_timeout": 2.0,
        "receive_timeout": 1.0,
    }
    values.update(overrides)
    return ENETConfig(**values)


class TestENETTransportInterfaceResolution:
    def test_unknown_interface_is_rejected(self):
        config = ENETConfig(interface="definitely-not-real0", host="127.0.0.1", port=1)
        with pytest.raises(InterfaceNotFoundError):
            ENETTransport(config).connect()

    def test_interface_without_link_is_rejected(self, monkeypatch):
        down = NetworkInterface(name="en99", flags=("UP",), mac="00:11:22:33:44:55",
                                status="inactive")
        monkeypatch.setattr(
            "f10diag.transport.enet.select_interface", lambda _name: down
        )
        config = ENETConfig(interface="en99", host="127.0.0.1", port=1)
        with pytest.raises(InterfaceUnavailableError, match="no active link"):
            ENETTransport(config).connect()


class TestENETTransportIO:
    def test_connect_reports_tcp_level_only(self, echo_server, loopback):
        transport = ENETTransport(_config(echo_server, loopback))
        transport.connect()
        try:
            assert transport.is_connected()
            assert transport.state is ConnectionState.CONNECTED
            # Rule 34: an open socket must never claim more than TCP_CONNECTED.
            assert transport.comms_level is CommsLevel.TCP_CONNECTED
            assert transport.comms_level < CommsLevel.ECU_RESPONDING
        finally:
            transport.disconnect()

    def test_send_and_receive_round_trip(self, echo_server, loopback):
        with ENETTransport(_config(echo_server, loopback)) as transport:
            assert transport.send(b"\x01\x02\x03") == 3
            assert transport.receive() == b"\x01\x02\x03"
            assert transport.bytes_sent == 3
            assert transport.bytes_received == 3

    def test_packets_are_observed_in_both_directions(self, echo_server, loopback):
        observed = []
        transport = ENETTransport(_config(echo_server, loopback))
        transport.add_packet_observer(observed.append)
        with transport:
            transport.send(b"\xaa")
            transport.receive()
        assert [packet.direction.value for packet in observed] == ["TX", "RX"]
        assert observed[0].transport["peer"] == f"{echo_server.host}:{echo_server.port}"

    def test_observer_failure_does_not_break_io(self, echo_server, loopback):
        def broken(_packet):
            raise RuntimeError("observer exploded")

        transport = ENETTransport(_config(echo_server, loopback))
        transport.add_packet_observer(broken)
        with transport:
            assert transport.send(b"\x01") == 1
        assert "observer failed" in (transport.last_error or "")

    def test_receive_exactly_reassembles(self, echo_server, loopback):
        with ENETTransport(_config(echo_server, loopback)) as transport:
            transport.send(bytes(range(16)))
            assert transport.receive_exactly(16) == bytes(range(16))

    def test_receive_times_out_when_peer_is_silent(self, loopback):
        server = EchoServer(echo=False)
        try:
            with ENETTransport(_config(server, loopback, receive_timeout=0.2)) as t:
                t.send(b"\x01")
                with pytest.raises(TransportTimeoutError, match="0.2"):
                    t.receive()
        finally:
            server.close()

    def test_receive_exactly_reports_how_much_arrived(self, loopback):
        # A truncated payload must say what was received, not just "timeout".
        server = EchoServer(echo=False, greeting=b"\x01\x02")
        try:
            with ENETTransport(_config(server, loopback, receive_timeout=0.3)) as t:
                with pytest.raises(TransportTimeoutError, match="Received 2 of 4 bytes"):
                    t.receive_exactly(4)
        finally:
            server.close()

    def test_peer_closing_raises_connection_lost(self, loopback):
        server = EchoServer(drop_immediately=True)
        try:
            transport = ENETTransport(_config(server, loopback))
            transport.connect()
            with pytest.raises(ConnectionLostError):
                transport.receive()
            assert not transport.is_connected()
        finally:
            server.close()

    def test_io_before_connect_is_rejected(self, echo_server, loopback):
        transport = ENETTransport(_config(echo_server, loopback))
        with pytest.raises(NotConnectedError):
            transport.send(b"\x01")
        with pytest.raises(NotConnectedError):
            transport.receive()

    def test_connect_to_closed_port_fails(self, loopback):
        server = EchoServer()
        host, port = server.host, server.port
        server.close()
        transport = ENETTransport(
            ENETConfig(interface=loopback, host=host, port=port, connect_timeout=1.0)
        )
        with pytest.raises(ConnectionFailedError):
            transport.connect()
        assert transport.state is ConnectionState.ERROR

    def test_disconnect_is_idempotent(self, echo_server, loopback):
        transport = ENETTransport(_config(echo_server, loopback))
        transport.connect()
        transport.disconnect()
        transport.disconnect()
        assert not transport.is_connected()

    def test_reconnect_restores_the_link(self, echo_server, loopback):
        transport = ENETTransport(_config(echo_server, loopback))
        transport.connect()
        transport.reconnect()
        try:
            assert transport.is_connected()
            transport.send(b"\x07")
            assert transport.receive() == b"\x07"
        finally:
            transport.disconnect()

    def test_reconnect_gives_up_after_configured_attempts(self, loopback):
        server = EchoServer()
        host, port = server.host, server.port
        server.close()
        config = ENETConfig(
            interface=loopback,
            host=host,
            port=port,
            connect_timeout=0.5,
            reconnect_attempts=1,
            reconnect_delay=0.0,
        )
        with pytest.raises(ConnectionFailedError):
            ENETTransport(config).reconnect()

    def test_interface_info_describes_the_transport(self, echo_server, loopback):
        with ENETTransport(_config(echo_server, loopback)) as transport:
            info = transport.get_interface_info()
        assert info["transport"] == "enet-tcp"
        assert info["comms_level"] == "TCP_CONNECTED"
        assert info["host"] == echo_server.host


class TestProbeTCP:
    def test_open_port_is_reachable(self, echo_server):
        reachable, detail = probe_tcp(echo_server.host, echo_server.port, timeout=1.0)
        assert reachable
        assert "handshake" in detail

    def test_closed_port_is_not_reachable(self):
        server = EchoServer()
        host, port = server.host, server.port
        server.close()
        reachable, detail = probe_tcp(host, port, timeout=1.0)
        assert not reachable
        assert detail
