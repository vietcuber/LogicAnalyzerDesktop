from queue import Empty, Queue
from threading import Event

from PySide6.QtCore import QThread, Signal
import serial

from .protocol import Packet, PacketParser, TriggerMode


class DeviceWorker(QThread):
    connected = Signal(str)
    packet_received = Signal(object)
    error = Signal(str)
    disconnected = Signal()

    def __init__(self, port_name: str):
        super().__init__()
        self.port_name = port_name
        self._commands: Queue[bytes] = Queue()
        self._stop_requested = Event()

    def configure(self, frequency: int, sample_count: int) -> None:
        command = f"CONFIGURE {frequency} {sample_count}".encode("ascii")
        self._commands.put(command)

    def start_capture(self) -> None:
        self._commands.put(b"START")

    def stop_capture(self) -> None:
        self._commands.put(b"STOP")

    def trigger(
        self,
        channel: int,
        mode: TriggerMode,
        pre_trigger_pct: int = 0,
        timeout_ms: int = 0,
    ) -> None:
        mode_name = mode.name.upper()
        command = f"TRIGGER {channel} {mode_name} {pre_trigger_pct} {timeout_ms}".encode("ascii")
        self._commands.put(command)

    def request_stop(self) -> None:
        self._stop_requested.set()

    def run(self) -> None:
        try:
            with serial.Serial(
                self.port_name,
                baudrate=115200,
                timeout=0.05,
                write_timeout=1,
            ) as port:
                port.reset_input_buffer()
                parser = PacketParser()
                self.connected.emit(self.port_name)

                while not self._stop_requested.is_set():
                    self._write_pending_commands(port)

                    chunk = port.read(4096)
                    if chunk:
                        for packet in parser.feed(chunk):
                            self.packet_received.emit(packet)
        except (serial.SerialException, OSError) as exc:
            self.error.emit(f"{self.port_name}: {exc}")
        finally:
            self.disconnected.emit()

    def _write_pending_commands(self, port: serial.Serial) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except Empty:
                return

            written = port.write(command)
            if written != len(command):
                raise serial.SerialTimeoutException(
                    f"Không gửi đủ lệnh: {written}/{len(command)} byte"
                )
            port.flush()
            if not self._commands.empty():
                self.msleep(5)
