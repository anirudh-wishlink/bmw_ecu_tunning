"""Structured diagnostic logging and packet capture.

Two things are recorded:

* Application events through the standard :mod:`logging` module.
* Every raw TX/RX payload through :class:`DiagnosticLogger`, which attaches
  itself to a transport as a packet observer.

Captures are written as JSON Lines so that a session survives a crash: each
packet is flushed as it happens. :func:`export_capture` converts a JSONL
capture to a single JSON document or to a plain-text transcript.
"""

from __future__ import annotations

import json
import logging
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO

from ..transport.packet import DiagnosticPacket, Direction

CAPTURE_FORMAT = "f10diag-capture"
CAPTURE_VERSION = 1

logger = logging.getLogger("f10diag")


def configure_logging(level: str = "INFO", *, stream: TextIO | None = None) -> None:
    """Configure the root ``f10diag`` logger.

    Args:
        level: One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
        stream: Destination stream, defaulting to stderr so that machine
            readable command output on stdout stays clean.
    """
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger("f10diag")
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False


@dataclass(slots=True)
class SessionMetadata:
    """Context recorded alongside a capture.

    ``comms_level`` records how far communication was actually proven during
    the session, so a capture can never imply more than was achieved.
    """

    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        )
    )
    tool_version: str = "0.1.0"
    host_os: str = field(default_factory=lambda: f"{platform.system()} {platform.release()}")
    python_version: str = field(default_factory=platform.python_version)
    vehicle: dict[str, Any] = field(default_factory=dict)
    transport: dict[str, Any] = field(default_factory=dict)
    read_only: bool = True
    comms_level: str = "NONE"
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "tool_version": self.tool_version,
            "host_os": self.host_os,
            "python_version": self.python_version,
            "vehicle": self.vehicle,
            "transport": self.transport,
            "read_only": self.read_only,
            "comms_level": self.comms_level,
            "notes": self.notes,
        }


class DiagnosticLogger:
    """Record raw traffic to a capture file and to the application log.

    Attach it to any :class:`~f10diag.transport.base.Transport`::

        with DiagnosticLogger(path) as capture:
            transport.add_packet_observer(capture.record)

    The logger only observes. It never modifies, injects, or reorders traffic.
    """

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        metadata: SessionMetadata | None = None,
        echo: bool = False,
    ) -> None:
        """Create a logger.

        Args:
            path: Capture file to write. ``None`` keeps packets in memory only.
            metadata: Session context written as the first record.
            echo: Also emit each packet to the application log at DEBUG level.
        """
        self._path = Path(path) if path is not None else None
        self._metadata = metadata or SessionMetadata()
        self._echo = echo
        self._handle: TextIO | None = None
        self._packets: list[DiagnosticPacket] = []
        self._counts = {Direction.TX: 0, Direction.RX: 0}

    # -- properties -------------------------------------------------------

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def packets(self) -> list[DiagnosticPacket]:
        """Every packet observed in this session."""
        return list(self._packets)

    @property
    def metadata(self) -> SessionMetadata:
        return self._metadata

    def counts(self) -> dict[str, int]:
        """Packet counts per direction."""
        return {
            direction.value: count for direction, count in self._counts.items()
        }

    # -- lifecycle --------------------------------------------------------

    def open(self) -> DiagnosticLogger:
        """Open the capture file and write the session header."""
        if self._path is None or self._handle is not None:
            return self
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("a", encoding="utf-8")
        self._write_line(
            {
                "type": "session",
                "format": CAPTURE_FORMAT,
                "version": CAPTURE_VERSION,
                "session": self._metadata.to_dict(),
            }
        )
        logger.debug("Capture opened: %s", self._path)
        return self

    def close(self) -> None:
        """Flush and close the capture file."""
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None
            logger.debug("Capture closed: %s", self._path)

    def __enter__(self) -> DiagnosticLogger:
        return self.open()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- recording --------------------------------------------------------

    def record(self, packet: DiagnosticPacket) -> None:
        """Observe one packet. Intended as a transport packet observer."""
        self._packets.append(packet)
        self._counts[packet.direction] = self._counts.get(packet.direction, 0) + 1
        self._write_line(packet.to_dict())
        if self._echo:
            logger.debug("%s", packet.format_line())

    def record_event(self, event: str, **fields: Any) -> None:
        """Record a non-packet event, such as a connection state change."""
        record = {
            "type": "event",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            **fields,
        }
        self._write_line(record)
        logger.info("%s %s", event, " ".join(f"{k}={v}" for k, v in fields.items()))

    def update_comms_level(self, level: str) -> None:
        """Record the highest communication level proven during the session."""
        self._metadata.comms_level = level
        self.record_event("comms_level", level=level)

    # -- export -----------------------------------------------------------

    def to_document(self) -> dict[str, Any]:
        """Build a single JSON document from the in-memory session."""
        return {
            "format": CAPTURE_FORMAT,
            "version": CAPTURE_VERSION,
            "session": self._metadata.to_dict(),
            "packets": [packet.to_dict() for packet in self._packets],
        }

    def export_json(self, path: Path | str) -> Path:
        """Write the session as one JSON document."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_document(), indent=2) + "\n", encoding="utf-8"
        )
        return target

    def export_text(self, path: Path | str) -> Path:
        """Write the session as a plain-text transcript."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# {CAPTURE_FORMAT} v{CAPTURE_VERSION}",
            f"# started_at      {self._metadata.started_at}",
            f"# host            {self._metadata.host_os}",
            f"# read_only       {self._metadata.read_only}",
            f"# comms_level     {self._metadata.comms_level}",
            "",
        ]
        lines.extend(packet.format_line() for packet in self._packets)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target

    # -- internals --------------------------------------------------------

    def _write_line(self, record: dict[str, Any]) -> None:
        if self._handle is None:
            return
        self._handle.write(json.dumps(record) + "\n")
        self._handle.flush()


def export_capture(source: Path | str, target: Path | str, fmt: str = "json") -> Path:
    """Convert a JSONL capture into another format.

    Args:
        source: Path to a capture written by :class:`DiagnosticLogger`.
        target: Output path.
        fmt: ``"json"`` for a single document, ``"text"`` for a transcript.

    Raises:
        ValueError: ``fmt`` is not a supported format.

    Note:
        PCAP export is not implemented. A capture records transport payloads,
        not complete Ethernet frames, so writing a faithful PCAP would require
        synthesising link and IP headers that were never observed. See
        docs/development.md.
    """
    from ..transport.replay import load_capture  # local import avoids a cycle

    packets, session = load_capture(source)
    output = Path(target)
    output.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        document = {
            "format": CAPTURE_FORMAT,
            "version": CAPTURE_VERSION,
            "session": session,
            "packets": [packet.to_dict() for packet in packets],
        }
        output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    elif fmt == "text":
        header = [f"# {CAPTURE_FORMAT} v{CAPTURE_VERSION}"]
        header += [f"# {key:15} {value}" for key, value in session.items()]
        body = [packet.format_line() for packet in packets]
        output.write_text("\n".join(header + [""] + body) + "\n", encoding="utf-8")
    else:
        raise ValueError(f"Unsupported export format: {fmt!r} (use 'json' or 'text')")

    return output


def default_capture_path(directory: Path | str, prefix: str = "session") -> Path:
    """Build a timestamped capture path inside ``directory``."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(directory) / f"{prefix}-{stamp}.jsonl"
