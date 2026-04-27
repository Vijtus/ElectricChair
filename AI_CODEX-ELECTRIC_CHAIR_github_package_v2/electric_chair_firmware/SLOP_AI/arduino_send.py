from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set, Tuple

import tkinter as tk
from tkinter import font as tkfont

import serial
from serial.tools import list_ports


# -----------------------------------------------------------------------------
# Backend bridge
# -----------------------------------------------------------------------------

BAUD_RATE = 115200
RECONNECT_INTERVAL_SEC = 1.8
WRITE_INTERVAL_SEC = 0.06
WORKER_SLEEP_SEC = 0.02


@dataclass(frozen=True)
class ButtonSpec:
    label: str
    command: str
    width: int = 146


class SerialBridge:
    """Non-blocking serial bridge for the Arduino backend.

    The C++ side expects exact newline-delimited command strings such as
    "ramiona" or "predkosc_plus" and echoes status lines like
    "Queued: ramiona -> 0x13".
    """

    def __init__(self, baud_rate: int = BAUD_RATE):
        self.baud_rate = baud_rate
        self.handle: Optional[serial.Serial] = None
        self.connected = False
        self.port_name = "No device"

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._outbox: "queue.Queue[str]" = queue.Queue()
        self._events: "queue.Queue[Tuple[str, str]]" = queue.Queue()
        self._last_connect_attempt = 0.0
        self._last_write = 0.0
        self._rx_buffer = bytearray()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="SerialBridge")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._close()

    def send(self, command: str) -> None:
        self._outbox.put(command)

    def poll_events(self) -> List[Tuple[str, str]]:
        items: List[Tuple[str, str]] = []
        while True:
            try:
                items.append(self._events.get_nowait())
            except queue.Empty:
                return items

    def _emit(self, kind: str, payload: str) -> None:
        self._events.put((kind, payload))

    @staticmethod
    def _port_score(port) -> int:
        text = " ".join(
            filter(
                None,
                [
                    getattr(port, "device", ""),
                    getattr(port, "description", ""),
                    getattr(port, "manufacturer", ""),
                    getattr(port, "product", ""),
                    getattr(port, "hwid", ""),
                ],
            )
        ).lower()
        score = 0
        for token in (
            "arduino",
            "ch340",
            "cp210",
            "wch",
            "usb serial",
            "ttyacm",
            "ttyusb",
            "usb",
            "serial",
        ):
            if token in text:
                score += 1
        return score

    def _pick_port(self) -> Optional[str]:
        ports = list(list_ports.comports())
        if not ports:
            return None
        ports.sort(key=self._port_score, reverse=True)
        return ports[0].device

    def _connect(self) -> bool:
        now = time.time()
        if now - self._last_connect_attempt < RECONNECT_INTERVAL_SEC:
            return False
        self._last_connect_attempt = now

        port = self._pick_port()
        if not port:
            if self.port_name != "No serial device":
                self.port_name = "No serial device"
                self._emit("connection", self.port_name)
            self.connected = False
            return False

        try:
            handle = serial.Serial(port, self.baud_rate, timeout=0.02, write_timeout=0.2)
            time.sleep(1.1)  # allow Arduino reset after opening the port
            try:
                handle.reset_input_buffer()
                handle.reset_output_buffer()
            except Exception:
                pass
            self.handle = handle
            self.port_name = port
            self.connected = True
            self._rx_buffer.clear()
            self._emit("connection", f"Connected: {port}")
            return True
        except Exception as exc:
            self.handle = None
            self.connected = False
            self.port_name = f"Connect failed: {exc}"
            self._emit("error", self.port_name)
            return False

    def _close(self) -> None:
        handle = self.handle
        self.handle = None
        if handle:
            try:
                handle.close()
            except Exception:
                pass
        was_connected = self.connected
        self.connected = False
        if was_connected:
            self._emit("connection", "Disconnected")

    def _write_once(self) -> None:
        if not self.connected or not self.handle:
            return
        now = time.time()
        if now - self._last_write < WRITE_INTERVAL_SEC:
            return
        try:
            command = self._outbox.get_nowait()
        except queue.Empty:
            return

        try:
            self.handle.write((command.strip() + "\n").encode("utf-8"))
            self.handle.flush()
            self._last_write = now
            self._emit("sent", command)
        except Exception as exc:
            self._emit("error", f"Write failed: {exc}")
            self._outbox.put(command)
            self._close()

    def _read_available(self) -> None:
        if not self.connected or not self.handle:
            return
        try:
            waiting = getattr(self.handle, "in_waiting", 0)
            if waiting <= 0:
                return
            data = self.handle.read(waiting)
            if not data:
                return
            self._rx_buffer.extend(data)
            while b"\n" in self._rx_buffer:
                raw, _, remainder = self._rx_buffer.partition(b"\n")
                self._rx_buffer = bytearray(remainder)
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    self._emit("backend", line)
        except Exception as exc:
            self._emit("error", f"Read failed: {exc}")
            self._close()

    def _worker(self) -> None:
        while not self._stop.is_set():
            if not self.connected:
                self._connect()
            else:
                self._write_once()
                self._read_available()
            time.sleep(WORKER_SLEEP_SEC)


