# Contributing

Keep changes small and hardware-safe.

## Before changing behavior

1. Update both command maps if a command changes:
   - `app.py`
   - `electric_chair_firmware/src/main.cpp`
2. Document any protocol changes in `docs/massage-chair-uart-protocol-v1.txt`.
3. Test UI-only behavior before testing on live hardware.
4. Test live hardware without a person seated first.

## Checks

```bash
python -m py_compile app.py
cd electric_chair_firmware && platformio run
```
