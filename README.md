# BMW F10 ENET Diagnostic Tool

A read-only BMW diagnostic framework for macOS, talking to the car over an ENET
Ethernet cable. No INPA, no EDIABAS, no ISTA, no Windows, no K+DCAN, no ELM327.

Primary target: **BMW F10 523i (2011), N52B25, DME believed to be MSV90.**

---

## Project status: foundation only

This build implements the host networking and transport layers. It does **not**
implement any BMW diagnostic protocol, and it will not talk to an ECU.

That is deliberate. The BMW Ethernet diagnostic protocol details this project
would need — the gateway address, the TCP port, the message framing, the
activation exchange, ECU addresses, data identifiers, DTC layouts — have not
been verified here, and the project rules forbid inventing them. A tool that
prints a confident coolant temperature derived from a guessed formula is worse
than a tool that prints nothing.

| Layer | Status |
| --- | --- |
| macOS interface discovery | Implemented |
| ENET TCP transport | Implemented |
| Packet capture, logging, replay | Implemented |
| Mock and replay transports | Implemented |
| Value decoders | Implemented |
| BMW Ethernet protocol | Not implemented — unverified |
| UDS | Not implemented — unverified |
| ISO-TP | Not implemented — may not be needed |
| ECU discovery, identification, DTCs, live data | Not implemented — unverified |

Commands from unimplemented phases do not print placeholder data. They explain
what is missing and exit with code `3`.

---

## Safety

Everything is read-only, and read-only is the default.

The codebase contains no implementation of ECU coding, programming, flashing,
bootloader access, adaptation writes, security access, immobiliser operations,
ECU reset, actuator activation, calibration writes, DME tuning, or emissions
defeat functionality. The `--allow-write` flag exists only so that a future
write path has a gate to check; today it changes nothing and says so.

`f10diag capture` transmits nothing at all.

---

## Requirements

- macOS (interface discovery uses `ifconfig` and `networksetup`)
- Python 3.11 or newer
- A BMW ENET cable, for anything beyond offline use

## Installation

```bash
cd bmw-f10-diag
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Verify the install without a car or a cable:

```bash
python -m f10diag        # offline demonstration of every implemented layer
pytest -q                # 214 tests, none of which need a vehicle
```

## Quick start

```bash
f10diag network interfaces      # what Ethernet interfaces does this Mac have?
f10diag network select          # pick one, interactively
f10diag vehicle info            # what the configuration says the car is
f10diag demo                    # exercise the implemented layers offline
```

Connecting requires a host and port, which this tool will not guess:

```bash
f10diag --host <address> --port <port> connect
```

Full command reference, configuration keys, and workflows are in
[docs/usage.md](docs/usage.md).

---

## Layout

```
bmw-f10-diag/
├── src/f10diag/
│   ├── cli.py            Command-line interface
│   ├── config.py         TOML configuration and validation
│   ├── status.py         The communication status ladder
│   ├── exceptions.py     Descriptive exception hierarchy
│   ├── transport/        Bytes only: ENET, mock, replay, packets
│   ├── protocols/        UDS, ISO-TP, BMW — all placeholders
│   ├── vehicle/          Vehicle and generic ECU abstractions
│   ├── ecus/             MSV90 and generic ECU implementations
│   ├── decoding/         Value decoders and signal definitions
│   ├── definitions/      JSON data files, deliberately empty
│   └── logging/          Structured logging and packet capture
├── tests/                pytest suite, no vehicle required
├── captures/             Recorded sessions (git-ignored)
└── docs/
    ├── usage.md          Detailed usage guide
    ├── architecture.md   How the layers fit together
    ├── protocol.md       VERIFIED / UNVERIFIED / TODO protocol notes
    └── development.md    Development workflow and phase plan
```

---

## The one rule that matters most

An open TCP socket is not a conversation with your car.

The tool tracks how far communication has actually been proven, and never
reports more than it has evidence for:

```
NONE → INTERFACE_PRESENT → ETHERNET_LINK → TCP_CONNECTED
     → BMW_TRANSPORT → DIAGNOSTIC_SESSION → ECU_RESPONDING → DATA_DECODED
```

Today the ladder stops at `TCP_CONNECTED`. "Connected to the DME" will only
ever be printed after the DME has actually answered and its answer has been
decoded with a verified definition.

## License

MIT. See [LICENSE](LICENSE).
