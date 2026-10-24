import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path


FORMAT_NAME = "stm32-logic-analyzer-capture"
FORMAT_VERSION = 2
MAX_SAMPLE_COUNT = 100_000
CHANNEL_COUNT = 8
MIN_CHANNEL_SPACING = 11
MAX_CHANNEL_SPACING = 30


@dataclass(frozen=True)
class ChannelSetting:
    channel: int
    name: str
    visible: bool
    order: int


@dataclass(frozen=True)
class ChannelLayout:
    channels: tuple[ChannelSetting, ...]
    vertical_spacing: int


@dataclass(frozen=True)
class CaptureData:
    frequency_hz: int
    samples: bytes
    captured_at: str
    channel_layout: ChannelLayout | None = None


def save_capture(
    path: str | Path,
    frequency_hz: int,
    samples: bytes,
    channel_layout: ChannelLayout | None = None,
) -> None:
    if not 1 <= frequency_hz <= 2_000_000:
        raise ValueError("Sampling frequency is outside the supported range")
    if not 1 <= len(samples) <= MAX_SAMPLE_COUNT:
        raise ValueError("Sample count is outside the supported range")
    if channel_layout is None:
        channel_layout = ChannelLayout(
            channels=tuple(
                ChannelSetting(channel, f"CH{channel}", True, channel)
                for channel in range(CHANNEL_COUNT)
            ),
            vertical_spacing=15,
        )
    _validate_channel_layout(channel_layout)

    document = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "frequency_hz": frequency_hz,
        "sample_count": len(samples),
        "channel_count": 8,
        "sample_encoding": "base64; one byte per sample, bit 0 is CH0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "samples": base64.b64encode(samples).decode("ascii"),
        "channel_layout": {
            "vertical_spacing": channel_layout.vertical_spacing,
            "channels": [
                {
                    "channel": setting.channel,
                    "name": setting.name,
                    "visible": setting.visible,
                    "order": setting.order,
                }
                for setting in channel_layout.channels
            ],
        },
    }

    Path(path).write_text(
        json.dumps(document, indent=2),
        encoding="utf-8",
    )


def load_capture(path: str | Path) -> CaptureData:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Capture file root must be a JSON object")
    if document.get("format") != FORMAT_NAME:
        raise ValueError("File is not an STM32 Logic Analyzer capture")
    version = document.get("version")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version not in (1, FORMAT_VERSION)
    ):
        raise ValueError("Unsupported capture file version")
    if document.get("channel_count") != 8:
        raise ValueError("Capture file must contain 8 digital channels")

    frequency_hz = document.get("frequency_hz")
    sample_count = document.get("sample_count")
    encoded_samples = document.get("samples")
    captured_at = document.get("captured_at")

    if (
        not isinstance(frequency_hz, int)
        or isinstance(frequency_hz, bool)
        or not 1 <= frequency_hz <= 2_000_000
    ):
        raise ValueError("Invalid sampling frequency in capture file")
    if (
        not isinstance(sample_count, int)
        or isinstance(sample_count, bool)
        or not 1 <= sample_count <= MAX_SAMPLE_COUNT
    ):
        raise ValueError("Invalid sample count in capture file")
    if not isinstance(encoded_samples, str):
        raise ValueError("Capture file is missing encoded sample data")
    if not isinstance(captured_at, str):
        raise ValueError("Capture file is missing capture timestamp")

    try:
        samples = base64.b64decode(encoded_samples, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid base64 sample data") from exc

    if len(samples) != sample_count:
        raise ValueError(
            f"Sample count mismatch: metadata says {sample_count}, "
            f"data contains {len(samples)}"
        )

    channel_layout = (
        _parse_channel_layout(document.get("channel_layout"))
        if version >= 2
        else None
    )

    return CaptureData(
        frequency_hz=frequency_hz,
        samples=samples,
        captured_at=captured_at,
        channel_layout=channel_layout,
    )


def _parse_channel_layout(value: object) -> ChannelLayout:
    if not isinstance(value, dict):
        raise ValueError("Capture file is missing channel layout")

    spacing = value.get("vertical_spacing")
    channel_entries = value.get("channels")
    if (
        not isinstance(spacing, int)
        or isinstance(spacing, bool)
        or not MIN_CHANNEL_SPACING <= spacing <= MAX_CHANNEL_SPACING
    ):
        raise ValueError("Invalid channel spacing in capture file")
    if not isinstance(channel_entries, list):
        raise ValueError("Invalid channel list in capture file")

    settings = []
    for entry in channel_entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid channel entry in capture file")
        channel = entry.get("channel")
        name = entry.get("name")
        visible = entry.get("visible")
        order = entry.get("order")
        if (
            not isinstance(channel, int)
            or isinstance(channel, bool)
            or not 0 <= channel < CHANNEL_COUNT
        ):
            raise ValueError("Invalid channel index in capture file")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 64
        ):
            raise ValueError("Invalid channel name in capture file")
        if not isinstance(visible, bool):
            raise ValueError("Invalid channel visibility in capture file")
        if (
            not isinstance(order, int)
            or isinstance(order, bool)
            or not 0 <= order < CHANNEL_COUNT
        ):
            raise ValueError("Invalid channel order in capture file")
        settings.append(ChannelSetting(channel, name, visible, order))

    layout = ChannelLayout(tuple(settings), spacing)
    _validate_channel_layout(layout)
    return layout


def _validate_channel_layout(layout: ChannelLayout) -> None:
    if (
        not isinstance(layout.vertical_spacing, int)
        or isinstance(layout.vertical_spacing, bool)
        or not MIN_CHANNEL_SPACING
        <= layout.vertical_spacing
        <= MAX_CHANNEL_SPACING
    ):
        raise ValueError("Channel spacing is outside the supported range")
    if len(layout.channels) != CHANNEL_COUNT:
        raise ValueError("Channel layout must contain exactly 8 channels")

    channel_ids = set()
    orders = set()
    for setting in layout.channels:
        if (
            not isinstance(setting.channel, int)
            or isinstance(setting.channel, bool)
            or not 0 <= setting.channel < CHANNEL_COUNT
        ):
            raise ValueError("Channel index is outside the supported range")
        if (
            not isinstance(setting.name, str)
            or not setting.name.strip()
            or len(setting.name) > 64
        ):
            raise ValueError("Channel name must contain 1 to 64 characters")
        if not isinstance(setting.visible, bool):
            raise ValueError("Channel visibility must be a boolean")
        if (
            not isinstance(setting.order, int)
            or isinstance(setting.order, bool)
            or not 0 <= setting.order < CHANNEL_COUNT
        ):
            raise ValueError("Channel order is outside the supported range")
        channel_ids.add(setting.channel)
        orders.add(setting.order)

    if channel_ids != set(range(CHANNEL_COUNT)):
        raise ValueError("Channel layout must include each channel exactly once")
    if orders != set(range(CHANNEL_COUNT)):
        raise ValueError("Channel order must include each position exactly once")