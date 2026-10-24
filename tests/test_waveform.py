import unittest

from app.waveform import find_channel_edges, format_time


class WaveformTests(unittest.TestCase):
    def test_finds_rising_and_falling_edges_at_sample_boundaries(self):
        samples = bytes([0, 0, 1, 1, 0, 0, 1])

        self.assertEqual(
            find_channel_edges(samples, 0),
            [(2, True), (4, False), (6, True)],
        )

    def test_edge_detection_uses_selected_channel_bit(self):
        samples = bytes([0b00000000, 0b00000010, 0b00000010, 0b00000000])

        self.assertEqual(find_channel_edges(samples, 1), [(1, True), (3, False)])
        self.assertEqual(find_channel_edges(samples, 0), [])

    def test_rejects_invalid_channel(self):
        with self.assertRaises(ValueError):
            find_channel_edges(bytes([0]), 8)

    def test_formats_time_with_scaled_units(self):
        self.assertEqual(format_time(0.00000025), "250 ns")
        self.assertEqual(format_time(0.00025), "250 us")
        self.assertEqual(format_time(0.25), "250 ms")
        self.assertEqual(format_time(2.0), "2 s")


if __name__ == "__main__":
    unittest.main()
