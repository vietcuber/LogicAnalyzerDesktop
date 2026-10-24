from dataclasses import dataclass
from enum import IntEnum
import struct


MAGIC = b"\xAA\x55"
HEADER_FORMAT = "<2sBBH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
MAX_DATA_PAYLOAD = 1024


class PacketType(IntEnum):
    STREAM_DATA = 0x01
    SNAPSHOT_DATA = 0x02
    CONFIG_OK = 0x10
    CAPTURE_STARTED = 0x11
    CAPTURE_DONE = 0x12
    ERROR = 0x7F


@dataclass(frozen=True)
class Packet:
    packet_type: PacketType
    sequence: int
    payload: bytes


class PacketParser:
    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Packet]:
        self._buffer.extend(data)
        packets = []

        while True:
            magic_index = self._buffer.find(MAGIC)

            if magic_index < 0:
                # Giữ lại AA cuối nếu magic bị chia giữa hai lần nhận.
                if self._buffer[-1:] == MAGIC[:1]:
                    self._buffer[:] = MAGIC[:1]
                else:
                    self._buffer.clear()
                break

            if magic_index > 0:
                del self._buffer[:magic_index]

            if len(self._buffer) < HEADER_SIZE:
                break

            _, raw_type, sequence, payload_length = struct.unpack_from(
                HEADER_FORMAT,
                self._buffer,
            )

            try:
                packet_type = PacketType(raw_type)
            except ValueError:
                # Header không hợp lệ: bỏ một byte rồi tìm magic tiếp theo.
                del self._buffer[0]
                continue

            if not self._valid_payload_length(packet_type, payload_length):
                del self._buffer[0]
                continue

            frame_length = HEADER_SIZE + payload_length
            if len(self._buffer) < frame_length:
                break

            payload = bytes(self._buffer[HEADER_SIZE:frame_length])
            del self._buffer[:frame_length]

            packets.append(
                Packet(
                    packet_type=packet_type,
                    sequence=sequence,
                    payload=payload,
                )
            )

        return packets

    @staticmethod
    def _valid_payload_length(packet_type: PacketType, length: int) -> bool:
        if packet_type in (PacketType.STREAM_DATA, PacketType.SNAPSHOT_DATA):
            return 0 < length <= MAX_DATA_PAYLOAD

        expected_lengths = {
            PacketType.CONFIG_OK: 0,
            PacketType.CAPTURE_STARTED: 0,
            PacketType.CAPTURE_DONE: 4,
            PacketType.ERROR: 1,
        }
        return length == expected_lengths[packet_type]


def encode_packet(
    packet_type: PacketType,
    sequence: int,
    payload: bytes = b"",
) -> bytes:
    """Tạo frame để kiểm tra parser mà chưa cần STM32."""
    header = struct.pack(
        HEADER_FORMAT,
        MAGIC,
        int(packet_type),
        sequence & 0xFF,
        len(payload),
    )
    return header + payload