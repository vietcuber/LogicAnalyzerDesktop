import unittest

from app.protocol import PacketParser, PacketType, encode_packet


class PacketParserTests(unittest.TestCase):
    def test_parses_packet_split_across_reads(self):
        parser = PacketParser()
        frame = encode_packet(PacketType.STREAM_DATA, 7, b"\x00\x01\xFF")

        self.assertEqual(parser.feed(frame[:3]), [])
        packets = parser.feed(frame[3:])

        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].packet_type, PacketType.STREAM_DATA)
        self.assertEqual(packets[0].sequence, 7)
        self.assertEqual(packets[0].payload, b"\x00\x01\xFF")

    def test_parses_multiple_packets_and_magic_inside_payload(self):
        parser = PacketParser()
        first = encode_packet(PacketType.STREAM_DATA, 10, b"\xAA\x55\x01")
        second = encode_packet(PacketType.CAPTURE_DONE, 11, b"\xA0\x86\x01\x00")

        packets = parser.feed(first + second)

        self.assertEqual(len(packets), 2)
        self.assertEqual(packets[0].payload, b"\xAA\x55\x01")
        self.assertEqual(packets[1].packet_type, PacketType.CAPTURE_DONE)
        self.assertEqual(packets[1].payload, b"\xA0\x86\x01\x00")

    def test_ignores_noise_before_packet(self):
        parser = PacketParser()
        frame = encode_packet(PacketType.CONFIG_OK, 3)

        packets = parser.feed(b"\x00\x12noise" + frame)

        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].packet_type, PacketType.CONFIG_OK)
        self.assertEqual(packets[0].sequence, 3)


if __name__ == "__main__":
    unittest.main()