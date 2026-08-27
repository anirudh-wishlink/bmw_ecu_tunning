"""BMW-specific diagnostic protocol layer - NOT IMPLEMENTED YET (Phase 3).

Status: placeholder.

This is where BMW-specific framing, activation, routing, and addressing will
live once they have been verified. Keeping them here, rather than inside the
generic UDS or transport code, is what will let the framework be extended to
other F-series cars later.

Nothing is implemented because every value the layer needs is currently
UNVERIFIED for this project:

TODO: VERIFY - the diagnostic gateway's IPv4 address and how the host is
    expected to obtain an address on that link.
TODO: VERIFY - the TCP port used for diagnostic requests.
TODO: VERIFY - whether any UDP announcement or discovery exchange precedes the
    TCP connection, and on which port.
TODO: VERIFY - the header layout of a diagnostic message on this transport
    (field order, field widths, byte order, length semantics).
TODO: VERIFY - the activation/registration exchange, if any, that must succeed
    before the gateway will route requests, and what a rejection looks like.
TODO: VERIFY - the source address a tester is expected to use.
TODO: VERIFY - the target addresses of the F10's control units.
TODO: VERIFY - the gateway's timeout and keep-alive behaviour.

Until these are answered by observation or by an authoritative source, the tool
cannot claim to reach the vehicle: :class:`~f10diag.status.CommsLevel` stops at
``TCP_CONNECTED``.

How to establish them safely: run ``f10diag capture`` while a known-good
diagnostic tool talks to the car, then analyse the recording. Record each
finding in ``docs/protocol.md`` under VERIFIED with the evidence.
"""

from __future__ import annotations

from ..exceptions import NotVerifiedError

__all__ = ["BMWDiagnosticSession", "BMWECUAddress", "BMWRouting", "BMWIdentification"]


class _UnverifiedComponent:
    """Base for placeholders that must not be instantiated yet."""

    _WHAT = "This BMW protocol component"

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotVerifiedError(
            f"{self._WHAT} is not implemented: the BMW Ethernet diagnostic "
            "protocol details it depends on are UNVERIFIED for this project. "
            "See the TODO list in f10diag/protocols/bmw.py and docs/protocol.md."
        )


class BMWDiagnosticSession(_UnverifiedComponent):
    """Placeholder for the gateway session/activation handshake."""

    _WHAT = "The BMW diagnostic session"


class BMWECUAddress(_UnverifiedComponent):
    """Placeholder for BMW diagnostic addressing."""

    _WHAT = "BMW ECU addressing"


class BMWRouting(_UnverifiedComponent):
    """Placeholder for gateway routing of requests to individual ECUs."""

    _WHAT = "BMW gateway routing"


class BMWIdentification(_UnverifiedComponent):
    """Placeholder for BMW ECU identification requests and responses."""

    _WHAT = "BMW ECU identification"
