"""Tests for configuration loading, validation, and the safety gate."""

from __future__ import annotations

import pytest

from f10diag.config import AppConfig, ENETConfig, SafetyConfig
from f10diag.exceptions import ConfigError, SafetyViolationError, UnverifiedParameterError


class TestENETConfigParsing:
    def test_auto_and_empty_become_none(self):
        config = ENETConfig.from_dict({"interface": "auto", "host": "", "port": "auto"})
        assert config.interface is None
        assert config.host is None
        assert config.port is None

    def test_explicit_values_are_kept(self):
        config = ENETConfig.from_dict(
            {"interface": "en7", "host": "10.0.0.1", "port": 5000}
        )
        assert (config.interface, config.host, config.port) == ("en7", "10.0.0.1", 5000)

    def test_port_may_be_a_string(self):
        assert ENETConfig.from_dict({"port": "5000"}).port == 5000

    def test_out_of_range_port_is_rejected(self):
        with pytest.raises(ConfigError, match="65535"):
            ENETConfig.from_dict({"port": 70000})

    def test_non_numeric_port_is_rejected(self):
        with pytest.raises(ConfigError, match="not a valid port"):
            ENETConfig.from_dict({"port": "http"})

    def test_negative_timeout_is_rejected(self):
        with pytest.raises(ConfigError, match="positive"):
            ENETConfig.from_dict({"connect_timeout": -1})

    def test_unknown_key_is_rejected(self):
        with pytest.raises(ConfigError, match="unknown key"):
            ENETConfig.from_dict({"protocol": "magic"})

    def test_negative_reconnect_attempts_is_rejected(self):
        with pytest.raises(ConfigError, match="negative"):
            ENETConfig.from_dict({"reconnect_attempts": -1})


class TestAppConfigLoading:
    def test_loads_a_complete_file(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            """
            [enet]
            interface = "en7"
            host = "10.0.0.1"
            port = 5000

            [vehicle]
            platform = "F10"
            model = "523i"

            [safety]
            read_only = true
            """
        )
        config = AppConfig.load(path)
        assert config.enet.interface == "en7"
        assert config.vehicle.model == "523i"
        assert config.safety.read_only
        assert config.source_path == path

    def test_missing_file_is_reported(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            AppConfig.load(tmp_path / "absent.toml")

    def test_invalid_toml_is_reported(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[enet\n")
        with pytest.raises(ConfigError, match="invalid TOML"):
            AppConfig.load(path)

    def test_unknown_section_is_rejected(self):
        with pytest.raises(ConfigError, match="Unknown configuration section"):
            AppConfig.from_dict({"tuning": {"boost": 2}})

    def test_section_must_be_a_table(self):
        with pytest.raises(ConfigError, match=r"\[enet\]: expected a table"):
            AppConfig.from_dict({"enet": "en7"})

    def test_defaults_are_usable_without_a_file(self):
        config = AppConfig()
        assert config.safety.read_only
        assert config.enet.host is None

    def test_shipped_config_defaults_to_read_only_with_no_gateway(self):
        # The repository's config.toml must not carry a guessed host or port.
        from pathlib import Path

        shipped = Path(__file__).resolve().parent.parent / "config.toml"
        config = AppConfig.load(shipped)
        assert config.safety.read_only
        assert config.enet.host is None
        assert config.enet.port is None


class TestOverrides:
    def test_cli_values_override_the_file(self):
        config = AppConfig().with_overrides(interface="en5", host="10.0.0.9", port=1)
        assert config.enet.interface == "en5"
        assert config.enet.host == "10.0.0.9"
        assert config.enet.port == 1

    def test_absent_overrides_do_not_clear_values(self):
        base = AppConfig(enet=ENETConfig(interface="en7", host="10.0.0.1", port=5000))
        assert base.with_overrides(port=6000).enet.host == "10.0.0.1"

    def test_allow_write_can_be_expressed(self):
        assert not AppConfig().with_overrides(read_only=False).safety.read_only


class TestSafetyGate:
    def test_read_only_is_the_default(self):
        assert SafetyConfig().read_only

    def test_write_is_blocked_in_read_only_mode(self):
        with pytest.raises(SafetyViolationError, match="read-only mode is"):
            SafetyConfig().guard_write("write_coding_data")

    def test_gate_names_the_attempted_operation(self):
        with pytest.raises(SafetyViolationError, match="ecu_reset"):
            SafetyConfig().guard_write("ecu_reset")

    def test_gate_passes_when_writes_are_enabled(self):
        SafetyConfig(read_only=False).guard_write("some_future_write")

    def test_read_only_must_be_boolean(self):
        with pytest.raises(ConfigError, match="true or false"):
            SafetyConfig.from_dict({"read_only": "yes"})


class TestConnectionPreconditions:
    def test_no_gateway_default_is_ever_substituted(self):
        with pytest.raises(UnverifiedParameterError):
            AppConfig().enet.validate_for_connection()
