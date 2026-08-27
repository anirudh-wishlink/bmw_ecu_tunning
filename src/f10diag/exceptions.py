"""Exception hierarchy for f10diag.

Every failure mode that the application can encounter has a descriptive
exception so that callers (and the CLI) can react without inspecting message
strings.
"""

from __future__ import annotations


class F10DiagError(Exception):
    """Base class for all f10diag errors."""


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


class ConfigError(F10DiagError):
    """Configuration file is missing, malformed, or semantically invalid."""


class UnverifiedParameterError(ConfigError):
    """A required parameter has no verified value and none was supplied.

    Raised instead of silently substituting a guessed BMW protocol value such
    as a gateway IP address or TCP port.
    """


# --------------------------------------------------------------------------
# Safety
# --------------------------------------------------------------------------


class SafetyViolationError(F10DiagError):
    """An operation was attempted that the current safety mode forbids."""


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


class TransportError(F10DiagError):
    """Base class for transport-layer failures."""


class InterfaceNotFoundError(TransportError):
    """The requested network interface does not exist on this host."""


class InterfaceUnavailableError(TransportError):
    """The interface exists but is not usable (down, no link, no address)."""


class NotConnectedError(TransportError):
    """An I/O operation was attempted while the transport was disconnected."""


class ConnectionFailedError(TransportError):
    """The transport could not establish a connection."""


class ConnectionLostError(TransportError):
    """An established connection was closed or reset by the peer."""


class TransportTimeoutError(TransportError):
    """No data arrived within the configured receive timeout."""


# --------------------------------------------------------------------------
# Protocol (used by later phases; defined here so the hierarchy is complete)
# --------------------------------------------------------------------------


class ProtocolError(F10DiagError):
    """Base class for protocol-layer failures."""


class MalformedPacketError(ProtocolError):
    """Received bytes could not be parsed as a valid protocol unit."""


class UnexpectedResponseError(ProtocolError):
    """A syntactically valid response did not match the pending request."""


class UnsupportedServiceError(ProtocolError):
    """The ECU rejected the service as not supported."""


class UnsupportedIdentifierError(ProtocolError):
    """The ECU rejected the data identifier as not supported."""


class ECUNotRespondingError(ProtocolError):
    """No response was received from the addressed ECU."""


class ECUBusyError(ProtocolError):
    """The ECU reported that it is busy and the request should be repeated."""


class NotVerifiedError(F10DiagError):
    """The requested functionality depends on unverified protocol details.

    Raised by placeholder implementations so that unfinished layers fail
    loudly and explicitly instead of returning fabricated data.
    """