# -----------------------------------------------------------------------------
# Theme + layout
# -----------------------------------------------------------------------------

WIN_W = 1365
WIN_H = 768

BG = "#020304"
PANEL_BG = "#04070A"
CHROME = "#1D232B"
CHROME_SOFT = "#2A313A"
WHITE = "#F2F4F7"
TEXT = "#F5F7FA"
TEXT_SOFT = "#9AA6B3"
TEXT_MUTE = "#6A7682"
CYAN = "#21B6FF"
CYAN_SOFT = "#6FDDFF"
CYAN_DARK = "#0F2230"
GREEN = "#9CF34A"
ORANGE = "#FF8745"
ORANGE_SOFT = "#FFB077"
RED = "#FF6C45"
YELLOW = "#FFC658"
SCREEN_GRID = "#0B2030"
SCREEN_BG = "#010304"
SCREEN_EDGE = "#10161D"
SCREEN_BEZEL = "#242B33"
BTN_FILL = "#0D1015"
BTN_FILL_ACTIVE = "#121A22"
BTN_FILL_PRESS = "#182330"
BTN_FILL_DISABLED = "#111317"

FONT = "Segoe UI"

SCREEN_X = 212
SCREEN_Y = 58
SCREEN_W = 946
SCREEN_H = 550

LEFT_X = 22
RIGHT_X = 1198
TOP_Y = 54
BTN_H = 54
BTN_GAP = 14

POWER_X = 30
POWER_Y = 668
POWER_SIZE = 86
BOTTOM_Y1 = 654
BOTTOM_Y2 = 718

LEFT_BUTTONS = [
    ButtonSpec("Ramiona", "ramiona"),
    ButtonSpec("Przedramiona", "przedramiona"),
    ButtonSpec("Nogi", "nogi"),
    ButtonSpec("Siła nacisku +", "sila_nacisku_plus"),
    ButtonSpec("Siła nacisku -", "sila_nacisku_minus"),
    ButtonSpec("Masaż pośladków", "masaz_posladkow"),
]

RIGHT_BUTTONS = [
    ButtonSpec("Szyja", "szyja"),
    ButtonSpec("Do przodu / Do tyłu", "do_przodu_do_tylu_1"),
    ButtonSpec("Plecy i talia", "plecy_i_talia"),
    ButtonSpec("Do przodu / Do tyłu", "do_przodu_do_tylu_2"),
    ButtonSpec("Prędkość +", "predkosc_plus"),
    ButtonSpec("Prędkość -", "predkosc_minus"),
]

BOTTOM_ROW_1 = [
    (168, ButtonSpec("Masaż stóp", "masaz_stop", 132)),
    (320, ButtonSpec("Pauza", "pauza", 126)),
    (452, ButtonSpec("Czas", "czas", 126)),
    (586, ButtonSpec("Grawitacja Zero", "grawitacja_zero", 144)),
    (740, ButtonSpec("Oparcie w górę", "oparcie_w_gore", 156)),
]

BOTTOM_ROW_2 = [
    (168, ButtonSpec("Prędkość masażu\nstóp", "predkosc_masazu_stop", 132)),
    (320, ButtonSpec("Ogrzewanie", "ogrzewanie", 126)),
    (452, ButtonSpec("Masaż całego\nciała", "masaz_calego_ciala", 126)),
    (586, ButtonSpec("Tryb automatyczny", "tryb_automatyczny", 144)),
    (740, ButtonSpec("Oparcie w dół", "oparcie_w_dol", 156)),
]

ALL_ZONES = {
    "ramiona",
    "przedramiona",
    "nogi",
    "masaz_posladkow",
    "masaz_stop",
    "szyja",
    "plecy_i_talia",
}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def lerp(current: float, target: float, speed: float = 0.16) -> float:
    delta = target - current
    if abs(delta) < 0.015:
        return target
    return current + delta * speed


