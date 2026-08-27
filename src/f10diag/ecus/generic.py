"""Generic ECU implementation.

Used for a control unit that responded but has no dedicated class yet. It
provides no ECU-specific decoding: whatever comes back is kept as raw bytes and
displayed as raw bytes.
"""

from __future__ import annotations

from typing import Any

from ..vehicle.ecu import ECU


class GenericECU(ECU):
    """An ECU with no model-specific knowledge attached.

    Args:
        name: Short name, e.g. ``"DSC"``.
        address: Diagnostic address, or ``None`` when unverified.
        protocol: Protocol client, once one exists.
    """

    def __init__(
        self,
        name: str,
        address: int | None = None,
        protocol: Any = None,
    ) -> None:
        super().__init__(
            name=name,
            address=address,
            protocol=protocol,
            description="Generic control unit, no model-specific decoding",
        )
