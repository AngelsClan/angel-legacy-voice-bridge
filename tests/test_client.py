from collections import deque
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient
from _alvb.protocol import Speech, Bookmark, Silence


class FakePipe:
    def __init__(self):
        self.replies = deque()
        self.sent = []
        self.closed = False
        self.auto_done = True
        self.markers = []
        self.delay = 0
        self.ready_after = 0

    def write(self, data):
        for line in data.decode().splitlines():
            fields = line.split("\t")
            self.sent.append(fields)
            if fields[0] == "HELLO":
                session = fields[2]
                name = "Test Mike".encode("utf-16-le").hex()
                token = "stable-token".encode("utf-16-le").hex()
                self.replies.append(f"READY\t2\t{session}\nVOICE\t0\t{name}\t{token}\nENDVOICES\n".encode())
            elif fields[0] == "PING":
                self.replies.append(f"PONG\t{fields[1]}\n".encode())
            elif fields[0] in ("BEGIN", "PART", "MARK", "BREAK", "COMMIT"):
                prefix = "\t".join(fields[1:4])
                self.replies.append(f"ACK\t{prefix}\n".encode())
                if fields[0] == "BEGIN":
                    self.markers = []
                    self.delay = 0
                elif fields[0] == "MARK":
                    self.markers.append(fields[4])
                elif fields[0] == "BREAK":
                    self.delay += int(fields[4]) / 1000
                elif fields[0] == "COMMIT" and self.auto_done:
                    self.ready_after = time.monotonic() + self.delay
                    for marker in self.markers:
                        self.replies.append(f"INDEX\t{prefix}\t{marker}\n".encode())
                    self.replies.append(f"DONE\t{prefix}\n".encode())

    def read(self):
        time.sleep(.002)
        if time.monotonic() < self.ready_after:
            return b""
        return self.replies.popleft() if self.replies else b""

    def close(self):
        self.closed = True


def wait_until(condition, seconds=2):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(.005)
    if not condition():
        raise AssertionError("Timed out")


