from __future__ import annotations

import argparse
import json
import os
import queue
import re
import socket
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import serial
from serial.tools import list_ports

try:
    import qrcode  # type: ignore
    import qrcode.image.svg  # type: ignore
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
SVG_PATH = ROOT / "massage_display_interface.svg"
ROOT_VIEW_PATH = ROOT / "ROOT-VIEW.html"
FIRMWARE_DEFAULT_BAUD = 115200
RECONNECT_INTERVAL = 1.5
SERIAL_LOOP_SLEEP = 0.02
WRITE_INTERVAL = 0.06
LISTEN_RETRY_SECONDS = 1.8
CONNECT_SETTLE_SECONDS = 4.0
SERIAL_CHAR_DELAY = 0.008
STARTUP_DRAIN_SECONDS = 0.8
# Live hardware treats repeated identical UART codes as repeated presses,
# so a browser click must map to a single command by default.
PRESS_REPEAT = 1
PROMPT_SECONDS = 1.0
OVERLAY_SECONDS = 0.9
POWER_OFF_TEXT_SECONDS = 1.4
STATE_POLL_HINT_MS = 350
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
FULL_FRAME_LENGTH = 33


@dataclass(frozen=True)
class CommandDef:
    key: str
    code: int
    label: str
    group: str


COMMANDS = [
    CommandDef("power", 0x01, "Power", "system"),
    CommandDef("predkosc_masazu_stop", 0x02, "Prędkość masażu stóp", "scalar"),
    CommandDef("ogrzewanie", 0x03, "Ogrzewanie", "toggle"),
    CommandDef("masaz_calego_ciala", 0x04, "Masaż całego ciała", "toggle"),
    CommandDef("tryb_automatyczny", 0x05, "Tryb automatyczny", "mode"),
    CommandDef("oparcie_w_dol", 0x06, "Oparcie w dół", "momentary"),
    CommandDef("czas", 0x07, "Czas", "scalar"),
    CommandDef("grawitacja_zero", 0x08, "Grawitacja zero", "momentary"),
    CommandDef("oparcie_w_gore", 0x09, "Oparcie w górę", "momentary"),
    CommandDef("pauza", 0x0B, "Pauza", "toggle"),
    CommandDef("masaz_stop", 0x0D, "Masaż stóp", "toggle"),
    CommandDef("masaz_posladkow", 0x0E, "Masaż pośladków", "toggle"),
    CommandDef("sila_nacisku_minus", 0x0F, "Siła nacisku -", "scalar"),
    CommandDef("sila_nacisku_plus", 0x10, "Siła nacisku +", "scalar"),
    CommandDef("nogi", 0x11, "Nogi", "toggle"),
    CommandDef("przedramiona", 0x12, "Przedramiona", "toggle"),
    CommandDef("ramiona", 0x13, "Ramiona", "toggle"),
    CommandDef("predkosc_minus", 0x14, "Prędkość -", "scalar"),
    CommandDef("predkosc_plus", 0x15, "Prędkość +", "scalar"),
    CommandDef("do_przodu_do_tylu_1", 0x16, "Do przodu / Do tyłu 1", "momentary"),
    CommandDef("plecy_i_talia", 0x17, "Plecy i talia", "toggle"),
    CommandDef("do_przodu_do_tylu_2", 0x18, "Do przodu / Do tyłu 2", "momentary"),
    CommandDef("szyja", 0x19, "Szyja", "toggle"),
]
COMMAND_INDEX = {command.key: command for command in COMMANDS}
BUTTON_ORDER = [command.key for command in COMMANDS]
AUTO_DEAD_COMMANDS = {"do_przodu_do_tylu_2"}
TIME_OPTIONS_MINUTES = [15, 20, 25, 30]
MOMENTARY_COMMANDS = {
    "sila_nacisku_plus",
    "sila_nacisku_minus",
    "predkosc_plus",
    "predkosc_minus",
    "do_przodu_do_tylu_1",
    "do_przodu_do_tylu_2",
    "grawitacja_zero",
    "oparcie_w_gore",
    "oparcie_w_dol",
}
AUTO_PROFILE_SEQUENCE = ["B", "C", "D", "A"]
FRAME_BYTE_RE = re.compile(r"RX:\s+0x([0-9A-Fa-f]{2})")


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def monotonic_deadline(seconds: float) -> float:
    return time.monotonic() + seconds


def load_svg_markup(path: Path) -> str:
    tree = ET.parse(path)
    root = tree.getroot()
    for element in root.iter():
        label = element.attrib.get(f"{{{INKSCAPE_NS}}}label")
        if label:
            element.set("data-layer", label)
    return ET.tostring(root, encoding="unicode")


