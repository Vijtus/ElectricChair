# AI CODEX Electric Chair

Web buttons for a massage chair.

It is not smart.
It is not safe by magic.
It sends bytes.
The chair moves.

Read the code.

## tree

```text
app.py          web server + serial bridge
ROOT-VIEW.html  main panel
static/         css + js + small pages
firmware/       Arduino Nano / PlatformIO code
notes/          protocol notes from testing
SAFETY          read this before hardware
LICENSE         0BSD. very open.
```

## run

```sh
make setup
make run
```

Open:

```text
http://127.0.0.1:8080/
```

Pick a port when auto-detect is wrong:

```sh
python app.py --serial-port /dev/ttyACM0
```

## firmware

```sh
make fw
make upload
make monitor
```

Known wiring from the code:

```text
USB serial  115200
chair UART  9600
Nano D10    RX
Nano D11    TX
```

Check it yourself.
Old notes lie.
Hands near motors teach faster.

## commands

Command names live in two places:

```text
app.py
firmware/src/main.cpp
```

If they disagree, stop.
Fix that first.

## old web rules

No framework for five buttons.
No build step for plain HTML.
No clever state you cannot draw on paper.
No mystery dependency.
No fake safety.
No big README to hide small code.

Use less.
Name things plainly.
Leave sharp edges visible.

## open source

License is `0BSD`.

No CLA.
No permission ritual.
Fork it.
Cut it down.
Sell it.
Break it.
Fix it.
Send patches or do not.

Think for yourself.
