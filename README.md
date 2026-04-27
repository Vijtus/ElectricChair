# Massage Chair Serial Bridge

Small local web bridge for a massage chair UART interface.

The project has two parts:

- `app.py` serves the web UI and writes command names to USB serial.
- `firmware/` receives those names and sends one-byte UART commands to the chair controller.

This is hardware-control software. Read the code before using it.

## Status

Experimental.

The command map is based on observed behavior and notes in `notes/`. Treat those notes as working notes, not as a vendor specification.

## Layout

```text
app.py                    Python web server and serial bridge
ROOT-VIEW.html            Main browser control panel
static/                   Browser assets
firmware/                 PlatformIO / Arduino Nano firmware
notes/                    UART and touch-panel notes
SAFETY.md                 Hardware and network safety notes
LICENSE                   0BSD license
```

## Requirements

- Python 3.10 or newer
- `pyserial`
- optional: `qrcode`
- PlatformIO, for firmware builds
- Arduino Nano compatible board

Known serial settings from the current code:

```text
USB serial:   115200 baud
chair UART:   9600 baud
Nano D10:     RX
Nano D11:     TX
```

Verify wiring and voltage levels on your own hardware.

## Run

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:8080/
```

Set the serial port if auto-detect chooses the wrong device:

```sh
python app.py --serial-port /dev/ttyACM0
```

Useful options:

```sh
python app.py --host 127.0.0.1 --port 8080 --serial-port /dev/ttyACM0
```

## Firmware

Build:

```sh
platformio run -d firmware
```

Upload:

```sh
platformio run -d firmware -t upload
```

Monitor:

```sh
platformio device monitor -d firmware -b 115200
```

The Makefile wraps the same commands:

```sh
make setup
make run
make fw
make upload
make monitor
```

## API

State:

```http
GET /api/state
```

Send a command:

```http
POST /api/command
Content-Type: application/json

{"command":"power"}
```

Command names are defined in both places:

```text
app.py
firmware/src/main.cpp
```

Keep them in sync. If they differ, fix that before testing hardware.

## Safety

Read `SAFETY.md` before connecting to hardware.

Do not expose this server to the public internet. Prefer `--host 127.0.0.1` unless you need LAN access.

## License

0BSD. Use it, modify it, ship it, fork it.
