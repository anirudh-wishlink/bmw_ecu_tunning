"""Tests for the packet abstraction."""

from __future__ import annotations

import pytest

from f10diag.transport.packet import (
    DiagnosticPacket,
    Direction,
    format_hex,
    parse_hex,
)


class TestHexHelpers:
    def test_format_hex_uses_uppercase_pairs(self):
        assert format_hex(bytes([0x00, 0x0A, 0xFF])) == "00 0A FF"

    def test_format_hex_of_empty_is_empty(self):
        assert format_hex(b"") == ""

    @pytest.mark.parametrize(
        "text",
        ["01 02 03", "01:02:03", "010203", "0x010x020x03", "01-02-03", "01,02,03"],
    )
    def test_parse_hex_accepts_common_separators(self, text):
        assert parse_hex(text) == bytes([1, 2, 3])

    def test_parse_hex_rejects_odd_digit_count(self):
        with pytest.raises(ValueError, match="odd number"):
            parse_hex("012")

    def test_parse_hex_rejects_non_hex(self):
        with pytest.raises(ValueError, match="invalid hex"):
            parse_hex("zz")


class TestDiagnosticPacket:
    def test_records_direction_and_payload(self):
        packet = DiagnosticPacket(direction=Direction.TX, raw_data=b"\x01\x02")
        assert packet.direction is Direction.TX
        assert packet.length == 2
        assert packet.hex == "01 02"

    def test_accepts_direction_as_string(self):
        assert DiagnosticPacket(direction="rx", raw_data=b"").direction is Direction.RX

    def test_rejects_non_bytes_payload(self):
        with pytest.raises(TypeError):
            DiagnosticPacket(direction=Direction.TX, raw_data="not bytes")

    def test_bytearray_is_normalised_to_bytes(self):
        packet = DiagnosticPacket(direction=Direction.TX, raw_data=bytearray(b"\xab"))
        assert isinstance(packet.raw_data, bytes)

    def test_iso_timestamp_is_utc(self):
        packet = DiagnosticPacket(direction=Direction.RX, raw_data=b"", timestamp=0.0)
        assert packet.iso_timestamp.startswith("1970-01-01T00:00:00")

    def test_decoded_defaults_to_none(self):
        # A transport-layer packet must never claim a protocol interpretation.
        assert DiagnosticPacket(direction=Direction.RX, raw_data=b"\x01").decoded is None

    def test_round_trips_through_dict(self):
        original = DiagnosticPacket(
            direction=Direction.RX,
            raw_data=bytes([0xDE, 0xAD, 0xBE, 0xEF]),
            timestamp=1234.5,
            transport={"peer": "10.0.0.1:1234"},
            note="hello",
        )
        restored = DiagnosticPacket.from_dict(original.to_dict())
        assert restored.raw_data == original.raw_data
        assert restored.direction == original.direction
        assert restored.timestamp == original.timestamp
        assert restored.transport == original.transport
        assert restored.note == original.note

    def test_from_dict_accepts_iso_timestamp(self):
        packet = DiagnosticPacket.from_dict(
            {"direction": "TX", "raw_hex": "01", "timestamp": "2026-01-01T00:00:00+00:00"}
        )
        assert packet.length == 1

    def test_from_dict_rejects_missing_direction(self):
        with pytest.raises(ValueError, match="direction"):
            DiagnosticPacket.from_dict({"raw_hex": "01"})

    def test_from_dict_rejects_invalid_direction(self):
        with pytest.raises(ValueError, match="invalid direction"):
            DiagnosticPacket.from_dict({"direction": "SIDEWAYS", "raw_hex": "01"})

    def test_from_dict_rejects_missing_payload(self):
        with pytest.raises(ValueError, match="raw_hex"):
            DiagnosticPacket.from_dict({"direction": "TX"})

    def test_from_dict_rejects_malformed_transport(self):
        with pytest.raises(ValueError, match="transport"):
            DiagnosticPacket.from_dict(
                {"direction": "TX", "raw_hex": "01", "transport": "nope"}
            )

    def test_format_line_includes_peer_and_payload(self):
        packet = DiagnosticPacket(
            direction=Direction.TX,
            raw_data=b"\x01",
            transport={"peer": "10.0.0.1:1234"},
        )
        line = packet.format_line()
        assert "TX" in line
        assert "PEER=10.0.0.1:1234" in line
        assert "RAW=01" in line
