# Security

This project exposes a local HTTP control surface for physical hardware.

- Prefer binding the bridge to `127.0.0.1` for local-only use.
- Use `--host 0.0.0.0` only on a trusted LAN.
- There is no authentication or authorization layer.
- Test chair movement and heating functions without a person seated first.
- Do not connect the Arduino to mains or high-voltage circuits.
- Verify UART voltage levels, ground reference, and isolation before connecting hardware.

Report security or safety issues privately to the project owner.
