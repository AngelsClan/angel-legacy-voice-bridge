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
        modules = {"config": types.SimpleNamespace(), "wx": types.SimpleNamespace(CallAfter=lambda fn, *args: fn(*args)),
                   "logHandler": types.SimpleNamespace(log=Mock()), "synthDriverHandler": self.handler}
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        path = Path(__file__).resolve().parents[1] / "addon/synthDrivers/_alvb/service.py"
        spec = importlib.util.spec_from_file_location("_alvb.serviceTest", path)
        self.service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.service)
        self.service.settings = lambda: self.values
        self.service.BridgeClient = Mock()

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
