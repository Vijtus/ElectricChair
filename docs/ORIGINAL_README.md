# Electric Chair Python Bridge

Run the web bridge with:

```bash
python3 app.py
```

Optional flags:

```bash
python3 app.py --host 0.0.0.0 --port 8080 --serial-port /dev/ttyACM0
```

What it does:

- serves the webpage and the reverse-engineered SVG display
- serves `ROOT-VIEW.html` on `/` and the verbose diagnostics view on `/debug`
- sends command names over USB serial to the firmware at `115200`
- enables firmware `listen on` mode automatically
- parses firmware `RX: 0x..` lines into 7-byte chair frames
- maintains a semantic UI state from the command list and protocol notes
- prefers live board frames for zone/level fallback when the protocol bytes are conclusive

The browser UI polls `GET /api/state` and posts commands to `POST /api/command`.
