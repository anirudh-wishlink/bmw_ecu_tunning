"""Transport layer.

Moves raw bytes between the host and the vehicle. Nothing in this package
knows about UDS, ECUs, DTCs, or BMW-specific behaviour.
"""

from .base import ConnectionState, PacketObserver, Transport
from .enet import ENETTransport, probe_tcp
from .ethernet import (
    InterfaceCandidate,
    IPv4Address,
    NetworkInterface,
    ethernet_interfaces,
    get_interface,
    is_macos,
    list_interfaces,
    rank_candidates,
    select_interface,
)
from .mock import MockTransport
from .packet import DiagnosticPacket, Direction, format_hex, parse_hex
from .replay import ReplayMismatchError, ReplayTransport, load_capture

__all__ = [
    "ConnectionState",
    "DiagnosticPacket",
    "Direction",
    "ENETTransport",
    "InterfaceCandidate",
    "IPv4Address",
    "MockTransport",
    "NetworkInterface",
    "PacketObserver",
    "ReplayMismatchError",
    "ReplayTransport",
    "Transport",
    "ethernet_interfaces",
    "format_hex",
    "get_interface",
    "is_macos",
    "list_interfaces",
    "load_capture",
    "parse_hex",
    "probe_tcp",
    "rank_candidates",
    "select_interface",
]
