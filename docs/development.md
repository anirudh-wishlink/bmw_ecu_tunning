# Development

## Setup

```bash
cd bmw-f10-diag
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Python 3.11 or newer, because configuration uses `tomllib` from the standard
library.

## Running the tests

```bash
pytest -q                       # whole suite
pytest tests/test_enet.py -v    # one file
pytest -k replay                # by name
pytest --tb=short -x            # stop at the first failure
```

The suite needs no vehicle, no cable, and no network access. The ENET transport
tests run against a local TCP echo server on the loopback interface, which
exercises real socket behaviour — timeouts, partial reads, peer disconnects,
reconnection — without any hardware.

If the host reports no loopback interface, those tests skip rather than fail.

## What the tests are actually protecting

Beyond ordinary correctness, several tests exist to keep the project honest,
and should not be deleted casually:

- `tests/test_uds.py` and `tests/test_isotp.py` assert that the placeholder
  protocol modules define **no numeric constants at all**. This is a structural
  guard against an unverified byte value appearing in the codebase.
- `tests/test_decoding.py::TestBundledDefinitions` asserts that the shipped
  JSON definition files are empty and that no ECU address is populated.
- `tests/test_config.py` asserts that the repository's `config.toml` ships no
  host or port.
- `tests/test_cli.py::TestReportingDiscipline` asserts that a TCP connection
  ranks below ECU communication, that a fresh ECU has proven nothing, and that
  an unresponsive ECU cannot be registered as discovered.

If one of these fails, the right response is usually to reconsider the change,
not to update the test.

## Adding a dependency

Don't, unless the layer being built genuinely needs it. `python-can`,
`udsoncan`, and an ISO-TP library are listed as commented-out candidates in
`requirements.txt` precisely because it is not yet known whether the selected
transport requires any of them.

## Coding standards

- Type hints throughout; `from __future__ import annotations` at the top.
- Frozen dataclasses for configuration and value objects.
- `pathlib` for paths, the standard `logging` module for logs.
- Descriptive exceptions from `f10diag.exceptions`, never bare `Exception`.
- Docstrings on public APIs, including what each method raises.
- No global mutable state, no monolithic files, no hard-coded packet blobs
  scattered through the code, no ECU definitions inside transport code.
- Comments explain intent or a constraint. They do not narrate the code.
- `asyncio` only where it earns its place. The current transport is
  synchronous, which is simpler and adequate for request/response diagnostics.

---

## Phase plan

Each phase ends when its layer works and is tested. Do not start the next one
before then, and never skip ahead.

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | macOS networking: project structure, interface discovery, ENET configuration, socket abstraction, logging | **Done** |
| 2 | ENET transport: connection, timeouts, packet logging, disconnect/reconnect, raw inspection. Validate against real hardware | Code done, **hardware validation outstanding** |
| 3 | BMW diagnostic transport: verified framing and routing to the gateway | Not started — blocked on `docs/protocol.md` TODO 1-7 |
| 4 | ECU discovery: `f10diag ecu list`, showing only ECUs that actually answered | Not started — blocked on TODO 8-9 |
| 5 | DME identification: hardware and software numbers, version, VIN | Not started — blocked on TODO 10-14 |
| 6 | DTC reading: raw and decoded, with `Unknown BMW DTC` where no source exists | Not started — blocked on TODO 15-17 |
| 7 | Read-only live data: only signals whose identifier and decoder are verified | Not started — blocked on TODO 18-19 |
| 8 | Optional macOS GUI, only once the backend is stable | Not started |

### Per-phase workflow

1. State what is known, with evidence.
2. State what is unverified.
3. Implement only the verified behaviour.
4. Add unit tests.
5. Add mock or replay tests.
6. Run the suite.
7. Write down the exact commands needed to test it on macOS.
8. Only then move to the next layer.

---

## Phase 2: validating against hardware

The transport code is written and tested against a local socket. What remains
is confirming it behaves on a real ENET link.

```bash
f10diag network interfaces          # before plugging in
# plug the ENET cable into the Mac and the OBD-II port, ignition on
f10diag network interfaces          # a new adapter should appear
f10diag network select
```

Record what you observe in `docs/protocol.md`: which interface appeared, what
address macOS assigned, and whether the link went active. Those are host-side
facts and can be verified without sending anything to the car.

Connecting requires a host and port, which is where Phase 3 begins.

---

## Phase 3: what to do first

The gateway address, port, and framing are unknown, and guessing them is out of
bounds. The intended route is observation:

1. Capture traffic while a known-good diagnostic tool talks to the car. This
   tool's own `capture` command transmits nothing; for on-the-wire observation
   of another tool, use `tcpdump` on the ENET interface.
2. Analyse the capture offline.
3. Record each finding in `docs/protocol.md` under VERIFIED with its evidence.
4. Implement only what was recorded, in `protocols/bmw.py`.
5. Build a `ReplayTransport` test on the capture so the behaviour is locked in.

Do not attempt to bypass authentication or security mechanisms.

---

## Adding a signal definition

Once a signal has genuinely been verified:

1. Add it to `src/f10diag/definitions/signals.json` with a `source` describing
   how it was verified, and `"verified": true`.
2. Add a decoding test with the raw bytes you observed and the value you
   expect.
3. If the value came from a capture, add a replay test too.

Adding one with `"verified": false` is allowed while it is still a hypothesis.
The tool will then refuse to apply it unless the operator opts in, and will
label every value it produces `[UNVERIFIED]`.

Never add a definition copied from another platform, a forum post, or memory
without testing it against this car and citing where it came from.

---

## Adding a write operation

There are none, and adding one is a separate, reviewed decision — not a
side-effect of another change. When the time comes:

1. Call `SafetyConfig.guard_write(operation_name)` before anything else. It is
   the single gate, and it already exists.
2. Require an explicit opt-in beyond the default, and an interactive
   confirmation naming what will change.
3. Log the operation, its parameters, and its result to the capture.
4. Keep it out of any code path a read-only command can reach.

Out of scope entirely, not merely unimplemented: SecurityAccess brute force,
key extraction, immobiliser operations, emissions defeat functionality.

---

## Known gaps

- **PCAP export** is not implemented. Captures record transport payloads, not
  complete Ethernet frames, so a faithful PCAP would require synthesising link
  and IP headers that were never observed. Either capture with `tcpdump` when a
  true PCAP is needed, or extend the capture format to record whole frames.
- **UDP discovery** is not implemented, because it is unknown whether any
  exists on this transport.
- **`asyncio`** is unused. If concurrent ECU polling turns out to be needed for
  live data, the `Transport` interface is the place to add an async variant.

---

## Extending to other F-series cars

The eventual goal is F11, F20, F30, F32 and similar, with F10 remaining the
primary target. The structure that makes that possible is already in place:
platform-specific values live in `definitions/*.json` keyed by platform, BMW
protocol behaviour lives in `protocols/bmw.py`, and generic UDS structures must
stay free of BMW quirks.

Keep it that way. The moment a platform-specific constant lands in the generic
layers, every new platform becomes a rewrite.
