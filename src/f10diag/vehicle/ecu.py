"""Generic ECU abstraction and DTC container.

The data containers here are complete: they hold whatever an ECU returned and
present it honestly, including when nothing is known about its meaning.

The *operations* (:meth:`ECU.identification`, :meth:`ECU.read_dtcs`,
:meth:`ECU.read_data_identifier`) are not implemented, because they depend on
the protocol layer, which depends on BMW details that are UNVERIFIED. They
raise :class:`~f10diag.exceptions.NotVerifiedError` rather than returning
plausible-looking data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..exceptions import NotVerifiedError
from ..status import CommsLevel

UNKNOWN_DTC_DESCRIPTION = "Unknown BMW DTC"


@dataclass(frozen=True, slots=True)
class DTC:
    """One diagnostic trouble code exactly as reported by an ECU.

    Attributes:
        code: The code as reported, rendered as an uppercase hex string. It is
            not translated into a P/B/C/U code unless that mapping has been
            verified for this platform.
        raw_data: The bytes the ECU returned for this entry, always preserved.
        status: Status text if the status byte layout has been verified,
            otherwise ``None``.
        status_byte: The raw status byte, when one was present.
        description: Text description, or ``None`` when unknown. A ``None``
            description is displayed as "Unknown BMW DTC"; a guessed
            description is never substituted.
        ecu: Which ECU reported the code.
    """

    code: str
    raw_data: bytes
    status: str | None = None
    status_byte: int | None = None
    description: str | None = None
    ecu: str | None = None

    @property
    def described(self) -> str:
        """Description for display, disclosing when nothing is known."""
        return self.description or UNKNOWN_DTC_DESCRIPTION

    @property
    def status_text(self) -> str:
        """Status for display, disclosing when the layout is unverified."""
        if self.status:
            return self.status
        if self.status_byte is not None:
            return f"0x{self.status_byte:02X} (status bit layout UNVERIFIED)"
        return "Unknown"

    def format_block(self) -> str:
        """Render as the multi-line block used by the CLI."""
        return "\n".join(
            [
                f"DTC: {self.code}",
                f"Status: {self.status_text}",
                f"Description: {self.described}",
                f"Raw: {self.raw_data.hex(' ').upper()}",
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "status_byte": self.status_byte,
            "description": self.description,
            "raw_hex": self.raw_data.hex(" ").upper(),
            "ecu": self.ecu,
        }


@dataclass(frozen=True, slots=True)
class ECUIdentification:
    """Identification data read from an ECU.

    Every field is optional: an ECU may not return a value, and an absent value
    is reported as absent rather than filled in.
    """

    ecu: str
    hardware_number: str | None = None
    software_number: str | None = None
    software_version: str | None = None
    vin: str | None = None
    supplier: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ecu": self.ecu,
            "hardware_number": self.hardware_number,
            "software_number": self.software_number,
            "software_version": self.software_version,
            "vin": self.vin,
            "supplier": self.supplier,
            "extra": self.extra,
            "raw": self.raw,
        }


class ECU:
    """A control unit reachable through a diagnostic protocol.

    Args:
        name: Short name such as ``"DME"``.
        address: Diagnostic address, or ``None`` when unverified. An ECU with
            no verified address cannot be addressed, by design.
        protocol: The protocol client used to talk to it, once one exists.
        description: Human description.
    """

    def __init__(
        self,
        name: str,
        address: int | None = None,
        protocol: Any = None,
        description: str | None = None,
    ) -> None:
        self.name = name
        self.address = address
        self.protocol = protocol
        self.description = description
        self._comms_level = CommsLevel.NONE

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        address = "unverified" if self.address is None else f"0x{self.address:02X}"
        return f"<{type(self).__name__} {self.name} address={address}>"

    @property
    def comms_level(self) -> CommsLevel:
        """How far communication with this specific ECU has been proven.

        Stays at :attr:`CommsLevel.NONE` until the ECU has actually returned a
        well-formed response. Reaching a lower layer, such as an open TCP
        socket, does not raise it.
        """
        return self._comms_level

    @property
    def is_responding(self) -> bool:
        """Whether this ECU has ever returned a valid response."""
        return self._comms_level >= CommsLevel.ECU_RESPONDING

    def _not_implemented(self, operation: str) -> NotVerifiedError:
        return NotVerifiedError(
            f"{self.name}.{operation}() is not implemented. It requires the BMW "
            "diagnostic protocol layer, whose framing, routing, and addressing "
            "are UNVERIFIED for this project. See docs/protocol.md."
        )

    def identification(self) -> ECUIdentification:
        """Read identification data from the ECU.

        Raises:
            NotVerifiedError: Always, until the protocol layer exists.
        """
        raise self._not_implemented("identification")

    def read_dtcs(self) -> list[DTC]:
        """Read stored diagnostic trouble codes.

        Raises:
            NotVerifiedError: Always, until the protocol layer exists.
        """
        raise self._not_implemented("read_dtcs")

    def read_data_identifier(self, identifier: int | str) -> bytes:
        """Read one data identifier.

        Raises:
            NotVerifiedError: Always, until the protocol layer exists.
        """
        raise self._not_implemented("read_data_identifier")
