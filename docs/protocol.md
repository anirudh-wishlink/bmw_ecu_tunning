# Protocol notes

This file is the project's record of what is known about talking to the car.
It is the single place where a protocol claim may be written down, and every
claim must carry evidence.

Sections:

- **VERIFIED** — confirmed by observation on this vehicle, or by an
  authoritative source that is cited. Only these may be implemented in code.
- **UNVERIFIED** — believed or reported, but not confirmed here. May not be
  implemented, and may not appear in code as a constant.
- **TODO** — open questions, in the order they need answering.
- **EXPERIMENTAL** — being investigated right now, with results so far.

An assumption must never be written as a fact. If something is not in the
VERIFIED section with evidence, it is not verified.

---

## VERIFIED

Nothing yet.

No BMW protocol detail has been confirmed for this project. In particular, none
of the following is known: the diagnostic gateway address, the TCP port, any
UDP discovery exchange, the diagnostic message header layout, the activation
handshake, the tester source address, the ECU target addresses, any data
identifier, any DTC record layout, or any signal scaling formula.

That is why `definitions/*.json` ship empty, `config.toml` ships with no host
or port, and everything above the transport layer raises `NotVerifiedError`.

### Verified about the host side

These are macOS facts, not BMW facts, and are what the current build relies on:

| Fact | Evidence |
| --- | --- |
| `ifconfig -a` lists interfaces with flags, MTU, MAC, IPv4/IPv6, media, and status | Standard macOS tooling; parser covered by `tests/test_enet.py` |
| `networksetup -listallhardwareports` maps device names to hardware port names | Standard macOS tooling; parser covered by tests |
| `status: active` indicates a carrier on the interface | Standard macOS tooling |
| A 169.254.0.0/16 address means macOS self-assigned because no DHCP server answered | APIPA behaviour, RFC 3927 |
| An ENET cable presents as a USB or Thunderbolt Ethernet adapter (`enN`) | Host-side observation; no BMW claim implied |

---

## UNVERIFIED

Kept deliberately short. Recording a rumour here and then treating it as a
starting point is how a guess becomes a "fact" three commits later.

| Claim | Status |
| --- | --- |
| The F10 has an Ethernet diagnostic gateway reachable over the OBD-II port with an ENET cable | Widely reported, not confirmed here. The whole project assumes it; nothing in the code depends on any specific detail of it. |
| The DME in this car is an MSV90 | From the vehicle description, not from an ECU read. `f10diag vehicle info` labels it as an assumption, and `MSV90.description` says "not confirmed". |
| The gateway may use a link-local address, so the host may need an APIPA or manually configured address | Consistent with the candidate ranking heuristic, but the specific address is unknown and no default is shipped. |

---

## TODO

In dependency order. Each must move to VERIFIED with evidence before the layer
above it can be written.

### Phase 3 — BMW diagnostic transport

1. **TODO: VERIFY** the diagnostic gateway's IPv4 address, and how the host is
   expected to obtain an address on that link.
2. **TODO: VERIFY** the TCP port used for diagnostic requests.
3. **TODO: VERIFY** whether any UDP announcement or discovery exchange precedes
   the TCP connection, and on which port.
4. **TODO: VERIFY** the header layout of a diagnostic message on this
   transport: field order, field widths, byte order, and what the length field
   counts.
5. **TODO: VERIFY** the activation or registration exchange, if any, that must
   succeed before the gateway routes requests, and what a rejection looks like.
6. **TODO: VERIFY** the source address a tester is expected to use.
7. **TODO: VERIFY** the gateway's timeout and keep-alive behaviour.

### Phase 4 — ECU discovery

8. **TODO: VERIFY** the diagnostic addresses of the F10's control units.
9. **TODO: VERIFY** what a response from a control unit that is absent or not
   routed looks like, so absence is not confused with a timeout.

### Phase 5 — Identification

10. **TODO: VERIFY** whether the gateway and ECUs speak UDS (ISO 14229) over
    this transport, or a BMW-specific service set.
11. **TODO: VERIFY** which diagnostic session, if any, must be established
    before a read is accepted.
12. **TODO: VERIFY** whether a tester-present message is needed to hold a
    session open, and at what interval.
13. **TODO: VERIFY** the request that returns hardware number, software number,
    and software version, and the layout of its response.
14. **TODO: VERIFY** how the VIN is read and from which control unit.

### Phase 6 — Fault memory

15. **TODO: VERIFY** the fault-memory read request accepted by the DME.
16. **TODO: VERIFY** the DTC record layout, including how many bytes per entry
    and the meaning of the status byte's bits.
17. **TODO: VERIFY** a source for BMW DTC descriptions. Until then every code
    displays as `Unknown BMW DTC` with its raw bytes.

### Phase 7 — Live data

18. **TODO: VERIFY** the data identifiers the DME accepts.
19. **TODO: VERIFY** the byte layout and scaling for each signal, one signal at
    a time, before adding it to `definitions/signals.json`.

### Possibly not needed

20. **TODO: VERIFY** whether the transport carries whole diagnostic payloads —
    in which case ISO-TP segmentation is unnecessary above it — or tunnels
    CAN-sized frames that must be reassembled.

---

## EXPERIMENTAL

Nothing in progress.

---

## How to verify something safely

1. Record first. `f10diag capture` opens a connection and transmits nothing, so
   it cannot provoke the car. To observe a known-good diagnostic tool's traffic,
   capture at the link layer with `tcpdump` on the ENET interface.
2. Analyse the recording offline. Build a `ReplayTransport` on it so the
   analysis is repeatable without the car.
3. Change one thing at a time, and write down what you did, what you expected,
   and what happened.
4. Add the finding to VERIFIED above with the evidence: the capture file, the
   command, or the citation.
5. Only then implement it, and add a replay test built on the capture.

Do not attempt to bypass authentication or security mechanisms. Security
access, key extraction, and immobiliser operations are out of scope for this
project, not merely unimplemented.

---

## Recording a finding

Use this shape, so a later reader can re-derive it:

```
### <what was established>

Evidence:   captures/2026-08-27-ignition-on.jsonl, packets 14-17
Method:     <exactly what was done>
Confidence: high | medium | low
Notes:      <what is still not known about it>
```
