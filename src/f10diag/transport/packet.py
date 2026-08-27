"""Transport-agnostic packet abstraction.

A :class:`DiagnosticPacket` records one chunk of bytes that crossed the
transport boundary, plus enough metadata to replay or analyse it later. It
carries no protocol knowledge: ``decoded`` stays ``None`` until a protocol
layer that understands the bytes fills it in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Direction(str, Enum):
    """Which way a packet travelled, from the tester's point of view."""

    TX = "TX"
    """Sent by this application towards the vehicle."""

    RX = "RX"
    """Received by this application from the vehicle."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


def format_hex(data: bytes, *, separator: str = " ") -> str:
    """Return ``data`` as uppercase hex byte pairs."""
    return separator.join(f"{byte:02X}" for byte in data)


def parse_hex(text: str) -> bytes:
    """Parse a hex string that may contain spaces, colons, or ``0x`` prefixes.

    Raises:
        ValueError: The string does not describe a whole number of bytes.
    """
    cleaned = text.replace("0x", "").replace("0X", "")
    for character in (" ", ":", "-", "\n", "\t", ","):
        cleaned = cleaned.replace(character, "")
    if len(cleaned) % 2:
        raise ValueError(f"hex string has an odd number of digits: {text!r}")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(f"invalid hex string: {text!r}") from exc


@dataclass(slots=True)
class DiagnosticPacket:
    """One raw transport payload plus its metadata.

    Attributes:
        direction: :class:`Direction.TX` or :class:`Direction.RX`.
        raw_data: The bytes exactly as they crossed the transport boundary.
        timestamp: Unix epoch seconds, captured as close to the I/O call as
            possible.
        transport: Free-form transport metadata (peer address, interface name,
            socket family, ...). Never interpreted by this class.
        decoded: Protocol interpretation, filled in by a higher layer once one
            exists. ``None`` means "not decoded", never "no meaning".
        note: Optional human annotation, used by capture tooling.
    """

    direction: Direction
    raw_data: bytes
    timestamp: float = field(default_factory=time.time)
    transport: dict[str, Any] = field(default_factory=dict)
    decoded: dict[str, Any] | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        # Accept a plain string for convenience at call sites and in captures.
        if not isinstance(self.direction, Direction):
            self.direction = Direction(str(self.direction).upper())
        if not isinstance(self.raw_data, (bytes, bytearray)):
            raise TypeError("raw_data must be bytes")
        self.raw_data = bytes(self.raw_data)

    @property
    def length(self) -> int:
        """Number of bytes in the payload."""
        return len(self.raw_data)

    @property
    def hex(self) -> str:
        """Payload as spaced uppercase hex."""
        return format_hex(self.raw_data)

    @property
    def iso_timestamp(self) -> str:
        """Timestamp as an ISO-8601 UTC string with millisecond precision."""
        moment = datetime.fromtimestamp(self.timestamp, tz=timezone.utc)
        return moment.isoformat(timespec="milliseconds")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary."""
        record: dict[str, Any] = {
            "timestamp": self.timestamp,
            "iso_timestamp": self.iso_timestamp,
            "direction": self.direction.value,
            "length": self.length,
            "raw_hex": self.hex,
        }
        if self.transport:
            record["transport"] = self.transport
        if self.decoded is not None:
            record["decoded"] = self.decoded
        if self.note is not None:
            record["note"] = self.note
        return record

    @classmethod
    def from_dict(cls, record: dict[str, Any]) -> DiagnosticPacket:
        """Rebuild a packet from :meth:`to_dict` output.

        Raises:
            ValueError: A required field is missing or malformed.
        """
        try:
            direction = Direction(str(record["direction"]).upper())
        except KeyError as exc:
            raise ValueError("packet record has no 'direction'") from exc
        except ValueError as exc:
            raise ValueError(
                f"packet record has an invalid direction: {record['direction']!r}"
            ) from exc

        if "raw_hex" in record:
            raw = parse_hex(str(record["raw_hex"]))
        elif "raw_data" in record:
            raw = parse_hex(str(record["raw_data"]))
        else:
            raise ValueError("packet record has neither 'raw_hex' nor 'raw_data'")

        timestamp = record.get("timestamp")
        if timestamp is None:
            timestamp = time.time()
        elif isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp).timestamp()

        transport = record.get("transport") or {}
        if not isinstance(transport, dict):
            raise ValueError("packet record 'transport' must be an object")

        decoded = record.get("decoded")
        if decoded is not None and not isinstance(decoded, dict):
            raise ValueError("packet record 'decoded' must be an object")

        return cls(
            direction=direction,
            raw_data=raw,
            timestamp=float(timestamp),
            transport=transport,
            decoded=decoded,
            note=record.get("note"),
        )

    def format_line(self) -> str:
        """Render a single-line, log-friendly representation."""
        parts = [self.iso_timestamp, self.direction.value, f"LEN={self.length}"]
        peer = self.transport.get("peer")
        if peer:
            parts.append(f"PEER={peer}")
        parts.append(f"RAW={self.hex}")
        if self.note:
            parts.append(f"NOTE={self.note}")
        return " ".join(parts)
