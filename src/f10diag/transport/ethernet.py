"""macOS network interface discovery.

This module only *inspects* the host. It never changes macOS network
configuration: no interface is brought up or down, no address is assigned, and
no service order is modified. When configuration appears to be required, the
CLI explains what the operator would have to change.

Everything here is derived from documented macOS tooling (``ifconfig`` and
``networksetup``). No BMW-specific assumption is encoded in this file.
"""

from __future__ import annotations

import ipaddress
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from ..exceptions import InterfaceNotFoundError

#: Interface name prefixes that can never carry an ENET cable on macOS.
_VIRTUAL_PREFIXES = (
    "lo",  # loopback
    "gif",  # generic tunnel
    "stf",  # 6to4 tunnel
    "utun",  # VPN / system tunnels
    "awdl",  # Apple Wireless Direct Link
    "llw",  # low-latency WLAN
    "bridge",  # software bridge
    "ap",  # AirPort software access point
    "anpi",  # Apple internal network processor
    "vmenet",  # virtualisation
    "vmnet",  # VMware
    "utap",
    "ipsec",
    "pflog",
    "XHC",  # USB host controller pseudo-interfaces
)

_WIRELESS_PORT_HINTS = ("wi-fi", "wifi", "airport", "wwan", "bluetooth", "iphone")
_ETHERNET_PORT_HINTS = ("ethernet", "lan", "rj45", "rj-45")

_IFACE_HEADER = re.compile(r"^(?P<name>[a-zA-Z0-9._-]+):\s+flags=(?P<flags>\d+)<(?P<names>[^>]*)>(?:\s+mtu\s+(?P<mtu>\d+))?")
_INET = re.compile(r"^\s*inet\s+(?P<addr>[0-9.]+)(?:\s+netmask\s+(?P<mask>0x[0-9a-fA-F]+|[0-9.]+))?(?:\s+broadcast\s+(?P<bcast>[0-9.]+))?")
_INET6 = re.compile(r"^\s*inet6\s+(?P<addr>[0-9a-fA-F:]+)")
_ETHER = re.compile(r"^\s*ether\s+(?P<mac>[0-9a-fA-F:]{17})")
_STATUS = re.compile(r"^\s*status:\s+(?P<status>\S+)")
_MEDIA = re.compile(r"^\s*media:\s+(?P<media>.+)$")


@dataclass(frozen=True, slots=True)
class IPv4Address:
    """A single IPv4 address configured on an interface."""

    address: str
    netmask: str | None = None
    broadcast: str | None = None

    @property
    def is_link_local(self) -> bool:
        """Whether the address is in 169.254.0.0/16 (APIPA).

        On macOS this means DHCP found no server on that link and the OS
        self-assigned an address. It is a statement about the host, not about
        any particular peer device.
        """
        try:
            return ipaddress.IPv4Address(self.address).is_link_local
        except ValueError:
            return False

    def __str__(self) -> str:
        return self.address if not self.netmask else f"{self.address}/{self.netmask}"


