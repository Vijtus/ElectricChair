# Architecture

## Components

### `app.py`

The Python bridge does four jobs:

1. serves the web UI;
2. maintains a semantic chair/display state model;
3. writes command names to the Arduino over USB serial;
4. parses firmware output lines such as `RX: 0x04` back into frame/state hints.

Important classes:

| Class | Role |
|---|---|
| `CommandDef` | Named command + byte-code metadata shared by the UI model |
| `ChairState` | Local model of power, mode, active zones, levels, timer, visible SVG layers, logs, and frame-derived state |
| `FirmwareSerialBridge` | Background serial reader/writer and reconnect loop |
| `AppHandler` | HTTP routes for the UI and API |
| `AppServer` | `ThreadingHTTPServer` with attached state, bridge, SVG markup, and LAN IP |

### Web UI

The active UI is served from `ROOT-VIEW.html` and enhanced by `static/root-view.js`.

The debug UI uses:

- `static/debug.html`
- `static/app.js`
- `static/app.css`

The UI polls `/api/state` and posts command names to `/api/command`.

### Firmware

`electric_chair_firmware/src/main.cpp` is a PlatformIO Arduino Nano sketch.

It listens on USB serial at `115200` and maps text commands to single-byte UART codes. It sends those bytes over `SoftwareSerial` at `9600` baud on pins `10` and `11`.

It also supports:

```text
listen
listen on
listen off
listen toggle
```

When listen mode is enabled, bytes received from the chair UART are printed to USB serial as timestamped `RX: 0x..` lines.

## Data flow

```text
Browser click
  ↓
POST /api/command {"command": "masaz_stop"}
  ↓
app.py updates local state + writes "masaz_stop\n" to USB serial
  ↓
Arduino lookup table maps "masaz_stop" → 0x0D
  ↓
Arduino writes 0x0D to chair UART
  ↓
Chair emits status bytes
  ↓
Arduino logs RX bytes
  ↓
app.py parses logs and updates /api/state
  ↓
Browser redraws active buttons, display layers, levels, timer, and diagnostics
```

## State model

The Python side keeps a live model for:

- connection status;
- port name;
- board listen mode;
- last command and errors;
- power state;
- manual/automatic/off mode;
- timer and remaining seconds;
- intensity, speed, and foot-speed levels;
- active massage zones;
- visible SVG layers;
- recent command history;
- recent backend log lines;
- raw frame bytes and matrix bytes.

## Protocol notes

The reverse-engineered protocol notes are kept in:

```text
docs/massage-chair-uart-protocol-v1.txt
```

The UI behavior notes are kept in:

```text
docs/display-touchpanel-behavior.pl.txt
```

The active command map is duplicated in both the Python bridge and Arduino firmware. Keep those maps synchronized when adding or changing commands.
