"""The communication status ladder.

Rule 34 of the project specification: a successful TCP connection must never be
reported as "connected to the DME". Each rung of this ladder is only reached
when the layer below it has produced positive evidence, and every rung above
the transport layer stays unreachable until the corresponding protocol
behaviour has been verified against real hardware.
"""

from __future__ import annotations

from enum import IntEnum


class CommsLevel(IntEnum):
    """How far up the stack communication has actually been proven.

    The value is ordinal: a higher level implies every lower level was reached.
    """

    NONE = 0
    """Nothing established."""

    INTERFACE_PRESENT = 1
    """A usable network interface was found on the host."""

    ETHERNET_LINK = 2
    """The interface reports an active link and carries an IPv4 address."""

    TCP_CONNECTED = 3
    """A TCP socket to the configured host:port is open.

    This proves only that *something* accepted a TCP connection. It says
    nothing about BMW protocol support, and must not be described as being
    connected to the vehicle or to an ECU.
    """

    BMW_TRANSPORT = 4
    """The BMW Ethernet diagnostic transport accepted us.

    Not reachable yet: the framing/activation handshake is UNVERIFIED.
    """

    DIAGNOSTIC_SESSION = 5
    """A diagnostic session with the gateway is active. Not reachable yet."""

    ECU_RESPONDING = 6
    """A specific ECU returned a well-formed response. Not reachable yet."""

    DATA_DECODED = 7
    """An ECU response was decoded using a verified definition. Not yet."""


DESCRIPTIONS: dict[CommsLevel, str] = {
    CommsLevel.NONE: "Nothing established",
    CommsLevel.INTERFACE_PRESENT: "Network interface present",
    CommsLevel.ETHERNET_LINK: "Ethernet link active with an IPv4 address",
    CommsLevel.TCP_CONNECTED: "TCP socket open (NOT proof of vehicle comms)",
    CommsLevel.BMW_TRANSPORT: "BMW Ethernet diagnostic transport established",
    CommsLevel.DIAGNOSTIC_SESSION: "Diagnostic session active",
    CommsLevel.ECU_RESPONDING: "ECU returned a valid response",
    CommsLevel.DATA_DECODED: "ECU data decoded with a verified definition",
}


def describe(level: CommsLevel) -> str:
    """Return a human-readable description of a communication level."""
    return DESCRIPTIONS[level]
