"""Configuration loading and validation.

Configuration comes from a TOML file (``config.toml`` by default) and can be
overridden by CLI flags. Anything that would require guessing a BMW protocol
value is left unset; attempting to use it raises
:class:`~f10diag.exceptions.UnverifiedParameterError` rather than falling back
to an invented default.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .exceptions import ConfigError, SafetyViolationError, UnverifiedParameterError

DEFAULT_CONFIG_FILENAME = "config.toml"

#: Sentinel used in the TOML file meaning "resolve at runtime from the host".
AUTO = "auto"


def _as_optional_str(value: Any, key: str) -> str | None:
    """Normalise a TOML value to ``None`` when it is empty or ``"auto"``."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{key}: expected a string, got {type(value).__name__}")
    stripped = value.strip()
    if stripped == "" or stripped.lower() == AUTO:
        return None
    return stripped


def _as_optional_port(value: Any, key: str) -> int | None:
    """Normalise a TOML port value, allowing "", "auto", or an integer."""
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass; reject explicitly
        raise ConfigError(f"{key}: expected a port number, got a boolean")
    if isinstance(value, int):
        port = value
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped == "" or stripped.lower() == AUTO:
            return None
        try:
            port = int(stripped)
        except ValueError as exc:
            raise ConfigError(f"{key}: {value!r} is not a valid port number") from exc
    else:
        raise ConfigError(f"{key}: expected a port number, got {type(value).__name__}")

    if not 1 <= port <= 65535:
        raise ConfigError(f"{key}: port {port} is outside the range 1-65535")
    return port


def _as_positive_float(value: Any, key: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key}: expected a number, got {type(value).__name__}")
    number = float(value)
    if number < 0 or (number == 0 and not allow_zero):
        raise ConfigError(f"{key}: must be a positive number, got {number}")
    return number


