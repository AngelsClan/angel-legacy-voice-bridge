import logging
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.diagnostics import DiagnosticLog, SwitchableLog, speech_backlog_counts


class DiagnosticTests(unittest.TestCase):
    def test_switchable_log_is_created_lazily_and_follows_the_flag(self):
        enabled = [False]
        inner = Mock(failed=False, dropped=3)
        factory = Mock(return_value=inner)
        sink = SwitchableLog(factory, lambda: enabled[0])
        sink.info("Off %d", 1)
        factory.assert_not_called()
        self.assertEqual((sink.failed, sink.dropped), (False, 0))
        enabled[0] = True
        sink.warning("On %d", 2)
        inner.warning.assert_called_once_with("On %d", 2)
        self.assertEqual(sink.dropped, 3)
        enabled[0] = False
        sink.warning("Off again")
        inner.warning.assert_called_once()

    def test_switchable_log_survives_a_failing_factory(self):
        sink = SwitchableLog(Mock(side_effect=RuntimeError("no threads")), lambda: True)
        sink.info("Record")
        self.assertTrue(sink.failed)
    def test_transient_write_failure_recovers_on_later_record(self):
        original = DiagnosticLog._write_line
        attempts = []
        def temporarily_locked(sink, text):
            attempts.append(text)
            if len(attempts) == 1:
                raise PermissionError("test file lock")
            original(sink, text)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(DiagnosticLog, "_write_line", temporarily_locked):
                sink = DiagnosticLog(Path(folder) / "bridge.log")
                sink.info("First record lost to file lock")
                sink.info("Recovery record")
                sink.close(wait=3)
                self.assertFalse(sink.failed)
                self.assertEqual(sink.dropped, 1)
                self.assertIn("Recovery record", sink.path.read_text())

    def test_unexpected_nvda_internal_exception_is_isolated(self):
        class ChangedManager:
            @property
            def _priQueues(self):
                raise RuntimeError("private implementation changed")
        speech = types.SimpleNamespace(speech=types.SimpleNamespace(_manager=ChangedManager()))
        with patch.dict(sys.modules, {"speech": speech}):
            self.assertEqual(speech_backlog_counts(), (-1, -1, -1))

    def test_records_are_flushed_and_rotation_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bridge.log"
            sink = DiagnosticLog(path, max_bytes=512)
            for number in range(100):
                sink.info("Count-only test: queue=%d completed=%d", number, number)
            sink.close(wait=3)
            self.assertTrue(sink.closed.is_set())
            self.assertFalse(sink.failed)
            self.assertIn("completed=99", path.read_text(encoding="utf-8"))
            self.assertLessEqual(len(list(Path(folder).iterdir())), 3)
            self.assertTrue(all(file.stat().st_size < 512 for file in Path(folder).iterdir()))

    def test_unwritable_destination_does_not_raise_in_caller(self):
        with tempfile.TemporaryDirectory() as folder:
            sink = DiagnosticLog(Path(folder))  # An existing directory is not a log file.
            sink.info("A diagnostic failure is not a speech failure")
            sink.close(wait=3)
            self.assertTrue(sink.closed.is_set())
            self.assertTrue(sink.failed)

    def test_slow_disk_does_not_block_speech_and_drops_excess_records(self):
        entered, release = threading.Event(), threading.Event()
        def slow_write(sink, text):
            entered.set()
            release.wait(3)
        with patch.object(DiagnosticLog, "_write_line", slow_write):
            sink = DiagnosticLog("unused.log", capacity=4)
            try:
                sink.info("First record")
                self.assertTrue(entered.wait(1))
                started = time.monotonic()
                for number in range(100):
                    sink.info("Count=%d", number)
                self.assertLess(time.monotonic() - started, .2)
                self.assertGreater(sink.dropped, 0)
            finally:
                release.set()
                sink.close(wait=3)

    def test_backlog_collects_counts_not_contents(self):
        manager = types.SimpleNamespace(
            _priQueues={0: types.SimpleNamespace(pendingSequences=["PRIVATE", "TEXT"])},
            _indexesSpeaking=[1], _indexesToCallbacks={1: object()})
        with patch.dict(sys.modules, {"speech": types.SimpleNamespace(speech=types.SimpleNamespace(_manager=manager))}):
            self.assertEqual(speech_backlog_counts(), (2, 1, 1))

    def test_future_nvda_changes_produce_unknown_counts_not_exception(self):
        with patch.dict(sys.modules, {"speech": types.SimpleNamespace(speech=object())}):
            self.assertEqual(speech_backlog_counts(), (-1, -1, -1))
