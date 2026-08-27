"""F10 vehicle model.

Holds what is known about the target car and, later, the set of ECUs that were
actually discovered on it.

Discovery is not implemented: it needs the BMW protocol layer. Critically,
:meth:`F10Vehicle.discovered_ecus` returns only control units that genuinely
answered. The catalogue in ``definitions/ecus.json`` lists expected names with
no addresses and is never presented as discovered hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import VehicleConfig
from ..exceptions import NotVerifiedError
from .ecu import ECU


@dataclass(slots=True)
class F10Vehicle:
    """The vehicle under test.

    Attributes:
        config: Descriptive vehicle information from configuration.
        _ecus: Control units proven to be present, keyed by short name. Empty
            until discovery has actually run and succeeded.
    """

    config: VehicleConfig = field(default_factory=VehicleConfig)
    _ecus: dict[str, ECU] = field(default_factory=dict, repr=False)

    @property
    def description(self) -> str:
        """One-line description of the configured vehicle."""
        year = f" ({self.config.model_year})" if self.config.model_year else ""
        return (
            f"BMW {self.config.platform} {self.config.model}{year}, "
            f"engine {self.config.engine}, DME {self.config.dme}"
        )

    @property
    def discovered_ecus(self) -> list[ECU]:
        """Control units that have actually responded, in discovery order."""
        return list(self._ecus.values())

    def register_discovered(self, ecu: ECU) -> None:
        """Record an ECU that returned a valid response.

        Raises:
            ValueError: The ECU has never responded, so it is not discovered.
        """
        if not ecu.is_responding:
            raise ValueError(
                f"{ecu.name} has not returned a valid response and therefore "
                "cannot be registered as discovered"
            )
        self._ecus[ecu.name] = ecu

    def get_ecu(self, name: str) -> ECU | None:
        """Return a discovered ECU by short name, or ``None``."""
        return self._ecus.get(name.upper())

    def discover_ecus(self) -> list[ECU]:
        """Scan the vehicle for responding control units.

        Raises:
            NotVerifiedError: Always, until the protocol layer exists.
        """
        raise NotVerifiedError(
            "ECU discovery is not implemented. It requires verified BMW "
            "diagnostic addressing and gateway routing, neither of which has "
            "been established for this project. See docs/protocol.md."
        )