class ClientTests(unittest.TestCase):
    def test_slow_refresh_warning_cannot_hold_speech_state_lock(self):
        from unittest.mock import Mock
        entered, release = threading.Event(), threading.Event()
        def slow_warning(*args):
            entered.set()
            release.wait(2)
        logger = Mock()
        logger.warning.side_effect = slow_warning
        self.client.log = logger
        try:
            with self.client._lock:
                self.client._refresh_pending = True
                self.client._last_refresh = time.monotonic() - 100
            self.assertTrue(entered.wait(2))
            acquired = self.client._lock.acquire(timeout=.1)
            self.assertTrue(acquired, "logging must not hold the state lock")
            if acquired:
                self.client._lock.release()
            started = time.monotonic()
            self.client.cancel()
            self.assertLess(time.monotonic() - started, .1)
        finally:
            release.set()

    def test_backlog_survives_lost_final_bookmarks(self):
        original = self.pipe.read
        def lose_periodic_bookmarks():
            reply = original()
            if reply.startswith(b"INDEX") and int(reply.split(b"\t")[-1]) % 3 == 0:
                return b""
            return reply
        self.pipe.read = lose_periodic_bookmarks
        for index in range(60):
            self.client.enqueue([Speech("Synthetic event"), Bookmark(index)])
        wait_until(lambda: any(event == "done" for event, data in self.events), 5)
        self.assertEqual([data[1] for event, data in self.events if event == "index"], list(range(60)))
        self.assertEqual(self.client._recovered_indexes, 20)

    def test_cancel_does_not_recover_indexes_from_old_done(self):
        self.pipe.auto_done = False
        self.client.enqueue([Speech("Canceled"), Bookmark(88)])
        wait_until(lambda: any(f[0] == "COMMIT" for f in self.pipe.sent))
        old = self.client._active
        self.client.cancel()
        self.client._process_line(["DONE", self.client._session, str(old[0]), str(old[1])])
        self.assertFalse(any(event == "index" for event, data in self.events))
        self.assertFalse(self.client._pending_indexes)

    def test_duplicate_and_unknown_indexes_are_not_forwarded(self):
        self.pipe.auto_done = False
        self.client.enqueue([Speech("Test"), Bookmark(88)])
        wait_until(lambda: any(f[0] == "COMMIT" for f in self.pipe.sent))
        active = self.client._active
        prefix = ["INDEX", self.client._session, str(active[0]), str(active[1])]
        for index in (99, 88, 88):
            self.client._process_line(prefix + [str(index)])
        self.assertEqual([data[1] for event, data in self.events if event == "index"], [88])

    def test_pause_resume_during_packet_preparation_preserves_work(self):
        entered, release = threading.Event(), threading.Event()
        from _alvb.protocol import utterance_frames
        def slow_frames(*args):
            entered.set()
            release.wait(2)
            return utterance_frames(*args)
        with patch("_alvb.client.utterance_frames", slow_frames):
            self.client.enqueue([Speech("Test"), Bookmark(17)])
            self.assertTrue(entered.wait(1))
            try:
                self.client.pause(True)
                self.client.pause(False)
            finally:
                release.set()
            wait_until(lambda: any(event == "done" for event, data in self.events))
        self.assertEqual([data[1] for event, data in self.events if event == "index"], [17])

    def test_done_recovers_missing_bookmarks_before_reporting_completion(self):
        original = self.pipe.read
        def lose_bookmark():
            reply = original()
            return b"" if reply.startswith(b"INDEX") else reply
        self.pipe.read = lose_bookmark
        self.client.enqueue([Speech("First"), Bookmark(31), Speech("Second"), Bookmark(32)])
        wait_until(lambda: any(event == "done" for event, data in self.events))
        self.assertEqual([data[1] for event, data in self.events if event == "index"], [31, 32])
        self.assertEqual(self.events[-1][0], "done")

    def test_later_bookmark_consumes_earlier_indexes_without_duplicate_completion(self):
        original = self.pipe.read
        def lose_first_bookmark():
            reply = original()
            return b"" if reply.startswith(b"INDEX") and reply.endswith(b"\t31\n") else reply
        self.pipe.read = lose_first_bookmark
        self.client.enqueue([Speech("First"), Bookmark(31), Speech("Second"), Bookmark(32)])
        wait_until(lambda: any(event == "done" for event, data in self.events))
        self.assertEqual([data[1] for event, data in self.events if event == "index"], [32])

    def test_preparing_large_utterance_does_not_block_cancel_or_enqueue(self):
        entered, release = threading.Event(), threading.Event()
        from _alvb.protocol import utterance_frames
        def slow_frames(*args):
            entered.set()
            release.wait(2)
            return utterance_frames(*args)
        with patch("_alvb.client.utterance_frames", slow_frames):
            self.client.enqueue([Speech("Large preparation"), Bookmark(91)])
            self.assertTrue(entered.wait(1))
            finished = threading.Event()
            def cancel_and_enqueue():
                self.client.cancel()
                self.client.enqueue([Speech("New request"), Bookmark(92)])
                finished.set()
            caller = threading.Thread(target=cancel_and_enqueue)
            caller.start()
            try:
                self.assertTrue(finished.wait(.2), "NVDA caller blocked by packet preparation")
            finally:
                release.set()
                caller.join(2)
        wait_until(lambda: any(event == "done" for event, data in self.events))
        self.assertEqual([data[1] for event, data in self.events if event == "index"], [92])

    def test_scan_timeout_with_live_link_retains_connection_and_stops_scans(self):
        with patch("_alvb.client.VOICE_REFRESH_TIMEOUT", .04):
            self.client._process_line(["CAPS", self.client._session, "voice-refresh"])
            self.client._last_refresh = 0
            wait_until(lambda: self.client._refresh_disabled)
        self.assertTrue(self.client.connected)
        self.assertFalse(self.client._refresh_pending)
        self.assertEqual(self.client.voices, {0: "Test Mike"})
        self.client._process_line(["CAPS", self.client._session, "voice-refresh"])
        self.assertFalse(self.client._refresh_supported)
        self.assertFalse(any(event == "disconnected" for event, data in self.events))

    def test_incomplete_scan_preserves_catalog_and_delays_next_scan(self):
        self.client.close()
        self.client.connected = True
        self.client._refresh_pending = True
        self.client._process_line(["VOICESRETRY", self.client._session])
        self.assertEqual(self.client.voices, {0: "Test Mike"})
        self.assertFalse(self.client._refresh_pending)
        self.assertGreater(self.client._last_refresh, time.monotonic() + 20)

    def test_removed_queued_voice_does_not_send_invalid_begin(self):
        self.client.close()
        self.client._stop.clear()
        self.client.connected = True
        self.client._commands.clear()
        self.client.enqueue([Speech("Test", 0)])
        self.client._catalog = {}
        pipe = FakePipe()
        self.events.clear()
        self.client._send_work(pipe)
        self.assertEqual(pipe.sent, [])
        self.assertEqual(self.events, [("voiceUnavailable", self.client.generation)])

    def test_mixer_requires_opt_in_and_capability(self):
        self.client.close()
        self.client.connected = True
        self.client._commands.clear()
        pipe = FakePipe()
        self.client.request_full_volume()
        self.client._send_work(pipe)
        self.assertEqual(pipe.sent, [])
        self.client.full_xp_volume = True
        self.client.request_full_volume()
        self.client._send_work(pipe)
        self.assertEqual(pipe.sent, [])
        self.client._process_line(["CAPS", self.client._session, "xp-volume"])
        self.client._send_work(pipe)
        self.assertEqual(pipe.sent, [["MIXER", self.client._session]])
        self.client._send_work(pipe)
        self.assertEqual(len(pipe.sent), 1)

    def test_mixer_off_cancels_pending_adjustment(self):
        self.client.close()
        self.client.connected = True
        self.client._commands.clear()
        self.client._mixer_supported = True
        self.client.full_xp_volume = True
        self.client.request_full_volume()
        self.client.full_xp_volume = False
        pipe = FakePipe()
        self.client._send_work(pipe)
        self.assertEqual(pipe.sent, [])

    def test_catalog_refresh_publishes_atomically_without_reconnect(self):
        self.client.close()
        self.events.clear()
        self.client.connected = True
        self.client._refresh_pending = True
        self.client._process_line(["READY", "2", self.client._session])
        self.assertEqual(self.client.voices, {0: "Test Mike"})
        self.client._process_line(["VOICE", "3", "New voice".encode("utf-16-le").hex(), "new-token".encode("utf-16-le").hex()])
        self.client._process_line(["ENDVOICES"])
        self.assertEqual(self.client.voices, {3: "New voice"})
        self.assertFalse(self.client._refresh_pending)
        self.assertEqual([event for event, data in self.events], ["voices"])

    def test_empty_catalog_refresh_removes_old_voices(self):
        self.client.close()
        self.client.connected = True
        self.client._process_line(["READY", "2", self.client._session])
        self.client._process_line(["ENDVOICES"])
        self.assertEqual(self.client.voices, {})

    def test_refresh_is_idle_only_and_blocks_dispatch_until_catalog_complete(self):
        self.client.close()
        self.client._stop.clear()
        self.client.connected = True
        self.client._refresh_supported = True
        self.client._last_refresh = 0
        self.pipe.sent.clear()
        self.client._send_work(self.pipe)
        self.assertTrue(self.client._refresh_pending)
        self.client.enqueue([Speech("Waiting for catalog")])
        self.client._send_work(self.pipe)
        self.assertNotIn("BEGIN", [f[0] for f in self.pipe.sent])
        self.client._process_line(["READY", "2", self.client._session])
        self.client._process_line(["VOICE", "0", "Test Mike".encode("utf-16-le").hex(), "stable-token".encode("utf-16-le").hex()])
        self.client._process_line(["ENDVOICES"])
        self.client._send_work(self.pipe)
        self.assertIn("BEGIN", [f[0] for f in self.pipe.sent])
    def test_close_rejects_new_speech(self):
        self.client.close(wait=False)
        self.assertFalse(self.client.enqueue([Speech("Do not speak")]))
        self.assertTrue(self.client.closed_event.wait(2))

    def test_missing_ack_times_out_despite_heartbeats(self):
        original = self.pipe.write
        def ignore_begin(data):
            if not data.startswith(b"BEGIN"):
                original(data)
        self.pipe.write = ignore_begin
        with patch("_alvb.client.ACK_TIMEOUT", .04):
            self.client.enqueue([Speech("Lost packet")])
            wait_until(lambda: any(event == "disconnected" for event, data in self.events))
        self.assertFalse(self.client.busy)

    def test_long_speech_uses_only_one_commit(self):
        self.client.enqueue([Speech("Words over many packets. " * 40)])
        wait_until(lambda: any(event == "done" for event, data in self.events))
        commands = [fields[0] for fields in self.pipe.sent]
        self.assertEqual(commands.count("COMMIT"), 1)
        self.assertGreater(commands.count("PART"), 1)

    def test_catalog_supports_more_than_two_voices(self):
        self.client.close()
        self.client._pending_catalog = {}
        self.client._ready_seen = True
        for index in range(12):
            self.client._process_line(["VOICE", str(index), f"Voice {index}".encode("utf-16-le").hex(),
                                       f"token-{index}".encode("utf-16-le").hex()])
        self.client._process_line(["ENDVOICES"])
        self.assertEqual(len(self.client.voices), 12)
        self.assertEqual(self.client.voices[11], "Voice 11")

    def setUp(self):
        self.pipe = FakePipe()
        self.events = []
        self.client = BridgeClient(callback=lambda event, data: self.events.append((event, data)),
                                   transport_factory=lambda name: self.pipe)
        self.client.start()
        wait_until(lambda: self.client.connected)

    def tearDown(self):
        self.client.close()

    def test_complete_and_bookmarks_in_order(self):
        self.client.enqueue([Speech("Hello"), Bookmark(3), Speech("World"), Bookmark(4)])
        wait_until(lambda: any(event == "done" for event, data in self.events))
        self.assertEqual([data[1] for event, data in self.events if event == "index"], [3, 4])

    def test_cancel_drops_queue_and_old_completion(self):
        self.pipe.auto_done = False
        self.client.enqueue([Speech("Old"), Bookmark(9), Speech("Never say this")])
        wait_until(lambda: self.client._active is not None)
        old = self.client._active
        self.client.cancel()
        self.pipe.replies.append(f"DONE\t{self.client._session}\t{old[0]}\t{old[1]}\n".encode())
        self.pipe.auto_done = True
        self.client.enqueue([Speech("New"), Bookmark(10)])
        wait_until(lambda: any(event == "done" for event, data in self.events))
        self.assertEqual([data[1] for event, data in self.events if event == "index"], [10])

    def test_pause_stops_new_speech(self):
        self.client.pause(True)
        self.client.enqueue([Speech("Waiting")])
        time.sleep(.05)
        self.assertFalse(any(fields[0] == "BEGIN" for fields in self.pipe.sent))
        self.client.pause(False)
        wait_until(lambda: any(fields[0] == "BEGIN" for fields in self.pipe.sent))

    def test_disconnected_speech_is_not_stored(self):
        self.client._disconnect("Test disconnect")
        self.assertFalse(self.client.enqueue([Speech("Must not replay")]))
        self.assertFalse(self.client._queue)

    def test_empty_sequence_finishes(self):
        self.client.enqueue([])
        wait_until(lambda: any(event == "done" for event, data in self.events))

    def test_cancel_does_not_wait_for_blocked_write(self):
        entered, release = threading.Event(), threading.Event()
        original = self.pipe.write
        def blocked(data):
            if data.startswith(b"BEGIN"):
                entered.set()
                release.wait(1)
            original(data)
        self.pipe.write = blocked
        self.client.enqueue([Speech("Block")])
        self.assertTrue(entered.wait(1))
        started = time.monotonic()
        self.client.cancel()
        elapsed = time.monotonic() - started
        release.set()
        self.assertLess(elapsed, .1)

    def test_trailing_silence_delays_done(self):
        self.client.enqueue([Silence(.08)])
        time.sleep(.02)
        self.assertFalse(any(event == "done" for event, data in self.events))
        wait_until(lambda: any(event == "done" for event, data in self.events))

    def test_callback_failure_does_not_kill_worker(self):
        def broken_callback(event, data):
            raise AssertionError("UI unavailable")
        self.client.callback = broken_callback
        self.client.enqueue([Speech("Still connected")])
        wait_until(lambda: not self.client._pending_done)
        self.assertTrue(self.client._thread.is_alive())
        self.assertTrue(self.client.connected)
        self.client.callback = lambda *args: None

    def test_voice_snapshot_is_stable(self):
        voices, tokens = self.client.voice_snapshot()
        voices[0] = "Changed locally"
        tokens[0] = "Changed locally"
        self.assertEqual(self.client.voices[0], "Test Mike")
        self.assertEqual(self.client.voice_tokens[0], "stable-token")

    def test_oversized_request_is_rejected_before_queue_growth(self):
        with self.assertRaises(ValueError):
            self.client.enqueue([Speech("x" * (120 * 2049))])
        self.assertFalse(self.client._queue)

    def test_unknown_reply_does_not_refresh_heartbeat(self):
        self.client.close()
        self.client._last_receive = 0
        self.client._process_line(["GARBAGE"])
        self.assertEqual(self.client._last_receive, 0)

    def test_resume_excludes_paused_duration(self):
        self.pipe.auto_done = False
        self.client.enqueue([Speech("Pause timing")])
        wait_until(lambda: self.client._active is not None)
        started = self.client._active[2]
        self.client.pause(True)
        self.client._pause_started -= 121
        self.client.pause(False)
        self.assertGreater(self.client._active[2], started + 120)

    def test_replacement_waits_for_previous_handle_without_ui_join(self):
        old_closed = []
        def factory(name):
            old_closed.append(self.pipe.closed)
            return FakePipe()
        self.client.close(wait=False)
        replacement = BridgeClient(transport_factory=factory, wait_for=self.client.closed_event)
        replacement.start()
        try:
            self.assertTrue(replacement.wait_connected(2))
            self.assertEqual(old_closed, [True])
        finally:
            replacement.close()

    def test_failed_thread_start_releases_handoff_barrier(self):
        client = BridgeClient(transport_factory=lambda name: FakePipe())
        with patch.object(client._thread, "start", side_effect=RuntimeError("No thread resources")):
            with self.assertRaises(RuntimeError):
                client.start()
        self.assertTrue(client.closed_event.is_set())

    def test_close_failure_still_releases_handoff_barrier(self):
        def broken_close():
            raise OSError("Test close fault")
        self.pipe.close = broken_close
        self.client.close()
        self.assertTrue(self.client.closed_event.is_set())


if __name__ == "__main__":
    unittest.main()
