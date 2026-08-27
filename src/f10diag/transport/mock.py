"""In-memory transport for development and testing without a vehicle.

:class:`MockTransport` behaves like a real transport but is driven entirely by
the test: responses are queued explicitly, or produced by a responder callable.

It contains no BMW protocol knowledge and ships with no canned BMW payloads.
Whatever a test queues is what comes back, so a passing test can never be
mistaken for evidence about real vehicle behaviour.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import Any

from ..exceptions import (
    ConnectionFailedError,
    ConnectionLostError,
    TransportTimeoutError,
)
from .base import ConnectionState, Transport
from .packet import Direction

Responder = Callable[[bytes], bytes | None]


class MockTransport(Transport):
    """A scripted, in-memory transport.

    Example:
        >>> transport = MockTransport(responses=[b"\\x01\\x02"])
        >>> transport.connect()
        >>> transport.send(b"\\xAA")
        1
        >>> transport.receive()
        b'\\x01\\x02'
        >>> transport.sent
        [b'\\xaa']
    """

    def __init__(
        self,
        responses: list[bytes] | None = None,
        *,
        responder: Responder | None = None,
        name: str = "mock",
        fail_on_connect: str | None = None,
        drop_after_sends: int | None = None,
        latency: float = 0.0,
    ) -> None:
        """Create a mock transport.

        Args:
            responses: Payloads returned by successive :meth:`receive` calls.
            responder: Called with each sent payload; a non-``None`` return
                value is queued as a response. Takes precedence over
                ``responses`` for reply generation.
            name: Identifier reported in :meth:`get_interface_info`.
            fail_on_connect: When set, :meth:`connect` raises
                :class:`ConnectionFailedError` with this message.
            drop_after_sends: Simulate the peer disappearing after this many
                successful sends.
            latency: Artificial delay, in seconds, applied to each I/O call.
        """
        super().__init__()
        self._name = name
        self._queue: deque[bytes] = deque(responses or [])
        self._responder = responder
        self._fail_on_connect = fail_on_connect
        self._drop_after_sends = drop_after_sends
        self._latency = latency
        self._sent: list[bytes] = []
        self._connect_calls = 0
        self._disconnect_calls = 0

    # -- inspection helpers used by tests ---------------------------------

    @property
    def sent(self) -> list[bytes]:
        """Every payload passed to :meth:`send`, in order."""
        return list(self._sent)

    @property
    def pending_responses(self) -> int:
        """How many queued responses have not been consumed."""
        return len(self._queue)

    @property
    def connect_calls(self) -> int:
        return self._connect_calls

    @property
    def disconnect_calls(self) -> int:
        return self._disconnect_calls

    def queue_response(self, data: bytes) -> None:
        """Append a payload to be returned by a future :meth:`receive`."""
        self._queue.append(bytes(data))

    def set_fail_on_connect(self, message: str | None) -> None:
        """Arm or disarm a simulated connection failure."""
        self._fail_on_connect = message

    # -- Transport interface ----------------------------------------------

    def connect(self) -> None:
        self._connect_calls += 1
        if self._fail_on_connect is not None:
            self._set_state(ConnectionState.ERROR, self._fail_on_connect)
            raise ConnectionFailedError(self._fail_on_connect)
        self._set_state(ConnectionState.CONNECTED)

    def disconnect(self) -> None:
        self._disconnect_calls += 1
        if self._state is not ConnectionState.ERROR:
            self._set_state(ConnectionState.DISCONNECTED)

    def send(self, data: bytes) -> int:
        self._require_connected()
        if self._latency:
            time.sleep(self._latency)

        if (
            self._drop_after_sends is not None
            and len(self._sent) >= self._drop_after_sends
        ):
            message = "Mock peer closed the connection"
            self._set_state(ConnectionState.ERROR, message)
            raise ConnectionLostError(message)

        payload = bytes(data)
        self._sent.append(payload)
        self._emit(Direction.TX, payload)

        if self._responder is not None:
            reply = self._responder(payload)
            if reply is not None:
                self._queue.append(bytes(reply))
        return len(payload)

    def receive(self, size: int = 4096, timeout: float | None = None) -> bytes:
        self._require_connected()
        if self._latency:
            time.sleep(self._latency)
        if not self._queue:
            raise TransportTimeoutError(
                "MockTransport has no queued response "
                f"(timeout={timeout if timeout is not None else 0:g}s)"
            )
        payload = self._queue.popleft()
        if len(payload) > size:
            # Behave like a stream socket: return a partial read and keep the
            # remainder for the next call.
            self._queue.appendleft(payload[size:])
            payload = payload[:size]
        self._emit(Direction.RX, payload)
        return payload

    def get_interface_info(self) -> dict[str, Any]:
        return {
            "transport": "mock",
            "name": self._name,
            "state": self._state.value,
            "queued_responses": len(self._queue),
            "sent_payloads": len(self._sent),
        }
