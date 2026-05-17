# Agilent 33120A — Home Assistant Integration

A Home Assistant custom integration that controls an **Agilent / HP 33120A 15 MHz function / arbitrary waveform generator** over an ESPHome-based RS-232-to-TCP serial proxy, with bi-directional state sync between HA and the instrument's front panel.

## Features

- Control **sine, square, and triangle** waveforms
- Set **frequency** (100 µHz – 15 MHz), **amplitude** (Vpp), and **DC offset**
- Set **duty cycle** for square waves (20–80% or 40–60% above 5 MHz)
- **Bi-directional sync**: front-panel changes reflected in HA within the poll interval
- Surface instrument **errors** as a diagnostic sensor
- Raw **SCPI escape hatch** service for features the integration doesn't model

## Architecture

```
Agilent 33120A  ──RS-232──►  ESP32/ESP8266      ──TCP──►  Home Assistant
  (DB-9 DTE)      1200 8N2   stream_server :6638            agilent_33120a
  DSR↔DTR         crossover
  strapped
```

The ESP runs ESPHome with the [oxan/esphome-stream-server](https://github.com/oxan/esphome-stream-server) component, exposing the 33120A's SCPI interface as a raw TCP socket.

## Hardware

### ESPHome YAML

See [`esphome/agilent-33120a-bridge.yaml`](esphome/agilent-33120a-bridge.yaml) for the recommended D1 Mini configuration.

### Wiring

- ESP TX → MAX3232 T1IN → DB-9 pin 2 (RXD into 33120A)
- ESP RX ← MAX3232 R1OUT ← DB-9 pin 3 (TXD from 33120A)
- GND ↔ DB-9 pin 5
- **DB-9 shell (33120A side)**: jumper pin 4 (DTR) to pin 6 (DSR)

The DTR↔DSR strap must be at the **33120A's connector**, not the ESP side.

## Installation

### HACS (recommended)

1. Add this repo as a custom repository in HACS (type: Integration).
2. Install **Agilent 33120A Function Generator**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** and search for *Agilent 33120A*.

### Manual

Copy `custom_components/agilent_33120a/` into your HA `config/custom_components/` directory and restart.

## Configuration

The config flow asks for:

| Field | Default | Notes |
|---|---|---|
| Host | — | IP or hostname of the ESPHome proxy |
| Port | 6638 | TCP port exposed by `stream_server` |
| Output termination | 50 Ω | Affects amplitude limits displayed |
| Poll interval | 2 s | How often HA queries the instrument |

## Services

### `agilent_33120a.send_raw_scpi`

Send any SCPI command (no response). Use for AM/FM, sweep, burst, arbitrary waveform, `*SAV`/`*RCL`, etc.

```yaml
service: agilent_33120a.send_raw_scpi
data:
  command: "APPL:SIN 1E3, 2.0, 0"
```

### `agilent_33120a.query_raw_scpi`

Send a SCPI query; the response is fired as an `agilent_33120a.query_response` event.

```yaml
service: agilent_33120a.query_raw_scpi
data:
  command: "SYST:VERS?"
```

## Development

See [`PLAN.md`](PLAN.md) for the full design document, including the phased development plan, test cases, and known watch-outs.

```
custom_components/agilent_33120a/
├── __init__.py        # entry setup / teardown
├── manifest.json
├── const.py           # DOMAIN, limits, command strings
├── transport.py       # asyncio TCP client, locking, reconnect
├── coordinator.py     # DataUpdateCoordinator: APPL?, PULS:DCYC?, SYST:ERR?
├── entity.py          # shared base + DeviceInfo
├── config_flow.py     # user step + *IDN? probe + reconfigure
├── select.py          # waveform shape
├── number.py          # frequency, amplitude, offset, duty cycle
├── sensor.py          # last_error, connection state
├── button.py          # local, clear_errors, beep
├── services.yaml
├── strings.json
└── translations/en.json
```

## License

MIT
