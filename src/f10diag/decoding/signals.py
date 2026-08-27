"""Signal definitions and decoded values.

A :class:`SignalDefinition` binds a byte range inside an ECU response to a
decoder, a scaling rule, and a unit. Definitions live in JSON files under
``f10diag/definitions`` so that identifiers are data rather than code.

Every definition carries a ``verified`` flag. An unverified definition is a
hypothesis: it is loaded and can be applied deliberately for investigation, but
:meth:`SignalDefinition.decode` refuses to run it unless the caller opts in, and
the resulting :class:`DecodedValue` always carries the flag through to display.
Unverified output is never presented as a fact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .values import DECODER_LENGTHS, DecodeError, apply_scaling, get_decoder, raw_hex

DEFINITIONS_DIR = Path(__file__).resolve().parent.parent / "definitions"


class UnverifiedDefinitionError(DecodeError):
    """An unverified definition was applied without an explicit opt-in."""


@dataclass(frozen=True, slots=True)
class SignalDefinition:
    """How to extract one value from an ECU response payload.

    Attributes:
        name: Machine-readable signal name.
        identifier: The data identifier this signal is carried in, as an
            uppercase hex string. ``None`` when not yet determined.
        decoder: Key into :data:`f10diag.decoding.values.DECODERS`.
        length: Number of bytes consumed by the decoder.
        offset_bytes: Where the value starts inside the response payload.
        scale: Multiplier applied to numeric results.
        offset: Constant added after scaling.
        unit: Physical unit of the scaled value, for display only.
        description: Human description.
        source: Where the definition came from (document, capture, measurement).
            Required in practice for anything marked verified.
        verified: Whether the definition was confirmed against a real vehicle
            or an authoritative source.
        ecu: Which ECU the definition applies to.
    """

    name: str
    decoder: str
    length: int
    identifier: str | None = None
    offset_bytes: int = 0
    scale: float = 1.0
    offset: float = 0.0
    unit: str | None = None
    description: str | None = None
    source: str | None = None
    verified: bool = False
    ecu: str | None = None

    def __post_init__(self) -> None:
        if self.length <= 0:
            raise ValueError(f"{self.name}: length must be positive")
        if self.offset_bytes < 0:
            raise ValueError(f"{self.name}: offset_bytes must not be negative")
        expected = DECODER_LENGTHS.get(self.decoder)
        if expected is not None and expected != self.length:
            raise ValueError(
                f"{self.name}: decoder {self.decoder!r} consumes {expected} byte(s) "
                f"but the definition declares length {self.length}"
            )

    @property
    def end_offset(self) -> int:
        return self.offset_bytes + self.length

    def extract(self, payload: bytes) -> bytes:
        """Slice this signal's bytes out of a response payload.

        Raises:
            DecodeError: The payload is shorter than the definition requires.
        """
        if len(payload) < self.end_offset:
            raise DecodeError(
                f"{self.name}: needs bytes [{self.offset_bytes}:{self.end_offset}] "
                f"but the payload is only {len(payload)} byte(s) long"
            )
        return payload[self.offset_bytes : self.end_offset]

    def decode(self, payload: bytes, *, allow_unverified: bool = False) -> DecodedValue:
        """Decode this signal from a response payload.

        Args:
            payload: The ECU response data, excluding any protocol header.
            allow_unverified: Permit applying a definition whose ``verified``
                flag is ``False``. The result is still marked unverified.

        Raises:
            UnverifiedDefinitionError: The definition is unverified and
                ``allow_unverified`` is ``False``.
            DecodeError: The payload is too short or malformed for the decoder.
        """
        if not self.verified and not allow_unverified:
            raise UnverifiedDefinitionError(
                f"{self.name}: this definition is not verified. Pass "
                "allow_unverified=True to apply it as a hypothesis; its output "
                "must not be treated as authoritative."
            )

        window = self.extract(payload)
        try:
            value = get_decoder(self.decoder)(window)
        except DecodeError:
            # Never crash on unexpected ECU data: fall back to a hex dump so the
            # raw bytes stay visible for analysis.
            return DecodedValue(
                definition=self,
                value=raw_hex(window),
                raw=window,
                unit=None,
                verified=False,
                error="decoder failed; showing raw bytes",
            )

        return DecodedValue(
            definition=self,
            value=apply_scaling(value, self.scale, self.offset),
            raw=window,
            unit=self.unit,
            verified=self.verified,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "identifier": self.identifier,
            "length": self.length,
            "offset_bytes": self.offset_bytes,
            "decoder": self.decoder,
            "scale": self.scale,
            "offset": self.offset,
            "unit": self.unit,
            "description": self.description,
            "source": self.source,
            "verified": self.verified,
            "ecu": self.ecu,
        }

    @classmethod
    def from_dict(cls, record: dict[str, Any]) -> SignalDefinition:
        """Build a definition from a JSON record.

        Raises:
            ValueError: A required field is missing or invalid.
        """
        missing = [key for key in ("name", "decoder", "length") if key not in record]
        if missing:
            raise ValueError(
                f"signal definition is missing required field(s): {', '.join(missing)}"
            )
        identifier = record.get("identifier")
        if identifier is not None:
            identifier = str(identifier).upper().replace("0X", "")
            if identifier in {"", "UNKNOWN", "TODO", "TODO: VERIFY"}:
                identifier = None

        return cls(
            name=str(record["name"]),
            decoder=str(record["decoder"]),
            length=int(record["length"]),
            identifier=identifier,
            offset_bytes=int(record.get("offset_bytes", 0)),
            scale=float(record.get("scale", 1.0)),
            offset=float(record.get("offset", 0.0)),
            unit=record.get("unit"),
            description=record.get("description"),
            source=record.get("source"),
            verified=bool(record.get("verified", False)),
            ecu=record.get("ecu"),
        )


@dataclass(frozen=True, slots=True)
class DecodedValue:
    """The result of applying a :class:`SignalDefinition` to raw bytes."""

    definition: SignalDefinition
    value: float | int | str | bool
    raw: bytes
    unit: str | None = None
    verified: bool = False
    error: str | None = None

    @property
    def name(self) -> str:
        return self.definition.name

    def format(self, *, precision: int = 2) -> str:
        """Render for display, always disclosing unverified results."""
        if isinstance(self.value, float):
            text = f"{self.value:.{precision}f}"
        else:
            text = str(self.value)
        if self.unit:
            text = f"{text} {self.unit}"
        if self.error:
            text = f"{text} ({self.error})"
        if not self.verified:
            text = f"{text} [UNVERIFIED]"
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "raw_hex": raw_hex(self.raw),
            "verified": self.verified,
            "error": self.error,
        }


class DefinitionRegistry:
    """A loaded set of signal definitions, indexed by name and identifier."""

    def __init__(self, definitions: list[SignalDefinition] | None = None) -> None:
        self._definitions: list[SignalDefinition] = list(definitions or [])

    def __len__(self) -> int:
        return len(self._definitions)

    def __iter__(self):
        return iter(self._definitions)

    @property
    def verified(self) -> list[SignalDefinition]:
        """Only the definitions confirmed against a vehicle or a source."""
        return [item for item in self._definitions if item.verified]

    @property
    def unverified(self) -> list[SignalDefinition]:
        """Definitions that are still hypotheses."""
        return [item for item in self._definitions if not item.verified]

    def add(self, definition: SignalDefinition) -> None:
        self._definitions.append(definition)

    def by_name(self, name: str) -> SignalDefinition | None:
        return next((item for item in self._definitions if item.name == name), None)

    def by_identifier(self, identifier: str) -> list[SignalDefinition]:
        wanted = identifier.upper().replace("0X", "")
        return [item for item in self._definitions if item.identifier == wanted]

    def for_ecu(self, ecu: str) -> list[SignalDefinition]:
        return [item for item in self._definitions if item.ecu == ecu]

    @classmethod
    def load(cls, path: Path | str) -> DefinitionRegistry:
        """Load definitions from a JSON file.

        The file may be a list of records, or an object with a ``signals`` or
        ``definitions`` array. Metadata keys are ignored.

        Raises:
            ValueError: The file is not valid JSON or a record is invalid.
        """
        file_path = Path(path)
        if not file_path.is_file():
            raise ValueError(f"definition file not found: {file_path}")
        try:
            document = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{file_path}: invalid JSON: {exc}") from exc

        if isinstance(document, dict):
            records = document.get("signals") or document.get("definitions") or []
        else:
            records = document
        if not isinstance(records, list):
            raise ValueError(f"{file_path}: expected a list of definitions")

        registry = cls()
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(f"{file_path}: entry {index} is not an object")
            try:
                registry.add(SignalDefinition.from_dict(record))
            except ValueError as exc:
                raise ValueError(f"{file_path}: entry {index}: {exc}") from exc
        return registry

    @classmethod
    def load_bundled(cls, filename: str) -> DefinitionRegistry:
        """Load one of the JSON files shipped in ``f10diag/definitions``."""
        return cls.load(DEFINITIONS_DIR / filename)
