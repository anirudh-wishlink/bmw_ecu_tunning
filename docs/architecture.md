# Architecture

## Layers

```
macOS host
    |
    | Ethernet
    v
ENET cable
    |
    | OBD-II
    v
BMW F10  →  Ethernet diagnostic gateway  →  ECU (e.g. MSV90 DME)
```

In software:

```
┌──────────────────────────────────────────────┐
│ cli.py            command-line interface     │
├──────────────────────────────────────────────┤
│ ecus/             MSV90, GenericECU          │  ← not implemented
│ vehicle/          F10Vehicle, ECU, DTC       │  ← containers only
├──────────────────────────────────────────────┤
│ protocols/bmw.py  BMW framing and routing    │  ← placeholder
│ protocols/uds.py  UDS services               │  ← placeholder
│ protocols/isotp.py segmentation              │  ← placeholder
├──────────────────────────────────────────────┤
│ transport/        ENET, Mock, Replay, Packet │  ← implemented
├──────────────────────────────────────────────┤
│ decoding/  logging/  config.py  status.py    │  ← implemented, cross-cutting
└──────────────────────────────────────────────┘
```

Each layer depends only on the one below it. The protocol layer talks to a
`Transport` interface, not to a socket, which is why the same protocol code
will run unchanged against a real cable, a mock, or a recording.

---

## Transport layer

`transport.base.Transport` is the abstract interface: `connect`, `disconnect`,
`send`, `receive`, `is_connected`, `get_interface_info`, plus packet observers
and a `ConnectionState`.

It knows nothing about UDS, ECUs, DTCs, RPM, or BMW. That restriction is what
keeps the mock and replay implementations honest: they can substitute for the
real transport because the real transport has no special knowledge to lose.

| Implementation | Purpose |
| --- | --- |
| `ENETTransport` | TCP over an Ethernet interface. Sends only what it is given: no handshake, no keep-alive, no activation frame. |
| `MockTransport` | In-memory, driven by queued responses or a responder callable. Can simulate connect failures, silent peers, and a peer disappearing. |
| `ReplayTransport` | Replays a recorded session. Strict mode rejects a request that differs from the recording. |

**Packet observers.** Any transport can have observers attached; each TX and RX
payload is wrapped in a `DiagnosticPacket` and handed to each one. This is how
logging and capture work without the transport knowing about either. An
observer that raises cannot break I/O: the failure is recorded on
`transport.last_error` and the transport carries on.

**`transport.ethernet`** handles macOS interface discovery by parsing
`ifconfig -a` and `networksetup -listallhardwareports`. It only inspects. It
never brings an interface up or down, assigns an address, or changes the
service order. Candidate ranking uses host-side facts only — link status,
adapter type, whether the address is APIPA — and explains every point it awards.

---

## Packets

`DiagnosticPacket` is the unit that crosses layer boundaries for logging:

```python
DiagnosticPacket(
    direction=Direction.TX,     # or RX, from the tester's point of view
    raw_data=b"...",            # bytes exactly as they crossed the boundary
    timestamp=...,              # unix epoch, taken next to the I/O call
    transport={...},            # peer, interface, state — never interpreted
    decoded=None,               # filled in by a protocol layer, once one exists
)
```

`decoded` starting as `None` is deliberate. A transport-layer packet must never
claim a protocol interpretation it is not entitled to make.

---

## Protocol layer

Currently three placeholders: `bmw.py`, `uds.py`, `isotp.py`. Each is
importable, documents the exact list of values that must be verified before it
can be written, and raises `NotVerifiedError` if constructed.

The separation matters for the project's stated goal of extending to F11, F20,
F30 and so on later: BMW-specific framing, addressing, and routing belong in
`bmw.py`, and generic UDS structures must not accumulate BMW quirks. Mixing
them would make every future platform a rewrite.

Tests in `tests/test_uds.py` and `tests/test_isotp.py` assert that these
modules define no numeric constants at all. That is a structural guard against
an unverified byte value quietly appearing to make something look finished.

---

## Vehicle and ECU layer

`ECU` holds a name, an optional diagnostic address, and a protocol client. Its
read operations raise `NotVerifiedError`.

`DTC` and `ECUIdentification` are complete data containers. `DTC` always keeps
the raw bytes, reports `Unknown BMW DTC` when no sourced description exists,
and labels a status byte as `UNVERIFIED` when the bit layout has not been
confirmed. Every identification field is optional, and an absent value is
reported as absent rather than filled in.

`F10Vehicle.register_discovered()` refuses any ECU that has not actually
responded, so `discovered_ecus` cannot be populated from a catalogue. The
catalogue in `definitions/ecus.json` is a list of expected short names carrying
no addresses, and is never printed as discovered hardware.

---

## Decoding layer

Two levels:

- **`decoding/values.py`** — primitive byte-to-value conversions: integers of
  each width and endianness, booleans, ASCII, Latin-1, BCD, and a raw hex
  fallback. Pure functions, no automotive knowledge.
- **`decoding/signals.py`** — `SignalDefinition` binds a byte window to a
  decoder, a scale, an offset, and a unit; `DefinitionRegistry` loads
  definitions from JSON.

Every definition carries a `verified` flag and a `source`. An unverified
definition raises unless the caller passes `allow_unverified=True`, and its
output is labelled `[UNVERIFIED]` wherever it is displayed. A decoder failure
on unexpected ECU data falls back to a hex dump rather than raising, so strange
data never crashes the tool and the raw bytes stay visible.

Definitions live in JSON rather than in code so that identifiers are data,
reviewable in isolation, and diffable when someone adds one.

---

## Cross-cutting concerns

**Configuration** (`config.py`) is frozen dataclasses loaded from TOML and
validated on load. `ENETConfig.validate_for_connection()` raises
`UnverifiedParameterError` when host or port is unset, which is what keeps a
guessed gateway address out of the codebase.

**Safety** (`SafetyConfig.guard_write`) is the single gate every future write
path must call. It exists now, before any write code does, so there is an
obvious place for it to be checked and an obvious thing to review.

**Logging** (`logging/diagnostic_logger.py`) writes JSON Lines, flushed per
packet. `SessionMetadata` records the host, the configured vehicle, the
read-only flag, and the highest communication level proven during the session.

**Status** (`status.py`) is the `CommsLevel` ladder:

```
NONE → INTERFACE_PRESENT → ETHERNET_LINK → TCP_CONNECTED
     → BMW_TRANSPORT → DIAGNOSTIC_SESSION → ECU_RESPONDING → DATA_DECODED
```

`ENETTransport.comms_level` never returns more than `TCP_CONNECTED`, and
`ECU.comms_level` starts at `NONE` and is raised only by a genuine response.
The levels above `TCP_CONNECTED` are unreachable in this build by construction,
not by convention.

---

## Design rules

1. **Layers do not leak.** No BMW definition in transport code, no socket
   detail in protocol code, no protocol knowledge in the packet class.
2. **Unknown is a value.** `None`, `Unknown BMW DTC`, and `[UNVERIFIED]` are
   valid outputs. A plausible guess is not.
3. **Refuse loudly.** An unfinished layer raises `NotVerifiedError` with an
   explanation, rather than returning empty or fabricated data.
4. **Never report above your evidence.** Report the `CommsLevel` actually
   reached, and describe it accurately.
5. **Data, not code.** Identifiers, addresses, and DTC descriptions live in
   JSON with a `source` and a `verified` flag.
6. **Offline first.** Every layer must be testable with no vehicle attached.
