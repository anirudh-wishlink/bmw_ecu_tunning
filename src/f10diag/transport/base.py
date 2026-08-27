"""Abstract transport interface.

A transport moves bytes and nothing else. It must not know about UDS, ECUs,
DTCs, or any BMW-specific concept; higher layers depend on this interface so
that the same protocol code can run over a real ENET cable, a mock, or a
recorded session.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from enum import Enum
from typing import Any

from ..exceptions import NotConnectedError
from .packet import DiagnosticPacket, Direction

PacketObserver = Callable[[DiagnosticPacket], None]


class ConnectionState(str, Enum):
    """Lifecycle state of a transport.

    ``CONNECTED`` describes the transport link only. For a TCP transport it
    means a socket is open, which is not evidence of vehicle communication.
    See :mod:`f10diag.status`.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class Transport(abc.ABC):
    """Base class for byte-level transports."""

    def __init__(self) -> None:
        self._state = ConnectionState.DISCONNECTED
        self._observers: list[PacketObserver] = []
        self._last_error: str | None = None

    # -- state ------------------------------------------------------------

    @property
    def state(self) -> ConnectionState:
        """Current lifecycle state."""
        return self._state

    @property
    def last_error(self) -> str | None:
        """Message of the most recent failure, if any."""
        return self._last_error

    def is_connected(self) -> bool:
        """Whether the transport link is currently open."""
        return self._state is ConnectionState.CONNECTED

    def _set_state(self, state: ConnectionState, error: str | None = None) -> None:
        self._state = state
        if error is not None:
            self._last_error = error
        elif state is ConnectionState.CONNECTED:
            self._last_error = None

    def _require_connected(self) -> None:
        if not self.is_connected():
            raise NotConnectedError(
                f"{type(self).__name__} is {self._state.value}; call connect() first"
            )

    # -- packet observation ----------------------------------------------

    def add_packet_observer(self, observer: PacketObserver) -> None:
        """Register a callback invoked for every TX and RX payload."""
        self._observers.append(observer)

    def remove_packet_observer(self, observer: PacketObserver) -> None:
        """Unregister a previously added observer. Unknown ones are ignored."""
        if observer in self._observers:
            self._observers.remove(observer)

    def _emit(
        self,
        direction: Direction,
        data: bytes,
        *,
        note: str | None = None,
    ) -> DiagnosticPacket:
        """Build a packet and hand it to every observer.

        An observer that raises must not break the transport, so exceptions are
        swallowed after being recorded on the transport's ``last_error``.
        """
        packet = DiagnosticPacket(
            direction=direction,
            raw_data=data,
            transport=self.get_interface_info(),
            note=note,
        )
        for observer in list(self._observers):
            try:
                observer(packet)
            except Exception as exc:  # noqa: BLE001 - logging must never break I/O
                self._last_error = f"packet observer failed: {exc}"
        return packet

    # -- interface --------------------------------------------------------

    @abc.abstractmethod
    def connect(self) -> None:
        """Open the transport link.

        Raises:
            TransportError: The link could not be established.
        """

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close the transport link. Must be safe to call when disconnected."""

    @abc.abstractmethod
    def send(self, data: bytes) -> int:
        """Send raw bytes and return the number of bytes written."""

    @abc.abstractmethod
    def receive(self, size: int = 4096, timeout: float | None = None) -> bytes:
        """Read up to ``size`` bytes.

        Args:
            size: Maximum number of bytes to return.
            timeout: Override for the configured receive timeout, in seconds.

        Raises:
            TransportTimeoutError: Nothing arrived within the timeout.
            ConnectionLostError: The peer closed the link.
        """

    @abc.abstractmethod
    def get_interface_info(self) -> dict[str, Any]:
        """Return transport metadata suitable for logs and capture files."""

    # -- context manager --------------------------------------------------

    def __enter__(self) -> Transport:
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.disconnect()