def mix(a: str, b: str, t: float) -> str:
    t = clamp(t, 0.0, 1.0)
    av = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    bv = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    rgb = [int(av[i] + (bv[i] - av[i]) * t) for i in range(3)]
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


# -----------------------------------------------------------------------------
# UI widgets
# -----------------------------------------------------------------------------


class NotchedButton(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        label: str,
        command_name: str,
        on_click: Callable[[str], None],
        width: int,
        height: int = BTN_H,
    ):
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=BG,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.label = label
        self.command_name = command_name
        self.on_click = on_click
        self.w = width
        self.h = height
        self.is_hover = False
        self.is_pressed = False
        self.is_active = False
        self.is_enabled = True
        self.flash_until = 0.0
        self.font = tkfont.Font(family=FONT, size=10 if width <= 132 else 11, weight="bold")

        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.redraw()

    def set_enabled(self, enabled: bool) -> None:
        self.is_enabled = enabled
        self.redraw()

    def set_active(self, active: bool) -> None:
        self.is_active = active
        self.redraw()

    def pulse(self) -> None:
        self.flash_until = time.time() + 0.20
        self.redraw()
        self.after(220, self.redraw)

    def _enter(self, _event) -> None:
        self.is_hover = True
        self.redraw()

    def _leave(self, _event) -> None:
        self.is_hover = False
        self.is_pressed = False
        self.redraw()

    def _press(self, _event) -> None:
        if not self.is_enabled:
            return
        self.is_pressed = True
        self.redraw()

    def _release(self, event) -> None:
        if not self.is_enabled:
            return
        inside = 0 <= event.x <= self.w and 0 <= event.y <= self.h
        was_pressed = self.is_pressed
        self.is_pressed = False
        self.redraw()
        if inside and was_pressed:
            self.on_click(self.command_name)

    def _shape(self, inset: int = 0) -> List[int]:
        left = 3 + inset
        right = self.w - 3 - inset
        top = 3 + inset
        bottom = self.h - 3 - inset
        cut = 8
        notch_w = 34
        notch_h = 7
        cx1 = (self.w - notch_w) / 2
        cx2 = (self.w + notch_w) / 2
        y1 = bottom - notch_h
        return [
            left + cut,
            top,
            right - cut,
            top,
            right,
            top + cut,
            right,
            y1,
            cx2 + 10,
            y1,
            cx2,
            bottom,
            cx1,
            bottom,
            cx1 - 10,
            y1,
            left,
            y1,
            left,
            top + cut,
        ]

    def redraw(self) -> None:
        self.delete("all")
        outline = WHITE
        fill = BTN_FILL
        text_color = TEXT
        accent = None

        if not self.is_enabled:
            outline = TEXT_MUTE
            fill = BTN_FILL_DISABLED
            text_color = TEXT_MUTE
        else:
            if self.is_active:
                outline = CYAN
                fill = BTN_FILL_ACTIVE
                accent = CYAN
            if self.is_hover and not self.is_pressed:
                fill = mix(fill, CYAN, 0.05)
            if self.is_pressed:
                outline = CYAN
                fill = BTN_FILL_PRESS
                accent = CYAN

        if time.time() < self.flash_until:
            outline = CYAN
            fill = mix(fill, CYAN, 0.11)
            accent = CYAN

        outer = self._shape(0)
        inner = self._shape(2)
        self.create_polygon(outer, fill=fill, outline=outline, width=2)
        self.create_polygon(inner, fill="", outline=mix(fill, WHITE, 0.10), width=1)
        if accent:
            self.create_line(16, 8, self.w - 16, 8, fill=accent, width=1)
        self.create_text(
            self.w / 2,
            self.h / 2 + (1 if self.is_pressed else 0),
            text=self.label,
            fill=text_color,
            font=self.font,
            justify="center",
            width=self.w - 18,
        )