@dataclass(frozen=True, slots=True)
class ENETConfig:
    """Transport parameters for the ENET Ethernet interface.

    Attributes:
        interface: macOS interface name (``"en7"``), or ``None`` for automatic
            selection of the most likely Ethernet-class interface.
        host: Diagnostic gateway IPv4 address. ``None`` means "not verified,
            not supplied" and blocks any connection attempt.
        port: Diagnostic gateway TCP port. ``None`` has the same meaning.
        connect_timeout: Seconds to wait for the TCP handshake.
        receive_timeout: Seconds to wait for inbound bytes.
        reconnect_attempts: How many times :meth:`ENETTransport.reconnect` may
            retry before giving up. ``0`` disables automatic retries.
        reconnect_delay: Seconds between reconnection attempts.
    """

    interface: str | None = None
    host: str | None = None
    port: int | None = None
    connect_timeout: float = 5.0
    receive_timeout: float = 2.0
    reconnect_attempts: int = 0
    reconnect_delay: float = 1.0

    def validate_for_connection(self) -> None:
        """Raise if the configuration is not sufficient to open a connection.

        Raises:
            UnverifiedParameterError: ``host`` or ``port`` was never supplied.
        """
        missing = [
            name
            for name, value in (("host", self.host), ("port", self.port))
            if value is None
        ]
        if missing:
            raise UnverifiedParameterError(
                "Cannot connect: "
                + " and ".join(f"[enet].{name}" for name in missing)
                + " is not set. f10diag ships no default BMW gateway address or"
                " port because those values are UNVERIFIED for this project."
                " Set them in config.toml or pass --host/--port."
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ENETConfig:
        unknown = set(data) - {
            "interface",
            "host",
            "port",
            "connect_timeout",
            "receive_timeout",
            "reconnect_attempts",
            "reconnect_delay",
        }
        if unknown:
            raise ConfigError(f"[enet]: unknown key(s): {', '.join(sorted(unknown))}")

        attempts = data.get("reconnect_attempts", 0)
        if isinstance(attempts, bool) or not isinstance(attempts, int):
            raise ConfigError("[enet].reconnect_attempts: expected an integer")
        if attempts < 0:
            raise ConfigError("[enet].reconnect_attempts: must not be negative")

        return cls(
            interface=_as_optional_str(data.get("interface"), "[enet].interface"),
            host=_as_optional_str(data.get("host"), "[enet].host"),
            port=_as_optional_port(data.get("port"), "[enet].port"),
            connect_timeout=_as_positive_float(
                data.get("connect_timeout", 5.0), "[enet].connect_timeout"
            ),
            receive_timeout=_as_positive_float(
                data.get("receive_timeout", 2.0), "[enet].receive_timeout"
            ),
            reconnect_attempts=attempts,
            reconnect_delay=_as_positive_float(
                data.get("reconnect_delay", 1.0),
                "[enet].reconnect_delay",
                allow_zero=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class VehicleConfig:
    """Descriptive information about the target vehicle.

    None of these fields influence protocol behaviour yet. They are recorded in
    capture metadata so that a session can be attributed to a specific car.
    """

    platform: str = "F10"
    model: str = "523i"
    model_year: int | None = 2011
    engine: str = "N52B25"
    dme: str = "MSV90"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VehicleConfig:
        year = data.get("model_year", 2011)
        if year is not None and (isinstance(year, bool) or not isinstance(year, int)):
            raise ConfigError("[vehicle].model_year: expected an integer")
        return cls(
            platform=str(data.get("platform", "F10")),
            model=str(data.get("model", "523i")),
            model_year=year,
            engine=str(data.get("engine", "N52B25")),
            dme=str(data.get("dme", "MSV90")),
        )


@dataclass(frozen=True, slots=True)
class SafetyConfig:
    """Safety gate for anything that could modify the vehicle.

    ``read_only`` defaults to ``True`` and no write operation exists yet. The
    gate is present from the first commit so that any future write path has a
    single, obvious place to be checked.
    """

    read_only: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SafetyConfig:
        value = data.get("read_only", True)
        if not isinstance(value, bool):
            raise ConfigError("[safety].read_only: expected true or false")
        return cls(read_only=value)

    def guard_write(self, operation: str) -> None:
        """Reject a write operation unless writes have been explicitly enabled.

        Args:
            operation: Human-readable name of the attempted operation.

        Raises:
            SafetyViolationError: Always, while ``read_only`` is ``True``.
        """
        if self.read_only:
            raise SafetyViolationError(
                f"'{operation}' is a write operation and read-only mode is"
                " active. Read-only mode is the default and is currently the"
                " only supported mode of this tool."
            )


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """Where and how diagnostic activity is recorded."""

    level: str = "INFO"
    capture_dir: Path = Path("captures")
    log_packets: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any], base_dir: Path) -> LoggingConfig:
        level = str(data.get("level", "INFO")).upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError(f"[logging].level: unknown level {level!r}")

        log_packets = data.get("log_packets", True)
        if not isinstance(log_packets, bool):
            raise ConfigError("[logging].log_packets: expected true or false")

        capture_dir = Path(str(data.get("capture_dir", "captures")))
        if not capture_dir.is_absolute():
            capture_dir = base_dir / capture_dir

        return cls(level=level, capture_dir=capture_dir, log_packets=log_packets)


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Top-level application configuration."""

    enet: ENETConfig = field(default_factory=ENETConfig)
    vehicle: VehicleConfig = field(default_factory=VehicleConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    source_path: Path | None = None

    @classmethod
    def load(cls, path: Path | str | None = None) -> AppConfig:
        """Load configuration from a TOML file.

        Args:
            path: Path to the TOML file. When ``None``, ``config.toml`` is
                looked up in the current working directory; if it is absent,
                defaults are used.

        Raises:
            ConfigError: The file is unreadable, is not valid TOML, or contains
                an invalid value.
        """
        if path is None:
            candidate = Path.cwd() / DEFAULT_CONFIG_FILENAME
            if not candidate.is_file():
                return cls()
            resolved = candidate
        else:
            resolved = Path(path).expanduser()
            if not resolved.is_file():
                raise ConfigError(f"Configuration file not found: {resolved}")

        try:
            raw = tomllib.loads(resolved.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{resolved}: invalid TOML: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"{resolved}: cannot be read: {exc}") from exc

        return cls.from_dict(raw, base_dir=resolved.parent).with_source(resolved)

    @classmethod
    def from_dict(cls, data: dict[str, Any], base_dir: Path | None = None) -> AppConfig:
        """Build a configuration from an already-parsed mapping."""
        base = base_dir or Path.cwd()
        known = {"enet", "vehicle", "safety", "logging"}
        unknown = set(data) - known
        if unknown:
            raise ConfigError(
                f"Unknown configuration section(s): {', '.join(sorted(unknown))}"
            )
        for section in known:
            if section in data and not isinstance(data[section], dict):
                raise ConfigError(f"[{section}]: expected a table")

        return cls(
            enet=ENETConfig.from_dict(data.get("enet", {})),
            vehicle=VehicleConfig.from_dict(data.get("vehicle", {})),
            safety=SafetyConfig.from_dict(data.get("safety", {})),
            logging=LoggingConfig.from_dict(data.get("logging", {}), base),
        )

    def with_source(self, path: Path) -> AppConfig:
        return replace(self, source_path=path)

    def with_overrides(
        self,
        *,
        interface: str | None = None,
        host: str | None = None,
        port: int | None = None,
        connect_timeout: float | None = None,
        receive_timeout: float | None = None,
        read_only: bool | None = None,
        log_level: str | None = None,
    ) -> AppConfig:
        """Return a copy with CLI overrides applied.

        Only non-``None`` arguments override the loaded configuration, so an
        absent CLI flag never clears a configured value.
        """
        enet = replace(
            self.enet,
            **{
                key: value
                for key, value in (
                    ("interface", interface),
                    ("host", host),
                    ("port", port),
                    ("connect_timeout", connect_timeout),
                    ("receive_timeout", receive_timeout),
                )
                if value is not None
            },
        )
        safety = self.safety if read_only is None else SafetyConfig(read_only=read_only)
        log_cfg = (
            self.logging
            if log_level is None
            else replace(self.logging, level=log_level.upper())
        )
        return replace(self, enet=enet, safety=safety, logging=log_cfg)
