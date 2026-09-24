"""Exercise real service ownership without importing or changing active NVDA."""
import importlib.util
from pathlib import Path
import sys
import threading
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
        self.values = dict(active=True, enabled=True, mirror=True, autoReturn=True, fullXPVolume=False, pipe=DEFAULT_PIPE, quality=0, announceStatus=True)
        self.handler = types.SimpleNamespace(getSynth=Mock(return_value=types.SimpleNamespace(name="ibmeci")), setSynth=Mock(),
            changeVoice=lambda synth, voice: setattr(synth, "voice", voice))
        self.pending = []
        self.cancel_speech = Mock()
        self.config = types.SimpleNamespace()
        self.ui = types.SimpleNamespace(message=Mock())
        modules = {"config": self.config, "ui": self.ui,
                   "speech": types.SimpleNamespace(cancelSpeech=self.cancel_speech),
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
        # A module-local clock: recovery timing is tested without sleeping.
        self.now = 1000.0
        self.service.time = types.SimpleNamespace(monotonic=lambda: self.now)

    def test_background_connection_announcements_can_be_disabled(self):
        source = types.SimpleNamespace(connected=True, generation=1)
        self.service.client = source
        self.service.try_recovery = Mock()
        self.service._deliver(source, "connected", None)
        self.ui.message.assert_called_once_with("XP voice bridge connected")
        self.service.recovery_event = Mock()
        source.connected = False
        self.service._deliver(source, "disconnected", "test")
        self.service._deliver(source, "disconnected", "test")
        self.ui.message.assert_any_call("XP voice bridge disconnected")
        self.assertEqual(self.ui.message.call_count, 2)
        self.values["announceStatus"] = False
        self.ui.message.reset_mock()
        source.connected = True
        self.service._deliver(source, "connected", None)
        self.ui.message.assert_not_called()

    def test_diagnostic_construction_failure_uses_disabled_sink(self):
        state = types.SimpleNamespace(WritePaths=types.SimpleNamespace(configDir="unused"))
        with patch.dict(sys.modules, {"NVDAState": state}):
            with patch.object(self.service, "DiagnosticLog", side_effect=RuntimeError("no threads")):
                sink = self.real_diagnostics()
                sink.info("Test record")
                self.assertTrue(sink.failed)
                self.assertIs(self.real_diagnostics(), sink)

    def test_diagnostics_preference_off_writes_nothing_and_creates_no_file(self):
        self.values["diagnostics"] = False
        self.service.refresh_diagnostics_preference()
        state = types.SimpleNamespace(WritePaths=types.SimpleNamespace(configDir="unused"))
        with patch.dict(sys.modules, {"NVDAState": state}), patch.object(self.service, "DiagnosticLog") as factory:
            sink = self.real_diagnostics()
            sink.warning("Failure snapshot: %d", 1)
            factory.assert_not_called()
            self.values["diagnostics"] = True
            self.service.refresh_diagnostics_preference()
            sink.warning("Failure snapshot: %d", 2)
            factory.assert_called_once()
            factory.return_value.warning.assert_called_once_with("Failure snapshot: %d", 2)
            self.values["diagnostics"] = False
            self.service.refresh_diagnostics_preference()
            sink.info("Ignored")
            factory.return_value.info.assert_called_once()  # only the start-up line

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

    def test_retired_instance_cannot_stop_its_replacement(self):
        # The observed failure: diagnostics went silent for hours while NVDA
        # kept running. A late terminate must only stop its own monitor.
        with patch.object(self.service.MainThreadDispatch, "start_monitor"):
            live = self.service.start_diagnostics()
            stale = threading.Event()
            self.service.stop_diagnostics(stale)
            self.assertIs(self.service.monitor_stopped, live)
            self.assertFalse(live.is_set())
            self.assertTrue(stale.is_set())
            self.service.stop_diagnostics(live)
            self.assertIsNone(self.service.monitor_stopped)

    def test_dead_monitor_thread_is_replaced_rather_than_left_silent(self):
        dead = Mock()
        dead.is_alive.return_value = False
        with patch.object(self.service.MainThreadDispatch, "start_monitor", return_value=dead) as start:
            first = self.service.start_diagnostics()
            second = self.service.start_diagnostics()
        self.assertEqual(start.call_count, 2)
        self.assertIsNot(first, second)
        self.assertTrue(first.is_set())
        self.service.stop_diagnostics()

    def test_idle_bridge_synth_does_not_log_every_tick(self):
        selected = Mock()
        selected.name = "angelLegacyVoiceBridge"
        self.handler.getSynth.return_value = selected
        with patch.object(self.service, "speech_backlog_counts", return_value=(0, 0, 0)):
            with patch.object(self.service.time, "monotonic") as clock:
                for second in range(200, 260):
                    clock.return_value = second
                    self.service._diagnostic_tick("health", None)
        # Once for the change to bridge_selected, once for the minute mark.
        self.assertLessEqual(self.service.diagnostics.return_value.info.call_count, 2)

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

    def arm(self, voice_tokens=None):
        source = self.service.ensure_client()
        source.connected = True
        source.busy = False
        source._route_active = "xp"
        source._silent_probe_supported = True
        source.generation = 7
        source.enqueue.return_value = True
        source.voice_tokens = {0: "other-voice", 3: "original-voice"} if voice_tokens is None else voice_tokens
        local = types.SimpleNamespace(name="espeak")
        self.handler.getSynth.return_value = local
        self.service.arm_recovery(source, local, dict(voice="original-voice", rate=65, pitch=45, volume=80))
        return source

    def advance(self, seconds):
        self.now += seconds
        self.service._deliver(self.service.client, "health", None)

    def render(self, source):
        """Wait for the first check, then report its final bookmark."""
        self.advance(self.service.recovery.delay)
        self.service._deliver(source, "observedIndex", (source.generation, self.service.PROBE_INDEX))
        self.service._deliver(source, "audioProduced", (source.generation, 400, True))

    def restorable(self):
        restored = types.SimpleNamespace(name="angelLegacyVoiceBridge", saveSettings=Mock())
        def select(name):
            self.handler.getSynth.return_value = restored
            return True
        self.handler.setSynth.side_effect = select
        return restored

    def test_handshake_alone_never_returns(self):
        source = self.arm()
        self.service._deliver(source, "connected", {})
        for second in range(4):
            self.advance(1)
        source.enqueue.assert_not_called()
        self.advance(2)
        self.service._deliver(source, "voices", {})
        self.advance(1)
        self.handler.setSynth.assert_not_called()
        self.cancel_speech.assert_not_called()
        source.enqueue.assert_called_once()

    def test_check_is_silent_fixed_text_in_original_voice(self):
        source = self.arm()
        self.advance(5)
        speech, mark = source.enqueue.call_args.args[0]
        self.assertEqual((speech.text, speech.voice, speech.volume, speech.rate, speech.pitch),
                         (self.service.PROBE_TEXT, 3, 100, 13, 9))
        self.assertEqual(mark.index, self.service.PROBE_INDEX)

    def test_old_helper_cannot_run_audible_recovery_check(self):
        source = self.arm()
        source._silent_probe_supported = False
        self.advance(5)
        source.enqueue.assert_not_called()
        self.assertIsNone(self.service.recovery)
        self.handler.setSynth.assert_not_called()

    def test_recovery_restores_original_voice_after_verified_render(self):
        source = self.arm()
        restored = self.restorable()
        self.render(source)
        self.handler.setSynth.assert_not_called()
        self.advance(1)
        self.handler.setSynth.assert_called_once_with("angelLegacyVoiceBridge")
        self.assertEqual(restored.voice, "original-voice")
        self.assertEqual((restored.rate, restored.volume, restored.pitch), (65, 80, 45))
        self.assertIsNone(self.service.recovery)
        self.cancel_speech.assert_called_once()
        self.ui.message.assert_called_once_with("Bridge voice recovered.")

    def test_routed_recovery_requires_pcm_and_playback_completion(self):
        source = self.arm()
        source._route_active = "nvda"
        self.restorable()
        self.advance(5)
        self.service._deliver(source, "observedIndex", (7, self.service.PROBE_INDEX))
        self.advance(1)
        self.assertIsNone(self.service.recovery.verified_at)
        source.busy = True
        self.service._deliver(source, "audioProduced", (7, 400, False))
        self.assertIsNone(self.service.recovery.verified_at)
        self.service._deliver(source, "audioProduced", (7, 400, True))
        self.assertIsNotNone(self.service.recovery.verified_at)
        self.advance(1)
        self.handler.setSynth.assert_not_called()
        source.busy = False
        self.advance(self.service.IDLE_WAIT)
        self.handler.setSynth.assert_called_once_with("angelLegacyVoiceBridge")

    def test_delayed_recovery_after_failed_checks(self):
        source = self.arm()
        restored = self.restorable()
        self.advance(5)
        self.service._deliver(source, "disconnected", "gone")
        self.assertEqual(self.service.recovery.delay, 10)
        source.connected = False
        self.advance(10)
        self.advance(30)
        self.assertEqual(source.enqueue.call_count, 1)
        source.connected = True
        source.generation = 9
        self.advance(1)
        self.assertEqual(source.enqueue.call_count, 2)
        self.service._deliver(source, "observedIndex", (9, self.service.PROBE_INDEX))
        self.service._deliver(source, "audioProduced", (9, 400, True))
        self.advance(1)
        self.assertIs(self.handler.getSynth(), restored)

    def test_engine_failure_during_check_backs_off_and_is_bounded(self):
        source = self.arm()
        for attempt in range(40):
            self.advance(61)
            if self.service.recovery is None:
                break
            self.service._deliver(source, "disconnected", "sapi-engine-failed")
        self.assertIsNone(self.service.recovery)
        self.assertLessEqual(source.enqueue.call_count, self.service.MAX_PROBES)
        self.handler.setSynth.assert_not_called()
        self.ui.message.assert_called_once_with("Bridge voice did not recover. Staying on eSpeak.")

    def test_unanswered_check_times_out_as_failure(self):
        source = self.arm()
        self.advance(5)
        self.advance(self.service.PROBE_TIMEOUT + 1)
        self.assertIsNone(self.service.recovery.probe_generation)
        self.assertEqual(self.service.recovery.delay, 10)
        self.service._deliver(source, "observedIndex", (7, self.service.PROBE_INDEX))
        self.advance(1)
        self.handler.setSynth.assert_not_called()

    def test_cancelled_check_is_not_success(self):
        source = self.arm()
        self.advance(5)
        source.generation = 8  # Mirroring or a test cancelled the silent check.
        self.advance(1)
        self.service._deliver(source, "observedIndex", (8, self.service.PROBE_INDEX))
        self.advance(1)
        self.handler.setSynth.assert_not_called()
        self.assertIsNone(self.service.recovery.verified_at)

    def test_stale_callbacks_cannot_verify(self):
        source = self.arm()
        self.advance(5)
        self.service._deliver(source, "observedIndex", (7, 12))
        self.service._deliver(Mock(), "observedIndex", (7, self.service.PROBE_INDEX))
        self.service.recovery_event(Mock(), "observedIndex", (7, self.service.PROBE_INDEX))
        self.advance(1)
        self.assertIsNone(self.service.recovery.verified_at)
        self.handler.setSynth.assert_not_called()

    def test_reconstructed_bookmark_does_not_verify_recovery(self):
        source = self.arm()
        self.advance(5)
        # The client emits ordinary index for a bookmark recovered from DONE.
        self.service._deliver(source, "index", (7, self.service.PROBE_INDEX))
        self.advance(1)
        self.assertIsNone(self.service.recovery.verified_at)
        self.handler.setSynth.assert_not_called()

    def test_total_window_is_bounded_even_while_disconnected(self):
        source = self.arm()
        source.connected = False
        for minute in range(16):
            self.advance(60)
        self.assertIsNone(self.service.recovery)
        source.enqueue.assert_not_called()
        self.ui.message.assert_called_once()

    def test_verified_return_waits_briefly_for_local_speech_to_finish(self):
        source = self.arm()
        self.restorable()
        with patch.object(self.service, "speech_backlog_counts", return_value=(3, 1, 0)):
            self.render(source)
            self.advance(4)
            self.handler.setSynth.assert_not_called()
            self.advance(5)
        self.handler.setSynth.assert_called_once_with("angelLegacyVoiceBridge")

    def test_connection_lost_after_check_requires_new_check(self):
        source = self.arm()
        self.render(source)
        source.connected = False
        self.advance(1)
        self.handler.setSynth.assert_not_called()
        self.assertIsNone(self.service.recovery.verified_at)

    def test_recovery_respects_profile_change_during_cancellation(self):
        source = self.arm()
        def change_profile():
            self.handler.getSynth.return_value = types.SimpleNamespace(name="ibmeci")
        self.cancel_speech.side_effect = change_profile
        self.render(source)
        self.advance(1)
        self.handler.setSynth.assert_not_called()
        self.assertIsNone(self.service.recovery)

    def test_profile_switch_that_keeps_espeak_cancels_return(self):
        self.config.conf = types.SimpleNamespace(profiles=[types.SimpleNamespace(name=None)])
        source = self.arm()
        self.config.conf.profiles.append(types.SimpleNamespace(name="Reading"))
        self.render(source)
        self.advance(1)
        self.handler.setSynth.assert_not_called()
        self.assertIsNone(self.service.recovery)

    def test_repeated_automatic_returns_are_capped_and_announced(self):
        self.service.automatic_returns.extend([self.now - 500] * 3)
        self.arm()
        self.assertIsNone(self.service.recovery)
        self.ui.message.assert_called_once_with("Bridge failed repeatedly. Staying on eSpeak.")

    def test_recent_returns_lengthen_first_wait(self):
        self.service.automatic_returns.extend([self.now - 30, self.now - 20])
        source = self.arm()
        self.assertEqual(self.service.recovery.delay, 20)
        self.advance(19)
        source.enqueue.assert_not_called()

    def test_repeated_failure_cycle_stops_after_limit(self):
        for cycle in range(5):
            source = self.arm()
            if self.service.recovery is None:
                break
            self.restorable()
            self.render(source)
            self.advance(1)
            self.handler.setSynth.side_effect = None
        self.assertEqual(self.handler.setSynth.call_count, self.service.RETURN_LIMIT)
        self.assertIsNone(self.service.recovery)

    def test_disabling_return_during_check_ignores_late_result(self):
        source = self.arm()
        self.advance(5)
        self.values["autoReturn"] = False
        self.advance(1)
        self.assertIsNone(self.service.recovery)
        self.values["autoReturn"] = True
        self.service._deliver(source, "observedIndex", (7, self.service.PROBE_INDEX))
        self.advance(1)
        self.handler.setSynth.assert_not_called()

    def test_another_local_synth_cancels_return(self):
        source = self.arm()
        self.handler.getSynth.return_value = types.SimpleNamespace(name="windtalker")
        self.render(source)
        self.advance(1)
        self.handler.setSynth.assert_not_called()
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
        self.advance(5)
        # NVDA creates a new eSpeak instance and notifies synthChanged.
        self.service.clear_recovery(synth=types.SimpleNamespace(name="espeak"))
        self.service._deliver(source, "observedIndex", (7, self.service.PROBE_INDEX))
        self.advance(10)
        self.handler.setSynth.assert_not_called()
        self.assertIsNone(self.service.recovery)

    def test_disable_or_preference_off_prevents_return(self):
        source = self.arm()
        self.values["autoReturn"] = False
        self.render(source)
        self.advance(1)
        self.handler.setSynth.assert_not_called()
        self.values["autoReturn"] = True
        self.arm()
        self.service.disable()
        self.assertIsNone(self.service.recovery)

    def test_return_waits_for_missing_voice(self):
        source = self.arm(voice_tokens={})
        self.advance(30)
        source.enqueue.assert_not_called()
        self.handler.setSynth.assert_not_called()
        self.assertIsNotNone(self.service.recovery)

    def test_failed_return_is_not_repeated_forever(self):
        source = self.arm()
        self.handler.setSynth.return_value = False
        self.render(source)
        self.advance(1)
        self.advance(60)
        self.handler.setSynth.assert_called_once()

    def test_manual_local_voice_change_cancels_pending_return(self):
        self.arm()
        self.handler.getSynth.return_value.voice = "another-local-voice"
        self.advance(5)
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
