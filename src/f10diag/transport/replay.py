"""Replay transport: re-run a recorded session with no vehicle attached.

A capture produced by :mod:`f10diag.logging.diagnostic_logger` is a chronological
list of TX and RX packets. :class:`ReplayTransport` walks that list: each
:meth:`send` consumes the next recorded TX packet, and each :meth:`receive`
yields the next recorded RX packet.

Because a replay only ever returns bytes that were genuinely observed, it can
be used to develop decoders without inventing data. A replay proves that a
decoder handles a recording; it proves nothing about traffic never recorded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..exceptions import (
    ConnectionFailedError,
    MalformedPacketError,
    TransportError,
    TransportTimeoutError,
)
from .base import ConnectionState, Transport
from .packet import DiagnosticPacket, Direction


class ReplayMismatchError(TransportError):
    """A replayed send did not match the recorded request in strict mode."""


def load_capture(path: Path | str) -> tuple[list[DiagnosticPacket], dict[str, Any]]:
    """Load a capture file.

    Two layouts are accepted:

    * JSON Lines: one packet object per line, optionally preceded by a
      ``{"type": "session"}`` header line.
    * A single JSON object with a ``packets`` array and optional ``session``
      metadata.

    Returns:
        ``(packets, session_metadata)``.

    Raises:
        MalformedPacketError: The file is not a readable capture.
    """
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MalformedPacketError(f"Cannot read capture {file_path}: {exc}") from exc

    stripped = text.strip()
    if not stripped:
        raise MalformedPacketError(f"Capture {file_path} is empty")

    packets: list[DiagnosticPacket] = []
    session: dict[str, Any] = {}

    if stripped.startswith("{") and '"packets"' in stripped[:4096]:
        try:
            document = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise MalformedPacketError(f"Capture {file_path}: {exc}") from exc
        session = document.get("session", {}) or {}
        records = document.get("packets", [])
        if not isinstance(records, list):
            raise MalformedPacketError(f"Capture {file_path}: 'packets' must be a list")
    else:
        records = []
        for number, line in enumerate(stripped.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MalformedPacketError(
                    f"Capture {file_path} line {number}: {exc}"
                ) from exc
            if record.get("type") == "session":
                session = record.get("session", record)
                continue
            records.append(record)

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise MalformedPacketError(
                f"Capture {file_path}: packet {index} is not an object"
            )
        try:
            packets.append(DiagnosticPacket.from_dict(record))
        except ValueError as exc:
            raise MalformedPacketError(
                f"Capture {file_path}: packet {index}: {exc}"
            ) from exc

    return packets, session


class ReplayTransport(Transport):
    """Replay a recorded session as if it were a live transport.

    Example:
        >>> transport = ReplayTransport("captures/session.json")  # doctest: +SKIP
        >>> transport.connect()                                   # doctest: +SKIP
        >>> transport.send(recorded_request)                      # doctest: +SKIP
        >>> transport.receive()                                   # doctest: +SKIP
    """

    def __init__(
        self,
        source: Path | str | list[DiagnosticPacket],
        *,
        strict: bool = True,
        session: dict[str, Any] | None = None,
    ) -> None:
        """Create a replay transport.

        Args:
            source: Path to a capture file, or an explicit packet list.
            strict: When ``True``, a :meth:`send` whose bytes differ from the
                next recorded TX packet raises :class:`ReplayMismatchError`.
                When ``False``, mismatches are recorded but tolerated.
            session: Session metadata, when ``source`` is a packet list.
        """
        super().__init__()
        if isinstance(source, list):
            self._packets = list(source)
            self._session = session or {}
            self._path: Path | None = None
        else:
            self._path = Path(source)
            self._packets, self._session = load_capture(self._path)
        self._strict = strict
        self._cursor = 0
        self._mismatches: list[tuple[int, bytes, bytes]] = []

    # -- inspection -------------------------------------------------------

    @property
    def packets(self) -> list[DiagnosticPacket]:
        """All packets in the capture."""
        return list(self._packets)

    @property
    def session(self) -> dict[str, Any]:
        """Session metadata recorded with the capture."""
        return dict(self._session)

    @property
    def cursor(self) -> int:
        """Index of the next packet to be replayed."""
        return self._cursor

    @property
    def exhausted(self) -> bool:
        """Whether every recorded packet has been replayed."""
        return self._cursor >= len(self._packets)

    @property
    def mismatches(self) -> list[tuple[int, bytes, bytes]]:
        """Non-strict mismatches as ``(index, expected, actual)`` tuples."""
        return list(self._mismatches)

    def rewind(self) -> None:
        """Return to the start of the capture."""
        self._cursor = 0
        self._mismatches.clear()

    # -- Transport interface ----------------------------------------------

    def connect(self) -> None:
        if not self._packets:
            message = "Capture contains no packets to replay"
            self._set_state(ConnectionState.ERROR, message)
            raise ConnectionFailedError(message)
        self._cursor = 0
        self._mismatches.clear()
        self._set_state(ConnectionState.CONNECTED)

    def disconnect(self) -> None:
        if self._state is not ConnectionState.ERROR:
            self._set_state(ConnectionState.DISCONNECTED)

    def send(self, data: bytes) -> int:
        """Consume the next recorded TX packet.

        Raises:
            TransportTimeoutError: The capture has no further TX packet.
            ReplayMismatchError: Strict mode, and the bytes differ.
        """
        self._require_connected()
        payload = bytes(data)

        index = self._next_index(Direction.TX)
        if index is None:
            raise TransportTimeoutError(
                "Replay exhausted: the capture contains no further TX packet"
            )

        expected = self._packets[index].raw_data
        if expected != payload:
            self._mismatches.append((index, expected, payload))
            if self._strict:
                raise ReplayMismatchError(
                    f"Replay mismatch at packet {index}: capture recorded "
                    f"{expected.hex(' ').upper()} but {payload.hex(' ').upper()} "
                    "was sent"
                )

        self._cursor = index + 1
        self._emit(Direction.TX, payload, note=f"replay index {index}")
        return len(payload)

    def receive(self, size: int = 4096, timeout: float | None = None) -> bytes:
        """Return the next recorded RX packet.

        Raises:
            TransportTimeoutError: The capture has no further RX packet.
        """
        self._require_connected()
        index = self._next_index(Direction.RX)
        if index is None:
            raise TransportTimeoutError(
                "Replay exhausted: the capture contains no further RX packet"
            )

        packet = self._packets[index]
        payload = packet.raw_data
        self._cursor = index + 1

        if len(payload) > size:
            remainder = payload[size:]
            payload = payload[:size]
            # Re-insert the remainder so stream semantics are preserved.
            self._packets.insert(
                self._cursor,
                DiagnosticPacket(
                    direction=Direction.RX,
                    raw_data=remainder,
                    timestamp=packet.timestamp,
                    transport=packet.transport,
                    note="replay split remainder",
                ),
            )

        self._emit(Direction.RX, payload, note=f"replay index {index}")
        return payload

    def get_interface_info(self) -> dict[str, Any]:
        return {
            "transport": "replay",
            "state": self._state.value,
            "source": str(self._path) if self._path else "<in-memory>",
            "packets": len(self._packets),
            "cursor": self._cursor,
            "strict": self._strict,
        }

    # -- internals --------------------------------------------------------

    def _next_index(self, direction: Direction) -> int | None:
        """Index of the next packet with the given direction, or ``None``."""
        for index in range(self._cursor, len(self._packets)):
            if self._packets[index].direction is direction:
                return index
        return None
