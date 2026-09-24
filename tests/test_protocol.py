import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.protocol import Bookmark, Silence, LineReader, Speech, bounded_utterances, chunks, speech_frame, utterance_frames


class ProtocolTests(unittest.TestCase):
    def test_large_nvda_request_keeps_all_text_and_bookmarks(self):
        source = [Bookmark(1), Speech("word " * 6000, voice=3), Bookmark(2)]
        batches = list(bounded_utterances(source))
        self.assertGreater(len(batches), 1)
        self.assertEqual(
            "".join(item.text for batch in batches for item in batch if isinstance(item, Speech)),
            source[1].text,
        )
        self.assertEqual(
            [item.index for batch in batches for item in batch if isinstance(item, Bookmark)],
            [1, 2],
        )
        self.assertTrue(all(len(batch) <= 256 for batch in batches))
        self.assertTrue(all(sum(len(item.text) for item in batch if isinstance(item, Speech)) <= 16000
                            for batch in batches))

    def test_packets_form_one_utterance_without_losing_text(self):
        text = "Some words, including an emoji \U0001f600. " * 30
        frames = utterance_frames("a" * 32, 1, 2, [Speech(text), Bookmark(6), Silence(.2)], 44100)
        fields = [frame.decode().strip().split("\t") for frame in frames]
        self.assertEqual(fields[0], ["BEGIN", "a" * 32, "1", "2", "0", "44100"])
        self.assertEqual([f[0] for f in fields].count("COMMIT"), 1)
        self.assertEqual("".join(bytes.fromhex(f[8]).decode("utf-16-le") for f in fields if f[0] == "PART"), text)
        self.assertEqual([f[0] for f in fields[-3:]], ["MARK", "BREAK", "COMMIT"])
        self.assertTrue(all(len(frame) < 1200 for frame in frames))

    def test_utterance_rejects_invalid_quality_and_voice_switch(self):
        for items, quality in (([Speech("a")], 123), ([Speech("a", voice=0), Speech("b", voice=1)], 0),
                               ([Speech("", rate=99)], 0)):
            with self.assertRaises(ValueError):
                utterance_frames("a" * 32, 0, 1, items, quality)

    def test_unicode_round_trip_and_no_line_injection(self):
        text = "Olá\t世界\n<hello> & \U0001f600"
        frame = speech_frame("a" * 32, 2, 8, Speech(text))
        self.assertEqual(frame.count(b"\n"), 1)
        fields = frame.decode().strip().split("\t")
        self.assertEqual(bytes.fromhex(fields[10]).decode("utf-16-le"), text)

    def test_split_and_coalesced_lines(self):
        parser = LineReader()
        self.assertEqual(parser.feed(b"REA"), [])
        self.assertEqual(parser.feed(b"DY\t1\nPONG\tx\n"), [["READY", "1"], ["PONG", "x"]])

    def test_reject_long_unterminated_frame(self):
        with self.assertRaises(ValueError):
            LineReader().feed(b"a" * 8192)

    def test_chunking_preserves_text(self):
        text = "Long speech with words. " * 100
        result = list(chunks(text))
        self.assertEqual("".join(result), text)
        self.assertTrue(all(len(part) <= 120 for part in result))

    def test_nulls_removed(self):
        self.assertEqual(list(chunks("a\x00b")), ["ab"])

    def test_xml_illegal_characters_replaced(self):
        self.assertEqual(list(chunks("a\x01b\x0cc\ufffed\uffff")), ["a b c d "])

    def test_setting_bounds(self):
        for item in (Speech("a", rate=21), Speech("a", volume=-1), Speech("a", voice=128)):
            with self.assertRaises(ValueError):
                speech_frame("a" * 32, 0, 0, item)


if __name__ == "__main__":
    unittest.main()
