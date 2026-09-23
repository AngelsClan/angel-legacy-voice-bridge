"""Routed-audio frames must stay bounded and unambiguous on the serial link."""
import base64
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.protocol import AudioFormat, parse_audio_format, parse_audio_frame


class AudioProtocolTests(unittest.TestCase):
    def test_pcm_format_and_chunk(self):
        self.assertEqual(parse_audio_format(
            ["AUDIOFORMAT", "session", "7", "11", "22050", "16", "1"]),
            (7, 11, AudioFormat(22050, 16, 1)))
        chunk = bytes(range(256)) * 8
        encoded = base64.b64encode(chunk).decode("ascii")
        self.assertEqual(parse_audio_frame(
            ["AUDIO", "session", "7", "11", "0", encoded]), (7, 11, 0, chunk))

    def test_rejects_malformed_and_oversized_frames(self):
        for fields in (
            ["AUDIOFORMAT", "session", "7", "11", "22050", "8", "1"],
            ["AUDIOFORMAT", "session", "7", "11", "96000", "16", "1"],
            ["AUDIOFORMAT", "session", "+7", "11", "22050", "16", "1"],
            ["AUDIOFORMAT", "session", "7", "11", "22050", "16"],
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                parse_audio_format(fields)
        for payload in ("", "A===", "AAAA*", "AB==", base64.b64encode(bytes(2049)).decode("ascii")):
            with self.subTest(payload=payload[:12]), self.assertRaises(ValueError):
                parse_audio_frame(["AUDIO", "session", "7", "11", "0", payload])
        with self.assertRaises(ValueError):
            parse_audio_frame(["AUDIO", "session", "7", "11", "-1", "AAAA"])


if __name__ == "__main__":
    unittest.main()
