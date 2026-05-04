# Safety

This bridge drives a real massage chair with motors, recliner actuators, and AC-mains heaters. Do not run it unattended.

## Operating Rules

- Do not auto-deploy this repository or push a branch to an environment that auto-deploys.
- Do not assume the chair is unplugged.
- Do not change command bytes, frame offsets, or zone masks without a captured UART log or explicit approval.
- Keep the chair's 33-byte UART status frame as the only source of truth. Python is a cache; the browser is a view.
- The "diode check" is the UART status frame, not GPIO reads.
- Do not replace the single-byte USB listen controls with whole-line controls unless live serial capture proves the replacement survives SoftwareSerial listening.

## Binding And LAN

The bridge now binds to `0.0.0.0` by default so the panel is reachable from
other devices on the same trusted LAN. Startup prints the selected LAN URL and
QR code; it should not print `0.0.0.0` as the address to open.

Use local-only mode for developer work that should not be reachable from other
devices:

```bash
python3 app.py --local
```

Run default LAN mode only on a trusted local network with the chair supervised.

## Failed vs Unverified

Each command gets a sequence number. Firmware reports `ACK` when it starts holding the byte and `DONE` after the post-press gap.

If the chair frame does not confirm the optimistic model immediately after `DONE`, the bridge waits a bounded 2.5 s verification-settle window because the chair frame can lag the emitted byte. After settle the bridge reaches one of three terminal states:

1. **Completed.** Confirmed frame fields agree with the optimistic values. Mute clears, button keeps its new state, no chip.
2. **Failed.** Confirmed frame fields disagree. The bridge:
    - records `state.last_error`
    - appends to `state.failed_commands`
    - clears the optimistic mute
    - surrenders the model back to the current chair frame
    - flashes the failed button red briefly
3. **Unverified.** None of the command's muted fields have a confirmed frame mapping yet, so the chair frame cannot prove agreement or disagreement. The bridge:
    - appends to `state.unverified_commands`
    - clears the optimistic mute
    - surfaces a neutral chip in the UI
    - does NOT flash the button red, does NOT set `state.last_error`, does NOT auto-resend

Unverified is the honest "the chair never confirmed and we couldn't tell either way" state. It exists so press-with-no-mapping does not paint the UI red on a press that may have actually worked. As `developer/bench-runs/` fills in with isolated capture results, fields move from unmapped to confirmed and the unverified path stops applying to those commands.

Automatic retry is reserved for future commands explicitly proven to be idempotent set-state actions, one at a time, each backed by hardware evidence in `developer/bench-runs/`.

Some buttons are frame-observed because live captures proved the old optimistic toggle model was wrong. For those, the bridge sends the button press and waits for the chair frame to update the view instead of displaying a guessed target state.

## Two-Agent Operations

When two AI agents (Codex on hardware, Claude on code review) operate the repo together, they coordinate through `COORDINATION/`:

- `COORDINATION/log.md` — append-only timeline of every agent action.
- `COORDINATION/locks/` — one file per locked resource (serial-port, app-py-runtime, firmware-build, python-modules, audit-md, bench-runs).
- `COORDINATION/handoff/` — one file per cross-agent handoff.
- `COORDINATION/STOP` — kill switch the user creates to stop all agents.

Both agents pre-flight every turn: read the last 50 lines of log.md, check the lock directory, and append a log entry before acting. Default lanes: Codex owns hardware (firmware flash, serial port, bench captures, app.py runtime); Claude owns code review, Python logic that does not require hardware to validate, audit, ARCHITECTURE/SAFETY/README, and frame analysis. Either agent may step into the other's lane with a lock and a log entry.

When only one agent is active, the protocol still applies but locks are formality.
