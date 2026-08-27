"""ENET (Ethernet) transport.

Moves raw bytes over a TCP socket to a host and port supplied by the operator.

What this module deliberately does NOT do:

* It does not hard-code a BMW gateway IP address or TCP port. Those values are
  UNVERIFIED for this project, so the transport refuses to connect until they
  are configured explicitly (see :meth:`ENETConfig.validate_for_connection`).
* It does not send anything on its own. No handshake, no keep-alive, no
  activation frame. Only bytes passed to :meth:`ENETTransport.send` are
  transmitted.
* It does not interpret received bytes.

Consequently, a successful :meth:`connect` proves only that a TCP peer
accepted the connection. It is never evidence of vehicle or ECU communication.
"""

from __future__ import annotations

import errno
import logging
import socket
import time
from typing import Any

from ..config import ENETConfig
from ..exceptions import (
    ConnectionFailedError,
    ConnectionLostError,
    InterfaceUnavailableError,
    TransportTimeoutError,
)
from ..status import CommsLevel
from .base import ConnectionState, Transport
from .ethernet import NetworkInterface, select_interface
from .packet import Direction

logger = logging.getLogger(__name__)


class ENETTransport(Transport):
    """TCP byte transport over an Ethernet (ENET) interface.

    Example:
        >>> config = ENETConfig(interface="en7", host="10.0.0.1", port=1234)
        >>> transport = ENETTransport(config)   # doctest: +SKIP
        >>> with transport:                     # doctest: +SKIP
        ...     transport.send(b"\\x00")
    """

    def __init__(
        self,
        config: ENETConfig,
        *,
        bind_to_interface: bool = True,
    ) -> None:
        """Create a transport.

        Args:
            config: Connection parameters.
            bind_to_interface: Bind the local socket to the selected
                interface's IPv4 address. Useful when several interfaces are
                active; harmless otherwise.
        """
        super().__init__()
        self._config = config
        self._bind_to_interface = bind_to_interface
        self._socket: socket.socket | None = None
        self._interface: NetworkInterface | None = None
        self._connected_at: float | None = None
        self._bytes_sent = 0
        self._bytes_received = 0

    # -- properties -------------------------------------------------------

    @property
    def config(self) -> ENETConfig:
        return self._config

    @property
    def interface(self) -> NetworkInterface | None:
        """The interface resolved during the last connect attempt."""
        return self._interface

    @property
    def comms_level(self) -> CommsLevel:
        """How far communication has actually been proven.

        A connected ENET transport never reports more than
        :attr:`CommsLevel.TCP_CONNECTED`; higher levels belong to protocol
        layers that do not exist yet.
        """
        if not self.is_connected():
            if self._interface is None:
                return CommsLevel.NONE
            if self._interface.has_link:
                return CommsLevel.ETHERNET_LINK
            return CommsLevel.INTERFACE_PRESENT
        return CommsLevel.TCP_CONNECTED

    @property
    def bytes_sent(self) -> int:
        return self._bytes_sent

    @property
    def bytes_received(self) -> int:
        return self._bytes_received

    # -- interface resolution --------------------------------------------

    def resolve_interface(self) -> NetworkInterface:
        """Resolve and validate the interface named in the configuration.

        Raises:
            InterfaceNotFoundError: The configured interface does not exist.
            InterfaceUnavailableError: The interface exists but has no link.
        """
        iface = select_interface(self._config.interface)
        if not iface.has_link:
            raise InterfaceUnavailableError(
                f"Interface {iface.name} has no active link "
                f"(status: {iface.describe_status()}). Check that the ENET "
                "cable is plugged into both the Mac and the OBD-II port."
            )
        self._interface = iface
        return iface

    # -- connection lifecycle ---------------------------------------------

    def connect(self) -> None:
        """Open a TCP connection to the configured host and port.

        Raises:
            UnverifiedParameterError: ``host`` or ``port`` was never supplied.
            InterfaceNotFoundError: The configured interface does not exist.
            InterfaceUnavailableError: The interface has no active link.
            ConnectionFailedError: The TCP handshake failed.
        """
        if self.is_connected():
            return

        self._config.validate_for_connection()
        host = self._config.host
        port = self._config.port
        assert host is not None and port is not None  # guaranteed by validate

        self._set_state(ConnectionState.CONNECTING)

        try:
            iface = self.resolve_interface()
        except Exception as exc:
            self._set_state(ConnectionState.ERROR, str(exc))
            raise

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self._config.connect_timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        try:
            if self._bind_to_interface and iface.ipv4:
                # Bind to the interface address so the OS does not route the
                # connection out of Wi-Fi when several links are up.
                sock.bind((iface.ipv4[0].address, 0))
            logger.debug("TCP connect %s:%s via %s", host, port, iface.name)
            sock.connect((host, port))
        except socket.timeout as exc:
            sock.close()
            message = (
                f"Timed out after {self._config.connect_timeout:g}s connecting to "
                f"{host}:{port} via {iface.name}. Nothing accepted the connection; "
                "check the cable, and that the vehicle ignition is on."
            )
            self._set_state(ConnectionState.ERROR, message)
            raise ConnectionFailedError(message) from exc
        except OSError as exc:
            sock.close()
            hint = ""
            if exc.errno == errno.ECONNREFUSED:
                hint = " The peer actively refused the connection."
            elif exc.errno == errno.EADDRNOTAVAIL:
                hint = f" The address bound to {iface.name} is no longer valid."
            elif exc.errno in (errno.EHOSTUNREACH, errno.ENETUNREACH):
                hint = " No route to that address from this interface."
            message = f"Could not connect to {host}:{port} via {iface.name}: {exc}.{hint}"
            self._set_state(ConnectionState.ERROR, message)
            raise ConnectionFailedError(message) from exc

        sock.settimeout(self._config.receive_timeout)
        self._socket = sock
        self._connected_at = time.time()
        self._set_state(ConnectionState.CONNECTED)
        logger.info(
            "TCP socket open to %s:%s via %s (transport level only)",
            host,
            port,
            iface.name,
        )

    def disconnect(self) -> None:
        """Close the socket. Safe to call repeatedly."""
        sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # already closed by the peer
            finally:
                sock.close()
            logger.info("TCP socket closed")
        self._connected_at = None
        if self._state is not ConnectionState.ERROR:
            self._set_state(ConnectionState.DISCONNECTED)

    def reconnect(self) -> None:
        """Close and reopen the connection, honouring the retry configuration.

        Raises:
            ConnectionFailedError: Every attempt failed.
        """
        self.disconnect()
        attempts = max(1, self._config.reconnect_attempts + 1)
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._set_state(ConnectionState.DISCONNECTED)
                self.connect()
                return
            except ConnectionFailedError as exc:
                last = exc
                logger.warning("Reconnect attempt %d/%d failed: %s", attempt, attempts, exc)
                if attempt < attempts and self._config.reconnect_delay:
                    time.sleep(self._config.reconnect_delay)
        assert last is not None
        raise last

    # -- I/O --------------------------------------------------------------

    def send(self, data: bytes) -> int:
        """Send raw bytes.

        Args:
            data: Payload to transmit, verbatim.

        Returns:
            Number of bytes written.

        Raises:
            NotConnectedError: The socket is not open.
            ConnectionLostError: The peer closed the connection.
        """
        self._require_connected()
        assert self._socket is not None
        try:
            self._socket.sendall(data)
        except socket.timeout as exc:
            message = f"Timed out sending {len(data)} bytes"
            self._set_state(ConnectionState.ERROR, message)
            raise TransportTimeoutError(message) from exc
        except OSError as exc:
            message = f"Connection lost while sending: {exc}"
            self._set_state(ConnectionState.ERROR, message)
            self.disconnect()
            raise ConnectionLostError(message) from exc

        self._bytes_sent += len(data)
        self._emit(Direction.TX, data)
        return len(data)

    def receive(self, size: int = 4096, timeout: float | None = None) -> bytes:
        """Read up to ``size`` bytes.

        Raises:
            NotConnectedError: The socket is not open.
            TransportTimeoutError: Nothing arrived before the timeout.
            ConnectionLostError: The peer closed the connection.
        """
        self._require_connected()
        assert self._socket is not None

        effective = self._config.receive_timeout if timeout is None else timeout
        previous = self._socket.gettimeout()
        if effective != previous:
            self._socket.settimeout(effective)

        try:
            chunk = self._socket.recv(size)
        except socket.timeout as exc:
            raise TransportTimeoutError(
                f"No data received within {effective:g}s"
            ) from exc
        except OSError as exc:
            message = f"Connection lost while receiving: {exc}"
            self._set_state(ConnectionState.ERROR, message)
            self.disconnect()
            raise ConnectionLostError(message) from exc
        finally:
            if self._socket is not None and effective != previous:
                try:
                    self._socket.settimeout(previous)
                except OSError:
                    pass

        if not chunk:
            message = "Peer closed the connection"
            self._set_state(ConnectionState.ERROR, message)
            self.disconnect()
            raise ConnectionLostError(message)

        self._bytes_received += len(chunk)
        self._emit(Direction.RX, chunk)
        return chunk

    def receive_exactly(self, size: int, timeout: float | None = None) -> bytes:
        """Read exactly ``size`` bytes, or raise.

        The overall deadline applies to the whole read, not to each chunk.

        Raises:
            TransportTimeoutError: The full payload did not arrive in time.
            ConnectionLostError: The peer closed the connection mid-payload.
        """
        effective = self._config.receive_timeout if timeout is None else timeout
        deadline = time.monotonic() + effective
        buffer = bytearray()
        while len(buffer) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportTimeoutError(
                    f"Received {len(buffer)} of {size} bytes before the "
                    f"{effective:g}s deadline"
                )
            try:
                buffer += self.receive(size - len(buffer), timeout=remaining)
            except TransportTimeoutError as exc:
                raise TransportTimeoutError(
                    f"Received {len(buffer)} of {size} bytes before the "
                    f"{effective:g}s deadline"
                ) from exc
        return bytes(buffer)

    # -- metadata ---------------------------------------------------------

    def get_interface_info(self) -> dict[str, Any]:
        """Return transport metadata for logs and capture files."""
        info: dict[str, Any] = {
            "transport": "enet-tcp",
            "state": self._state.value,
            "comms_level": self.comms_level.name,
            "host": self._config.host,
            "port": self._config.port,
            "interface": self._interface.name if self._interface else self._config.interface,
        }
        if self._interface is not None:
            info["interface_status"] = self._interface.describe_status()
            info["interface_mac"] = self._interface.mac
            if self._interface.ipv4:
                info["local_ipv4"] = self._interface.ipv4[0].address
        if self._config.host and self._config.port:
            info["peer"] = f"{self._config.host}:{self._config.port}"
        if self._socket is not None:
            try:
                info["local_endpoint"] = "%s:%d" % self._socket.getsockname()
            except OSError:
                pass
        if self._connected_at is not None:
            info["connected_for"] = round(time.time() - self._connected_at, 3)
        return info


def probe_tcp(
    host: str,
    port: int,
    *,
    timeout: float = 3.0,
    source_address: str | None = None,
) -> tuple[bool, str]:
    """Test whether a TCP connection can be opened, sending no payload.

    This is a pure reachability check. A ``True`` result means a TCP peer
    accepted the connection; it says nothing about BMW protocol support.

    Returns:
        ``(reachable, explanation)``.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        if source_address:
            sock.bind((source_address, 0))
        started = time.monotonic()
        sock.connect((host, port))
        elapsed = (time.monotonic() - started) * 1000
        return True, f"TCP handshake completed in {elapsed:.1f} ms"
    except socket.timeout:
        return False, f"No response within {timeout:g}s"
    except OSError as exc:
        return False, str(exc)
    finally:
        sock.close()
