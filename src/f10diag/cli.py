"""Command-line interface.

Every command is read-only. Commands whose implementation depends on
unverified BMW protocol details do not print placeholder data: they explain
what is missing and exit with :data:`EXIT_NOT_VERIFIED`.

Reporting discipline (project rule 34): the CLI reports the communication
level actually reached. An open TCP socket is described as an open TCP socket,
never as being connected to the vehicle or to an ECU.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from .config import AppConfig
from .exceptions import (
    ConfigError,
    F10DiagError,
    NotVerifiedError,
    TransportTimeoutError,
)
from .logging.diagnostic_logger import (
    DiagnosticLogger,
    SessionMetadata,
    configure_logging,
    default_capture_path,
    export_capture,
)
from .status import CommsLevel, describe
from .transport.enet import ENETTransport, probe_tcp
from .transport.ethernet import (
    NetworkInterface,
    is_macos,
    list_interfaces,
    rank_candidates,
)
from .transport.mock import MockTransport
from .transport.replay import ReplayTransport
from .vehicle.f10 import F10Vehicle

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NOT_VERIFIED = 3

console = Console()
error_console = Console(stderr=True)

__version__ = "0.1.0"


# --------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------


def _emit_json(payload: Any) -> None:
    """Print a JSON document on stdout, bypassing rich formatting."""
    sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")


def _render_interfaces(interfaces: list[NetworkInterface], *, raw: bool) -> None:
    table = Table(title="Network interfaces", header_style="bold")
    table.add_column("Interface", style="bold")
    table.add_column("Status")
    table.add_column("IPv4")
    table.add_column("MAC")
    table.add_column("Hardware port")

    for iface in interfaces:
        status = iface.describe_status()
        status_style = "green" if iface.has_link else "yellow"
        addresses = "\n".join(str(addr) for addr in iface.ipv4) or "-"
        table.add_row(
            iface.name,
            f"[{status_style}]{status}[/{status_style}]",
            addresses,
            iface.mac or "-",
            iface.hardware_port or "-",
        )
    console.print(table)

    if raw:
        for iface in interfaces:
            console.print(f"[dim]{iface.name}: flags={','.join(iface.flags)} "
                          f"mtu={iface.mtu} media={iface.media}[/dim]")


def _render_candidates(candidates: list[Any]) -> None:
    if not candidates:
        console.print(
            "[yellow]No Ethernet-class interface found.[/yellow] An ENET cable "
            "normally appears as a USB or Thunderbolt Ethernet adapter. Plug it "
            "in and run this command again."
        )
        return

    console.print("\n[bold]Likely ENET attachment points[/bold]")
    console.print(
        "[dim]Ranked from host-side facts only. This does not detect BMW "
        "hardware and nothing was transmitted.[/dim]\n"
    )
    for position, candidate in enumerate(candidates, start=1):
        iface = candidate.interface
        console.print(f"  {position}. [bold]{iface.name}[/bold]  (score {candidate.score})")
        for reason in candidate.reasons:
            console.print(f"     [green]+[/green] {reason}")
        for warning in candidate.warnings:
            console.print(f"     [yellow]![/yellow] {warning}")


def _not_verified(message: str, *, todo: Sequence[str] = ()) -> int:
    """Print a "not implemented because unverified" explanation.

    Messages often contain TOML section names such as ``[enet]``, so the text is
    escaped rather than interpreted as rich markup.
    """
    body = [escape(message)]
    if todo:
        body.append("")
        body.append("Still to be established:")
        body.extend(f"  - {item}" for item in todo)
    error_console.print(
        Panel(
            "\n".join(body),
            title="Not implemented",
            border_style="yellow",
        )
    )
    return EXIT_NOT_VERIFIED


# --------------------------------------------------------------------------
# Commands: network
# --------------------------------------------------------------------------


def cmd_network_interfaces(args: argparse.Namespace, config: AppConfig) -> int:
    interfaces = list_interfaces()

    if not interfaces:
        if not is_macos():
            error_console.print(
                "[red]No interfaces found.[/red] This tool reads interface "
                "information using macOS tooling (ifconfig, networksetup) and "
                "this host does not appear to be macOS."
            )
        else:
            error_console.print(
                "[red]No interfaces found.[/red] 'ifconfig -a' returned nothing "
                "usable."
            )
        return EXIT_ERROR

    if not args.all:
        interfaces = [
            iface
            for iface in interfaces
            if not iface.is_virtual and not iface.is_loopback
        ]

    if args.json:
        _emit_json(
            {
                "interfaces": [iface.to_dict() for iface in interfaces],
                "candidates": [
                    {
                        "interface": candidate.interface.name,
                        "score": candidate.score,
                        "reasons": list(candidate.reasons),
                        "warnings": list(candidate.warnings),
                    }
                    for candidate in rank_candidates()
                ],
            }
        )
        return EXIT_OK

    _render_interfaces(interfaces, raw=args.raw)
    _render_candidates(rank_candidates())
    console.print(
        "\n[dim]macOS network settings were not modified. If an interface needs "
        "an address, configure it yourself in System Settings > Network.[/dim]"
    )
    return EXIT_OK


def cmd_network_select(args: argparse.Namespace, config: AppConfig) -> int:
    candidates = rank_candidates()
    if not candidates:
        error_console.print(
            "[red]No Ethernet-class interface is available to select.[/red]"
        )
        return EXIT_ERROR

    _render_candidates(candidates)

    if not sys.stdin.isatty():
        chosen = candidates[0].interface
        console.print(f"\nNon-interactive: highest ranked is [bold]{chosen.name}[/bold]")
    else:
        console.print("")
        try:
            answer = console.input(
                f"Select an interface [1-{len(candidates)}] (Enter for 1): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nCancelled.")
            return EXIT_ERROR
        index = 1 if not answer else int(answer) if answer.isdigit() else 0
        if not 1 <= index <= len(candidates):
            error_console.print(f"[red]{answer!r} is not one of the listed options.[/red]")
            return EXIT_USAGE
        chosen = candidates[index - 1].interface

    console.print(
        Panel(
            f"To use this interface, set it in config.toml:\n\n"
            f"  [enet]\n"
            f'  interface = "{chosen.name}"\n\n'
            f"or pass --interface {chosen.name} on the command line.\n\n"
            "Nothing was changed for you, and no macOS network setting was "
            "touched.",
            title=f"Selected {chosen.name}",
            border_style="green",
        )
    )
    return EXIT_OK


# --------------------------------------------------------------------------
# Commands: connect
# --------------------------------------------------------------------------


def cmd_connect(args: argparse.Namespace, config: AppConfig) -> int:
    """Open a TCP connection and report exactly what that proves."""
    try:
        config.enet.validate_for_connection()
    except F10DiagError as exc:
        error_console.print(Panel(escape(str(exc)), title="Cannot connect", border_style="red"))
        return EXIT_NOT_VERIFIED

    transport = ENETTransport(config.enet)
    capture_path = default_capture_path(config.logging.capture_dir, "connect")
    metadata = SessionMetadata(
        vehicle=asdict(config.vehicle),
        transport={"host": config.enet.host, "port": config.enet.port},
        read_only=config.safety.read_only,
    )

    with DiagnosticLogger(
        capture_path if config.logging.log_packets else None,
        metadata=metadata,
        echo=args.raw,
    ) as capture:
        transport.add_packet_observer(capture.record)
        try:
            transport.connect()
        except F10DiagError as exc:
            error_console.print(Panel(escape(str(exc)), title="Connection failed", border_style="red"))
            capture.record_event("connect_failed", error=str(exc))
            return EXIT_ERROR

        level = transport.comms_level
        capture.update_comms_level(level.name)
        info = transport.get_interface_info()

        try:
            console.print(
                Panel(
                    f"Interface:      {info.get('interface')}\n"
                    f"Local address:  {info.get('local_endpoint', '-')}\n"
                    f"Peer:           {info.get('peer')}\n"
                    f"Level reached:  {level.name} - {describe(level)}\n\n"
                    "[bold yellow]This is a TCP socket only.[/bold yellow] "
                    "Nothing has been sent, no BMW diagnostic transport has "
                    "been established, and no ECU has been contacted.",
                    title="TCP connection open",
                    border_style="green",
                )
            )
            if args.listen:
                console.print(
                    f"\nListening passively for {args.listen:g}s, transmitting nothing..."
                )
                received = _passive_listen(transport, args.listen, raw=args.raw)
                console.print(
                    f"Received {received} byte(s) without sending anything."
                    if received
                    else "Nothing arrived. A gateway that only answers requests "
                    "would stay silent, which tells us nothing either way."
                )
        finally:
            transport.disconnect()

        if config.logging.log_packets:
            console.print(f"\n[dim]Capture written to {capture_path}[/dim]")

    return EXIT_OK


def _passive_listen(transport: ENETTransport, duration: float, *, raw: bool) -> int:
    """Read whatever arrives for ``duration`` seconds without transmitting."""
    deadline = time.monotonic() + duration
    total = 0
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            chunk = transport.receive(timeout=min(0.5, max(0.05, remaining)))
        except TransportTimeoutError:
            continue
        except F10DiagError as exc:
            error_console.print(f"[yellow]Link closed while listening: {escape(str(exc))}[/yellow]")
            break
        total += len(chunk)
        if raw:
            console.print(f"[dim]RX {chunk.hex(' ').upper()}[/dim]")
    return total


# --------------------------------------------------------------------------
# Commands: vehicle / ecu / dme
# --------------------------------------------------------------------------


def cmd_vehicle_info(args: argparse.Namespace, config: AppConfig) -> int:
    vehicle = F10Vehicle(config=config.vehicle)
    if args.json:
        _emit_json(
            {
                "configured": {
                    "platform": config.vehicle.platform,
                    "model": config.vehicle.model,
                    "model_year": config.vehicle.model_year,
                    "engine": config.vehicle.engine,
                    "dme": config.vehicle.dme,
                },
                "read_from_vehicle": None,
                "source": "config.toml",
            }
        )
        return EXIT_OK

    console.print(
        Panel(
            f"{vehicle.description}\n\n"
            "[yellow]Source: config.toml.[/yellow] None of this was read from "
            "the car. In particular the DME model is an assumption until an "
            "identification response confirms it.",
            title="Vehicle (configured)",
            border_style="cyan",
        )
    )
    return EXIT_OK


def cmd_ecu_list(args: argparse.Namespace, config: AppConfig) -> int:
    return _not_verified(
        "ECU discovery (Phase 4) is not implemented, so there is nothing to "
        "list. Only control units that actually answer will ever be listed; "
        "the catalogue in definitions/ecus.json is a list of expected names "
        "with no addresses and will not be printed as if it were discovered "
        "hardware.",
        todo=[
            "BMW Ethernet diagnostic message framing",
            "Gateway activation/registration exchange",
            "Diagnostic addresses of F10 control units",
            "What a 'no such ECU' response looks like",
        ],
    )


def cmd_ecu_identify(args: argparse.Namespace, config: AppConfig) -> int:
    return _not_verified(
        f"Identification of {args.ecu} (Phase 5) is not implemented. It needs "
        "the BMW diagnostic transport and a verified identification request.",
        todo=[
            "BMW Ethernet diagnostic message framing",
            "The request that returns hardware and software numbers",
            "The response layout for those fields",
        ],
    )


def cmd_dme_dtc(args: argparse.Namespace, config: AppConfig) -> int:
    return _not_verified(
        "Reading DTCs (Phase 6) is not implemented. Fault codes will be shown "
        "with their raw bytes, and any code without a sourced description will "
        "read 'Unknown BMW DTC' rather than a guess.",
        todo=[
            "BMW Ethernet diagnostic message framing",
            "The fault-memory read request accepted by the DME",
            "The DTC record layout, including the status byte",
        ],
    )


def cmd_dme_live(args: argparse.Namespace, config: AppConfig) -> int:
    return _not_verified(
        "Live data (Phase 7) is not implemented. definitions/signals.json is "
        "deliberately empty: no data identifier or scaling formula for this "
        "engine has been verified, and a plausible-looking wrong number is "
        "worse than no number.",
        todo=[
            "BMW Ethernet diagnostic message framing",
            "Data identifiers the DME accepts",
            "Byte layout and scaling for each signal",
        ],
    )


# --------------------------------------------------------------------------
# Commands: capture
# --------------------------------------------------------------------------


def cmd_capture(args: argparse.Namespace, config: AppConfig) -> int:
    """Record traffic on an open connection without transmitting anything."""
    if args.export:
        try:
            output = export_capture(args.export, args.output or "capture.json", args.format)
        except (ValueError, F10DiagError) as exc:
            error_console.print(f"[red]{escape(str(exc))}[/red]")
            return EXIT_ERROR
        console.print(f"Exported to {output}")
        return EXIT_OK

    try:
        config.enet.validate_for_connection()
    except F10DiagError as exc:
        error_console.print(
            Panel(
                f"{escape(str(exc))}\n\n"
                "To record the traffic of another diagnostic tool on the wire "
                "instead, capture at the link layer with tcpdump on the ENET "
                "interface. That is outside this tool and requires "
                "administrator rights.",
                title="Cannot capture",
                border_style="red",
            )
        )
        return EXIT_NOT_VERIFIED

    path = Path(args.output) if args.output else default_capture_path(
        config.logging.capture_dir, "capture"
    )
    transport = ENETTransport(config.enet)
    metadata = SessionMetadata(
        transport={"host": config.enet.host, "port": config.enet.port},
        read_only=config.safety.read_only,
        notes="Passive capture: this tool transmitted nothing.",
    )

    with DiagnosticLogger(path, metadata=metadata, echo=args.raw) as capture:
        transport.add_packet_observer(capture.record)
        try:
            transport.connect()
        except F10DiagError as exc:
            error_console.print(f"[red]{escape(str(exc))}[/red]")
            return EXIT_ERROR
        capture.update_comms_level(transport.comms_level.name)
        console.print(
            f"Capturing for {args.duration:g}s into {path}\n"
            "[dim]Read-only: nothing will be transmitted.[/dim]"
        )
        try:
            _passive_listen(transport, args.duration, raw=args.raw)
        except KeyboardInterrupt:
            console.print("\nStopped by user.")
        finally:
            transport.disconnect()
        counts = capture.counts()

    console.print(
        f"Captured TX={counts.get('TX', 0)} RX={counts.get('RX', 0)} packets -> {path}"
    )
    return EXIT_OK


# --------------------------------------------------------------------------
# Commands: demo (no vehicle required)
# --------------------------------------------------------------------------


def cmd_demo(args: argparse.Namespace, config: AppConfig) -> int:
    """Exercise the implemented layers offline, with no vehicle attached."""
    console.print(
        Panel(
            "Offline demonstration. No vehicle, no ENET cable, and no real "
            "network traffic are involved. The bytes below are invented by the "
            "demo itself and carry no automotive meaning.",
            title="f10diag demo",
            border_style="cyan",
        )
    )

    console.print("\n[bold]1. Network layer[/bold]")
    interfaces = [iface for iface in list_interfaces() if not iface.is_virtual]
    console.print(f"   Found {len(interfaces)} physical interface(s) on this host.")
    candidates = rank_candidates()
    console.print(f"   {len(candidates)} of them could plausibly carry an ENET cable.")

    console.print("\n[bold]2. Transport layer (MockTransport)[/bold]")
    mock = MockTransport(responder=lambda request: bytes(reversed(request)))
    packets: list[Any] = []
    mock.add_packet_observer(packets.append)
    mock.connect()
    mock.send(bytes([0x01, 0x02, 0x03]))
    echoed = mock.receive()
    mock.disconnect()
    console.print(f"   Sent 01 02 03, mock echoed back {echoed.hex(' ').upper()}")
    console.print(f"   Observed {len(packets)} packet(s) through the observer hook.")

    console.print("\n[bold]3. Capture and replay[/bold]")
    logger = DiagnosticLogger(metadata=SessionMetadata(notes="demo"))
    for packet in packets:
        logger.record(packet)
    replay = ReplayTransport(logger.packets, strict=True)
    replay.connect()
    replay.send(bytes([0x01, 0x02, 0x03]))
    console.print(f"   Replayed request, response {replay.receive().hex(' ').upper()}")
    replay.disconnect()

    console.print("\n[bold]4. Decoding layer[/bold]")
    from .decoding.values import DECODERS, apply_scaling, uint16

    console.print(f"   {len(DECODERS)} primitive decoders registered.")
    console.print(
        f"   uint16(01 F4) = {uint16(bytes([0x01, 0xF4]))}, "
        f"scaled by 0.1 = {apply_scaling(uint16(bytes([0x01, 0xF4])), 0.1):.1f}"
    )

    console.print("\n[bold]5. Protocol and ECU layers[/bold]")
    try:
        F10Vehicle(config=config.vehicle).discover_ecus()
    except NotVerifiedError as exc:
        console.print(f"   [yellow]Refused, as designed:[/yellow] {escape(str(exc))}")

    console.print(
        f"\n[bold]Highest level reachable today:[/bold] "
        f"{CommsLevel.TCP_CONNECTED.name} - {describe(CommsLevel.TCP_CONNECTED)}"
    )
    return EXIT_OK


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def _add_global_flags(parser: argparse.ArgumentParser, *, top_level: bool) -> None:
    """Add the flags that every command accepts.

    They are attached both to the top-level parser and to each leaf command, so
    that ``f10diag --raw dme live`` and ``f10diag dme live --raw`` behave the
    same. Leaf copies default to ``SUPPRESS`` so that an omitted flag does not
    overwrite the value already parsed at the top level.
    """
    default: Any = None if top_level else argparse.SUPPRESS

    parser.add_argument("-v", "--verbose", action="count",
                        default=0 if top_level else argparse.SUPPRESS,
                        help="increase log verbosity (repeatable)")
    parser.add_argument("--raw", action="store_true",
                        default=False if top_level else argparse.SUPPRESS,
                        help="show raw bytes and low-level detail")
    parser.add_argument("--json", action="store_true",
                        default=False if top_level else argparse.SUPPRESS,
                        help="emit machine-readable JSON where supported")
    parser.add_argument("--config", type=Path, default=default,
                        help="path to config.toml")
    parser.add_argument("--interface", default=default,
                        help="network interface, e.g. en7")
    parser.add_argument("--host", default=default,
                        help="diagnostic gateway address")
    parser.add_argument("--port", type=int, default=default,
                        help="diagnostic gateway TCP port")
    parser.add_argument("--timeout", type=float, default=default,
                        help="receive timeout in seconds")

    safety = parser.add_mutually_exclusive_group()
    safety.add_argument("--read-only", dest="read_only", action="store_true",
                        default=default, help="read-only mode (the default)")
    safety.add_argument("--allow-write", dest="read_only", action="store_false",
                        default=default,
                        help="lift the read-only gate (no write operation exists yet)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="f10diag",
        description="Read-only BMW F10 ENET diagnostic tool for macOS",
    )
    parser.add_argument("--version", action="version", version=f"f10diag {__version__}")
    _add_global_flags(parser, top_level=True)

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def leaf(group: Any, name: str, help_text: str) -> argparse.ArgumentParser:
        command = group.add_parser(name, help=help_text)
        _add_global_flags(command, top_level=False)
        return command

    network = sub.add_parser("network", help="inspect host networking")
    network_sub = network.add_subparsers(dest="subcommand", metavar="<subcommand>")
    interfaces = leaf(network_sub, "interfaces", "list network interfaces")
    interfaces.add_argument("--all", action="store_true",
                            help="include loopback and virtual interfaces")
    interfaces.set_defaults(func=cmd_network_interfaces)
    leaf(network_sub, "select", "choose an ENET interface").set_defaults(
        func=cmd_network_select
    )

    connect = leaf(sub, "connect", "open a TCP connection and report the level reached")
    connect.add_argument("--listen", type=float, default=0.0, metavar="SECONDS",
                         help="after connecting, listen passively without transmitting")
    connect.set_defaults(func=cmd_connect)

    vehicle = sub.add_parser("vehicle", help="vehicle information")
    vehicle_sub = vehicle.add_subparsers(dest="subcommand", metavar="<subcommand>")
    leaf(vehicle_sub, "info", "show configured vehicle").set_defaults(
        func=cmd_vehicle_info
    )

    ecu = sub.add_parser("ecu", help="control units")
    ecu_sub = ecu.add_subparsers(dest="subcommand", metavar="<subcommand>")
    leaf(ecu_sub, "list", "list discovered control units").set_defaults(func=cmd_ecu_list)
    ecu_identify = leaf(ecu_sub, "identify", "identify one control unit")
    ecu_identify.add_argument("ecu", help="short name, e.g. DME")
    ecu_identify.set_defaults(func=cmd_ecu_identify)

    dme = sub.add_parser("dme", help="engine control unit")
    dme_sub = dme.add_subparsers(dest="subcommand", metavar="<subcommand>")
    leaf(dme_sub, "dtc", "read fault codes").set_defaults(func=cmd_dme_dtc)
    leaf(dme_sub, "live", "read live data").set_defaults(func=cmd_dme_live)

    capture = leaf(sub, "capture", "record traffic, transmitting nothing")
    capture.add_argument("--duration", type=float, default=10.0, help="seconds to record")
    capture.add_argument("--output", type=Path, default=None, help="capture file path")
    capture.add_argument("--export", type=Path, default=None,
                         help="convert an existing capture instead of recording")
    capture.add_argument("--format", choices=("json", "text"), default="json",
                         help="export format")
    capture.set_defaults(func=cmd_capture)

    leaf(sub, "demo", "offline demonstration, no vehicle required").set_defaults(
        func=cmd_demo
    )

    return parser


def _log_level(verbosity: int) -> str:
    return {0: "WARNING", 1: "INFO"}.get(verbosity, "DEBUG")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE

    configure_logging(_log_level(args.verbose))

    try:
        config = AppConfig.load(args.config).with_overrides(
            interface=args.interface,
            host=args.host,
            port=args.port,
            receive_timeout=args.timeout,
            read_only=args.read_only,
        )
    except ConfigError as exc:
        error_console.print(f"[red]Configuration error:[/red] {escape(str(exc))}")
        return EXIT_USAGE

    if not config.safety.read_only:
        error_console.print(
            "[yellow]--allow-write was given. This build implements no write "
            "operation of any kind, so nothing changes; the flag exists only so "
            "future write paths have a gate to check.[/yellow]"
        )

    try:
        return int(args.func(args, config))
    except NotVerifiedError as exc:
        return _not_verified(str(exc))
    except F10DiagError as exc:
        error_console.print(f"[red]{type(exc).__name__}:[/red] {escape(str(exc))}")
        return EXIT_ERROR
    except KeyboardInterrupt:
        error_console.print("\nInterrupted.")
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
