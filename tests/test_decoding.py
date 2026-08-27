"""Tests for the decoding layer."""

from __future__ import annotations

import json

import pytest

from f10diag.decoding.signals import (
    DEFINITIONS_DIR,
    DefinitionRegistry,
    SignalDefinition,
    UnverifiedDefinitionError,
)
from f10diag.decoding.values import (
    DECODERS,
    DecodeError,
    apply_scaling,
    ascii_text,
    bcd,
    boolean,
    get_decoder,
    int16,
    raw_hex,
    uint8,
    uint16,
    uint16_le,
    uint32,
)


class TestPrimitiveDecoders:
    def test_uint8(self):
        assert uint8(b"\xff") == 255

    def test_uint16_is_big_endian(self):
        assert uint16(b"\x01\x00") == 256

    def test_uint16_le_is_little_endian(self):
        assert uint16_le(b"\x01\x00") == 1

    def test_int16_handles_negatives(self):
        assert int16(b"\xff\xff") == -1

    def test_uint32(self):
        assert uint32(b"\x00\x00\x01\x00") == 256

    def test_boolean(self):
        assert boolean(b"\x01") is True
        assert boolean(b"\x00") is False

    def test_ascii_strips_padding(self):
        assert ascii_text(b"WBA12345\x00\x00") == "WBA12345"

    def test_ascii_rejects_binary(self):
        with pytest.raises(DecodeError, match="printable ASCII"):
            ascii_text(b"\x80\x81")

    def test_bcd(self):
        assert bcd(b"\x12\x34") == 1234

    def test_bcd_rejects_invalid_nibbles(self):
        with pytest.raises(DecodeError, match="valid BCD"):
            bcd(b"\x1a")

    def test_raw_hex_never_fails(self):
        assert raw_hex(b"\x00\xff") == "00 FF"

    @pytest.mark.parametrize("decoder,length", [(uint8, 1), (uint16, 2), (uint32, 4)])
    def test_wrong_length_is_rejected(self, decoder, length):
        with pytest.raises(DecodeError, match=f"exactly {length} byte"):
            decoder(b"\x00" * (length + 1))

    def test_decoder_lookup_by_name(self):
        assert get_decoder("uint16") is uint16

    def test_unknown_decoder_lists_the_alternatives(self):
        with pytest.raises(DecodeError, match="available decoders"):
            get_decoder("float128")

    def test_every_registered_decoder_is_callable(self):
        assert all(callable(fn) for fn in DECODERS.values())


class TestScaling:
    def test_scale_and_offset_are_applied(self):
        assert apply_scaling(100, 0.1, -40.0) == pytest.approx(-30.0)

    def test_identity_scaling_returns_the_input(self):
        assert apply_scaling(42) == 42

    def test_text_passes_through(self):
        assert apply_scaling("ABC", 0.5, 1.0) == "ABC"

    def test_boolean_passes_through(self):
        assert apply_scaling(True, 10.0) is True