@dataclass(frozen=True, slots=True)
class NetworkInterface:
    """A network interface as reported by the operating system."""

    name: str
    flags: tuple[str, ...] = ()
    mtu: int | None = None
    mac: str | None = None
    ipv4: tuple[IPv4Address, ...] = ()
    ipv6: tuple[str, ...] = ()
    status: str | None = None
    media: str | None = None
    hardware_port: str | None = None

    # -- derived properties ----------------------------------------------

    @property
    def is_up(self) -> bool:
        """Interface is administratively up."""
        return "UP" in self.flags

    @property
    def is_running(self) -> bool:
        """Interface has resources allocated (usually implies carrier)."""
        return "RUNNING" in self.flags

    @property
    def is_loopback(self) -> bool:
        return "LOOPBACK" in self.flags

    @property
    def has_link(self) -> bool:
        """Interface reports an active link.

        ``ifconfig`` prints ``status: active`` when a carrier is present. Some
        interfaces omit the status line, in which case RUNNING is used.
        """
        if self.status is not None:
            return self.status == "active"
        return self.is_running

    @property
    def is_virtual(self) -> bool:
        return self.name.startswith(_VIRTUAL_PREFIXES)

    @property
    def is_wireless(self) -> bool:
        port = (self.hardware_port or "").lower()
        return any(hint in port for hint in _WIRELESS_PORT_HINTS)

    @property
    def is_ethernet_like(self) -> bool:
        """Whether this interface could plausibly carry an ENET cable.

        True for a physical, non-wireless interface with a MAC address. USB and
        Thunderbolt Ethernet adapters, which is what an ENET cable presents as,
        appear as ``enN`` with an Ethernet-style hardware port name.
        """
        if self.is_loopback or self.is_virtual or self.is_wireless:
            return False
        if self.mac is None:
            return False
        port = (self.hardware_port or "").lower()
        if any(hint in port for hint in _ETHERNET_PORT_HINTS):
            return True
        # No hardware port information (e.g. a hot-plugged adapter that
        # networksetup has not catalogued): fall back to the naming convention.
        return self.hardware_port is None and self.name.startswith("en")

    @property
    def link_local_ipv4(self) -> IPv4Address | None:
        """First APIPA address on the interface, if any."""
        return next((addr for addr in self.ipv4 if addr.is_link_local), None)

    def describe_status(self) -> str:
        """Short human-readable status such as ``active`` or ``inactive``."""
        if self.status:
            return self.status
        if self.is_running:
            return "running"
        return "up" if self.is_up else "down"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "hardware_port": self.hardware_port,
            "status": self.describe_status(),
            "flags": list(self.flags),
            "mtu": self.mtu,
            "mac": self.mac,
            "ipv4": [
                {
                    "address": addr.address,
                    "netmask": addr.netmask,
                    "broadcast": addr.broadcast,
                    "link_local": addr.is_link_local,
                }
                for addr in self.ipv4
            ],
            "ipv6": list(self.ipv6),
            "media": self.media,
            "ethernet_like": self.is_ethernet_like,
        }


