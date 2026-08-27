"""MSV90 DME (BMW F10 523i, N52B25) - IDENTIFICATION NOT YET CONFIRMED.

Target: the engine control unit of a 2011 F10 523i with the N52B25 engine. The
DME is *believed* to be an MSV90; that has not been confirmed by reading the
ECU, which is one of the first things this tool should be used to establish.

This class deliberately contains no MSV90-specific constants. Adding a DID,
byte layout, or scaling formula here before it has been verified would make the
tool report confident numbers that could be wrong, which is worse than
reporting nothing.

Live data is driven by ``definitions/signals.json``. That file is empty, so
:meth:`MSV90.live_data` currently has nothing verified to read, and says so.
"""

from __future__ import annotations

from typing import Any

from ..decoding.signals import DecodedValue, DefinitionRegistry, SignalDefinition
from ..exceptions import NotVerifiedError
from ..vehicle.ecu import ECU

ECU_NAME = "DME"


class MSV90(ECU):
    """The engine control unit.

    Args:
        address: Diagnostic address, or ``None`` when unverified.
        protocol: Protocol client, once one exists.
        definitions: Signal definitions. Defaults to the bundled
            ``signals.json``, filtered to this ECU.
    """

    def __init__(
        self,
        address: int | None = None,
        protocol: Any = None,
        definitions: DefinitionRegistry | None = None,
    ) -> None:
        super().__init__(
            name=ECU_NAME,
            address=address,
            protocol=protocol,
            description=(
                "Digital Motor Electronics, believed MSV90 (N52B25). "
                "Model not confirmed by an ECU read."
            ),
        )
        self._definitions = definitions or DefinitionRegistry.load_bundled(
            "signals.json"
        )

    # -- definitions ------------------------------------------------------

    @property
    def definitions(self) -> DefinitionRegistry:
        """Signal definitions available for this ECU."""
        return self._definitions

    def available_signals(self, *, include_unverified: bool = False) -> list[SignalDefinition]:
        """Signals that can be read.

        Args:
            include_unverified: Also return definitions that are still
                hypotheses. Their values are always labelled ``[UNVERIFIED]``.
        """
        if include_unverified:
            return list(self._definitions)
        return self._definitions.verified

    # -- read operations --------------------------------------------------

    def vin(self) -> str:
        """Read the vehicle identification number from the DME.

        Raises:
            NotVerifiedError: Always, until the protocol layer exists.
        """
        raise self._not_implemented("vin")

    def live_data(
        self,
        signals: list[str] | None = None,
        *,
        allow_unverified: bool = False,
    ) -> list[DecodedValue]:
        """Read live engine data.

        Raises:
            NotVerifiedError: No verified signal definitions exist, or the
                protocol layer is missing.
        """
        available = self.available_signals(include_unverified=allow_unverified)
        if not available:
            raise NotVerifiedError(
                "No verified live-data signals are defined for the DME. "
                "definitions/signals.json is intentionally empty because no "
                "identifier or scaling formula for this vehicle has been "
                "verified. Nothing will be displayed until one is."
            )
        raise self._not_implemented("live_data")