class TestSignalDefinition:
    @staticmethod
    def _definition(**overrides) -> SignalDefinition:
        values = {
            "name": "test_signal",
            "decoder": "uint16",
            "length": 2,
            "scale": 0.25,
            "offset": -10.0,
            "unit": "degC",
            "verified": True,
            "source": "unit test fixture",
        }
        values.update(overrides)
        return SignalDefinition(**values)

    def test_decodes_with_scaling(self):
        result = self._definition().decode(b"\x00\x64")
        assert result.value == pytest.approx(15.0)
        assert result.unit == "degC"
        assert result.verified

    def test_honours_byte_offset(self):
        definition = self._definition(offset_bytes=2, scale=1.0, offset=0.0)
        assert definition.decode(b"\xff\xff\x00\x05").value == 5

    def test_unverified_definition_is_refused_by_default(self):
        with pytest.raises(UnverifiedDefinitionError, match="not verified"):
            self._definition(verified=False).decode(b"\x00\x64")

    def test_unverified_definition_can_be_opted_into(self):
        result = self._definition(verified=False).decode(b"\x00\x64", allow_unverified=True)
        assert result.value == pytest.approx(15.0)
        assert not result.verified

    def test_unverified_value_is_labelled_in_output(self):
        result = self._definition(verified=False).decode(b"\x00\x64", allow_unverified=True)
        assert "[UNVERIFIED]" in result.format()

    def test_verified_value_is_not_labelled(self):
        assert "[UNVERIFIED]" not in self._definition().decode(b"\x00\x64").format()

    def test_short_payload_is_reported_not_guessed(self):
        with pytest.raises(DecodeError, match="only 1 byte"):
            self._definition().decode(b"\x00")

    def test_decoder_failure_falls_back_to_raw_bytes(self):
        # An ECU sending unexpected data must never crash the tool.
        definition = self._definition(decoder="ascii", length=2, scale=1.0, offset=0.0)
        result = definition.decode(b"\x80\x81")
        assert result.value == "80 81"
        assert result.error
        assert not result.verified

    def test_length_must_match_the_decoder(self):
        with pytest.raises(ValueError, match="consumes 2 byte"):
            SignalDefinition(name="bad", decoder="uint16", length=4)

    def test_length_must_be_positive(self):
        with pytest.raises(ValueError, match="length must be positive"):
            SignalDefinition(name="bad", decoder="raw_hex", length=0)

    def test_from_dict_requires_core_fields(self):
        with pytest.raises(ValueError, match="missing required field"):
            SignalDefinition.from_dict({"name": "x"})

    def test_from_dict_defaults_to_unverified(self):
        definition = SignalDefinition.from_dict(
            {"name": "x", "decoder": "uint8", "length": 1}
        )
        assert not definition.verified

    def test_from_dict_treats_placeholder_identifiers_as_unknown(self):
        definition = SignalDefinition.from_dict(
            {"name": "x", "decoder": "uint8", "length": 1, "identifier": "UNKNOWN"}
        )
        assert definition.identifier is None

    def test_from_dict_normalises_identifier_case(self):
        definition = SignalDefinition.from_dict(
            {"name": "x", "decoder": "uint8", "length": 1, "identifier": "0xf190"}
        )
        assert definition.identifier == "F190"


class TestDefinitionRegistry:
    def test_loads_a_list_of_definitions(self, tmp_path):
        path = tmp_path / "signals.json"
        path.write_text(
            json.dumps(
                {
                    "signals": [
                        {"name": "a", "decoder": "uint8", "length": 1, "verified": True},
                        {"name": "b", "decoder": "uint8", "length": 1},
                    ]
                }
            )
        )
        registry = DefinitionRegistry.load(path)
        assert len(registry) == 2
        assert [d.name for d in registry.verified] == ["a"]
        assert [d.name for d in registry.unverified] == ["b"]

    def test_lookup_by_name_and_identifier(self, tmp_path):
        path = tmp_path / "signals.json"
        path.write_text(
            json.dumps(
                [{"name": "a", "decoder": "uint8", "length": 1, "identifier": "F190"}]
            )
        )
        registry = DefinitionRegistry.load(path)
        assert registry.by_name("a") is not None
        assert registry.by_identifier("f190")
        assert registry.by_name("missing") is None

    def test_invalid_json_is_reported(self, tmp_path):
        path = tmp_path / "signals.json"
        path.write_text("{not json")
        with pytest.raises(ValueError, match="invalid JSON"):
            DefinitionRegistry.load(path)

    def test_bad_entry_is_reported_with_its_index(self, tmp_path):
        path = tmp_path / "signals.json"
        path.write_text(json.dumps([{"name": "ok", "decoder": "uint8", "length": 1}, {}]))
        with pytest.raises(ValueError, match="entry 1"):
            DefinitionRegistry.load(path)

    def test_missing_file_is_reported(self, tmp_path):
        with pytest.raises(ValueError, match="not found"):
            DefinitionRegistry.load(tmp_path / "nope.json")


class TestBundledDefinitions:
    """The shipped definition files must stay empty until values are verified."""

    @pytest.mark.parametrize("filename", ["signals.json", "dids.json", "dtcs.json"])
    def test_definition_files_are_valid_json(self, filename):
        json.loads((DEFINITIONS_DIR / filename).read_text())

    def test_no_signal_is_shipped_unverified_as_if_real(self):
        registry = DefinitionRegistry.load_bundled("signals.json")
        assert len(registry) == 0, (
            "signals.json must stay empty until an identifier and its scaling "
            "have been verified against the vehicle"
        )

    def test_no_dids_are_shipped(self):
        assert len(DefinitionRegistry.load_bundled("dids.json")) == 0

    def test_no_ecu_addresses_are_shipped(self):
        document = json.loads((DEFINITIONS_DIR / "ecus.json").read_text())
        assert all(entry["address"] is None for entry in document["ecus"]), (
            "no BMW diagnostic address has been verified, so none may be shipped"
        )

    def test_no_dtc_descriptions_are_shipped(self):
        document = json.loads((DEFINITIONS_DIR / "dtcs.json").read_text())
        assert document["dtcs"] == []
