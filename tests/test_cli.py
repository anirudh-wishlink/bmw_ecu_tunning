"""Tests for the CLI and the reporting discipline it must follow."""

from __future__ import annotations

import json

import pytest

from f10diag.cli import EXIT_NOT_VERIFIED, EXIT_OK, EXIT_USAGE, build_parser, main
from f10diag.exceptions import NotVerifiedError
from f10diag.status import CommsLevel, describe
from f10diag.vehicle.ecu import DTC, ECU
from f10diag.vehicle.f10 import F10Vehicle


class TestParser:
    def test_read_only_is_the_default(self):
        args = build_parser().parse_args(["network", "interfaces"])
        assert args.read_only is None  # unset, so configuration decides

    def test_read_only_and_allow_write_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--read-only", "--allow-write", "connect"])

    def test_every_command_accepts_verbose_and_raw(self):
        for command in (
            ["network", "interfaces"],
            ["connect"],
            ["vehicle", "info"],
            ["ecu", "list"],
            ["dme", "dtc"],
            ["dme", "live"],
            ["capture"],
        ):
            args = build_parser().parse_args(["--verbose", "--raw", *command])
            assert args.verbose == 1
            assert args.raw


class TestCommands:
    def test_no_command_prints_help(self, capsys):
        assert main([]) == EXIT_USAGE
        assert "usage" in capsys.readouterr().out.lower()

    def test_network_interfaces_runs(self, capsys):
        assert main(["network", "interfaces"]) == EXIT_OK
        assert "Interface" in capsys.readouterr().out

    def test_network_interfaces_json_is_machine_readable(self, capsys):
        assert main(["network", "interfaces", "--json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert "interfaces" in payload
        assert "candidates" in payload

    def test_vehicle_info_discloses_that_nothing_was_read(self, capsys):
        assert main(["vehicle", "info"]) == EXIT_OK
        output = capsys.readouterr().out
        assert "config.toml" in output
        assert "assumption" in output

    def test_vehicle_info_json_marks_vehicle_data_as_unread(self, capsys):
        assert main(["vehicle", "info", "--json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["read_from_vehicle"] is None

    def test_demo_runs_without_a_vehicle(self, capsys):
        assert main(["demo"]) == EXIT_OK
        output = capsys.readouterr().out
        assert "MockTransport" in output
        assert "carry no automotive meaning" in output

    def test_connect_without_a_gateway_refuses(self, capsys, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # no config.toml, so host/port stay unset
        assert main(["connect"]) == EXIT_NOT_VERIFIED
        assert "UNVERIFIED" in capsys.readouterr().err

    def test_invalid_config_is_a_usage_error(self, tmp_path):
        path = tmp_path / "bad.toml"
        path.write_text("[enet]\nport = 99999\n")
        assert main(["--config", str(path), "vehicle", "info"]) == EXIT_USAGE


class TestUnimplementedCommandsAreHonest:
    """Commands from later phases must explain, not fabricate."""

    @pytest.mark.parametrize(
        "command",
        [["ecu", "list"], ["ecu", "identify", "DME"], ["dme", "dtc"], ["dme", "live"]],
    )
    def test_they_exit_with_the_not_verified_code(self, command, capsys):
        assert main(command) == EXIT_NOT_VERIFIED
        assert "Not implemented" in capsys.readouterr().err

    def test_ecu_list_does_not_print_the_catalogue_as_discovered(self, capsys):
        main(["ecu", "list"])
        output = capsys.readouterr().err
        # Naming DME is fine in an explanation; claiming discovery is not.
        assert "actually answer" in output

    def test_dme_live_explains_the_empty_definitions(self, capsys):
        main(["dme", "live"])
        assert "signals.json" in capsys.readouterr().err


class TestAllowWriteFlag:
    def test_it_warns_that_no_write_operation_exists(self, capsys):
        main(["--allow-write", "vehicle", "info"])
        assert "implements no write operation" in capsys.readouterr().err


class TestReportingDiscipline:
    def test_tcp_is_below_ecu_communication(self):
        assert CommsLevel.TCP_CONNECTED < CommsLevel.ECU_RESPONDING

    def test_tcp_level_description_carries_the_caveat(self):
        assert "NOT proof" in describe(CommsLevel.TCP_CONNECTED)

    def test_a_fresh_ecu_has_proven_nothing(self):
        ecu = ECU("DME")
        assert ecu.comms_level is CommsLevel.NONE
        assert not ecu.is_responding

    def test_an_unresponsive_ecu_cannot_be_registered_as_discovered(self):
        vehicle = F10Vehicle()
        with pytest.raises(ValueError, match="has not returned a valid response"):
            vehicle.register_discovered(ECU("DME"))
        assert vehicle.discovered_ecus == []

    def test_ecu_operations_refuse_rather_than_invent(self):
        ecu = ECU("DME")
        for operation in (ecu.identification, ecu.read_dtcs):
            with pytest.raises(NotVerifiedError, match="UNVERIFIED"):
                operation()

    def test_ecu_discovery_refuses_rather_than_invent(self):
        with pytest.raises(NotVerifiedError, match="not implemented"):
            F10Vehicle().discover_ecus()


class TestDTCPresentation:
    def test_unknown_code_is_labelled_not_guessed(self):
        dtc = DTC(code="A1B2", raw_data=bytes([0xA1, 0xB2, 0x08]))
        assert dtc.described == "Unknown BMW DTC"

    def test_raw_bytes_are_always_preserved(self):
        dtc = DTC(code="A1B2", raw_data=bytes([0xA1, 0xB2, 0x08]))
        assert "A1 B2 08" in dtc.format_block()

    def test_status_byte_without_a_verified_layout_says_so(self):
        dtc = DTC(code="A1B2", raw_data=b"\x00", status_byte=0x08)
        assert "UNVERIFIED" in dtc.status_text

    def test_absent_status_is_reported_as_unknown(self):
        assert DTC(code="A1B2", raw_data=b"\x00").status_text == "Unknown"

    def test_known_status_is_shown_verbatim(self):
        dtc = DTC(code="A1B2", raw_data=b"\x00", status="Stored")
        assert dtc.status_text == "Stored"


class TestMSV90:
    def test_it_ships_no_signal_definitions(self):
        from f10diag.ecus.msv90 import MSV90

        assert MSV90().available_signals() == []

    def test_live_data_explains_the_absence(self):
        from f10diag.ecus.msv90 import MSV90

        with pytest.raises(NotVerifiedError, match="intentionally empty"):
            MSV90().live_data()

    def test_the_dme_model_is_presented_as_unconfirmed(self):
        from f10diag.ecus.msv90 import MSV90

        assert "not confirmed" in (MSV90().description or "")
