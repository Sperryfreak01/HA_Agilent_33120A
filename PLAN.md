# Agilent 33120A — Home Assistant Integration via ESPHome Serial Proxy

A plan for a Home Assistant custom integration that controls an Agilent 33120A 15 MHz function / arbitrary waveform generator over an ESPHome-based RS-232-to-TCP serial proxy, with bi-directional state sync between HA and the instrument's front panel.

---

## 1. Goals & Scope

### In scope (v1)

- Generate **sine, square, and triangle** waveforms.
- Set **frequency, amplitude (Vpp), and DC offset (V)** within the instrument's allowable ranges.
- Set **duty cycle** for square waves.
- **Bi-directional sync**: when the user changes settings on the 33120A front panel, the HA entities update; when the user changes HA entities, the instrument follows.
- Connection is over **RS-232 through an ESPHome serial-over-TCP proxy** (no GPIB).
- Surface instrument errors as a diagnostic sensor.
- Provide a **raw SCPI escape hatch** as a service so power users can drive features the integration does not model.

### Out of scope (v1, but designed to extend)

- AM / FM / FSK / Burst modulation
- Frequency sweep
- Arbitrary waveform download / management (DATA, DATA:DAC, DATA:COPY, etc.)
- Instrument state save/recall slots (`*SAV` / `*RCL`)
- Calibration commands
- GPIB transport

These remain accessible via the `send_raw_scpi` / `query_raw_scpi` services.

---

## 2. Background — what the 33120A manual tells us that drives the design

### 2.1 Command surface we actually use

The 33120A speaks SCPI. The waveform/amplitude state collapses to a tiny surface:

