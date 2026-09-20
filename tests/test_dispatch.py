import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.dispatch import MainThreadDispatch, main_thread_locations


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.pending = []
        self.now = 0
        self.deliver = Mock()
        self.log = Mock()
        self.dispatch = MainThreadDispatch(lambda fn, *args: self.pending.append((fn, args)),
                                           self.deliver, self.log, clock=lambda: self.now)

    def flush(self):
        while self.pending:
            function, args = self.pending.pop(0)
            function(*args)

    def test_does_not_deliver_in_worker_callback(self):
        self.dispatch("index", (2, 5))
        self.deliver.assert_not_called()
        self.flush()
        self.deliver.assert_called_once_with("index", (2, 5))

    def test_healthy_main_thread_does_not_emit_freeze_warning(self):
        for i in range(30):
            self.now = i
            self.dispatch("health", None)
            self.flush()
        self.log.warning.assert_not_called()

    def test_stalled_main_thread_coalesces_health_but_keeps_indexes(self):
        for i in range(30):
            self.now = i
            self.dispatch("health", None)
            self.dispatch("index", (1, i))
        self.assertEqual(len(self.pending), 31)
        self.assertEqual(self.log.warning.call_count, 2)
        self.flush()
        self.assertEqual(self.deliver.call_count, 31)
        self.log.info.assert_called_once()

    def test_schedule_failure_allows_heartbeat_retry(self):
        self.dispatch.schedule = Mock(side_effect=RuntimeError("failure"))
        with self.assertRaises(RuntimeError):
            self.dispatch("health", None)
        self.assertIsNone(self.dispatch._health_pending_since)

    def test_stack_summary_has_no_locals_or_source_text(self):
        private_value = "MUST-NOT-LOG-THIS-CONTENT"
        result = main_thread_locations(self.dispatch.main_thread)
        self.assertNotIn(private_value, result)
        self.assertNotIn(str(Path(__file__).parent), result)
        self.assertIn("test_stack_summary_has_no_locals_or_source_text", result)
