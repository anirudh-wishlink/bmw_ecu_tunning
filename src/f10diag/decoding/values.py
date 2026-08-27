"""Primitive value decoders.

Pure byte-to-value conversions with no automotive knowledge whatsoever. A
decoder here says how to turn N bytes into a number or a string; *which* bytes
mean *what* is the job of a signal definition, and must be verified separately.
"""

from __future__ import annotations

from collections.abc import Callable

DecoderFn = Callable[[bytes], float | int | str | bool]


class DecodeError(ValueError):
    """Raw bytes could not be decoded with the requested decoder."""


def _require_length(data: bytes, expected: int, name: str) -> None:
    if len(data) != expected:
        raise DecodeError(
            f"{name} needs exactly {expected} byte(s), got {len(data)}: "
            f"{data.hex(' ').upper() or '<empty>'}"
        )


def uint8(data: bytes) -> int:
    _require_length(data, 1, "uint8")
    return int.from_bytes(data, "big", signed=False)


def int8(data: bytes) -> int:
    _require_length(data, 1, "int8")
    return int.from_bytes(data, "big", signed=True)


def uint16(data: bytes) -> int:
    _require_length(data, 2, "uint16")
    return int.from_bytes(data, "big", signed=False)


def int16(data: bytes) -> int:
    _require_length(data, 2, "int16")
    return int.from_bytes(data, "big", signed=True)


def uint16_le(data: bytes) -> int:
    _require_length(data, 2, "uint16_le")
    return int.from_bytes(data, "little", signed=False)


def int16_le(data: bytes) -> int:
    _require_length(data, 2, "int16_le")
    return int.from_bytes(data, "little", signed=True)


def uint32(data: bytes) -> int:
    _require_length(data, 4, "uint32")
    return int.from_bytes(data, "big", signed=False)


def int32(data: bytes) -> int:
    _require_length(data, 4, "int32")
    return int.from_bytes(data, "big", signed=True)


def uint32_le(data: bytes) -> int:
    _require_length(data, 4, "uint32_le")
    return int.from_bytes(data, "little", signed=False)


def boolean(data: bytes) -> bool:
    _require_length(data, 1, "boolean")
    return data[0] != 0


def ascii_text(data: bytes) -> str:
    """Decode printable ASCII, dropping padding NULs and 0xFF filler."""
    trimmed = data.rstrip(b"\x00\xff").strip()
    try:
        return trimmed.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DecodeError(
            f"not printable ASCII: {data.hex(' ').upper()}"
        ) from exc


def latin1_text(data: bytes) -> str:
    """Decode Latin-1, which never fails, for tolerant display of text fields."""
    return data.rstrip(b"\x00\xff").decode("latin-1").strip()


def bcd(data: bytes) -> int:
    """Decode packed binary-coded decimal, two digits per byte."""
    value = 0
    for byte in data:
        high, low = byte >> 4, byte & 0x0F
        if high > 9 or low > 9:
            raise DecodeError(f"not valid BCD: {data.hex(' ').upper()}")
        value = value * 100 + high * 10 + low
    return value


def raw_hex(data: bytes) -> str:
    """Return the bytes as spaced uppercase hex, the always-safe fallback."""
    return data.hex(" ").upper()


#: Decoders addressable by name from a JSON definition file.
DECODERS: dict[str, DecoderFn] = {
    "uint8": uint8,
    "int8": int8,
    "uint16": uint16,
    "int16": int16,
    "uint16_le": uint16_le,
    "int16_le": int16_le,
    "uint32": uint32,
    "int32": int32,
    "uint32_le": uint32_le,
    "boolean": boolean,
    "ascii": ascii_text,
    "latin1": latin1_text,
    "bcd": bcd,
    "raw_hex": raw_hex,
}

#: Fixed byte length required by each decoder, or ``None`` when variable.
DECODER_LENGTHS: dict[str, int | None] = {
    "uint8": 1,
    "int8": 1,
    "uint16": 2,
    "int16": 2,
    "uint16_le": 2,
    "int16_le": 2,
    "uint32": 4,
    "int32": 4,
    "uint32_le": 4,
    "boolean": 1,
    "ascii": None,
    "latin1": None,
    "bcd": None,
    "raw_hex": None,
}


def get_decoder(name: str) -> DecoderFn:
    """Look up a decoder by name.

    Raises:
        DecodeError: No decoder is registered under that name.
    """
    try:
        return DECODERS[name]
    except KeyError as exc:
        available = ", ".join(sorted(DECODERS))
        raise DecodeError(
            f"unknown decoder {name!r}; available decoders: {available}"
        ) from exc


def apply_scaling(
    value: float | int | str | bool,
    scale: float = 1.0,
    offset: float = 0.0,
) -> float | int | str | bool:
    """Apply ``value * scale + offset`` to numeric results.

    Non-numeric values (text, hex dumps, booleans) pass through untouched.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    if scale == 1.0 and offset == 0.0:
        return value
    return value * scale + offset
