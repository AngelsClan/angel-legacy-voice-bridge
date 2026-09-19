import os
import threading
import unittest
from pathlib import Path
import sys
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.control import DisableControl, request_disable


class ControlTests(unittest.TestCase):
    def test_failed_disable_is_not_acknowledged_as_success(self):
        api = Mock()
        api.CreateEventW.side_effect = [101, 102]
        api.WaitForSingleObject.return_value = 0
        control = DisableControl(api, 123)
        with self.assertLogs("_alvb.control", level="ERROR"):
            control.poll(Mock(side_effect=OSError("Cannot restore local speech")), lambda: True)
        api.SetEvent.assert_not_called()
        self.assertFalse(control.pending)
        control.close()
    def test_ack_waits_for_worker_shutdown(self):
        api = Mock()
        api.CreateEventW.side_effect = [101, 102]
        api.WaitForSingleObject.side_effect = [0, 258]
        control = DisableControl(api, 123)
        disable = Mock()
        control.poll(disable, lambda: False)
        disable.assert_called_once()
        api.SetEvent.assert_not_called()
        control.poll(disable, lambda: True)
        api.SetEvent.assert_called_once_with(102)
        control.close()
        self.assertEqual(api.CloseHandle.call_count, 2)

    @unittest.skipUnless(os.name == "nt", "Windows named event test")
    def test_real_windows_signal_without_touching_nvda(self):
        control = DisableControl()
        stop = threading.Event()
        disabled = threading.Event()
        def poll():
            while not stop.wait(.01):
                control.poll(disabled.set, disabled.is_set)
        worker = threading.Thread(target=poll)
        worker.start()
        try:
            request_disable(os.getpid())
            self.assertTrue(disabled.is_set())
        finally:
            stop.set()
            worker.join()
            control.close()
