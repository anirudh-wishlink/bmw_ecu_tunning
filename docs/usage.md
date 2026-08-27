# Usage guide

Everything in this document works today. Commands that belong to unimplemented
phases are listed too, with an explanation of what they will do and what still
has to be verified before they can do it.

- [Installation](#installation)
- [Global options](#global-options)
- [Exit codes](#exit-codes)
- [Commands](#commands)
- [Configuration](#configuration)
- [Capture files](#capture-files)
- [Using the library directly](#using-the-library-directly)
- [Workflows](#workflows)
- [Troubleshooting](#troubleshooting)

---

## Installation

```bash
cd bmw-f10-diag
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

This installs the `f10diag` console script into the virtual environment. Both
of these are equivalent:

```bash
f10diag network interfaces
python -m f10diag network interfaces
```

`python -m f10diag` with no arguments runs the offline demonstration.

To check the install without a cable or a car:

```bash
pytest -q
python -m f10diag
```

---

## Global options

These are accepted by every command, and may appear before or after the
subcommand. `f10diag --raw dme live` and `f10diag dme live --raw` are the same.

| Option | Meaning |
| --- | --- |
| `-v`, `--verbose` | Raise log verbosity. Once for INFO, twice or more for DEBUG. Overrides `[logging].level`. |
| `--raw` | Show raw bytes and low-level detail: interface flags, every TX/RX payload as hex. |
| `--json` | Emit machine-readable JSON on stdout instead of formatted tables. Supported by `network interfaces` and `vehicle info`. |
| `--config PATH` | Use a specific `config.toml`. Default: `config.toml` in the current directory, or built-in defaults if absent. |
| `--interface NAME` | Network interface to use, e.g. `en7`. Overrides `[enet].interface`. |
| `--host ADDRESS` | Diagnostic gateway address. Overrides `[enet].host`. |
| `--port PORT` | Diagnostic gateway TCP port. Overrides `[enet].port`. |
| `--timeout SECONDS` | Receive timeout. Overrides `[enet].receive_timeout`. |
| `--read-only` | Read-only mode. This is the default; the flag is for making it explicit in scripts. |
| `--allow-write` | Lifts the read-only gate. No write operation exists in this build, so nothing changes and the tool says so. |
| `--version` | Print the version. |

A flag you do not pass never clears a configured value, so
`f10diag --port 1234 connect` keeps the host from `config.toml`.

---

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Runtime failure: connection lost, interface unavailable, unreadable capture. |
| `2` | Usage or configuration error: bad flag, invalid TOML, out-of-range port. |
| `3` | Refused because something is unverified: the command depends on protocol details this project has not established, or a required parameter has no value and no default may be guessed. |

Code `3` is the interesting one. It means the tool knew it could not answer
honestly and declined, rather than making something up.

---

## Commands

### `f10diag network interfaces`

Lists the network interfaces on this Mac, then ranks the ones that could
plausibly carry an ENET cable.

```bash
f10diag network interfaces
f10diag network interfaces --all      # include loopback and virtual interfaces
f10diag network interfaces --raw      # also show flags, MTU, media
f10diag network interfaces --json     # machine-readable
```

Output shows each interface's name, link status, IPv4 addresses, MAC address,
and macOS hardware port name, followed by a ranked candidate list:

```
  1. en7  (score 90)
     + link is active
     + external adapter (USB 10/100/1000 LAN)
     + has a 169.254.x.x self-assigned address, i.e. no DHCP server responded
       on this link
```

The ranking is built entirely from host-side facts, and nothing is transmitted.
It is a hint about which interface to try, not detection of BMW hardware. Wi-Fi,
loopback, tunnels, bridges, and Apple's internal interfaces are excluded from
the candidate list.

This command never changes macOS network configuration. If an interface needs
an address, the tool tells you and leaves the change to you.

### `f10diag network select`

Shows the same ranked list and asks you to pick one, then prints the exact
configuration change needed:

```
╭──────────────── Selected en7 ────────────────╮
│ To use this interface, set it in config.toml:│
│                                              │
│   [enet]                                     │
│   interface = "en7"                          │
│                                              │
│ or pass --interface en7 on the command line. │
╰──────────────────────────────────────────────╯
```

It does not edit `config.toml` for you, and does not touch macOS networking.
When stdin is not a terminal it reports the highest-ranked interface without
prompting.

### `f10diag connect`

Opens a TCP connection to the configured host and port, and reports exactly
what that proves.

```bash
f10diag --host 10.0.0.1 --port 1234 connect
f10diag connect --listen 5            # then listen 5s without transmitting
f10diag connect --listen 5 --raw      # print each received payload as hex
```

Requires `[enet].host` and `[enet].port`. This tool ships no default for either,
because neither has been verified for this project; without them the command
exits with code `3` and explains why.

On success:

```
╭────────────── TCP connection open ──────────────╮
│ Interface:      en7                             │
│ Local address:  169.254.10.20:52341             │
│ Peer:           10.0.0.1:1234                   │
│ Level reached:  TCP_CONNECTED - TCP socket open │
│                 (NOT proof of vehicle comms)    │
│                                                 │
│ This is a TCP socket only. Nothing has been     │
│ sent, no BMW diagnostic transport has been      │
│ established, and no ECU has been contacted.     │
╰─────────────────────────────────────────────────╯
```

`connect` transmits nothing. `--listen N` reads for N seconds without sending.
Silence during that window proves nothing either way: a gateway that only
answers requests would stay silent by design.

### `f10diag vehicle info`

Prints the vehicle described by `config.toml`, clearly labelled as
configuration rather than anything read from the car.

```bash
f10diag vehicle info
f10diag vehicle info --json
```

The JSON form has an explicit `"read_from_vehicle": null` so a script can never
mistake configured values for measured ones. The DME model in particular is an
assumption until an identification response confirms it.

### `f10diag capture`

Records traffic to a capture file, transmitting nothing.

```bash
f10diag capture --duration 30
f10diag capture --duration 30 --output captures/ignition-on.jsonl
f10diag capture --raw                                    # echo packets to the console
f10diag capture --export captures/old.jsonl --output out.json --format json
f10diag capture --export captures/old.jsonl --output out.txt  --format text
```

| Option | Meaning |
| --- | --- |
| `--duration SECONDS` | How long to record. Default 10. Ctrl-C stops early and keeps what was recorded. |
| `--output PATH` | Capture file. Defaults to a timestamped file in `[logging].capture_dir`. |
| `--export PATH` | Convert an existing capture instead of recording. |
| `--format json\|text` | Export format. `json` produces one document; `text` produces a transcript. |

Recording needs a host and port, for the same reason `connect` does. To record
another diagnostic tool's traffic on the wire rather than your own connection,
capture at the link layer with `tcpdump` on the ENET interface; that is outside
this tool and needs administrator rights.

Captures may contain the VIN and other identifying data, so `captures/` is
git-ignored.

### `f10diag demo`

Runs every implemented layer offline. No vehicle, no cable, no real network
traffic. It walks through interface discovery, a mock transport round trip, a
capture-and-replay cycle, the value decoders, and then shows the protocol layer
correctly refusing to invent anything.

```bash
f10diag demo
python -m f10diag      # same thing
```

The bytes in the demo are invented by the demo and carry no automotive meaning.

### Commands not implemented yet

These parse and run, but exit with code `3` and an explanation instead of
printing data.

| Command | Phase | Blocked on |
| --- | --- | --- |
| `f10diag ecu list` | 4 | BMW message framing, gateway activation, ECU diagnostic addresses, what a "no such ECU" reply looks like |
| `f10diag ecu identify DME` | 5 | BMW message framing, the identification request, the response layout |
| `f10diag dme dtc` | 6 | BMW message framing, the fault-memory read request, the DTC record layout including the status byte |
| `f10diag dme live` | 7 | BMW message framing, the data identifiers the DME accepts, byte layout and scaling per signal |

When implemented, they will still be honest about what they do not know. A
fault code with no sourced description will read `Unknown BMW DTC` and show its
raw bytes. A value decoded with an unverified definition will be printed with
an `[UNVERIFIED]` label.

---

## Configuration

`config.toml` is read from the current directory unless `--config` says
otherwise. If no file exists, built-in defaults apply.

```toml
[enet]
interface = "auto"     # macOS interface name, or "auto" to rank and pick
host = ""              # gateway address; "" means unset and blocks connecting
port = ""              # gateway TCP port; "" means unset and blocks connecting
connect_timeout = 5.0
receive_timeout = 2.0
reconnect_attempts = 0
reconnect_delay = 1.0

[vehicle]
platform = "F10"
model = "523i"
model_year = 2011
engine = "N52B25"
dme = "MSV90"

[safety]
read_only = true

[logging]
level = "INFO"          # DEBUG, INFO, WARNING, ERROR, CRITICAL
capture_dir = "captures"
log_packets = true
```

Notes on specific keys:

- **`interface`** — `"auto"` selects the highest-ranked Ethernet-class
  interface. It only chooses; it never reconfigures macOS.
- **`host`, `port`** — `""` and `"auto"` both mean "not set". The tool ships no
  default and refuses to connect without them, rather than guessing a BMW
  gateway address. Set them once you have determined them, and record how you
  determined them in `docs/protocol.md`.
- **`reconnect_attempts`** — how many extra tries `reconnect()` makes. `0`
  means a single attempt.
- **`read_only`** — the default and the only supported mode. Setting it to
  `false` changes nothing today because no write operation exists.
- **`capture_dir`** — relative paths resolve against the directory containing
  `config.toml`.
- **`level`** — overridden by `-v` when that flag is given.

Configuration is validated on load. Unknown sections, unknown `[enet]` keys,
out-of-range ports, negative timeouts, and non-boolean flags are all rejected
with exit code `2` and a message naming the offending key.

---

## Capture files

A capture is JSON Lines: one JSON object per line, flushed as each packet is
recorded, so a crash mid-session loses nothing already written.

The first line is the session header:

```json
{"type":"session","format":"f10diag-capture","version":1,
 "session":{"started_at":"2026-08-27T12:03:11.482+00:00","tool_version":"0.1.0",
            "host_os":"Darwin 25.0.0","read_only":true,"comms_level":"TCP_CONNECTED"}}
```

Each subsequent packet line looks like:

```json
{"timestamp":1787577791.51,"iso_timestamp":"2026-08-27T12:03:11.510+00:00",
 "direction":"RX","length":2,"raw_hex":"DE AD",
 "transport":{"transport":"enet-tcp","peer":"10.0.0.1:1234","interface":"en7"}}
```

`comms_level` in the header records how far communication was actually proven
during that session, so a capture can never imply more than was achieved.
A packet's `decoded` field is absent until a protocol layer that understands
the bytes fills it in; absent means "not decoded", never "meaningless".

Convert a capture to a single JSON document or a plain-text transcript with
`f10diag capture --export`.

PCAP export is not implemented. A capture records transport payloads rather
than complete Ethernet frames, so writing a faithful PCAP would mean
synthesising link and IP headers that were never observed.

---

## Using the library directly

The CLI is a thin layer over the package, which is usable from your own code.

Discover interfaces:

```python
from f10diag.transport.ethernet import rank_candidates

for candidate in rank_candidates():
    print(candidate.interface.name, candidate.score, candidate.reasons)
```

Open a transport and record everything it sees:

```python
from f10diag.config import ENETConfig
from f10diag.transport.enet import ENETTransport
from f10diag.logging.diagnostic_logger import DiagnosticLogger

config = ENETConfig(interface="en7", host="10.0.0.1", port=1234)
transport = ENETTransport(config)

with DiagnosticLogger("captures/session.jsonl") as capture:
    transport.add_packet_observer(capture.record)
    with transport:
        print(transport.comms_level)      # CommsLevel.TCP_CONNECTED
```

Test protocol code with no hardware:

```python
from f10diag.transport.mock import MockTransport

transport = MockTransport(responder=lambda request: bytes(reversed(request)))
transport.connect()
transport.send(b"\x01\x02\x03")
assert transport.receive() == b"\x03\x02\x01"
assert transport.sent == [b"\x01\x02\x03"]
```

Re-run a recorded session:

```python
from f10diag.transport.replay import ReplayTransport

transport = ReplayTransport("captures/session.jsonl", strict=True)
transport.connect()
transport.send(recorded_request)     # must match the recording, or it raises
response = transport.receive()
```

Strict mode is the default and is what makes a replay meaningful: it fails if
your code sends something the recording never contained, so a passing replay
test cannot be satisfied by invented traffic.

Decode a value:

```python
from f10diag.decoding.signals import SignalDefinition

definition = SignalDefinition(
    name="example", decoder="uint16", length=2,
    scale=0.25, offset=-10.0, unit="degC",
    source="how you verified it", verified=True,
)
print(definition.decode(b"\x00\x64").format())   # 15.00 degC
```

An unverified definition raises `UnverifiedDefinitionError` unless you pass
`allow_unverified=True`, and its results are always labelled `[UNVERIFIED]`.

---

## Workflows

### First run with a new ENET cable

```bash
f10diag network interfaces          # before plugging in
# plug the cable into the Mac and the OBD-II port, ignition on
f10diag network interfaces          # a new interface should have appeared
f10diag network select              # confirm which one to use
```

Add the chosen interface to `config.toml`. The tool will not edit it for you.

### Recording a session for later analysis

```bash
f10diag --host <address> --port <port> capture --duration 60 \
        --output captures/2026-08-27-ignition-on.jsonl
f10diag capture --export captures/2026-08-27-ignition-on.jsonl \
        --output captures/2026-08-27-ignition-on.txt --format text
```

The text transcript is easy to skim; the JSONL original is what
`ReplayTransport` reads.

### Turning a recording into a test

Once you have a capture of a real exchange, drop it into `captures/` and build a
`ReplayTransport` on it in a test. Decoder work can then proceed offline against
bytes that genuinely came from the car.

---

## Troubleshooting

**"No Ethernet-class network interface was found"**
Nothing on this Mac looks like a wired adapter. Plug in the ENET cable and
re-run `f10diag network interfaces`. An ENET cable normally appears as a USB or
Thunderbolt Ethernet adapter.

**"Interface enN has no active link"**
The interface exists but reports no carrier. Check the cable at both ends, and
that the vehicle ignition is on.

**"Cannot connect: [enet].host and [enet].port is not set"**
Working as intended. The tool ships no default gateway address or port because
neither has been verified for this project. Supply them with `--host`/`--port`
or in `config.toml`.

**"Timed out connecting"**
Nothing accepted the TCP connection within the timeout. Check the cable, the
ignition, and the address. Raise `connect_timeout` if the link is slow to come
up.

**"The peer actively refused the connection"**
Something answered at that address but nothing is listening on that port.

**Nothing arrives during `--listen`**
Expected, and not a fault. A gateway that only replies to requests stays silent
until asked, and this tool asks nothing.

**Interface has a 192.168.x.x address instead of 169.254.x.x**
Flagged as a warning in the candidate list. A routable address suggests the
interface is on a normal network rather than a point-to-point link, so it is
probably not the one the ENET cable is on.

**A command exits with code 3**
It depends on protocol details this project has not verified. The message lists
what still has to be established; `docs/protocol.md` tracks the same list.
