import json
import tempfile
import unittest
from pathlib import Path

from app.capture_file import (
    ChannelLayout,
    ChannelSetting,
    load_capture,
    save_capture,
)


class CaptureFileTests(unittest.TestCase):
    def test_round_trip_preserves_metadata_and_samples(self):
        samples = bytes([0x00, 0x01, 0x80, 0xFF])
        layout = ChannelLayout(
            channels=(
                ChannelSetting(3, "CLOCK", True, 0),
                ChannelSetting(0, "DATA", True, 1),
                ChannelSetting(1, "CH1", False, 2),
                ChannelSetting(2, "CH2", True, 3),
                ChannelSetting(4, "CH4", True, 4),
                ChannelSetting(5, "CH5", True, 5),
                ChannelSetting(6, "CH6", True, 6),
                ChannelSetting(7, "CH7", True, 7),
            ),
            vertical_spacing=22,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.la"
            save_capture(path, 50_000, samples, layout)
            capture = load_capture(path)

        self.assertEqual(capture.frequency_hz, 50_000)
        self.assertEqual(capture.samples, samples)
        self.assertTrue(capture.captured_at)
        self.assertEqual(capture.channel_layout, layout)

    def test_loads_legacy_file_without_channel_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.la"
            save_capture(path, 100, bytes([0, 1]))
            document = json.loads(path.read_text(encoding="utf-8"))
            document["version"] = 1
            del document["channel_layout"]
            path.write_text(json.dumps(document), encoding="utf-8")

            capture = load_capture(path)

        self.assertIsNone(capture.channel_layout)

    def test_rejects_channel_layout_with_duplicate_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-layout.la"
            save_capture(path, 100, bytes([0, 1]))
            document = json.loads(path.read_text(encoding="utf-8"))
            document["channel_layout"]["channels"][1]["channel"] = 0
            path.write_text(json.dumps(document), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "each channel exactly once"):
                load_capture(path)

    def test_rejects_sample_count_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.la"
            save_capture(path, 100, bytes([0, 1]))
            content = path.read_text(encoding="utf-8").replace(
                '"sample_count": 2',
                '"sample_count": 3',
            )
            path.write_text(content, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Sample count mismatch"):
                load_capture(path)


if __name__ == "__main__":
    unittest.main()