class PowerButton(tk.Canvas):
    def __init__(self, parent: tk.Misc, callback: Callable[[str], None]):
        super().__init__(
            parent,
            width=POWER_SIZE,
            height=POWER_SIZE,
            bg=BG,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.callback = callback
        self.is_pressed = False
        self.is_on = True
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.redraw()

    def set_power(self, is_on: bool) -> None:
        self.is_on = is_on
        self.redraw()

    def _press(self, _event) -> None:
        self.is_pressed = True
        self.redraw()

    def _release(self, event) -> None:
        inside = 0 <= event.x <= POWER_SIZE and 0 <= event.y <= POWER_SIZE
        self.is_pressed = False
        self.redraw()
        if inside:
            self.callback("power")

    def redraw(self) -> None:
        self.delete("all")
        outer = "#FFB69C" if self.is_on else "#6A4A44"
        fill = RED if self.is_on else "#5A2E28"
        if self.is_pressed:
            fill = mix(fill, "#FFFFFF", 0.10)
        self.create_oval(8, 8, POWER_SIZE - 8, POWER_SIZE - 8, fill=fill, outline=outer, width=3)
        self.create_oval(16, 16, POWER_SIZE - 16, POWER_SIZE - 16, outline=mix(fill, WHITE, 0.16), width=1)
        self.create_text(POWER_SIZE / 2, POWER_SIZE / 2 - 1, text="⏻", fill="white", font=(FONT, 35, "bold"))


# -----------------------------------------------------------------------------
# Application
# -----------------------------------------------------------------------------


class MassageChairUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Massage Chair Interface")
        self.geometry(f"{WIN_W}x{WIN_H}")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.tk.call("tk", "scaling", 1.0)

        self.bridge = SerialBridge()
        self.command_buttons: Dict[str, NotchedButton] = {}

        self.state: Dict[str, object] = {
            "power_on": True,
            "auto_mode": True,
            "paused": False,
            "heat": True,
            "zero_gravity": False,
            "timer": 14,
            "speed": 4,
            "roller": 3,
            "intensity": 4,
            "foot_speed": 2,
            "zones": {"szyja", "plecy_i_talia", "masaz_posladkow"},
            "last_action": "System ready",
            "backend_line": "Waiting for backend",
            "port": "Searching for serial device...",
        }

        self.display = {
            "timer": 14.0,
            "speed": 4.0,
            "roller": 3.0,
            "intensity": 4.0,
        }
        self.connected = False
        self.toast_text = ""
        self.toast_until = 0.0
        self.send_flash_until = 0.0
        self.connection_pulse = 0.0

        self._build_layout()
        self._sync_button_states()
        self._redraw_screen()

        self.bridge.start()
        self.after(40, self._poll_bridge)
        self.after(16, self._animate)

        self.protocol("WM_DELETE_WINDOW", self._shutdown)
        self.bind("<Escape>", lambda _e: self._shutdown())

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        self.chrome = tk.Canvas(self, width=WIN_W, height=WIN_H, bg=BG, highlightthickness=0, bd=0)
        self.chrome.place(x=0, y=0)
        self._draw_frame()

        for idx, spec in enumerate(LEFT_BUTTONS):
            button = NotchedButton(self, label=spec.label, command_name=spec.command, on_click=self._handle_command, width=spec.width)
            button.place(x=LEFT_X, y=TOP_Y + idx * (BTN_H + BTN_GAP))
            self.command_buttons[spec.command] = button

        for idx, spec in enumerate(RIGHT_BUTTONS):
            button = NotchedButton(self, label=spec.label, command_name=spec.command, on_click=self._handle_command, width=spec.width)
            button.place(x=RIGHT_X, y=TOP_Y + idx * (BTN_H + BTN_GAP))
            self.command_buttons[spec.command] = button

        for x, spec in BOTTOM_ROW_1:
            button = NotchedButton(self, label=spec.label, command_name=spec.command, on_click=self._handle_command, width=spec.width)
            button.place(x=x, y=BOTTOM_Y1)
            self.command_buttons[spec.command] = button

        for x, spec in BOTTOM_ROW_2:
            button = NotchedButton(self, label=spec.label, command_name=spec.command, on_click=self._handle_command, width=spec.width)
            button.place(x=x, y=BOTTOM_Y2)
            self.command_buttons[spec.command] = button

        self.power_button = PowerButton(self, callback=self._handle_command)
        self.power_button.place(x=POWER_X, y=POWER_Y)

        self.screen = tk.Canvas(self, width=SCREEN_W, height=SCREEN_H, bg=SCREEN_BG, highlightthickness=0, bd=0)
        self.screen.place(x=SCREEN_X, y=SCREEN_Y)

    def _draw_frame(self) -> None:
        c = self.chrome
        c.create_rectangle(0, 0, WIN_W, WIN_H, fill=BG, outline="")
        c.create_rectangle(3, 3, WIN_W - 3, WIN_H - 3, outline=CHROME_SOFT, width=2)
        c.create_rectangle(10, 10, WIN_W - 10, WIN_H - 10, outline=CHROME, width=2)

        c.create_rectangle(SCREEN_X - 20, SCREEN_Y - 20, SCREEN_X + SCREEN_W + 20, SCREEN_Y + SCREEN_H + 20, fill=SCREEN_BEZEL, outline="")
        c.create_rectangle(SCREEN_X - 10, SCREEN_Y - 10, SCREEN_X + SCREEN_W + 10, SCREEN_Y + SCREEN_H + 10, fill=SCREEN_EDGE, outline="")
        c.create_rectangle(SCREEN_X - 3, SCREEN_Y - 3, SCREEN_X + SCREEN_W + 3, SCREEN_Y + SCREEN_H + 3, outline="#11171D", width=2)

        c.create_text(WIN_W / 2, 18, text="Massage Chair Interface", fill=TEXT_SOFT, font=(FONT, 12, "normal"))
        c.create_text(WIN_W / 2, 40, text="Massage Chair Control Panel", fill="#D6C8B8", font=(FONT, 12, "bold"))
        c.create_text(62, 638, text="POWER", fill=TEXT_SOFT, font=(FONT, 10, "bold"))

        self.badge_dot = c.create_oval(WIN_W - 112, 32, WIN_W - 100, 44, fill=RED, outline="")
        self.badge_text = c.create_text(WIN_W - 58, 38, text="OFFLINE", fill=RED, font=(FONT, 11, "bold"))

    # ------------------------------------------------------------------
    # Command handling
    # ------------------------------------------------------------------

    def _handle_command(self, command_name: str) -> None:
        if command_name != "power" and not self.state["power_on"]:
            self._show_toast("Chair is powered off")
            return

        self._apply_local_state(command_name)
        self._sync_button_states()
        self._redraw_screen()

        self.bridge.send(command_name)
        btn = self.command_buttons.get(command_name)
        if btn:
            btn.pulse()

    def _apply_local_state(self, command_name: str) -> None:
        zones = set(self.state["zones"])

        if command_name == "power":
            self.state["power_on"] = not bool(self.state["power_on"])
            self.state["last_action"] = "Power on" if self.state["power_on"] else "Power off"
            self.power_button.set_power(bool(self.state["power_on"]))
            if not self.state["power_on"]:
                self.state["paused"] = False
            self._show_toast(str(self.state["last_action"]))
            return

        if command_name == "pauza":
            self.state["paused"] = not bool(self.state["paused"])
            self.state["last_action"] = "Paused" if self.state["paused"] else "Resumed"
        elif command_name == "tryb_automatyczny":
            self.state["auto_mode"] = not bool(self.state["auto_mode"])
            self.state["last_action"] = "Auto mode" if self.state["auto_mode"] else "Manual mode"
        elif command_name == "ogrzewanie":
            self.state["heat"] = not bool(self.state["heat"])
            self.state["last_action"] = "Heat on" if self.state["heat"] else "Heat off"
        elif command_name == "grawitacja_zero":
            self.state["zero_gravity"] = not bool(self.state["zero_gravity"])
            self.state["last_action"] = "Zero gravity on" if self.state["zero_gravity"] else "Zero gravity off"
        elif command_name == "czas":
            value = int(self.state["timer"]) + 5
            self.state["timer"] = 5 if value > 30 else value
            self.state["last_action"] = f"Timer {self.state['timer']} min"
        elif command_name == "predkosc_plus":
            self.state["speed"] = min(5, int(self.state["speed"]) + 1)
            self.state["last_action"] = f"Speed {self.state['speed']}"
        elif command_name == "predkosc_minus":
            self.state["speed"] = max(1, int(self.state["speed"]) - 1)
            self.state["last_action"] = f"Speed {self.state['speed']}"
        elif command_name == "sila_nacisku_plus":
            self.state["intensity"] = min(5, int(self.state["intensity"]) + 1)
            self.state["last_action"] = f"Intensity {self.state['intensity']}"
        elif command_name == "sila_nacisku_minus":
            self.state["intensity"] = max(1, int(self.state["intensity"]) - 1)
            self.state["last_action"] = f"Intensity {self.state['intensity']}"
        elif command_name == "do_przodu_do_tylu_1":
            self.state["roller"] = min(5, int(self.state["roller"]) + 1)
            self.state["last_action"] = f"Roller {self.state['roller']}"
        elif command_name == "do_przodu_do_tylu_2":
            self.state["roller"] = max(1, int(self.state["roller"]) - 1)
            self.state["last_action"] = f"Roller {self.state['roller']}"
        elif command_name == "predkosc_masazu_stop":
            # backend offers a single command; cycle locally for feedback only
            step = int(self.state["speed"]) + 1
            self.state["speed"] = 1 if step > 5 else step
            self.state["last_action"] = f"Foot speed {self.state['speed']}"
        elif command_name == "masaz_calego_ciala":
            zones = set(ALL_ZONES)
            self.state["last_action"] = "Full body massage"
        elif command_name in ALL_ZONES:
            if command_name in zones:
                zones.remove(command_name)
            else:
                zones.add(command_name)
            pretty = command_name.replace("_", " ")
            self.state["last_action"] = f"Zone {pretty}"

        self.state["zones"] = zones
        self._show_toast(str(self.state["last_action"]))

    def _sync_button_states(self) -> None:
        powered = bool(self.state["power_on"])
        active = set(self.state["zones"])
        if self.state["paused"]:
            active.add("pauza")
        if self.state["heat"]:
            active.add("ogrzewanie")
        if self.state["zero_gravity"]:
            active.add("grawitacja_zero")
        if self.state["auto_mode"]:
            active.add("tryb_automatyczny")
        if set(self.state["zones"]) == ALL_ZONES:
            active.add("masaz_calego_ciala")

        self.power_button.set_power(powered)
        for name, button in self.command_buttons.items():
            button.set_enabled(powered)
            button.set_active(name in active)

    # ------------------------------------------------------------------
    # Serial polling + animation
    # ------------------------------------------------------------------

    def _poll_bridge(self) -> None:
        for kind, message in self.bridge.poll_events():
            if kind == "connection":
                self.connected = message.startswith("Connected:")
                self.state["port"] = message
                self._show_toast(message)
            elif kind == "sent":
                self.send_flash_until = time.time() + 0.18
            elif kind == "backend":
                self.state["backend_line"] = message
                if message.startswith("Queued:"):
                    self._show_toast(message)
                elif message.startswith("Unknown command"):
                    self._show_toast(message)
            elif kind == "error":
                self.connected = False
                self.state["port"] = message
                self._show_toast(message)
            self._redraw_screen()
        self.after(40, self._poll_bridge)

    def _animate(self) -> None:
        dirty = False
        self.connection_pulse += 0.08

        for key in ("timer", "speed", "roller", "intensity"):
            target = float(self.state[key])
            current = float(self.display[key])
            new_value = lerp(current, target, 0.18)
            if new_value != current:
                self.display[key] = new_value
                dirty = True

        if self.toast_text and time.time() > self.toast_until:
            self.toast_text = ""
            dirty = True

        if dirty:
            self._redraw_screen()
        self.after(16, self._animate)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _redraw_screen(self) -> None:
        s = self.screen
        s.delete("all")
        s.create_rectangle(0, 0, SCREEN_W, SCREEN_H, fill=SCREEN_BG, outline="")

        for x in range(0, SCREEN_W, 40):
            s.create_line(x, 0, x, SCREEN_H, fill=SCREEN_GRID, width=1)
        for y in range(0, SCREEN_H, 40):
            s.create_line(0, y, SCREEN_W, y, fill=SCREEN_GRID, width=1)

        self._draw_top_bars()
        self._draw_mode_block()
        self._draw_timer()
        self._draw_chair_figure()
        self._draw_icons()
        self._draw_heat_block()
        self._draw_status_lines()
        self._draw_toast()

        if not self.state["power_on"]:
            s.create_rectangle(0, 0, SCREEN_W, SCREEN_H, fill="#000000", stipple="gray50", outline="")
            s.create_text(SCREEN_W / 2, SCREEN_H / 2, text="POWER OFF", fill=TEXT_SOFT, font=(FONT, 28, "bold"))

        pulse = (math.sin(self.connection_pulse) + 1.0) / 2.0
        dot_color = mix("#5D2320", GREEN if self.connected else RED, 0.35 + 0.65 * pulse)
        self.chrome.itemconfig(self.badge_dot, fill=dot_color)
        self.chrome.itemconfig(self.badge_text, text="ONLINE" if self.connected else "OFFLINE", fill=GREEN if self.connected else RED)

    def _draw_top_bars(self) -> None:
        self._draw_meter(164, 26, "SPEED", float(self.display["speed"]), 5)
        self._draw_meter(524, 26, "ROLLER", float(self.display["roller"]), 5)
        self._draw_meter(524, 88, "INTENSITY", float(self.display["intensity"]), 5)

    def _draw_meter(self, x: int, y: int, label: str, value: float, segments: int) -> None:
        s = self.screen
        s.create_text(x, y, anchor="w", text=label, fill=CYAN, font=(FONT, 20, "bold"))
        s.create_line(x - 8, y + 14, x + 176, y + 14, fill=CYAN, width=2)
        s.create_line(x + 188, y + 14, x + 296, y + 14, fill=CYAN, width=2)
        s.create_line(x - 8, y + 14, x - 8, y - 10, fill=CYAN, width=2)
        s.create_line(x + 296, y + 14, x + 296, y - 10, fill=CYAN, width=2)

        lit = int(round(clamp(value, 0, segments)))
        for i in range(segments):
            color = GREEN if i < 2 else CYAN
            if i >= 3:
                color = ORANGE
            fill = color if i < lit else CYAN_DARK
            x1 = x + 176 + i * 28
            s.create_rectangle(x1, y - 16, x1 + 20, y + 8, fill=fill, outline="")

    def _draw_mode_block(self) -> None:
        s = self.screen
        s.create_rectangle(28, 32, 98, 48, fill="#124BFF", outline="")
        s.create_text(20, 82, anchor="w", text="AUTO" if self.state["auto_mode"] else "MANUAL", fill=CYAN, font=(FONT, 26, "bold"))
        s.create_text(52, 130, text="♨", fill=CYAN_SOFT, font=(FONT, 30, "bold"))
        s.create_text(54, 176, text="A" if self.state["auto_mode"] else "M", fill=CYAN, font=(FONT, 36, "bold"))

    def _draw_timer(self) -> None:
        s = self.screen
        timer_val = int(round(self.display["timer"]))
        s.create_text(154, 228, anchor="w", text=f"{timer_val:02d}", fill=CYAN, font=(FONT, 60, "bold"))
        s.create_text(286, 214, anchor="w", text="TIME", fill=CYAN, font=(FONT, 26, "bold"))

    def _draw_chair_figure(self) -> None:
        s = self.screen
        bx = 430
        by = 204

        chair_points = [
            bx - 44,
            by + 252,
            bx + 10,
            by + 206,
            bx + 72,
            by + 154,
            bx + 132,
            by + 104,
            bx + 166,
            by + 60,
            bx + 192,
            by + 18,
            bx + 212,
            by - 4,
            bx + 228,
            by + 6,
            bx + 238,
            by + 30,
            bx + 248,
            by + 62,
            bx + 252,
            by + 96,
            bx + 252,
            by + 166,
            bx + 244,
            by + 198,
            bx + 226,
            by + 214,
            bx + 180,
            by + 222,
            bx + 120,
            by + 224,
            bx + 48,
            by + 246,
            bx - 18,
            by + 258,
        ]
        s.create_line(*chair_points, fill=CYAN, width=4, smooth=True)

        # Person / silhouette
        s.create_oval(bx + 154, by - 54, bx + 220, by + 12, outline=CYAN, width=4)
        s.create_line(bx + 186, by + 10, bx + 206, by + 118, fill=CYAN, width=4, smooth=True)
        s.create_line(bx + 158, by + 42, bx + 118, by + 92, fill=CYAN, width=4, smooth=True)
        s.create_line(bx + 112, by + 88, bx + 164, by + 148, fill=CYAN, width=4, smooth=True)
        s.create_line(bx + 120, by + 110, bx + 32, by + 132, bx - 26, by + 186, fill=CYAN, width=4, smooth=True)
        s.create_line(bx - 20, by + 186, bx - 70, by + 224, fill=CYAN, width=4, smooth=True)
        s.create_line(bx + 180, by + 30, bx + 176, by + 102, fill=CYAN, width=4, smooth=True)

        # Blue detail dashes
        dash = CYAN_SOFT
        s.create_line(bx + 160, by + 56, bx + 130, by + 92, fill=dash, width=3)
        s.create_line(bx + 154, by + 108, bx + 170, by + 132, fill=dash, width=3)
        s.create_line(bx + 118, by + 124, bx + 114, by + 160, fill=dash, width=3)
        s.create_line(bx + 82, by + 140, bx + 66, by + 164, fill=dash, width=3)
        s.create_line(bx + 22, by + 178, bx - 20, by + 212, fill=dash, width=3)
        s.create_line(bx - 44, by + 224, bx - 74, by + 246, fill=dash, width=3)

        zones: Set[str] = set(self.state["zones"])

        def node(x: int, y: int, active: bool) -> None:
            fill = ORANGE if active else "#26140D"
            outline = ORANGE_SOFT if active else "#3E2419"
            s.create_oval(x - 11, y - 11, x + 11, y + 11, fill=fill, outline=outline, width=2)
            s.create_line(x - 5, y, x + 5, y, fill=ORANGE_SOFT if active else outline, width=2)
            s.create_line(x, y - 5, x, y + 5, fill=ORANGE_SOFT if active else outline, width=2)

        node(bx + 252, by + 22, "szyja" in zones)
        node(bx + 252, by + 60, "ramiona" in zones)
        node(bx + 252, by + 148, "plecy_i_talia" in zones)
        node(bx + 252, by + 182, "masaz_posladkow" in zones)
        node(bx + 196, by + 230, "przedramiona" in zones)
        node(bx + 228, by + 230, "nogi" in zones)
        node(bx - 76, by + 260, "masaz_stop" in zones)
        node(bx - 52, by + 260, "masaz_stop" in zones)

    def _draw_icons(self) -> None:
        s = self.screen
        color = CYAN_SOFT
        # top icons
        s.create_arc(824, 96, 854, 132, start=60, extent=240, style="arc", outline=color, width=3)
        s.create_line(838, 108, 829, 119, 837, 133, fill=color, width=3, smooth=True)
        s.create_arc(880, 96, 910, 132, start=-120, extent=240, style="arc", outline=color, width=3)
        s.create_line(896, 108, 905, 119, 897, 133, fill=color, width=3, smooth=True)
        # lower icons
        s.create_arc(812, 362, 842, 398, start=-40, extent=170, style="arc", outline=color, width=3)
        s.create_line(820, 378, 834, 370, 842, 389, fill=color, width=3, smooth=True)
        s.create_arc(874, 362, 904, 398, start=50, extent=170, style="arc", outline=color, width=3)
        s.create_line(898, 378, 884, 370, 876, 389, fill=color, width=3, smooth=True)

    def _draw_heat_block(self) -> None:
        s = self.screen
        active = bool(self.state["heat"])
        outline = ORANGE_SOFT if active else "#483028"
        fill = ORANGE if active else "#24140E"
        cx, cy = 278, 476
        s.create_oval(cx - 14, cy - 14, cx + 14, cy + 14, outline=outline, width=3)
        s.create_line(cx, cy - 26, cx, cy - 8, fill=outline, width=3)
        s.create_line(cx - 6, cy - 28, cx - 6, cy - 38, fill=outline, width=2)
        s.create_line(cx, cy - 30, cx, cy - 40, fill=outline, width=2)
        s.create_line(cx + 6, cy - 28, cx + 6, cy - 38, fill=outline, width=2)

        s.create_text(328, 476, anchor="w", text="HEAT", fill=CYAN, font=(FONT, 22, "bold"))
        s.create_line(226, 506, 426, 506, fill=CYAN, width=2)
        s.create_line(226, 506, 226, 478, fill=CYAN, width=2)
        s.create_line(426, 506, 426, 478, fill=CYAN, width=2)
        s.create_rectangle(238, 462, 252, 478, fill=fill, outline="")
        s.create_rectangle(256, 462, 270, 478, fill=fill, outline="")

    def _draw_status_lines(self) -> None:
        s = self.screen
        backend = str(self.state["backend_line"])
        port = str(self.state["port"])
        action = str(self.state["last_action"])

        message_color = CYAN_SOFT if time.time() < self.send_flash_until else TEXT_SOFT
        s.create_text(18, SCREEN_H - 42, anchor="w", text=backend if backend else action, fill=message_color, font=(FONT, 11, "bold"))
        s.create_text(18, SCREEN_H - 22, anchor="w", text=port, fill=TEXT_MUTE, font=(FONT, 10, "normal"))

        if self.state["paused"]:
            s.create_text(SCREEN_W - 24, SCREEN_H - 40, anchor="e", text="PAUSED", fill=YELLOW, font=(FONT, 13, "bold"))
        elif self.connected:
            s.create_text(SCREEN_W - 24, SCREEN_H - 40, anchor="e", text="LIVE", fill=GREEN, font=(FONT, 13, "bold"))

    def _draw_toast(self) -> None:
        if not self.toast_text:
            return
        s = self.screen
        w = min(540, 26 + len(self.toast_text) * 7)
        x1 = (SCREEN_W - w) / 2
        x2 = x1 + w
        y1 = SCREEN_H - 88
        y2 = SCREEN_H - 50
        s.create_rectangle(x1, y1, x2, y2, fill="#08131B", outline=CYAN, width=2)
        s.create_text(SCREEN_W / 2, (y1 + y2) / 2, text=self.toast_text, fill=TEXT, font=(FONT, 10, "bold"))

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _show_toast(self, text: str) -> None:
        self.toast_text = text
        self.toast_until = time.time() + 2.2

    def _shutdown(self) -> None:
        self.bridge.stop()
        self.destroy()


if __name__ == "__main__":
    app = MassageChairUI()
    app.mainloop()
