"""UDS layer - NOT IMPLEMENTED YET (Phase 5+).

Status: placeholder.

This module exists so the architecture is visible and so that nothing else in
the codebase has to guess where UDS will live. It contains no service
identifiers, no request builders, and no response parsers, because none of the
values that would be needed have been verified for this vehicle yet, and the
project rules forbid inventing them to make code look finished.

Before this module can be written, the following must be established and
written down in ``docs/protocol.md`` with a source:

TODO: VERIFY - whether the F10 diagnostic gateway speaks UDS (ISO 14229) over
    the Ethernet transport at all, or a BMW-specific service set.
TODO: VERIFY - the exact service identifiers accepted by the target ECUs.
TODO: VERIFY - the positive and negative response formats actually observed.
TODO: VERIFY - which diagnostic session, if any, is required before a read.
TODO: VERIFY - whether TesterPresent is needed to hold a session open, and at
    what interval.

Scope restriction that applies when this module is implemented: read-only
services only. SecurityAccess, RoutineControl, WriteDataByIdentifier, ECUReset,
and ClearDiagnosticInformation are out of scope until a write safety gate has
been designed and separately reviewed.
"""

from __future__ import annotations

from ..exceptions import NotVerifiedError

__all__ = ["UDSClient"]


class UDSClient:
    """Placeholder for the future UDS client.

    Every method raises :class:`~f10diag.exceptions.NotVerifiedError` so that an
    unfinished layer fails loudly instead of returning fabricated data.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotVerifiedError(
            "The UDS layer is not implemented. The service identifiers and "
            "response formats used by the F10 diagnostic gateway have not been "
            "verified for this project. See docs/protocol.md."
        )