@dataclass(frozen=True, slots=True)
class InterfaceCandidate:
    """An Ethernet-class interface ranked as a possible ENET attachment point."""

    interface: NetworkInterface
    score: int
    reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _run(command: list[str], timeout: float = 5.0) -> str:
    """Run a read-only system command, returning stdout or ``""`` on failure."""
    executable = shutil.which(command[0])
    if executable is None:
        return ""
    try:
        result = subprocess.run(  # noqa: S603 - fixed, read-only commands
            [executable, *command[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _netmask_to_dotted(mask: str | None) -> str | None:
    """Convert ``ifconfig``'s hex netmask (``0xffffff00``) to dotted quad."""
    if mask is None:
        return None
    if not mask.startswith("0x"):
        return mask
    try:
        value = int(mask, 16)
    except ValueError:
        return None
    return str(ipaddress.IPv4Address(value))


def parse_ifconfig(output: str) -> list[NetworkInterface]:
    """Parse ``ifconfig -a`` output into interface records.

    Unrecognised lines are ignored so that macOS version differences degrade
    gracefully instead of raising.
    """
    interfaces: list[NetworkInterface] = []
    current: dict[str, Any] | None = None

    def flush() -> None:
        if current is None:
            return
        interfaces.append(
            NetworkInterface(
                name=current["name"],
                flags=tuple(current["flags"]),
                mtu=current["mtu"],
                mac=current["mac"],
                ipv4=tuple(current["ipv4"]),
                ipv6=tuple(current["ipv6"]),
                status=current["status"],
                media=current["media"],
            )
        )

    for line in output.splitlines():
        header = _IFACE_HEADER.match(line)
        if header:
            flush()
            names = [flag for flag in header.group("names").split(",") if flag]
            mtu = header.group("mtu")
            current = {
                "name": header.group("name"),
                "flags": names,
                "mtu": int(mtu) if mtu else None,
                "mac": None,
                "ipv4": [],
                "ipv6": [],
                "status": None,
                "media": None,
            }
            continue

        if current is None:
            continue

        if match := _ETHER.match(line):
            current["mac"] = match.group("mac").lower()
        elif match := _INET.match(line):
            current["ipv4"].append(
                IPv4Address(
                    address=match.group("addr"),
                    netmask=_netmask_to_dotted(match.group("mask")),
                    broadcast=match.group("bcast"),
                )
            )
        elif match := _INET6.match(line):
            current["ipv6"].append(match.group("addr"))
        elif match := _STATUS.match(line):
            current["status"] = match.group("status")
        elif match := _MEDIA.match(line):
            current["media"] = match.group("media").strip()

    flush()
    return interfaces


def parse_hardware_ports(output: str) -> dict[str, str]:
    """Map device name to hardware port name from ``networksetup`` output."""
    ports: dict[str, str] = {}
    port_name: str | None = None
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Hardware Port:"):
            port_name = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Device:") and port_name:
            device = stripped.split(":", 1)[1].strip()
            if device:
                ports[device] = port_name
            port_name = None
    return ports


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def is_macos() -> bool:
    """Whether the host is macOS."""
    return platform.system() == "Darwin"


def list_interfaces() -> list[NetworkInterface]:
    """Enumerate host network interfaces.

    Returns an empty list if the platform tools are unavailable rather than
    raising, so that the CLI can print a useful explanation.
    """
    interfaces = parse_ifconfig(_run(["ifconfig", "-a"]))
    ports = parse_hardware_ports(_run(["networksetup", "-listallhardwareports"]))
    if not ports:
        return interfaces
    return [
        NetworkInterface(
            name=iface.name,
            flags=iface.flags,
            mtu=iface.mtu,
            mac=iface.mac,
            ipv4=iface.ipv4,
            ipv6=iface.ipv6,
            status=iface.status,
            media=iface.media,
            hardware_port=ports.get(iface.name),
        )
        for iface in interfaces
    ]


def get_interface(name: str) -> NetworkInterface:
    """Look up a single interface by name.

    Raises:
        InterfaceNotFoundError: No interface with that name exists.
    """
    for iface in list_interfaces():
        if iface.name == name:
            return iface
    raise InterfaceNotFoundError(f"No network interface named {name!r} on this host")


def ethernet_interfaces(
    interfaces: list[NetworkInterface] | None = None,
) -> list[NetworkInterface]:
    """Filter for interfaces that could plausibly carry an ENET cable."""
    pool = list_interfaces() if interfaces is None else interfaces
    return [iface for iface in pool if iface.is_ethernet_like]


def rank_candidates(
    interfaces: list[NetworkInterface] | None = None,
) -> list[InterfaceCandidate]:
    """Rank Ethernet-class interfaces by how likely they are to be the ENET link.

    The ranking uses only host-side facts and is a hint, not a detection of
    BMW hardware. Nothing about the peer is assumed or probed.
    """
    candidates: list[InterfaceCandidate] = []

    for iface in ethernet_interfaces(interfaces):
        score = 0
        reasons: list[str] = []
        warnings: list[str] = []

        if iface.has_link:
            score += 40
            reasons.append("link is active")
        else:
            warnings.append("no link detected - cable may be unplugged")

        port = (iface.hardware_port or "").lower()
        if "usb" in port or "thunderbolt" in port:
            score += 20
            reasons.append(f"external adapter ({iface.hardware_port})")

        if iface.link_local_ipv4 is not None:
            score += 25
            reasons.append(
                "has a 169.254.x.x self-assigned address, i.e. no DHCP server "
                "responded on this link"
            )
        elif iface.ipv4:
            addresses = ", ".join(addr.address for addr in iface.ipv4)
            score += 5
            warnings.append(
                f"has a routable address ({addresses}); this looks like a normal "
                "network rather than a point-to-point link"
            )
        else:
            warnings.append("no IPv4 address configured")

        if iface.is_up:
            score += 5

        candidates.append(
            InterfaceCandidate(
                interface=iface,
                score=score,
                reasons=tuple(reasons),
                warnings=tuple(warnings),
            )
        )

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.interface.name))
    return candidates


def select_interface(preferred: str | None = None) -> NetworkInterface:
    """Resolve the interface to use.

    Args:
        preferred: Explicit interface name, or ``None`` for automatic
            selection of the highest-ranked Ethernet-class interface.

    Raises:
        InterfaceNotFoundError: The named interface does not exist, or
            automatic selection found no Ethernet-class interface.
    """
    if preferred:
        return get_interface(preferred)

    candidates = rank_candidates()
    if not candidates:
        raise InterfaceNotFoundError(
            "No Ethernet-class network interface was found. Connect the ENET "
            "cable and re-run 'f10diag network interfaces'."
        )
    return candidates[0].interface
