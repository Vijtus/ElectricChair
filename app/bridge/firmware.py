from __future__ import annotations

import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, replace
from typing import Any

import serial
from serial.tools import list_ports

from . import config
from .commands import COMMAND_INDEX, RETRY_SAFE_COMMANDS
from .framing import FRAME_BYTE_RE, FRAME_LINE_RE
from .state import ChairState, CommandOutcome

ACK_RE = re.compile(r"^ACK\s+seq=(\d+)\s+code=0x([0-9A-Fa-f]{2})")
DONE_RE = re.compile(r"^DONE\s+seq=(\d+)\s+code=0x([0-9A-Fa-f]{2})")
NACK_RE = re.compile(r"^NACK\s+seq=(\d+)\s+code=0x([0-9A-Fa-f]{2})(?:\s+error=(.*))?")


@dataclass
class CommandTx:
    seq: int
    command: str
    code: int
    muted_fields: set[str]
    expected_fields: dict[str, Any]
    retries_left: int
    sent_at: float | None = None
    acked_at: float | None = None
    done_at: float | None = None
    verify_deadline: float | None = None


class FirmwareSerialBridge:
    config = config

    def __init__(
        self, state: ChairState, baud_rate: int, port: str | None = None
    ) -> None:
        self.state = state
        self.baud_rate = baud_rate
        self.requested_port = port
        self.serial_handle: serial.Serial | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.write_queue: queue.Queue[str | CommandTx] = queue.Queue()
        self.last_connect_attempt = 0.0
        self.last_write_at = 0.0
        self.last_listen_sent = 0.0
        self.last_listen_off_sent = 0.0
        self.listen_failures = 0
        self.read_buffer = bytearray()
        self.rx_text_tail = ""
        self.seq_counter = 0
        self.tx_lock = threading.RLock()
        self.in_flight: dict[int, CommandTx] = {}
        self.acked: dict[int, CommandTx] = {}
        self.verifying: dict[int, CommandTx] = {}
        self.completed: dict[int, CommandTx] = {}
        self.logger = logging.getLogger("electric_chair_bridge.firmware")

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._worker, daemon=True, name="firmware-serial-bridge"
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self._disconnect()

    def send_command(self, command: str) -> int | None:
        if command not in COMMAND_INDEX:
            raise KeyError(command)
        with self.tx_lock:
            if self.is_busy():
                self.state.note_backend_line(
                    f"blocked command={command}: bridge command pending"
                )
                return None
            if command == "power" and self._has_pending_power_locked():
                self.state.note_backend_line(
                    "blocked command=power: previous power command pending"
                )
                return None
            if not self.serial_handle:
                self.state.note_error(f"cannot send {command}: serial disconnected")
                return None
            seq = self._next_seq_locked()
            outcome = self.state.apply_command(command, seq=seq)
            if not outcome.should_send:
                return None
            tx = self._build_tx_locked(
                seq, command, outcome, self._retry_budget_for_command(command)
            )
            self.in_flight[seq] = tx
            if self.state.listening:
                self.write_queue.put("listen off")
            self.write_queue.put(tx)
            self.logger.info("seq=%s queued command=%s", seq, command)
            return seq

    def pending_count(self) -> int:
        return self.write_queue.qsize()

    def is_busy(self) -> bool:
        with self.tx_lock:
            return bool(
                self.write_queue.qsize()
                or self.in_flight
                or self.acked
                or self.verifying
            )

    def note_backend_line(self, line: str) -> None:
        self.state.note_backend_line(line)
        if "Chair read: OFF" in line:
            self.last_listen_off_sent = 0.0
        elif "Chair read: ON" in line:
            self.listen_failures = 0
        ack_match = ACK_RE.match(line)
        if ack_match:
            self._handle_ack(int(ack_match.group(1)))
            return
        done_match = DONE_RE.match(line)
        if done_match:
            self._handle_done(int(done_match.group(1)))
            return
        nack_match = NACK_RE.match(line)
        if nack_match:
            self._handle_nack(int(nack_match.group(1)), nack_match.group(3) or "nack")

    def _build_tx_locked(
        self, seq: int, command: str, outcome: CommandOutcome, retries_left: int
    ) -> CommandTx:
        return CommandTx(
            seq=seq,
            command=command,
            code=COMMAND_INDEX[command].code,
            muted_fields=set(outcome.muted_fields),
            expected_fields=dict(outcome.expected_fields),
            retries_left=retries_left,
        )

    def _next_seq_locked(self) -> int:
        self.seq_counter = (self.seq_counter + 1) & 0xFFFF
        if self.seq_counter == 0:
            self.seq_counter = 1
        return self.seq_counter

    def _has_pending_power_locked(self) -> bool:
        return (
            any(tx.command == "power" for tx in self.in_flight.values())
            or any(tx.command == "power" for tx in self.acked.values())
            or any(tx.command == "power" for tx in self.verifying.values())
        )

    def _retry_budget_for_command(self, command: str) -> int:
        if command in RETRY_SAFE_COMMANDS:
            return config.DEFAULT_RETRIES
        return 0

    def _pick_port(self) -> str | None:
        if self.requested_port:
            return self.requested_port
        ports = list(list_ports.comports())
        if not ports:
            return None

        def score(port_info: Any) -> tuple[int, str]:
            text = " ".join(
                str(getattr(port_info, field, "") or "")
                for field in (
                    "device",
                    "description",
                    "manufacturer",
                    "product",
                    "hwid",
                )
            ).lower()
            rank = 0
            for token in (
                "arduino",
                "wch",
                "ch340",
                "cp210",
                "ttyacm",
                "ttyusb",
                "usb serial",
            ):
                if token in text:
                    rank += 1
            return rank, str(getattr(port_info, "device", ""))

        ports.sort(key=score, reverse=True)
        return ports[0].device

    def _connect(self) -> None:
        now = time.monotonic()
        if now - self.last_connect_attempt < config.RECONNECT_INTERVAL_SECONDS:
            return
        self.last_connect_attempt = now

        port_name = self._pick_port()
        if not port_name:
            self.state.set_connection(False, "No serial device found")
            return

        try:
            handle = serial.Serial(
                port_name, self.baud_rate, timeout=0.05, write_timeout=0.3
            )
            self.serial_handle = handle
            self.state.set_connection(True, port_name)
            self.state.invalidate_frame()
            self.state.note_backend_line(f"Connected to {port_name} @ {self.baud_rate}")
            time.sleep(config.CONNECT_SETTLE_SECONDS)
            self._drain_startup_output(handle)
            handle.reset_output_buffer()
        except Exception as exc:
            self.serial_handle = None
            self.state.set_connection(False, f"Connect failed: {exc}")
            self.state.note_error(f"connect failed: {exc}")
            self.logger.exception("seq=- connect failed")

    def _disconnect(self) -> None:
        handle = self.serial_handle
        self.serial_handle = None
        self._clear_pending_transactions()
        if handle:
            try:
                handle.close()
            except Exception as exc:
                self.logger.warning("seq=- close failed: %s", exc)
        self.state.set_connection(False, "Disconnected")

    def _clear_pending_transactions(self) -> None:
        with self.tx_lock:
            while True:
                try:
                    self.write_queue.get_nowait()
                except queue.Empty:
                    break
            self.in_flight.clear()
            self.acked.clear()
            self.verifying.clear()

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
            self.logger.exception("seq=- read failed")
            self._disconnect()

    def _write_commands(self) -> None:
        if not self.serial_handle:
            return
        now = time.monotonic()
        if now - self.last_write_at < config.WRITE_INTERVAL_SECONDS:
            return
        try:
            item = self.write_queue.get_nowait()
        except queue.Empty:
            return
        if isinstance(item, CommandTx) and self.state.listening:
            self.write_queue.put(item)
            if now - self.last_listen_off_sent >= config.LISTEN_OFF_RETRY_SECONDS:
                self._write_control("listen off", now)
            return
        try:
            if isinstance(item, CommandTx):
                payload = f"{item.seq} {item.command}\n".encode("ascii")
                with self.tx_lock:
                    current = self.in_flight.get(item.seq)
                    if current:
                        current.sent_at = now
                self.logger.info("seq=%s write command=%s", item.seq, item.command)
            else:
                payload = self._control_payload(item)
                if item == "listen on":
                    self.last_listen_sent = now
                elif item == "listen off":
                    self.last_listen_off_sent = now
                self.logger.info("seq=- write control=%s", item)
            self.serial_handle.write(payload)
            self.serial_handle.flush()
            self.last_write_at = now
        except Exception as exc:
            if isinstance(item, CommandTx):
                self.state.note_error(f"write failed seq={item.seq}: {exc}")
                self.logger.exception("seq=%s write failed", item.seq)
            else:
                self.state.note_error(f"write failed: {exc}")
                self.logger.exception("seq=- write failed")
            self._disconnect()

    def _write_control(self, control: str, now: float) -> None:
        if not self.serial_handle:
            return
        try:
            payload = self._control_payload(control)
            if control == "listen on":
                self.last_listen_sent = now
            elif control == "listen off":
                self.last_listen_off_sent = now
            self.logger.info("seq=- write control=%s", control)
            self.serial_handle.write(payload)
            self.serial_handle.flush()
            self.last_write_at = now
        except Exception as exc:
            self.state.note_error(f"write failed: {exc}")
            self.logger.exception("seq=- write failed")
            self._disconnect()

    def _control_payload(self, control: str) -> bytes:
        if control == "listen off":
            return config.LISTEN_OFF_CONTROL_PAYLOAD.encode("ascii")
        if control == "listen on":
            return config.LISTEN_ON_CONTROL_PAYLOAD.encode("ascii")
        return f"{control}\n".encode("ascii")

    def _ensure_listening(self) -> None:
        if not self.serial_handle or self.state.listening:
            return
        with self.tx_lock:
            if self.in_flight or self.acked:
                return
        now = time.monotonic()
        delay = self._listen_retry_delay(self.listen_failures)
        if now - self.last_listen_sent < delay:
            return
        if not self.state.board_ready and now - self.last_connect_attempt < 1.1:
            return
        self.write_queue.put("listen on")
        self.last_listen_sent = now
        self.listen_failures += 1

    def _listen_retry_delay(self, failures: int) -> float:
        if failures < config.LISTEN_BACKOFF_AFTER_FAILURES:
            return config.LISTEN_INITIAL_RETRY_SECONDS
        exponent = failures - config.LISTEN_BACKOFF_AFTER_FAILURES + 1
        return min(
            config.LISTEN_MAX_RETRY_SECONDS,
            config.LISTEN_INITIAL_RETRY_SECONDS * (2**exponent),
        )

    def _worker(self) -> None:
        while not self.stop_event.is_set():
            if not self.serial_handle:
                self._connect()
            else:
                self._ensure_listening()
                self._check_timeouts()
                self._write_commands()
                self._read_lines()
            time.sleep(config.SERIAL_LOOP_SLEEP_SECONDS)

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
                frame_match = FRAME_LINE_RE.match(line)
                if frame_match:
                    frame_hex = frame_match.group(1)
                    frame = [
                        int(frame_hex[index : index + 2], 16)
                        for index in range(0, len(frame_hex), 2)
                    ]
                    self.state.note_frame(frame)
                    continue
                self.note_backend_line(line)

    def _drain_startup_output(self, handle: serial.Serial) -> None:
        deadline = time.monotonic() + config.STARTUP_DRAIN_SECONDS
        while time.monotonic() < deadline:
            chunk = self._read_available_bytes(handle)
            if chunk:
                self._consume_serial_chunk(chunk)
                deadline = time.monotonic() + config.STARTUP_DRAIN_EXTEND_SECONDS
                continue
            time.sleep(config.STARTUP_DRAIN_SLEEP_SECONDS)

    def _handle_ack(self, seq: int) -> None:
        with self.tx_lock:
            tx = self.in_flight.pop(seq, None)
            if not tx:
                self.logger.warning("seq=%s unexpected ACK", seq)
                return
            tx.acked_at = time.monotonic()
            self.acked[seq] = tx
            self.logger.info("seq=%s ACK command=%s", seq, tx.command)

    def _handle_done(self, seq: int) -> None:
        with self.tx_lock:
            tx = self.acked.pop(seq, None) or self.in_flight.pop(seq, None)
        if not tx:
            self.logger.warning("seq=%s unexpected DONE", seq)
            return
        tx.done_at = time.monotonic()
        if not self.state.listening:
            self.write_queue.put("listen on")
        self._defer_verification(tx)

    def _defer_verification(self, tx: CommandTx) -> None:
        now = time.monotonic()
        if tx.done_at is None:
            tx.done_at = now
        tx.verify_deadline = now + config.VERIFY_SETTLE_SECONDS
        with self.tx_lock:
            self.verifying[tx.seq] = tx
        self.state.extend_mute(tx.muted_fields, config.VERIFY_SETTLE_SECONDS)
        self.state.note_backend_line(
            f"verify pending seq={tx.seq} command={tx.command} "
            f"settle={config.VERIFY_SETTLE_SECONDS:.1f}s"
        )
        self.logger.info(
            "seq=%s verify pending command=%s settle=%.1fs",
            tx.seq,
            tx.command,
            config.VERIFY_SETTLE_SECONDS,
        )

    def _finish_disagreeing_tx(
        self, tx: CommandTx, disagreements: list[dict[str, Any]], reason: str
    ) -> None:
        if tx.retries_left > 0:
            self._retry_tx(tx, reason)
            return
        self.state.surrender_command(tx.command, tx.seq, tx.muted_fields, disagreements)
        if not self.state.listening:
            self.write_queue.put("listen on")
        self.logger.error("seq=%s exhausted command=%s", tx.seq, tx.command)

    def _finish_unverified_tx(self, tx: CommandTx) -> None:
        with self.tx_lock:
            self.completed[tx.seq] = tx
        self.state.note_unverified_command(tx.command, tx.seq, tx.muted_fields)
        if not self.state.listening:
            self.write_queue.put("listen on")
        self.logger.info(
            "seq=%s unverified command=%s fields=%s",
            tx.seq,
            tx.command,
            sorted(tx.muted_fields),
        )

    def _handle_nack(self, seq: int, reason: str) -> None:
        with self.tx_lock:
            tx = (
                self.in_flight.pop(seq, None)
                or self.acked.pop(seq, None)
                or self.verifying.pop(seq, None)
            )
        if not tx:
            self.logger.warning("seq=%s unexpected NACK reason=%s", seq, reason)
            return
        self.state.surrender_command(
            tx.command,
            seq,
            tx.muted_fields,
            [{"field": "firmware", "expected": "ACK/DONE", "actual": reason}],
        )
        self.state.note_error(f"firmware rejected {tx.command} seq={seq}: {reason}")
        if not self.state.listening:
            self.write_queue.put("listen on")
        self.logger.error("seq=%s NACK command=%s reason=%s", seq, tx.command, reason)

    def _check_timeouts(self) -> None:
        now = time.monotonic()
        with self.tx_lock:
            in_flight = list(self.in_flight.values())
            acked = list(self.acked.values())
            verifying = list(self.verifying.values())
        for tx in in_flight:
            if tx.sent_at is None:
                continue
            if now - tx.sent_at > config.ACK_TIMEOUT_SECONDS:
                self._timeout_tx(tx, "ack_timeout")
        for tx in acked:
            if tx.acked_at is None:
                continue
            if now - tx.acked_at > config.DONE_TIMEOUT_SECONDS:
                result = self.state.verify_command(
                    tx.command, tx.seq, tx.muted_fields, tx.expected_fields
                )
                if result.agreed:
                    with self.tx_lock:
                        self.acked.pop(tx.seq, None)
                        self.completed[tx.seq] = tx
                    if not self.state.listening:
                        self.write_queue.put("listen on")
                    continue
                if result.unverified:
                    with self.tx_lock:
                        self.acked.pop(tx.seq, None)
                    self._finish_unverified_tx(tx)
                    continue
                self._timeout_tx(tx, "done_timeout", result.disagreements)
        for tx in verifying:
            if tx.verify_deadline is None or now < tx.verify_deadline:
                continue
            with self.tx_lock:
                self.verifying.pop(tx.seq, None)
            if not self._has_post_done_frame(tx):
                self._finish_disagreeing_tx(
                    tx,
                    [
                        {
                            "field": "frame",
                            "expected": "fresh post-DONE status frame",
                            "actual": "missing",
                        }
                    ],
                    "post_done_frame_timeout",
                )
                continue
            result = self.state.verify_command(
                tx.command, tx.seq, tx.muted_fields, tx.expected_fields
            )
            if result.agreed:
                with self.tx_lock:
                    self.completed[tx.seq] = tx
                self.logger.info(
                    "seq=%s DONE verified after settle command=%s",
                    tx.seq,
                    tx.command,
                )
                continue
            if result.unverified:
                self._finish_unverified_tx(tx)
                continue
            self._finish_disagreeing_tx(tx, result.disagreements, "verify_disagree")

    def _has_post_done_frame(self, tx: CommandTx) -> bool:
        if tx.done_at is None:
            return False
        seen = self.state.frame_seen_monotonic
        return seen is not None and seen >= tx.done_at

    def _timeout_tx(
        self,
        tx: CommandTx,
        reason: str,
        disagreements: list[dict[str, Any]] | None = None,
    ) -> None:
        with self.tx_lock:
            self.in_flight.pop(tx.seq, None)
            self.acked.pop(tx.seq, None)
            self.verifying.pop(tx.seq, None)
        if tx.retries_left > 0:
            self._retry_tx(tx, reason)
            return
        self.state.surrender_command(
            tx.command, tx.seq, tx.muted_fields, disagreements or []
        )
        if not self.state.listening:
            self.write_queue.put("listen on")

    def _retry_tx(self, tx: CommandTx, reason: str) -> None:
        with self.tx_lock:
            retry_seq = self._next_seq_locked()
            retry = replace(
                tx,
                seq=retry_seq,
                retries_left=tx.retries_left - 1,
                sent_at=None,
                acked_at=None,
                done_at=None,
                verify_deadline=None,
            )
            self.in_flight[retry_seq] = retry
            if self.state.listening:
                self.write_queue.put("listen off")
            self.write_queue.put(retry)
        self.state.extend_mute(tx.muted_fields)
        self.state.note_backend_line(
            f"retry seq={retry_seq} prior_seq={tx.seq} command={tx.command} reason={reason}"
        )
        self.logger.warning(
            "seq=%s retry prior_seq=%s command=%s reason=%s",
            retry_seq,
            tx.seq,
            tx.command,
            reason,
        )
