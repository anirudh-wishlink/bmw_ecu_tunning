"""ISO-TP layer - NOT IMPLEMENTED YET, AND POSSIBLY NOT NEEDED.

Status: placeholder.

ISO-TP (ISO 15765-2) exists to segment long payloads across short CAN frames.
Whether it is needed here depends entirely on the transport that turns out to
be in use:

TODO: VERIFY - does the BMW Ethernet diagnostic transport carry whole
    diagnostic payloads, making ISO-TP segmentation unnecessary above it? Or
    does it tunnel CAN-sized frames that must be reassembled?

Implementing a segmentation layer before that question is answered risks
building a layer that is either unused or subtly wrong for this vehicle, so it
is deliberately deferred to a later phase.

If it does turn out to be required, the implementation must cover Single Frame,
First Frame, Consecutive Frame, Flow Control, segmentation, reassembly,
sequence-number validation, separation-time and block-size handling, timeouts,
and maximum payload length. It must stay free of BMW-specific behaviour.
"""

from __future__ import annotations

from ..exceptions import NotVerifiedError

__all__ = ["IsoTpLayer"]


class IsoTpLayer:
    """Placeholder for a future ISO-TP implementation."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotVerifiedError(
            "The ISO-TP layer is not implemented. It is unverified whether the "
            "BMW Ethernet diagnostic transport requires ISO-TP segmentation at "
            "all. See docs/protocol.md."
        )