| Purpose | Command | Notes |
|---|---|---|
| One-shot configure | `APPL:SIN <freq>,<amp>,<offset>` (also `:SQU`, `:TRI`) | Sets shape + 3 params atomically |
| Granular: shape | `FUNC:SHAP {SIN\|SQU\|TRI\|RAMP\|NOIS\|DC\|USER}` | We only expose SIN/SQU/TRI |
| Granular: frequency | `FREQ <Hz>` | |
| Granular: amplitude | `VOLT <value>` | Units selected by `VOLT:UNIT` (we force VPP) |
| Granular: DC offset | `VOLT:OFFS <V>` | |
| Square duty cycle | `PULS:DCYC <percent>` | Only valid in SQU |
| Amplitude units | `VOLT:UNIT VPP` | Force VPP on init |
| Output termination | `OUTP:LOAD {50\|INF}` | Affects displayed amp/offset, not actual hardware |
| Read everything | `APPL?` | Returns `"SIN +5.000…E+03,+3.0…E+00,-2.5…E+00"` — **the linchpin of front-panel sync** |
| Read duty cycle | `PULS:DCYC?` | Only when shape == SQU |
| Identification | `*IDN?` | Returns `HEWLETT-PACKARD,33120A,0,<rev>` (newer firmware: `Agilent Technologies,33120A,...`) |
| Error queue | `SYST:ERR?` | FIFO, ≤20 entries, format `-113,"Undefined header"`; returns `+0,"No error"` when empty |
| Clear status | `*CLS` | Clears event registers and error queue |
| Reset | `*RST` | Default state (we don't auto-issue) |
| Remote mode | `SYST:REM` | Disables front panel except LOCAL key |
| Local mode | `SYST:LOC` | Returns control to front panel |
| Remote w/ lockout | `SYST:RWL` | Disables LOCAL too — **we never use this** |
| Device clear | `<Ctrl-C>` (0x03) | RS-232 equivalent of IEEE-488 device clear; aborts stuck operation |

### 2.2 Limits the integration must enforce

If we send an out-of-range value the 33120A silently clamps and generates `-221, "Settings conflict"`. We pre-validate to avoid this, and we still read back to confirm.

| Function | Freq min | Freq max | Amp min (50 Ω) | Amp max (50 Ω) | Amp min (HiZ) | Amp max (HiZ) |
|---|---|---|---|---|---|---|
| Sine | 100 µHz | 15 MHz | 50 mVpp | 10 Vpp | 100 mVpp | 20 Vpp |
| Square | 100 µHz | 15 MHz | 50 mVpp | 10 Vpp | 100 mVpp | 20 Vpp |
| Triangle | 100 µHz | **100 kHz** | 50 mVpp | 10 Vpp | 100 mVpp | 20 Vpp |

**Offset constraint** (for all three functions):
```
|Voffset| + Vpp/2  ≤  Vmax
|Voffset|          ≤  2 · Vpp
```
where Vmax = 5 V into 50 Ω, 10 V into high-Z.

**Square duty cycle**:
- 20 % – 80 % when frequency ≤ 5 MHz
- 40 % – 60 % when frequency > 5 MHz

**Default state after `*RST` / power-on** (per manual): sine, 1 kHz, 100 mVpp, 0 V offset, 50 Ω, VPP, duty 50 %.

### 2.3 RS-232 specifics that affect wiring & framing

- The 33120A is wired as a **DTE** device, so the cable to anything else that's a DTE (like our ESP UART) is a **null-modem / crossover**.
- Frame is fixed at **1 start bit + 7/8 data + optional parity + 2 stop bits**.
- Baud options: 300 / 600 / 1200 / 2400 / 4800 / 9600.
- Handshake uses **DTR (pin 4)** and **DSR (pin 6)**:
  - The 33120A drops DTR when its 100-char input buffer fills, or when it has a query response queued and saw `<newline>`.
  - It needs ≤10 chars of headroom after dropping DTR.
  - It will only transmit when DSR is asserted.
- **Sanctioned escape hatch** (manual p. 198): leave DTR floating, tie DSR true, and use **≤ 1200 baud**.
- `<Ctrl-C>` resets a stuck interface.
- Newer firmware (rev > 2.0) responds to either `HEWLETT-PACKARD` or `Agilent Technologies` in `*IDN?` — accept both.

### 2.4 The front-panel sync constraint

Over RS-232, the 33120A has **no SRQ and no Operation Status / Questionable Data registers** — only Status Byte + Standard Event. Neither flags user front-panel edits.

> **The only way to detect a front-panel change is to poll `APPL?` (plus `PULS:DCYC?` when in square mode).**

This is cheap: a single query returns shape + freq + amp + offset.

---

## 3. Architecture

```
┌────────────────┐   SCPI over     ┌─────────────────┐   TCP raw   ┌──────────────────────┐
│ Agilent 33120A │ ◄── RS-232 ───► │ ESP32 / ESP8266 │ ◄── WiFi ──►│ Home Assistant       │
│   (DB-9 DTE)   │   1200 8N2       │  UART + stream_  │             │  custom_components/  │
│   DSR↔DTR      │   crossover      │  server (oxan)   │             │  agilent_33120a/     │
│   strapped     │                  │                  │             │                      │
└────────────────┘                  └─────────────────┘             └──────────────────────┘
```

### 3.1 ESPHome side

A minimal `agilent_33120a.yaml`:

```yaml
external_components:
  - source: github://oxan/esphome-stream-server

uart:
  id: gen_uart
  tx_pin: GPIO17
  rx_pin: GPIO16
  baud_rate: 1200
  data_bits: 8
  parity: NONE
  stop_bits: 2

stream_server:
  uart_id: gen_uart
  port: 6638

binary_sensor:
  - platform: template
    name: "33120A Proxy Client Connected"
    lambda: 'return id(stream_server_id).has_clients();'
```

**Wiring**:
- ESP TX (GPIO17) → MAX3232 T1IN → DB-9 pin 2 (RXD into 33120A)
- ESP RX (GPIO16) ← MAX3232 R1OUT ← DB-9 pin 3 (TXD from 33120A)
- GND ↔ DB-9 pin 5
- **At the DB-9 shell going into the 33120A**: solder a jumper between **pin 4 (DTR)** and **pin 6 (DSR)** — this makes the 33120A see "the host is always ready", which the manual explicitly sanctions when handshake is disabled.

**Why 1200 8N2 and not 9600?** ESPHome's `stream_server` exposes the UART as raw bytes over TCP and gives us no way to manipulate or read DTR/DSR modem-control lines. The manual is explicit that disabling DTR/DSR handshake requires baud ≤ 1200. At 1200 baud an `APPL?` round-trip is ~80 ms send + ~500 ms response — fine for a 2 s poll loop.

**Optional upgrade path**: a custom ESPHome component that drives the 33120A's DTR/DSR lines from two GPIOs and implements the handshake in firmware. This would unlock 9600 baud but is **not** part of v1.

### 3.2 Home Assistant integration layout

```
custom_components/agilent_33120a/
├── __init__.py             # async_setup_entry / async_unload_entry; owns transport + coordinator
├── manifest.json           # domain, version, dependencies, iot_class=local_polling
├── const.py                # DOMAIN, defaults, command strings
├── transport.py            # asyncio TCP client, framing, locking, reconnect, Ctrl-C reset
├── coordinator.py          # DataUpdateCoordinator: APPL?, PULS:DCYC?, SYST:ERR?
├── entity.py               # base CoordinatorEntity with shared DeviceInfo
├── config_flow.py          # user step + reconfigure; *IDN? probe
├── select.py               # waveform shape
├── number.py               # frequency, amplitude, offset, duty cycle
├── sensor.py               # last_error (diagnostic), connection state
├── button.py               # local, clear_errors, beep
├── services.yaml           # send_raw_scpi, query_raw_scpi
├── strings.json
└── translations/en.json
```

### 3.3 Transport layer (`transport.py`)

- One persistent `asyncio.open_connection(host, port)` socket.
- One `asyncio.Lock` serializes all command/query pairs — the 33120A's RS-232 contract is strict request/response.
- `send(cmd)`: append `\n`, `writer.write`, await `drain`. No response expected.
- `query(cmd)`: append `\n`, `write`, `drain`, then `await reader.readuntil(b"\n")`, strip, return as `str`.
- Default per-call timeout 3 s; on timeout send `<Ctrl-C>`, close, reconnect with backoff (1 s → 2 s → 5 s → 10 s, capped).
- On any unexpected disconnect: emit a `homeassistant.helpers.dispatcher` signal so the coordinator can mark entities unavailable.
- All command strings are constructed from typed parameters — **never** interpolate user-supplied text without sanitising (no `;`, `\n`, or non-ASCII).

### 3.4 Coordinator (`coordinator.py`)

A `DataUpdateCoordinator` with `update_interval=timedelta(seconds=cfg["poll_interval"])` (default 2 s).

Per poll:

1. `APPL?` → parse the quoted string `"<SHAPE> <freq>,<amp>,<offset>"` into a dataclass `InstrumentState`.
2. If `shape == "SQU"`, also `PULS:DCYC?` → float.
3. Drain `SYST:ERR?` in a small loop (≤5 reads) until `+0,"No error"`; surface the most recent non-zero error.
4. Return `InstrumentState(shape, freq_hz, amplitude_vpp, offset_v, duty_pct, last_error)`.

**Write path**:

```
entity.async_set_native_value(x):
    await transport.send(<scpi command>)
    await transport.send("SYST:LOC")              # release the front panel immediately
    await coordinator.async_request_refresh()      # next read defines truth (handles -221 clamps)
```

We deliberately **do not** optimistically update `coordinator.data` — letting the read-back drive state is what makes auto-clamps and out-of-range corrections transparent in the UI.

### 3.5 Entities

| Platform | Entity | Notes |
|---|---|---|
| `select` | `select.gen_33120a_waveform` | Options: `sine`, `square`, `triangle`. Setting issues `APPL:<shape> <last_freq>,<last_amp>,<last_offset>` so freq/amp/offset survive the change. |
| `number` | `number.gen_33120a_frequency` | `mode: box`. `native_min/max` recomputed each refresh from the current shape. Unit `Hz`. |
| `number` | `number.gen_33120a_amplitude` | `mode: box`. Limits from the (shape, OUTP:LOAD) table. Unit `Vpp` (custom unit; HA doesn't have one built in). |
| `number` | `number.gen_33120a_offset` | `mode: box`. Limits computed each refresh from current Vpp + termination. Unit `V`. |
| `number` | `number.gen_33120a_duty_cycle` | Only `available` when shape is square. Limits depend on current frequency. Unit `%`. |
| `sensor` | `sensor.gen_33120a_last_error` | Diagnostic entity. Value is the error string; `code` and `timestamp` as attributes. `+0,"No error"` clears to `unknown`. |
| `binary_sensor` | `binary_sensor.gen_33120a_connected` | Diagnostic; mirrors the transport state. |
| `button` | `button.gen_33120a_local` | Sends `SYST:LOC`. |
| `button` | `button.gen_33120a_clear_errors` | Sends `*CLS` and drains queue. |
| `button` | `button.gen_33120a_beep` | Sends `SYST:BEEP`. Mostly for a "round-trip works" smoke test. |

### 3.6 Config flow

1. **User step**: host (string), port (int, default 6638), output termination (`50 Ω` / `High-Z`), poll interval (int s, default 2, range 1–30).
2. **Probe**:
   - Open TCP to host:port.
   - Send `*CLS`.
   - Send `*IDN?`, expect a line containing `33120A`. Accept both `HEWLETT-PACKARD,33120A,…` and `Agilent Technologies,33120A,…`.
   - On success, force `VOLT:UNIT VPP` and `OUTP:LOAD <selected>`, then `SYST:LOC`.
3. **Failure mapping**:
   - TCP `ECONNREFUSED` → `cannot_connect`
   - Timeout on `*IDN?` → `no_response_check_baud_and_cable`
   - Wrong IDN → `wrong_device` (show what we got)
4. **Unique ID**: derived from the IDN string (revision-stripped) + host to allow multiple instruments on the same network.
5. **Reconfigure flow**: lets the user change host/port/poll interval/termination without re-adding.

### 3.7 Services

```yaml
# services.yaml
send_raw_scpi:
  description: >
    Send a raw SCPI command to the function generator. Use for features
    the integration does not model (AM/FM, sweep, burst, arbitrary
    waveform management, *SAV/*RCL, etc).
  fields:
    command:
      description: A single SCPI command, no terminating newline.
      example: "APPL:SIN 1E3, 2.0, 0"
      required: true
      selector: { text: }

query_raw_scpi:
  description: >
    Send a raw SCPI query and return its response. Fires
    agilent_33120a.query_response event.
  fields:
    command:
      description: A SCPI query ending with '?'.
      example: "SYST:VERS?"
      required: true
      selector: { text: }
```

Both services validate that the string is printable ASCII, contains no `\n`, and (for `query_raw_scpi`) ends with `?`.

---

## 4. Order of Development

Build bottom-up so each layer is testable against fakes before the next is written.

### Phase 0 — Hardware bring-up (no code yet)

1. Wire the MAX3232 + DB-9.
2. Strap DSR↔DTR on the 33120A side of the connector.
3. Flash a "dumb" ESPHome config with `stream_server` and `logger: level: VERY_VERBOSE`.
4. From a laptop on the same network: `nc <esp-ip> 6638`, type `*IDN?\n`, expect a 33120A response.

**Exit criterion**: `*IDN?` returns the expected string via `nc`. If this fails, no software is going to save it.

### Phase 1 — Transport

1. Implement `transport.py` (connect, lock, send, query, reconnect, Ctrl-C reset).
2. Build a `tests/fake_33120a.py` — an asyncio TCP server that emulates `*IDN?`, `APPL?`, the setters, and an error queue.
3. Pytest the transport against the fake: connect, send a write, send a query, handle disconnect mid-query, handle slow responses, handle `<Ctrl-C>` recovery.

**Exit criterion**: 100 % of `transport.py` paths covered by tests against the fake.

### Phase 2 — Coordinator + state model

1. `InstrumentState` dataclass with parser for the `APPL?` quoted string (regex + float parsing; handle `+5.000000000000E+03` notation).
2. `DataUpdateCoordinator` subclass that polls `APPL?`, conditionally `PULS:DCYC?`, and drains `SYST:ERR?`.
3. Tests against the fake: shape change is detected within one poll interval; duty-cycle is only queried when shape is square; error queue surfaces correctly.

**Exit criterion**: changing instrument state on the fake propagates to `coordinator.data` within one tick.

### Phase 3 — Entities (read-only first)

1. `entity.py` base class.
2. `sensor.last_error`, `binary_sensor.connected` — these are pure read-back, no writes to debug.
3. Run inside HA via `hass --debug` against the fake instrument.

**Exit criterion**: in the HA UI, changing the fake's state causes the sensors to update.

### Phase 4 — Entities (writable)

1. `select.waveform` — uses APPLy so freq/amp/offset survive.
2. `number.frequency`, `number.amplitude`, `number.offset` with dynamic limits.
3. `number.duty_cycle` with `available` gating.
4. After each write: `SYST:LOC` + `async_request_refresh`.

**Exit criterion**: every entity is round-trippable. Setting an out-of-range value gets clamped by the (fake) instrument and the UI reflects the clamp on the next refresh.

### Phase 5 — Config flow

1. User step + validation + IDN probe.
2. Reconfigure step.
3. Error mapping for the three common failures (no TCP, no response, wrong device).
4. Translations.

**Exit criterion**: integration adds cleanly, gives clear errors for each failure class, and can be removed without leaving entities behind.

### Phase 6 — Services + buttons

1. `send_raw_scpi` / `query_raw_scpi` with input validation.
2. Three buttons.

**Exit criterion**: sending `BM:STAT ON` via the service enables burst (this proves the escape hatch is real).

### Phase 7 — Real hardware soak test

1. Run against the actual 33120A for ≥ 24 h with poll interval 2 s.
2. Verify no leaked sockets, no stuck Ctrl-C states, no memory growth, no orphaned tasks across HA restarts.
3. Validate behaviour on power-cycle of the instrument and reboot of the ESP.

### Phase 8 — Documentation & ship

1. README with wiring photo, ESPHome YAML, HA install instructions, services reference.
2. `info.md` for HACS.
3. CHANGELOG.

---

## 5. Watch-outs / Things That Will Bite

### 5.1 Wiring & RS-232

- **DSR-DTR strap on the wrong end.** The strap must be at the **33120A's DB-9**, not the ESP side. If you strap them at the ESP, the 33120A still sees DSR floating and won't transmit.
- **Wrong null-modem.** A straight-through DB-9 cable will *appear* to work for outgoing commands (you can see the LEDs blink) but the 33120A will never reply because TXD is going into TXD. Always verify with a multimeter that pins 2 and 3 are swapped.
- **MAX3232 capacitor values.** The charge-pump caps need to be the right value (usually 0.1 µF) for the chip you're actually using. The data eyes get ugly at 1200 baud with the wrong caps and you'll see intermittent framing errors.
- **ESPHome `stream_server` does not expose modem-control lines.** Don't plan around DTR/DSR handshake unless you write a custom ESPHome component.

### 5.2 Protocol

- **Two stop bits, not one.** The 33120A's UART frame is fixed at 2 stop bits. Most defaults assume 1.
- **Newer firmware identifies as Agilent**, not Hewlett-Packard. Match on `33120A`, not the vendor prefix.
- **APPL? returns a *quoted* string.** Strip the surrounding double quotes before parsing.
- **Float format is `+5.000000000000E+03`.** Python's `float()` handles it but a naïve regex might miss the leading `+`.
- **`-221, "Settings conflict"` is normal**, not a fault. The instrument is telling you it clamped a value. Surface it as an info-level event, not an error.
- **Don't issue `*RST` automatically.** It would wipe whatever the user had dialed in on the front panel and is the kind of thing that costs trust the first time it happens.

### 5.3 State sync

- **The read-back is canonical.** Never set `coordinator.data` from the write path. Always re-read.
- **Don't park the instrument in remote mode.** If you forget to issue `SYST:LOC` after a write, the front panel locks up and the user can't twist the knob. Always pair writes with `SYST:LOC`.
- **Poll interval vs. UART throughput.** At 1200 baud you can fit roughly one `APPL?` round-trip per second. Don't let the poll interval drop below 1 s.
- **Locking discipline.** The transport's lock must wrap the entire query (write + read). If a write and a query interleave the responses can pair to the wrong requests and you'll spend a day debugging "ghost values".

### 5.4 HA integration mechanics

- **Dynamic `native_min/max` on `number` entities.** Recompute on every coordinator update — the offset range depends on current Vpp; the frequency range depends on current shape.
- **`available` on duty cycle.** Must return `False` for non-square shapes, otherwise HA will let the user set a value that goes nowhere.
- **Unique IDs.** Derive from the `*IDN?` plus host so two 33120As on the same LAN don't collide. The 33120A has no serial number in `*IDN?`, so host:port is the disambiguator.
- **Disconnect handling.** When the TCP socket dies, mark entities `available = False` rather than removing them — the user's automations should pause, not crash.
- **Config validation must not block.** Run the IDN probe in an executor / asyncio task with a hard timeout so the config flow doesn't hang HA's UI when the proxy is offline.

### 5.5 Operational

- **Power cycling order.** If the user power-cycles the 33120A, the integration must reconnect cleanly without a HA restart. Test this explicitly.
- **ESP reboot during a query.** The transport must time out, send Ctrl-C (which the dead UART will swallow), reconnect, and keep going.
- **Multiple HA writers.** If two automations both write to `frequency` in the same tick, the lock serializes them — but the second one will see the first's clamp via read-back. Document this.

---

## 6. Important Test Cases

### 6.1 Transport (`tests/test_transport.py`)

| # | Test | Expected |
|---|---|---|
| T1 | Connect to a live fake, send `*IDN?`, read response | Returns matching IDN string |
| T2 | `query()` while another `query()` is in flight | Second waits for first; both succeed |
| T3 | Server closes mid-query | Raises `Disconnected`; subsequent `query()` triggers reconnect and succeeds |
| T4 | Server stops responding for >3 s | Per-call timeout fires; transport sends Ctrl-C and reconnects |
| T5 | Send a command containing `\n` | Rejected by sanitiser before bytes hit the wire |
| T6 | Rapid 100 × `APPL?` against fake | All succeed in order, no interleaving |
| T7 | Reconnect backoff cap | After 5 failed attempts, backoff stays at 10 s, doesn't grow unbounded |

### 6.2 State parsing (`tests/test_state.py`)

| # | Input | Expected |
|---|---|---|
| S1 | `"SIN +1.000000000000E+03,+1.000000E-01,+0.000000E+00"` | `(SIN, 1000.0, 0.1, 0.0)` |
| S2 | `"SQU +5.000000000000E+06,+5.000000E+00,-2.500000E+00"` | `(SQU, 5e6, 5.0, -2.5)` |
| S3 | `"TRI +1.000000000000E-04,+5.000000E-02,+0.000000E+00"` | `(TRI, 1e-4, 0.05, 0.0)` (minimum frequency) |
| S4 | `"USER +1.000000000000E+03,…"` | Treated as unsupported shape; coordinator surfaces a warning, entity goes unavailable |
| S5 | Missing quotes | Parser still succeeds (some firmware revs omit them) |
| S6 | Garbage line | Raises `ParseError`; transport doesn't crash |

### 6.3 Coordinator (`tests/test_coordinator.py`)

| # | Scenario | Expected |
|---|---|---|
| C1 | Fake switches SIN → SQU between polls | Within one tick, `coordinator.data.shape == SQU` and a `PULS:DCYC?` is issued |
| C2 | Fake switches SQU → SIN | No `PULS:DCYC?` issued; entity `duty_cycle.available` becomes False |
| C3 | Fake reports `-221,"Settings conflict"` in error queue | Sensor reflects it, queue drained, next poll shows `+0` |
| C4 | Fake's error queue has 5 stacked errors | All five are drained; sensor shows the most recent |
| C5 | Transport throws mid-poll | Coordinator marks update failed; entities become unavailable |
| C6 | Poll interval 1 s, 60 polls | Mean round-trip < 600 ms; no missed ticks |

### 6.4 Entities (`tests/test_entities.py`)

| # | Scenario | Expected |
|---|---|---|
| E1 | Set frequency to 1000 Hz on a sine | `FREQ 1.000000E+03` sent; next read shows 1000 |
| E2 | Set frequency to 1 MHz, then change shape to triangle | Fake clamps freq to 100 kHz, raises `-221`; entity shows 100 kHz, sensor shows the conflict |
| E3 | Set amplitude that violates the offset constraint | Pre-validation in the entity rejects the call with a clear error before sending |
| E4 | Set duty cycle while shape is sine | Entity is unavailable; service call is a no-op with a warning |
| E5 | Change shape from HA | `APPL:<shape> <last_freq>,<last_amp>,<last_offset>` sent; freq/amp/offset unchanged after |
| E6 | Press "Local" button | `SYST:LOC` sent; front panel responsive (manual verification on hardware) |
| E7 | Set offset that drives `|offset| + Vpp/2 > Vmax` | Entity rejects with clear error before sending |

### 6.5 Front-panel sync (`tests/test_sync.py`)

| # | Scenario | Expected |
|---|---|---|
| F1 | Fake simulates a knob turn (freq changes) | HA entity reflects new value within one poll interval |
| F2 | Fake changes shape | HA select entity reflects new shape; affected entity limits update |
| F3 | Fake reports it's in REM mode (post HA write) | Subsequent fake "front-panel" change is ignored (correct: user can't change it) — but after the next `SYST:LOC` from HA, sync resumes |
| F4 | Simultaneous: HA sets freq while fake-front-panel sets amp in same tick | Last writer wins per parameter; coordinator read converges to instrument state |

### 6.6 Config flow (`tests/test_config_flow.py`)

| # | Scenario | Expected |
|---|---|---|
| CF1 | Happy path: valid host, fake responds | Entry created, `VOLT:UNIT VPP` + `OUTP:LOAD` applied, entities appear |
| CF2 | TCP refused | Error `cannot_connect` shown in form |
| CF3 | TCP connects but no `*IDN?` response | Error `no_response_check_baud_and_cable` |
| CF4 | `*IDN?` returns a different instrument | Error `wrong_device` with the unexpected IDN included |
| CF5 | Duplicate add (same host:port) | Aborted with `already_configured` |
| CF6 | Reconfigure: change poll interval | Entry updated, no entity removal |

### 6.7 Hardware integration tests (manual checklist, on real 33120A)

| # | Procedure | Expected |
|---|---|---|
| H1 | Power on instrument, then start HA | Integration connects; entities populate to current instrument state |
| H2 | Power-cycle the 33120A while HA is running | Entities go unavailable for ≤ 30 s, then recover |
| H3 | Reboot the ESPHome proxy while HA is running | Same as H2 |
| H4 | Set sine 1 kHz 2 Vpp 0 V offset from HA, verify with scope | Output matches within instrument tolerance |
| H5 | Turn the front-panel knob 100 times over 60 s | HA entity tracks within one poll interval; no error queue growth |
| H6 | Send `BM:STAT ON` via `send_raw_scpi`, observe burst on scope | Burst mode enabled; integration entities still poll correctly |
| H7 | Soak: 24 h at 2 s poll | No reconnects, no errors logged, no memory growth in HA |

---

## 7. Quick Reference — File Manifests

### `manifest.json`

```json
{
  "domain": "agilent_33120a",
  "name": "Agilent 33120A Function Generator",
  "version": "0.1.0",
  "documentation": "https://github.com/<owner>/agilent_33120a",
  "iot_class": "local_polling",
  "config_flow": true,
  "requirements": [],
  "codeowners": ["@<owner>"]
}
```

### Constants (`const.py`)

```python
DOMAIN = "agilent_33120a"

DEFAULT_PORT = 6638
DEFAULT_POLL_INTERVAL = 2  # seconds
DEFAULT_TERMINATION = "50"

SHAPES = ("SIN", "SQU", "TRI")

FREQ_LIMITS = {
    "SIN": (1e-4, 1.5e7),
    "SQU": (1e-4, 1.5e7),
    "TRI": (1e-4, 1.0e5),
}

AMP_LIMITS = {
    "50":  (0.05, 10.0),   # Vpp into 50 Ω
    "INF": (0.10, 20.0),   # Vpp into high-Z
}

VMAX = {"50": 5.0, "INF": 10.0}
```

---

## 8. Open Questions to Confirm Before Coding

1. **Baud rate / handshake**: 1200 8N2 no-handshake (proposed default) vs. 9600 with a custom ESPHome component implementing DTR/DSR. Recommend 1200.
2. **Polling interval default**: 2 s feels right; 1 s is snappier but is near the UART throughput ceiling.
3. **Should `OUTP:LOAD` be a config-flow option or a runtime entity?** Proposed as config-flow only (it rarely changes after install).
4. **Should we expose Vrms / dBm units?** Proposed: no — force VPP at startup to keep the model simple.
5. **HACS vs. manual install only for v1?** Proposed: ship for HACS from day one.
