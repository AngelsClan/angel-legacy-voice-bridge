"""Exercise real service ownership without importing or changing active NVDA."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import DEFAULT_PIPE


class ServiceTests(unittest.TestCase):
    def test_disable_cannot_claim_success_when_local_synth_load_returns_false(self):
        self.service.ensure_client()
        self.handler.getSynth.return_value = types.SimpleNamespace(name="angelLegacyVoiceBridge")
        self.handler.setSynth.return_value = False
        with self.assertRaises(RuntimeError):
            self.service.disable()
        self.assertIsNone(self.service.client)
        self.assertFalse(self.values["active"])

    def setUp(self):
        self.values = dict(active=True, enabled=True, mirror=True, autoReturn=True, fullXPVolume=False, pipe=DEFAULT_PIPE, quality=0)
        self.handler = types.SimpleNamespace(getSynth=Mock(return_value=types.SimpleNamespace(name="ibmeci")), setSynth=Mock(),
            changeVoice=lambda synth, voice: setattr(synth, "voice", voice))
        self.pending = []
        modules = {"config": types.SimpleNamespace(),
                   "queueHandler": types.SimpleNamespace(eventQueue=Mock(), queueFunction=lambda queue, fn, *args: self.pending.append((fn, args))),
                   "logHandler": types.SimpleNamespace(log=Mock()), "synthDriverHandler": self.handler}
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        path = Path(__file__).resolve().parents[1] / "addon/synthDrivers/_alvb/service.py"
        spec = importlib.util.spec_from_file_location("_alvb.serviceTest", path)
        self.service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.service)
        self.service.settings = lambda: self.values
        self.real_diagnostics = self.service.diagnostics
        self.service.diagnostics = Mock(return_value=Mock())
        self.service.BridgeClient = Mock()

    def test_diagnostic_construction_failure_uses_disabled_sink(self):
        state = types.SimpleNamespace(WritePaths=types.SimpleNamespace(configDir="unused"))
        with patch.dict(sys.modules, {"NVDAState": state}):
            with patch.object(self.service, "DiagnosticLog", side_effect=RuntimeError("no threads")):
                sink = self.real_diagnostics()
                self.assertTrue(sink.failed)
                sink.info("Test record")
                self.assertIs(self.real_diagnostics(), sink)

    def test_monitor_start_failure_can_be_retried(self):
        with patch.object(self.service.MainThreadDispatch, "start_monitor", side_effect=RuntimeError("no threads")):
            with self.assertRaises(RuntimeError):
                self.service.start_diagnostics()
        self.assertIsNone(self.service.monitor_stopped)

    def test_diagnostics_does_not_connect_or_change_synth(self):
        with patch.object(self.service.MainThreadDispatch, "start_monitor") as start:
            self.service.start_diagnostics()
            self.service.start_diagnostics()
            start.assert_called_once()
            stopped = start.call_args.args[0]
            self.service.stop_diagnostics()
            self.assertTrue(stopped.is_set())
        self.service.BridgeClient.assert_not_called()
        self.handler.setSynth.assert_not_called()

    def test_diagnostic_tick_with_bridge_off_records_counts_only(self):
        with patch.object(self.service, "speech_backlog_counts", return_value=(12, 2, 1)):
            self.service._diagnostic_tick("health", None)
        self.assertIsNone(self.service.client)
        self.service.diagnostics.return_value.info.assert_called_once()
        self.service.BridgeClient.assert_not_called()

    def test_unknown_idle_backlog_does_not_churn_log(self):
        with patch.object(self.service, "speech_backlog_counts", return_value=(-1, -1, -1)) as counts:
            with patch.object(self.service.time, "monotonic") as clock:
                for second in range(100, 160):
                    clock.return_value = second
                    self.service._diagnostic_tick("health", None)
        self.assertEqual(counts.call_count, 12)
        self.service.diagnostics.return_value.info.assert_called_once()

    def test_retired_monitor_cannot_deliver_after_plugin_reload(self):
        with patch.object(self.service.MainThreadDispatch, "start_monitor"):
            with patch.object(self.service, "_diagnostic_tick") as tick:
                with patch.object(self.service, "MainThreadDispatch", wraps=self.service.MainThreadDispatch) as factory:
                    self.service.start_diagnostics()
                    deliver = factory.call_args.args[1]
                    self.service.stop_diagnostics()
                    self.service.start_diagnostics()
                    deliver("health", None)
                    tick.assert_not_called()
                    self.service.stop_diagnostics()

    def test_startup_callback_waits_for_nvda_queue_without_wx(self):
        source = self.service.ensure_client()
        listener = Mock()
        self.service.listeners.append(listener)
        source.callback("connected", None)
        listener.assert_not_called()
        function, args = self.pending.pop()
        function(*args)
        listener.assert_called_once_with("connected", None)

    def test_queued_callback_after_disable_cannot_restore_bridge(self):
        source = self.service.ensure_client()
        listener = Mock()
        self.service.listeners.append(listener)
        source.callback("connected", None)
        self.service.stop()
        function, args = self.pending.pop()
        function(*args)
        listener.assert_not_called()

    def arm(self):
        source = self.service.ensure_client()
        source.connected = True
        source.voice_tokens = {0: "original-voice"}
        local = types.SimpleNamespace(name="espeak")
        self.handler.getSynth.return_value = local
        self.service.arm_recovery(source, local, dict(voice="original-voice", rate=65, pitch=45, volume=80))
        return source

    def test_recovery_restores_original_voice_and_settings(self):
        source = self.arm()
        restored = types.SimpleNamespace(name="angelLegacyVoiceBridge", saveSettings=Mock())
        def select(name):
            self.handler.getSynth.return_value = restored
            return True
        self.handler.setSynth.side_effect = select
        self.service._deliver(source, "connected", {})
        self.handler.setSynth.assert_called_once_with("angelLegacyVoiceBridge")
        self.assertEqual(restored.voice, "original-voice")
        self.assertEqual(restored.rate, 65)
        self.assertIsNone(self.service.recovery)

    def test_repeated_automatic_returns_are_capped(self):
        import time
        self.service.automatic_returns.extend([time.monotonic()] * 3)
        self.arm()
        self.assertIsNone(self.service.recovery)

    def test_test_overrides_restore_saved_client_settings(self):
        source = self.service.ensure_client()
        self.service.testing = True
        source.quality = 48000
        source.full_xp_volume = True
        self.service.finish_test()
        self.assertEqual(source.quality, 0)
        self.assertFalse(source.full_xp_volume)
        self.assertFalse(self.service.testing)

    def test_stop_acknowledgement_waits_for_all_retiring_workers(self):
        first = self.service.ensure_client()
        first.closed_event.is_set.return_value = False
        self.service.stop()
        second = Mock()
        second.closed_event.is_set.return_value = True
        self.service.client = second
        self.service.stop()
        self.assertFalse(self.service.is_stopped())
        first.closed_event.is_set.return_value = True
        self.assertTrue(self.service.is_stopped())

    def test_manual_selection_cancels_return_even_when_selecting_espeak_again(self):
        source = self.arm()
        self.service.clear_recovery(synth=types.SimpleNamespace(name="espeak"))
        self.service._deliver(source, "connected", {})
        self.handler.setSynth.assert_not_called()

    def test_disable_or_preference_off_prevents_return(self):
        source = self.arm()
        self.values["autoReturn"] = False
        self.service._deliver(source, "connected", {})
        self.handler.setSynth.assert_not_called()
        self.values["autoReturn"] = True
        self.arm()
        self.service.disable()
        self.assertIsNone(self.service.recovery)

    def test_return_waits_for_missing_voice(self):
        source = self.arm()
        source.voice_tokens = {}
        self.service.try_recovery()
        self.handler.setSynth.assert_not_called()
        self.assertIsNotNone(self.service.recovery)

    def test_failed_return_is_not_repeated_forever(self):
        self.arm()
        self.handler.setSynth.return_value = False
        self.service.try_recovery()
        self.service.try_recovery()
        self.handler.setSynth.assert_called_once()

    def test_manual_local_voice_change_cancels_pending_return(self):
        self.arm()
        self.handler.getSynth.return_value.voice = "another-local-voice"
        self.service.try_recovery()
        self.handler.setSynth.assert_not_called()
        self.assertIsNone(self.service.recovery)

    def test_disable_stops_owned_worker_and_keeps_local_synth(self):
        client = self.service.ensure_client()
        self.service.testing = True
        self.service.disable()
        client.close.assert_called_once_with(wait=False)
        self.assertIsNone(self.service.client)
        self.assertFalse(self.service.testing)
        self.assertFalse(any(self.values[key] for key in ("active", "enabled", "mirror")))
        self.handler.setSynth.assert_not_called()

    def test_disable_restores_local_speech_only_if_bridge_selected(self):
        self.handler.getSynth.return_value.name = "angelLegacyVoiceBridge"
        self.service.disable()
        self.handler.setSynth.assert_called_once_with("espeak")

    def test_automatic_discovery_only_chooses_unambiguous_match(self):
        candidate = DEFAULT_PIPE + "-example"
        with patch("_alvb.pipe.discover_pipes", return_value=[candidate]):
            self.service.ensure_client()
        self.assertEqual(self.values["pipe"], candidate)
        self.service.stop()
        self.values["pipe"] = DEFAULT_PIPE
        with patch("_alvb.pipe.discover_pipes", return_value=[candidate, candidate + "2"]):
            self.service.ensure_client()
        self.assertEqual(self.values["pipe"], DEFAULT_PIPE)

    def test_old_done_cannot_end_new_test(self):
        client = self.service.ensure_client()
        client.generation = 4
        self.service.testing = True
        self.service._deliver(client, "done", 3)
        self.assertTrue(self.service.testing)
        self.service._deliver(client, "done", 4)
        self.assertFalse(self.service.testing)