class ChairState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.command_history: list[dict[str, Any]] = []
        self.backend_log: list[str] = []
        self.rx_bytes: list[int] = []
        self.last_command: str | None = None
        self.last_error: str | None = None
        self.connected = False
        self.port_name = "Disconnected"
        self.listening = False
        self.board_ready = False
        self.raw_frame: list[int] | None = None
        self.frame_seen_at: float | None = None
        self.frame_signature = "unknown"
        self.bytes_3_to_6 = [0, 0, 0, 0]
        self.full_frame_tail = []
        self.power_on = False
        self.mode = "off"
        self.auto_profile: str | None = None
        self.auto_profile_variant: str | None = None
        self.timer_minutes = 15
        self.remaining_seconds = 15 * 60
        self.last_tick = time.monotonic()
        self._elapsed_accumulator = 0.0
        self.paused = False
        self.intensity_level = 2
        self.speed_level = 2
        self.foot_speed_level = 2
        self.heat_on = False
        self.shoulders_on = False
        self.forearms_on = False
        self.legs_on = False
        self.buttocks_on = False
        self.foot_massage_on = False
        self.neck_on = False
        self.back_waist_on = False
        self.full_body_on = False
        self.flash_command_until: dict[str, float] = {}
        self.check_until = 0.0
        self.mask_until = 0.0
        self.power_off_text_until = 0.0
        self.power_off_started_at = 0.0
        self.prompt_text = ""
        self.prompt_until = 0.0
        self.back_forward_cycle_1 = 0
        self.back_forward_cycle_2 = 0

    def _tick_locked(self) -> None:
        now = time.monotonic()
        if self.power_on and not self.paused and self.remaining_seconds > 0:
            elapsed = now - self.last_tick
            if elapsed > 0:
                self._elapsed_accumulator += elapsed
                if self._elapsed_accumulator >= 1.0:
                    whole_seconds = int(self._elapsed_accumulator)
                    self.remaining_seconds = max(0, self.remaining_seconds - whole_seconds)
                    self._elapsed_accumulator -= whole_seconds
        self.last_tick = now

    def _remember_log_locked(self, line: str) -> None:
        self.backend_log.append(line)
        if len(self.backend_log) > 20:
            self.backend_log = self.backend_log[-20:]

    def _remember_command_locked(self, command: str) -> None:
        self.command_history.append(
            {
                "command": command,
                "label": COMMAND_INDEX[command].label,
                "at": time.time(),
            }
        )
        if len(self.command_history) > 20:
            self.command_history = self.command_history[-20:]

    def set_connection(self, connected: bool, port_name: str) -> None:
        with self.lock:
            self.connected = connected
            self.port_name = port_name
            if not connected:
                self.listening = False
                self.board_ready = False

    def note_error(self, message: str) -> None:
        with self.lock:
            self.last_error = message
            self._remember_log_locked(f"error: {message}")

    def note_backend_line(self, line: str) -> None:
        with self.lock:
            self._remember_log_locked(line)
            if "Chair read: ON" in line:
                self.listening = True
            elif "Chair read: OFF" in line:
                self.listening = False
            if line.startswith("Ready.") or line.startswith("Controls:"):
                self.board_ready = True

    def note_backend_rx_value(self, value: int) -> None:
        with self.lock:
            self._note_rx_byte_locked(value)

    def _note_rx_byte_locked(self, value: int) -> None:
            if value == 0xAA:
                self.rx_bytes = [value]
                return

            if not self.rx_bytes:
                return

            self.rx_bytes.append(value)
            if len(self.rx_bytes) == 2 and self.rx_bytes[:2] == [0xAA, 0x55]:
                return

            if len(self.rx_bytes) < FULL_FRAME_LENGTH:
                return

            if len(self.rx_bytes) > FULL_FRAME_LENGTH:
                self.rx_bytes = self.rx_bytes[-FULL_FRAME_LENGTH:]

            if self.rx_bytes[:2] == [0xAA, 0x55]:
                candidate = self.rx_bytes[:]
                if candidate[-4:] == [0x00, 0x00, 0x00, 0x00]:
                    self.raw_frame = candidate
                    self.frame_seen_at = time.time()
                    self.bytes_3_to_6 = self._extract_matrix_bytes_locked()
                    self.full_frame_tail = self.raw_frame[17:29]
                    self.frame_signature = self._describe_frame_signature_locked()
                    self._sync_from_frame_locked()
                    self.rx_bytes = []
                    return

                try:
                    next_start = candidate[1:].index(0xAA) + 1
                    self.rx_bytes = candidate[next_start:]
                except ValueError:
                    self.rx_bytes = []
                return
            self.rx_bytes = []

    def _extract_matrix_bytes_locked(self) -> list[int]:
        if not self.raw_frame or len(self.raw_frame) < FULL_FRAME_LENGTH:
            return [0, 0, 0, 0]
        # The 7-byte reverse-engineering bytes b3..b6 map onto the full
        # 33-byte frame at positions 3, 4, 11, 12.
        # Verified against live UART: pos 11,12 carry stable zone info
        # matching the original protocol doc, while pos 5,6 vary independently.
        return [
            self.raw_frame[3],
            self.raw_frame[4],
            self.raw_frame[11],
            self.raw_frame[12],
        ]

    def _describe_frame_signature_locked(self) -> str:
        b3, b4, b5, b6 = self.bytes_3_to_6
        tail = tuple(self.full_frame_tail[:4]) if self.full_frame_tail else ()
        if [b3, b4, b5, b6] == [0x00, 0x00, 0x00, 0x00]:
            return "all-zero"
        # Auto profile signatures — verified against live UART 2026-04-13.
        # All auto profiles share b3..b6 = 04 02 0C 0F; tail[17:21] differentiates.
        if [b3, b4, b5, b6] == [0x04, 0x02, 0x0C, 0x0F] and tail == (0x0A, 0x0B, 0x0C, 0x08):
            return "auto-program-a"
        if [b3, b4, b5, b6] == [0x04, 0x02, 0x0C, 0x0F] and tail == (0x04, 0x0D, 0x06, 0x00):
            return "auto-program-b"
        if [b3, b4, b5, b6] == [0x04, 0x02, 0x0C, 0x0F] and tail == (0x04, 0x09, 0x0E, 0x00):
            return "auto-program-c"
        if [b3, b4, b5, b6] == [0x04, 0x02, 0x0C, 0x0F] and tail == (0x04, 0x02, 0x0E, 0x00):
            return "auto-program-d"
        if [b3, b4, b5, b6] == [0x04, 0x02, 0x0C, 0x0F] and tail == (0x04, 0x00, 0x0A, 0x00):
            return "auto-program-a-cycled"
        # Manual mode signatures
        if [b3, b4, b5, b6] == [0x00, 0x0E, 0x0C, 0x0F]:
            return "manual-neck"
        if [b3, b4, b5, b6] == [0x04, 0x0E, 0x0C, 0x0F]:
            return "manual-neck-back"
        if [b3, b4, b5, b6] == [0x04, 0x0C, 0x0C, 0x0F]:
            return "manual-back"
        # Running signatures (auto or manual with intensity variation)
        if [b3, b4, b5, b6] == [0x04, 0x02, 0x0F, 0x0F]:
            return "intensity-up-signature"
        if [b3, b4, b5, b6] == [0x04, 0x02, 0x0C, 0x0F]:
            return "shared-running-signature"
        if b4 == 0x0E:
            return "neck-signature"
        if b4 == 0x0C:
            return "back-waist-signature"
        return f"b3={b3:02X} b4={b4:02X} b5={b5:02X} b6={b6:02X}"

    def _running_signature_locked(self) -> bool:
        return self.power_on and self.mode != "off"

    def _show_intensity_ui_locked(self) -> bool:
        return self._running_signature_locked() and (
            self.shoulders_on or self.forearms_on or self.legs_on
        )

    def _show_speed_ui_locked(self) -> bool:
        return self._running_signature_locked() and (
            self.neck_on or self.back_waist_on
        )

    def _can_adjust_foot_speed_locked(self) -> bool:
        return self._running_signature_locked() and self.foot_massage_on

    def _show_foot_speed_ui_locked(self) -> bool:
        return self._can_adjust_foot_speed_locked() and not (
            self.mode == "auto" and self.auto_profile == "C"
        )

    def _clear_zones_locked(self) -> None:
        self.shoulders_on = False
        self.forearms_on = False
        self.legs_on = False
        self.buttocks_on = False
        self.foot_massage_on = False
        self.heat_on = False
        self.neck_on = False
        self.back_waist_on = False
        self.full_body_on = False

    def _switch_to_manual_zone_locked(self, zone_key: str) -> None:
        self.mode = "manual"
        self.auto_profile = None
        self.auto_profile_variant = None
        self.paused = False
        self.check_until = 0.0
        self.mask_until = 0.0
        self._clear_zones_locked()
        if zone_key == "szyja":
            self.neck_on = True
            self._set_prompt_locked(f"A{self.back_forward_cycle_2 or 1}")
        else:
            self.back_waist_on = True
            self._set_prompt_locked(f"b{self.back_forward_cycle_1 or 1}")

    def _sync_from_frame_locked(self) -> None:
        if not self.raw_frame or len(self.raw_frame) < FULL_FRAME_LENGTH:
            return
        b3, b4, b5, b6 = self.bytes_3_to_6
        tail = tuple(self.full_frame_tail[:4]) if self.full_frame_tail else ()
        overlay_active = time.monotonic() < self.mask_until
        full_payload_zero = all(value == 0x00 for value in self.raw_frame[2:])

        if full_payload_zero:
            self._power_off_locked()
            self.check_until = 0.0
            self.mask_until = 0.0
            self.power_off_text_until = 0.0
            self.power_off_started_at = 0.0
            return

        if [b3, b4, b5, b6] == [0x00, 0x00, 0x00, 0x00]:
            if overlay_active:
                return
            if self.last_command == "power" and not self.power_on:
                return
            return

        self.power_on = True

        # --- Zone bitfield from position 21 (verified live UART) ---
        zone_byte = self.raw_frame[21] if len(self.raw_frame) > 21 else 0
        # --- Heat flag from position 23: bits 2-3 indicate heat (verified live) ---
        heat_byte = self.raw_frame[23] if len(self.raw_frame) > 23 else 0

        # Auto profile detection — tail[17:21] differentiates profiles.
        # Verified against live UART 2026-04-13.
        # Only apply full profile defaults when profile CHANGES to avoid
        # resetting timer and overriding user zone toggles on every frame.
        detected_profile = None
        detected_variant = None
        if [b3, b4, b5, b6] == [0x04, 0x02, 0x0C, 0x0F]:
            if tail == (0x0A, 0x0B, 0x0C, 0x08):
                detected_profile = "A"
                detected_variant = "default"
            elif tail == (0x04, 0x00, 0x0A, 0x00):
                detected_profile = "A"
                detected_variant = "cycled"
            elif tail == (0x04, 0x0D, 0x06, 0x00):
                detected_profile = "B"
            elif tail == (0x04, 0x09, 0x0E, 0x00):
                detected_profile = "C"
            elif tail == (0x04, 0x02, 0x0E, 0x00):
                detected_profile = "D"

        if detected_profile is not None:
            if (
                self.mode != "auto"
                or self.auto_profile != detected_profile
                or self.auto_profile_variant != detected_variant
            ):
                if detected_profile == "A" and detected_variant == "default":
                    self._set_default_auto_locked()
                else:
                    self._apply_auto_profile_locked(detected_profile, detected_variant)
            # On steady-state frames, update zones from bitfield and heat
            self.shoulders_on = bool(zone_byte & 0x01)
            self.forearms_on = bool(zone_byte & 0x02)
            self.legs_on = bool(zone_byte & 0x04)
            self.full_body_on = self.shoulders_on and self.forearms_on and self.legs_on
            self.heat_on = (heat_byte & 0x0C) != 0
            return

        # Manual neck mode: b4 == 0x0E
        if b4 == 0x0E:
            self.mode = "manual"
            self.auto_profile = None
            self.auto_profile_variant = None
            self.neck_on = True
            self.back_waist_on = b3 == 0x04
            self.shoulders_on = bool(zone_byte & 0x01)
            self.forearms_on = bool(zone_byte & 0x02)
            self.legs_on = bool(zone_byte & 0x04)
            self.buttocks_on = False
            self.foot_massage_on = False
            self.full_body_on = self.shoulders_on and self.forearms_on and self.legs_on
            self.heat_on = (heat_byte & 0x0C) != 0
            return

        # Manual back/waist mode: b4 == 0x0C
        if b4 == 0x0C:
            self.mode = "manual"
            self.auto_profile = None
            self.auto_profile_variant = None
            self.back_waist_on = True
            self.neck_on = False
            self.shoulders_on = bool(zone_byte & 0x01)
            self.forearms_on = bool(zone_byte & 0x02)
            self.legs_on = bool(zone_byte & 0x04)
            self.buttocks_on = False
            self.foot_massage_on = False
            self.full_body_on = self.shoulders_on and self.forearms_on and self.legs_on
            self.heat_on = (heat_byte & 0x0C) != 0
            return

        # Generic running signatures (auto mode without tail match,
        # or manual with zones active).
        if b3 == 0x04 and b4 == 0x02 and b6 == 0x0F:
            if self.mode == "off":
                self._set_default_auto_locked()
            # b5 (frame position 11) encodes intensity:
            # 0x0F = level 3, 0x0C = level 2 (verified live UART)
            if b5 == 0x0F:
                self.intensity_level = 3
            elif b5 == 0x0C:
                self.intensity_level = 2

        # Apply zone bitfield and heat for running modes
        self.shoulders_on = bool(zone_byte & 0x01)
        self.forearms_on = bool(zone_byte & 0x02)
        self.legs_on = bool(zone_byte & 0x04)
        self.full_body_on = self.shoulders_on and self.forearms_on and self.legs_on
        self.heat_on = (heat_byte & 0x0C) != 0

    def _set_prompt_locked(self, text: str, seconds: float = PROMPT_SECONDS) -> None:
        self.prompt_text = text
        self.prompt_until = monotonic_deadline(seconds)

    def _flash_locked(self, command: str, seconds: float = 0.22) -> None:
        self.flash_command_until[command] = monotonic_deadline(seconds)

    def _set_timer_minutes_locked(self, minutes: int) -> None:
        self.timer_minutes = minutes
        self.remaining_seconds = minutes * 60
        self.last_tick = time.monotonic()
        self._elapsed_accumulator = 0.0

    def _set_default_auto_locked(self) -> None:
        self.mode = "auto"
        self.auto_profile = "A"
        self.auto_profile_variant = "default"
        self.paused = False
        self.intensity_level = 2
        self.speed_level = 2
        self.foot_speed_level = 2
        self.heat_on = False
        self.shoulders_on = True
        self.forearms_on = True
        self.legs_on = True
        self.buttocks_on = False
        self.foot_massage_on = True
        self.neck_on = True
        self.back_waist_on = True
        self.full_body_on = True
        self._set_timer_minutes_locked(15)

    def _apply_auto_profile_locked(self, profile: str, variant: str | None = None) -> None:
        self.mode = "auto"
        self.auto_profile = profile
        self.auto_profile_variant = variant or ("cycled" if profile == "A" else None)
        self.paused = False
        self.intensity_level = 2
        self.speed_level = 2
        self.foot_speed_level = 2
        self.heat_on = False
        self._set_timer_minutes_locked(15)
        if profile == "A":
            self.shoulders_on = True
            self.forearms_on = True
            self.legs_on = True
            self.buttocks_on = False
            self.foot_massage_on = False
            self.neck_on = False
            self.back_waist_on = False
        elif profile == "B":
            self.shoulders_on = True
            self.forearms_on = True
            self.legs_on = True
            self.buttocks_on = True
            self.foot_massage_on = True
            self.neck_on = True
            self.back_waist_on = True
        elif profile == "C":
            self.shoulders_on = False
            self.forearms_on = True
            self.legs_on = True
            self.buttocks_on = False
            self.foot_massage_on = True
            self.neck_on = False
            self.back_waist_on = False
        elif profile == "D":
            self.shoulders_on = True
            self.forearms_on = True
            self.legs_on = True
            self.buttocks_on = True
            self.foot_massage_on = True
            self.neck_on = True
            self.back_waist_on = True
        self.full_body_on = self.shoulders_on and self.forearms_on and self.legs_on

    def _power_off_locked(self) -> None:
        self.power_on = False
        self.mode = "off"
        self.auto_profile = None
        self.auto_profile_variant = None
        self.paused = False
        self.heat_on = False
        self.shoulders_on = False
        self.forearms_on = False
        self.legs_on = False
        self.buttocks_on = False
        self.foot_massage_on = False
        self.neck_on = False
        self.back_waist_on = False
        self.full_body_on = False
        self.check_until = monotonic_deadline(POWER_OFF_TEXT_SECONDS)
        self.mask_until = self.check_until
        self.power_off_text_until = monotonic_deadline(POWER_OFF_TEXT_SECONDS)
        self.power_off_started_at = time.monotonic()
        self.prompt_text = ""
        self.prompt_until = 0.0

    def apply_command(self, command: str) -> None:
        with self.lock:
            self._tick_locked()
            if command not in COMMAND_INDEX:
                raise KeyError(command)
            self.last_command = command
            self._remember_command_locked(command)

            if command == "power":
                if self.power_on:
                    self._power_off_locked()
                else:
                    self.power_on = True
                    self.check_until = 0.0
                    self.mask_until = 0.0
                    self.power_off_text_until = 0.0
                    self._set_default_auto_locked()
                return

            if not self.power_on:
                return

            if self.paused and command != "pauza":
                return

            if self.mode == "auto" and command in AUTO_DEAD_COMMANDS:
                return

            if command in MOMENTARY_COMMANDS:
                self._flash_locked(command)

            if command in {"grawitacja_zero", "oparcie_w_gore", "oparcie_w_dol"}:
                self.check_until = monotonic_deadline(OVERLAY_SECONDS)
                self.mask_until = monotonic_deadline(OVERLAY_SECONDS)
                return

            if command == "tryb_automatyczny":
                if self.mode != "auto":
                    self._set_default_auto_locked()
                    return

                next_profile = AUTO_PROFILE_SEQUENCE[0]
                if self.auto_profile in AUTO_PROFILE_SEQUENCE:
                    current_index = AUTO_PROFILE_SEQUENCE.index(self.auto_profile)
                    next_profile = AUTO_PROFILE_SEQUENCE[
                        (current_index + 1) % len(AUTO_PROFILE_SEQUENCE)
                    ]
                self._apply_auto_profile_locked(next_profile)
                self._set_prompt_locked(f"F{['A', 'B', 'C', 'D'].index(next_profile) + 1}")
                return

            if command == "czas":
                current_index = TIME_OPTIONS_MINUTES.index(self.timer_minutes)
                next_minutes = TIME_OPTIONS_MINUTES[(current_index + 1) % len(TIME_OPTIONS_MINUTES)]
                self._set_timer_minutes_locked(next_minutes)
                return

            if command == "pauza":
                self.paused = not self.paused
                return

            if command == "ogrzewanie":
                self.heat_on = not self.heat_on
                return

            if command == "masaz_stop":
                self.foot_massage_on = not self.foot_massage_on
                return

            if command == "masaz_posladkow":
                self.buttocks_on = not self.buttocks_on
                return

            if command == "masaz_calego_ciala":
                next_value = not self.full_body_on
                self.full_body_on = next_value
                self.shoulders_on = next_value
                self.forearms_on = next_value
                self.legs_on = next_value
                return

            if command == "ramiona":
                self.shoulders_on = not self.shoulders_on
                self.full_body_on = self.shoulders_on and self.forearms_on and self.legs_on
                return

            if command == "przedramiona":
                self.forearms_on = not self.forearms_on
                self.full_body_on = self.shoulders_on and self.forearms_on and self.legs_on
                return

            if command == "nogi":
                self.legs_on = not self.legs_on
                self.full_body_on = self.shoulders_on and self.forearms_on and self.legs_on
                return

            if command == "plecy_i_talia":
                if self.mode == "auto" or self.neck_on:
                    self._switch_to_manual_zone_locked("plecy_i_talia")
                else:
                    self.back_waist_on = not self.back_waist_on
                    self.mode = "manual"
                    self.auto_profile = None
                    if self.back_waist_on:
                        self._set_prompt_locked(f"b{self.back_forward_cycle_1 or 1}")
                return

            if command == "szyja":
                if self.mode == "auto" or self.back_waist_on:
                    self._switch_to_manual_zone_locked("szyja")
                else:
                    self.neck_on = not self.neck_on
                    self.mode = "manual"
                    self.auto_profile = None
                    if self.neck_on:
                        self._set_prompt_locked(f"A{self.back_forward_cycle_2 or 1}")
                return

            if command == "predkosc_masazu_stop":
                if self._can_adjust_foot_speed_locked():
                    self.foot_speed_level = 1 if self.foot_speed_level >= 3 else self.foot_speed_level + 1
                return

            if command == "sila_nacisku_plus":
                if self._show_intensity_ui_locked():
                    self.intensity_level = clamp(self.intensity_level + 1, 1, 3)
                return

            if command == "sila_nacisku_minus":
                if self._show_intensity_ui_locked():
                    self.intensity_level = clamp(self.intensity_level - 1, 1, 3)
                return

            if command == "predkosc_plus":
                if self.mode == "manual" and self._show_speed_ui_locked():
                    self.speed_level = clamp(self.speed_level + 1, 1, 3)
                return

            if command == "predkosc_minus":
                if self.mode == "manual" and self._show_speed_ui_locked():
                    self.speed_level = clamp(self.speed_level - 1, 1, 3)
                return

            if command == "do_przodu_do_tylu_1" and self.back_waist_on:
                self.back_forward_cycle_1 = 1 if self.back_forward_cycle_1 == 2 else self.back_forward_cycle_1 + 1
                self._set_prompt_locked(f"b{self.back_forward_cycle_1}")
                return

            if command == "do_przodu_do_tylu_2" and self.neck_on:
                self.back_forward_cycle_2 = 1 if self.back_forward_cycle_2 == 2 else self.back_forward_cycle_2 + 1
                self._set_prompt_locked(f"A{self.back_forward_cycle_2}")
                return

    def _current_time_text_locked(self) -> str:
        now = time.monotonic()
        if not self.power_on:
            if now < self.power_off_text_until:
                return "OF"
            return ""
        if now < self.prompt_until:
            return self.prompt_text
        total_seconds = max(0, self.remaining_seconds)
        if total_seconds <= 0:
            return "0"
        minutes = max(1, (total_seconds + 59) // 60)
        return str(minutes)

    def _show_overlay_locked(self) -> bool:
        return self.power_on and time.monotonic() < self.mask_until

    def _expand_cumulative_level_layers_locked(self, visible: set[str]) -> set[str]:
        expanded = set(visible)
        for prefix in (
            "Sila_nacisku-LVL",
            "Predkosc-LVL",
            "Predkosc_masazu_stop-LVL",
        ):
            for level in range(3, 0, -1):
                label = f"{prefix}{level}"
                if label in expanded:
                    for fill in range(1, level):
                        expanded.add(f"{prefix}{fill}")
        return expanded

    def _visible_layers_locked(self) -> list[str]:
        now = time.monotonic()
        visible = {"Background"}

        if not self.power_on:
            if now < self.power_off_text_until:
                visible.add("Czas-NUMBER")
            if now < self.check_until:
                blink_phase = int((now - self.power_off_started_at) / 0.22)
                if blink_phase % 2 == 0:
                    visible.add("SHAPE_CHECK-TEXT")
            return sorted(visible)

        visible.update({"Body", "Czas-TEXT", "Czas-NUMBER"})
        if self.mode == "manual":
            visible.add("Tryb_manualny")
        else:
            visible.add("Tryb_automatyczny")
            if self.auto_profile:
                visible.add(f"Tryb_automatyczny-{self.auto_profile}")

        if self._show_overlay_locked():
            if now < self.check_until:
                visible.add("SHAPE_CHECK-TEXT")
            return sorted(visible)

        if self.shoulders_on:
            visible.add("Ramiona")
        if self.forearms_on:
            visible.add("Przedramiona")
        if self.legs_on:
            visible.add("Nogi")
        if self.buttocks_on:
            visible.add("Masaz_Posladkow")
        if self.foot_massage_on:
            visible.add("Masaz_Stop")
        if self.heat_on:
            visible.add("Ogrzewanie")
        if self.neck_on:
            visible.update({"Szyja", "? Szyja"})
        if self.back_waist_on:
            visible.update({"Plecy_i_talia", "? Plecy_i_talia"})

        intensity_visible = self._show_intensity_ui_locked()
        speed_visible = self._show_speed_ui_locked()
        foot_speed_visible = self._show_foot_speed_ui_locked()

        if intensity_visible:
            visible.add("Sila_nacisku-TEXT")
            visible.add(f"Sila_nacisku-LVL{self.intensity_level}")
        if speed_visible:
            visible.add("PredkoscTEXT")
            visible.add(f"Predkosc-LVL{self.speed_level}")
        if foot_speed_visible:
            visible.add("Predkosc_masazu_stop")
            visible.add(f"Predkosc_masazu_stop-LVL{self.foot_speed_level}")
        if now < self.check_until:
            visible.add("SHAPE_CHECK-TEXT")
        return sorted(self._expand_cumulative_level_layers_locked(visible))

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            self._tick_locked()
            now = time.monotonic()
            frame_age_ms = None
            if self.frame_seen_at is not None:
                frame_age_ms = max(0, int((time.time() - self.frame_seen_at) * 1000))
            flash_active = {
                command: True
                for command, deadline in self.flash_command_until.items()
                if deadline > now
            }
            self.flash_command_until = {
                command: deadline
                for command, deadline in self.flash_command_until.items()
                if deadline > now
            }
            active_buttons = {command: False for command in BUTTON_ORDER}
            active_buttons["power"] = self.power_on
            active_buttons["ogrzewanie"] = self.heat_on
            active_buttons["pauza"] = self.paused
            active_buttons["masaz_stop"] = self.foot_massage_on
            active_buttons["masaz_posladkow"] = self.buttocks_on
            active_buttons["masaz_calego_ciala"] = self.full_body_on
            active_buttons["ramiona"] = self.shoulders_on
            active_buttons["przedramiona"] = self.forearms_on
            active_buttons["nogi"] = self.legs_on
            active_buttons["plecy_i_talia"] = self.back_waist_on
            active_buttons["szyja"] = self.neck_on
            active_buttons["tryb_automatyczny"] = self.mode == "auto"
            for command in flash_active:
                active_buttons[command] = True

            blocked_buttons = {}
            for command in BUTTON_ORDER:
                blocked = False
                if command == "power":
                    blocked = False
                elif not self.power_on:
                    blocked = True
                elif self.paused:
                    blocked = command != "pauza"
                elif self.mode == "auto" and command in AUTO_DEAD_COMMANDS:
                    blocked = True
                elif command in {"sila_nacisku_plus", "sila_nacisku_minus"}:
                    blocked = not self._show_intensity_ui_locked()
                elif command == "predkosc_masazu_stop":
                    blocked = not self._can_adjust_foot_speed_locked()
                elif command in {"predkosc_plus", "predkosc_minus"}:
                    blocked = self.mode != "manual" or not self._show_speed_ui_locked()
                elif command == "do_przodu_do_tylu_1":
                    blocked = self.mode != "manual" or not self.back_waist_on
                elif command == "do_przodu_do_tylu_2":
                    blocked = self.mode != "manual" or not self.neck_on
                blocked_buttons[command] = blocked

            return {
                "connected": self.connected,
                "port_name": self.port_name,
                "listening": self.listening,
                "board_ready": self.board_ready,
                "last_error": self.last_error,
                "last_command": self.last_command,
                "power_on": self.power_on,
                "mode": self.mode,
                "auto_profile": self.auto_profile,
                "auto_profile_variant": self.auto_profile_variant,
                "timer_minutes": self.timer_minutes,
                "remaining_seconds": self.remaining_seconds,
                "time_text": self._current_time_text_locked(),
                "levels": {
                    "intensity": self.intensity_level,
                    "speed": self.speed_level,
                    "foot_speed": self.foot_speed_level,
                },
                "raw_frame": self.raw_frame,
                "frame_signature": self.frame_signature,
                "bytes_3_to_6": self.bytes_3_to_6,
                "full_frame_tail": self.full_frame_tail,
                "frame_seen_at": self.frame_seen_at,
                "frame_age_ms": frame_age_ms,
                "layers": {
                    "visible": self._visible_layers_locked(),
                    "text": {"Czas-NUMBER": self._current_time_text_locked()},
                },
                "sync": {
                    "frame_live": bool(frame_age_ms is not None and frame_age_ms < 3000),
                    "time_source": "model",
                    "levels_source": "frame-assisted" if frame_age_ms is not None else "model",
                    "zones_source": "frame-assisted" if frame_age_ms is not None else "model",
                },
                "buttons": {
                    command: {
                        "active": active_buttons[command],
                        "blocked": blocked_buttons[command],
                        "label": COMMAND_INDEX[command].label,
                    }
                    for command in BUTTON_ORDER
                },
                "zones": {
                    "ramiona": self.shoulders_on,
                    "przedramiona": self.forearms_on,
                    "nogi": self.legs_on,
                    "masaz_posladkow": self.buttocks_on,
                    "masaz_stop": self.foot_massage_on,
                    "szyja": self.neck_on,
                    "plecy_i_talia": self.back_waist_on,
                    "ogrzewanie": self.heat_on,
                },
                "command_history": list(self.command_history),
                "backend_log": list(self.backend_log),
                "poll_hint_ms": STATE_POLL_HINT_MS,
            }


class FirmwareSerialBridge:
    def __init__(self, state: ChairState, baud_rate: int, port: str | None = None) -> None:
        self.state = state
        self.baud_rate = baud_rate
        self.requested_port = port
        self.serial_handle: serial.Serial | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.queue: queue.Queue[str] = queue.Queue()
        self.last_connect_attempt = 0.0
        self.last_write_at = 0.0
        self.last_listen_sent = 0.0
        self.read_buffer = bytearray()
        self.rx_text_tail = ""

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._worker, daemon=True, name="firmware-serial-bridge")
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self._disconnect()

    def send_command(self, command: str, repeats: int | None = None) -> None:
        count = repeats if repeats is not None else (1 if command.startswith("listen ") else PRESS_REPEAT)
        for _ in range(max(1, count)):
            self.queue.put(command)

    def _pick_port(self) -> str | None:
        if self.requested_port:
            return self.requested_port
        ports = list(list_ports.comports())
        if not ports:
            return None
        def score(port_info: Any) -> tuple[int, str]:
            text = " ".join(
                str(getattr(port_info, field, "") or "")
                for field in ("device", "description", "manufacturer", "product", "hwid")
            ).lower()
            rank = 0
            for token in ("arduino", "wch", "ch340", "cp210", "ttyacm", "ttyusb", "usb serial"):
                if token in text:
                    rank += 1
            return rank, str(getattr(port_info, "device", ""))
        ports.sort(key=score, reverse=True)
        return ports[0].device

    def _connect(self) -> None:
        now = time.monotonic()
        if now - self.last_connect_attempt < RECONNECT_INTERVAL:
            return
        self.last_connect_attempt = now

        port_name = self._pick_port()
        if not port_name:
            self.state.set_connection(False, "No serial device found")
            return

        try:
            handle = serial.Serial(port_name, self.baud_rate, timeout=0.05, write_timeout=0.3)
            self.serial_handle = handle
            self.state.set_connection(True, port_name)
            self.state.note_backend_line(f"Connected to {port_name} @ {self.baud_rate}")
            # Opening the CH340/Nano bridge resets the MCU. Give it enough time
            # to finish rebooting, then drain and parse the startup banner before
            # auto-sending listen mode commands.
            time.sleep(CONNECT_SETTLE_SECONDS)
            try:
                self._drain_startup_output(handle)
                handle.reset_output_buffer()
            except Exception:
                pass
        except Exception as exc:
            self.serial_handle = None
            self.state.set_connection(False, f"Connect failed: {exc}")
            self.state.note_error(f"connect failed: {exc}")

    def _disconnect(self) -> None:
        handle = self.serial_handle
        self.serial_handle = None
        if handle:
            try:
                handle.close()
            except Exception:
                pass
        self.state.set_connection(False, "Disconnected")

    def _read_lines(self) -> None:
        if not self.serial_handle:
            return
        try:
            chunk = self._read_available_bytes(self.serial_handle)
            if not chunk:
                return
            self._consume_serial_chunk(chunk)
        except Exception as exc:
            self.state.note_error(f"read failed: {exc}")
            self._disconnect()

    def _write_commands(self) -> None:
        if not self.serial_handle:
            return
        now = time.monotonic()
        if now - self.last_write_at < WRITE_INTERVAL:
            return
        try:
            command = self.queue.get_nowait()
            self._write_command_safely(command)
            self.serial_handle.flush()
            self.last_write_at = now
            if command == "listen on":
                self.last_listen_sent = now
        except queue.Empty:
            return
        except Exception as exc:
            self.state.note_error(f"write failed: {exc}")
            self._disconnect()

    def _ensure_listening(self) -> None:
        if not self.serial_handle:
            return
        if self.state.listening:
            return
        now = time.monotonic()
        if now - self.last_listen_sent < LISTEN_RETRY_SECONDS:
            return
        if not self.state.board_ready and now - self.last_connect_attempt < 1.1:
            return
        self.send_command("listen on")
        self.last_listen_sent = now

    def _worker(self) -> None:
        while not self.stop_event.is_set():
            if not self.serial_handle:
                self._connect()
            else:
                self._ensure_listening()
                self._write_commands()
                self._read_lines()
            time.sleep(SERIAL_LOOP_SLEEP)

    def _read_available_bytes(self, handle: serial.Serial) -> bytes:
        waiting = getattr(handle, "in_waiting", 0)
        if waiting <= 0:
            return b""
        return handle.read(waiting)

    def _consume_serial_chunk(self, chunk: bytes) -> None:
        decoded = chunk.decode("utf-8", errors="replace")
        stream_text = self.rx_text_tail + decoded
        overlap = len(self.rx_text_tail)
        for match in FRAME_BYTE_RE.finditer(stream_text):
            if match.end() <= overlap:
                continue
            self.state.note_backend_rx_value(int(match.group(1), 16))
        self.rx_text_tail = stream_text[-64:]
        self.read_buffer.extend(chunk)
        while b"\n" in self.read_buffer:
            raw_line, _, remainder = self.read_buffer.partition(b"\n")
            self.read_buffer = bytearray(remainder)
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                self.state.note_backend_line(line)

    def _drain_startup_output(self, handle: serial.Serial) -> None:
        deadline = time.monotonic() + STARTUP_DRAIN_SECONDS
        while time.monotonic() < deadline:
            chunk = self._read_available_bytes(handle)
            if chunk:
                self._consume_serial_chunk(chunk)
                deadline = time.monotonic() + 0.12
                continue
            time.sleep(0.03)

    def _write_command_safely(self, command: str) -> None:
        payload = (command + "\n").encode("utf-8")
        for byte in payload:
            self.serial_handle.write(bytes([byte]))
            time.sleep(SERIAL_CHAR_DELAY)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "ElectricChairBridge/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_root_view()
            return
        if parsed.path in {"/ROOT-VIEW.html", "/root-view"}:
            self._serve_root_view()
            return
        if parsed.path == "/static/ROOT-VIEW.html":
            self._serve_file(STATIC_DIR / "ROOT-VIEW.html", "text/html; charset=utf-8")
            return
        if parsed.path in {"/debug", "/debug.html"}:
            self._serve_file(STATIC_DIR / "debug.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/static/debug.html":
            self._serve_file(STATIC_DIR / "debug.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/network":
            html = build_network_page(self.server.server_address[1], self.server.lan_ip)
            self._send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/qr.svg":
            lan_url = f"http://{self.server.lan_ip}:{self.server.server_address[1]}"
            svg = generate_qr_svg(lan_url)
            if svg:
                self._send_bytes(svg.encode("utf-8"), "image/svg+xml; charset=utf-8")
            else:
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "qrcode library not installed")
            return
        if parsed.path == "/app.css":
            self._serve_file(STATIC_DIR / "app.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._serve_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/root-view.js":
            self._serve_file(STATIC_DIR / "root-view.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/display.svg":
            self._send_bytes(self.server.svg_markup.encode("utf-8"), "image/svg+xml; charset=utf-8")
            return
        if parsed.path == "/api/state":
            payload = json.dumps(self.server.state.snapshot()).encode("utf-8")
            self._send_bytes(payload, "application/json; charset=utf-8")
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/command":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return

        command = body.get("command")
        if command not in COMMAND_INDEX:
            self.send_error(HTTPStatus.BAD_REQUEST, "Unknown command")
            return

        self.server.state.apply_command(command)
        self.server.bridge.send_command(command)

        payload = json.dumps({"ok": True, "state": self.server.state.snapshot()}).encode("utf-8")
        self._send_bytes(payload, "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Missing file")
            return
        self._send_bytes(path.read_bytes(), content_type)

    def _serve_root_view(self) -> None:
        if not ROOT_VIEW_PATH.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Missing file")
            return
        html = ROOT_VIEW_PATH.read_text(encoding="utf-8")
        html = re.sub(
            r"<script>[\s\S]*?</script>\s*</body>",
            '  <script src="/root-view.js" defer></script>\n</body>',
            html,
            count=1,
        )
        self._send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")

    def _send_bytes(self, payload: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


class AppServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], state: ChairState, bridge: FirmwareSerialBridge, svg_markup: str, lan_ip: str = "127.0.0.1") -> None:
        super().__init__(server_address, AppHandler)
        self.state = state
        self.bridge = bridge
        self.svg_markup = svg_markup
        self.lan_ip = lan_ip


def get_lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_qr_svg(data: str) -> str | None:
    if not HAS_QRCODE:
        return None
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    import io
    factory = qrcode.image.svg.SvgPathImage
    img = qr.make_image(image_factory=factory)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def build_network_page(port: int, lan_ip: str) -> str:
    local_url = f"http://localhost:{port}"
    lan_url = f"http://{lan_ip}:{port}"
    return f"""\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Electric Chair - Network Access</title>
  <style>
    :root {{ --bg: #081217; --panel: #10232c; --ink: #e9f5ff; --muted: #9ab5c7; --accent: #66e0ff; }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100vh; background: var(--bg); color: var(--ink); font-family: "Segoe UI", Arial, sans-serif; }}
    .wrap {{ max-width: 600px; margin: 0 auto; padding: 40px 24px; text-align: center; }}
    h1 {{ font-size: 1.8rem; margin-bottom: 8px; }}
    .sub {{ color: var(--muted); margin-bottom: 32px; }}
    .card {{ background: var(--panel); border: 1px solid rgba(255,255,255,0.08); border-radius: 18px; padding: 24px; margin-bottom: 20px; }}
    .card h2 {{ font-size: 0.85rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; margin: 0 0 10px; }}
    .url {{ font-size: 1.3rem; color: var(--accent); word-break: break-all; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    #qr {{ margin: 20px auto; display: inline-block; background: #fff; padding: 16px; border-radius: 12px; }}
    #qr img, #qr svg {{ display: block; width: 240px; height: 240px; }}
    .back {{ display: inline-block; margin-top: 24px; padding: 12px 24px; border: 1px solid rgba(255,255,255,0.12); border-radius: 999px; color: var(--ink); text-decoration: none; }}
    .back:hover {{ border-color: var(--accent); }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Network Access</h1>
    <p class="sub">Open this app from any device on the same network</p>
    <div class="card">
      <h2>Local (this machine)</h2>
      <p class="url"><a href="{local_url}">{local_url}</a></p>
    </div>
    <div class="card">
      <h2>LAN (other devices)</h2>
      <p class="url"><a href="{lan_url}">{lan_url}</a></p>
    </div>
    <div class="card">
      <h2>Scan QR Code</h2>
      <div id="qr"><img id="qrImg" src="/qr.svg" alt="QR code for LAN URL" onerror="this.parentElement.innerHTML='<p style=\\'color:#000;font-size:1rem;padding:8px\\'>QR unavailable. Install: pip install qrcode</p>'"></div>
    </div>
    <a class="back" href="/">Back to Control Panel</a>
  </div>
</body>
</html>"""


def print_startup_banner(host: str, port: int, lan_ip: str) -> None:
    local_url = f"http://localhost:{port}"
    lan_url = f"http://{lan_ip}:{port}"
    network_url = f"http://{lan_ip}:{port}/network"
    print()
    print("=" * 56)
    print("  Electric Chair Bridge")
    print("=" * 56)
    print(f"  Local:    {local_url}")
    print(f"  LAN:      {lan_url}")
    print(f"  Network:  {network_url}  (QR code)")
    print("-" * 56)
    print(f"  Bound to {host}:{port}")
    print("=" * 56)
    print()

    try:
        import qrcode  # type: ignore
        qr = qrcode.QRCode(border=1)
        qr.add_data(lan_url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        print()
    except ImportError:
        print(f"  (install 'qrcode' for terminal QR: pip install qrcode)")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Electric chair web bridge")
    parser.add_argument("--host", default=os.environ.get("CHAIR_BRIDGE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CHAIR_BRIDGE_HTTP_PORT", "8080")))
    parser.add_argument("--serial-port", default=os.environ.get("CHAIR_BRIDGE_SERIAL_PORT"))
    parser.add_argument("--baud", type=int, default=int(os.environ.get("CHAIR_BRIDGE_BAUD", str(FIRMWARE_DEFAULT_BAUD))))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    lan_ip = get_lan_ip()
    state = ChairState()
    bridge = FirmwareSerialBridge(state=state, baud_rate=args.baud, port=args.serial_port)
    bridge.start()
    server = AppServer(
        (args.host, args.port),
        state=state,
        bridge=bridge,
        svg_markup=load_svg_markup(SVG_PATH),
        lan_ip=lan_ip,
    )
    try:
        print_startup_banner(args.host, args.port, lan_ip)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        bridge.stop()


if __name__ == "__main__":
    main()
