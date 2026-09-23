"""Audio playback contract using a fake NVDA player, never active NVDA."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.audio import AudioPlayback
from _alvb.protocol import AudioFormat


def wait_for(predicate, timeout=1):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.005)
    if not predicate():
        raise AssertionError("Audio worker did not reach expected state")


class FakePlayer:
    def __init__(self, audio_format, device):
        self.format = audio_format
        self.device = device
        self.items = []
        self.stopped = False
        self.closed = False

    def feed(self, data, size=None, onDone=None):
        self.items.append((data, size, onDone))

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True

    def pause(self, value):
        self.items.append(("pause", value, None))


class AudioPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.players = []
        def make_player(audio_format, device):
            player = FakePlayer(audio_format, device)
            self.players.append(player)
            return player
        self.audio = AudioPlayback(lambda kind, value: self.events.append((kind, value)),
                                   lambda: "chosen-device", make_player)

    def tearDown(self):
        self.audio.close()

    def test_plays_on_requested_device_and_waits_for_playback_callbacks(self):
        self.audio.start(AudioFormat(22050, 16, 1))
        self.audio.feed(b"\x01\x00" * 100)
        self.audio.index(7)
        self.audio.finish()
        wait_for(lambda: self.players and len(self.players[0].items) == 3)
        player = self.players[0]
        self.assertEqual(player.device, "chosen-device")
        self.assertEqual(self.events, [])
        player.items[1][2]()
        player.items[2][2]()
        self.assertEqual(self.events, [("index", 7), ("done", None)])

    def test_cancel_invalidates_delayed_callbacks(self):
        self.audio.start(AudioFormat(22050, 16, 1))
        self.audio.index(5)
        self.audio.finish()
        wait_for(lambda: self.players and len(self.players[0].items) == 2)
        callbacks = [item[2] for item in self.players[0].items]
        self.audio.cancel()
        for callback in callbacks:
            callback()
        self.assertTrue(self.players[0].stopped)
        self.assertEqual(self.events, [])

    def test_probe_discards_audio_and_reports_what_was_produced(self):
        self.audio.start(AudioFormat(22050, 16, 1), probe=True)
        self.audio.feed(b"\x00\x00\x02\x00")
        self.audio.finish()
        wait_for(lambda: len(self.events) == 2)
        self.assertEqual(self.players, [])
        self.assertEqual(self.events, [("probe", (4, True)), ("done", None)])

    def test_audio_queue_has_a_finite_bound(self):
        with patch("_alvb.audio.MAX_QUEUED_AUDIO", 4):
            with self.assertRaises(BufferError):
                self.audio.feed(b"12345")

    def test_pause_before_player_creation_is_kept(self):
        self.audio.pause(True)
        self.audio.start(AudioFormat(16000, 16, 1))
        wait_for(lambda: self.players and self.players[0].items)
        self.assertEqual(self.players[0].items[0][:2], ("pause", True))


if __name__ == "__main__":
    unittest.main()
