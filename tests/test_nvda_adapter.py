"""NVDA adapter contract tests with isolated API doubles, not a live NVDA UI.

The mapping double deliberately has no .update(), matching AggregatedSection.
These tests must never import/configure the user's running screen reader.
"""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon/synthDrivers"))


class Settings:
    def __init__(self):
        self.values = dict(active=True, quality=0, autoReturn=False, fullXPVolume=False, enabled=True, speechRoute="xp", pipe=r"\\.\pipe\AngelLegacySpeech-test",
                           mirror=True, mirrorVoice="token", mirrorRate=50,
                           mirrorVolume=100, fallback=True, diagnostics=True)

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        self.values[key] = value


class Control:
    def __init__(self, value):
        self.value = value

    def GetValue(self):
        return self.value

    def GetSelection(self):
        return self.value

    def SetValue(self, value):
        self.value = value


class Base:
    def terminate(self):
        self.base_terminated = True

    VoiceSetting = RateSetting = PitchSetting = VolumeSetting = staticmethod(lambda: object())


def module(name, **attributes):
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    return result


class AdapterTests(unittest.TestCase):
    def test_toggle_command_switches_auto_return_and_announces(self):
        plugin = self.plugin.GlobalPlugin()
        message = self.plugin.ui.message
        plugin.script_toggleAutoReturn(None)
        self.assertTrue(self.settings["autoReturn"])
        message.assert_called_with("Automatic return to the bridge on")
        self.service.clear_recovery.assert_not_called()
        plugin.script_toggleAutoReturn(None)
        self.assertFalse(self.settings["autoReturn"])
        message.assert_called_with("Automatic return to the bridge off")
        self.service.clear_recovery.assert_called_once_with()
        plugin.terminate()

    def test_profile_switch_cancels_pending_return_for_plugin_lifetime(self):
        plugin = self.plugin.GlobalPlugin()
        self.profile_switch.register.assert_called_once_with(self.service.clear_recovery)
        plugin.terminate()
        self.profile_switch.unregister.assert_called_once_with(self.service.clear_recovery)

    def test_failed_diagnostics_and_startup_preserve_plugin_controls(self):
        self.service.start_diagnostics.side_effect = RuntimeError("No thread resources")
        self.service.ensure_client.side_effect = RuntimeError("No transport resources")
        plugin = self.plugin.GlobalPlugin()
        self.assertTrue(plugin.registered)
        self.assertIn(self.plugin.BridgePanel, self.plugin.NVDASettingsDialog.categoryClasses)
        plugin.pollControl()  # Missing maintenance control is safe too.
        plugin.terminate()
        self.assertNotIn(self.plugin.BridgePanel, self.plugin.NVDASettingsDialog.categoryClasses)

    def test_disabling_mirror_cancels_immediately(self):
        panel = self.panel()
        panel.onMirror(None)
        self.assertFalse(self.settings["mirror"])
        self.client.cancel.assert_called_once()

    def test_master_off_blocks_mirror_even_when_mirror_flag_remains(self):
        self.settings["active"] = False
        plugin = self.plugin.GlobalPlugin.__new__(self.plugin.GlobalPlugin)
        plugin.onSpeech(["Must not leak into the bridge"])
        self.client.enqueue.assert_not_called()

    def test_test_speech_does_not_collect_mirrored_settings_announcements(self):
        self.service.testing = True
        plugin = self.plugin.GlobalPlugin.__new__(self.plugin.GlobalPlugin)
        plugin.onSpeech(["Settings announcement"])
        self.client.enqueue.assert_not_called()

    def test_idle_stop_test_does_not_cancel_unrelated_speech(self):
        self.panel().onStop(None)
        self.client.cancel.assert_not_called()

    def test_disable_button_updates_all_three_controls(self):
        panel = self.panel()
        panel.onDisable(None)
        self.service.disable.assert_called_once()
        self.assertFalse(panel.active.GetValue())
        self.assertFalse(panel.enabled.GetValue())
        self.assertFalse(panel.mirror.GetValue())

    def setUp(self):
        self.settings = Settings()
        self.client = Mock(connected=True, voices={0: "Test Mike"}, voice_tokens={0: "token"})
        self.client.voice_snapshot.return_value = ({0: "Test Mike"}, {0: "token"})
        self.service = module("service", settings=lambda: self.settings, client=self.client,
                              ensure_client=Mock(return_value=self.client), stop=Mock(),
                              start_diagnostics=Mock(), stop_diagnostics=Mock(),
                              listeners=[], testing=False, disable=Mock(), finish_test=Mock(), arm_recovery=Mock(), clear_recovery=Mock(), refresh_diagnostics_preference=Mock(),
                              diagnostics=Mock(return_value=Mock()), speech_backlog_counts=Mock(return_value=(30000, 1, 0)))
        self.handler = module("synthDriverHandler", SynthDriver=Base,
                              getSynth=Mock(return_value=types.SimpleNamespace(name="espeak")),
                              setSynth=Mock(), VoiceInfo=lambda token, name: (token, name),
                              synthIndexReached=Mock(), synthDoneSpeaking=Mock(), synthChanged=Mock())
        self.gui = module("gui", guiHelper=Mock(), messageBox=Mock())
        self.variables = module("globalVars", appArgs=types.SimpleNamespace(secure=False), settingsRing=Mock())
        self.wx = module("wx", CallAfter=lambda function, *args: function(*args))
        sequence = module("sequence", SUPPORTED_COMMANDS=set(), translate=Mock(return_value=[]))
        from _alvb import protocol
        from _alvb import formats
        package = module("synthDrivers", __path__=[str(ROOT / "addon/synthDrivers")])
        shared = module("synthDrivers._alvb", __path__=[], service=self.service)
        speech_extensions = types.SimpleNamespace(pre_speechQueued=Mock(), speechCanceled=Mock(), post_speechPaused=Mock())
        self.cancel_speech = Mock()
        self.profile_switch = Mock()
        modules = {
            "config": module("config", post_configProfileSwitch=self.profile_switch),
            "autoSettingsUtils": module("autoSettingsUtils", __path__=[]),
            "autoSettingsUtils.driverSetting": module("autoSettingsUtils.driverSetting",
                DriverSetting=lambda id, label, **options: types.SimpleNamespace(id=id, label=label, **options)),
            "autoSettingsUtils.utils": module("autoSettingsUtils.utils",
                StringParameterInfo=lambda id, label: types.SimpleNamespace(id=id, displayName=label)),
            "globalPluginHandler": module("globalPluginHandler", GlobalPlugin=Base),
            "globalVars": self.variables, "gui": self.gui,
            "gui.settingsDialogs": module("gui.settingsDialogs", SettingsPanel=Base,
                NVDASettingsDialog=types.SimpleNamespace(categoryClasses=[])),
            "scriptHandler": module("scriptHandler", script=lambda **kwargs: lambda function: function),
            "speech": module("speech", extensions=speech_extensions, cancelSpeech=self.cancel_speech),
            "synthDriverHandler": self.handler, "ui": module("ui", message=Mock()),
            "wx": self.wx, "logHandler": module("logHandler", log=Mock()),
            "queueHandler": module("queueHandler", eventQueue=object(), queueFunction=lambda queue, fn, *args: fn(*args)),
            "synthDrivers": package, "synthDrivers._alvb": shared,
            "synthDrivers._alvb.service": self.service,
            "synthDrivers._alvb.protocol": protocol,
            "synthDrivers._alvb.formats": formats,
            "synthDrivers._alvb.sequence": sequence,
        }
        self.patcher = patch.dict(sys.modules, modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.plugin = self.load("bridgePluginTest", ROOT / "addon/globalPlugins/angelLegacyVoiceBridge.py")
        self.synth = self.load("synthDrivers.bridgeSynthTest", ROOT / "addon/synthDrivers/angelLegacyVoiceBridge.py")

    def load(self, name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        return loaded

    def panel(self):
        panel = self.plugin.BridgePanel()
        for name, value in dict(active=True, quality=0, autoReturn=False, fullXPVolume=False, enabled=True, pipe=self.settings["pipe"], mirror=False,
                                rate=60, volume=70, fallback=True, diagnostics=True, voice=0).items():
            setattr(panel, name, Control(value))
        panel.voice_tokens = ["token"]
        panel.onRefresh = Mock()
        return panel

    def test_connection_action_disconnects_existing_worker(self):
        panel = self.panel()
        panel.onToggleConnection(None)
        self.service.disable.assert_called_once()

    def test_connection_action_connects_when_stopped(self):
        self.service.client = None
        panel = self.panel()
        panel.onConnect = Mock()
        panel.onToggleConnection(None)
        panel.onConnect.assert_called_once()

    def test_connection_label_tracks_connected_retrying_and_stopped(self):
        panel = self.panel()
        panel._quality_value = 0
        panel._autoReturn_value = False
        panel._catalog = ((0, "Test Mike", "token"),)
        panel.status = Mock()
        panel.buttons = {name: Mock() for name in ("onStop", "onTest", "onToggleConnection")}
        self.client.full_xp_volume = False
        self.client.status = "Test status"
        for client, label in ((self.client, "&Disconnect"), (self.client, "Cancel &connection"), (None, "&Connect")):
            self.service.client = client
            if client:
                client.connected = label == "&Disconnect"
            self.plugin.BridgePanel.onRefresh(panel, None)
            panel.buttons["onToggleConnection"].SetLabel.assert_called_with(label)

    def test_open_panel_follows_toggle_command_so_apply_cannot_revert_it(self):
        panel = self.panel()
        panel._quality_value = 0
        panel._autoReturn_value = False
        panel._catalog = ((0, "Test Mike", "token"),)
        panel.status = Mock()
        panel.buttons = {name: Mock() for name in ("onStop", "onTest", "onToggleConnection")}
        self.client.full_xp_volume = False
        self.client.status = "Test status"
        self.settings["autoReturn"] = True  # Changed by the command meanwhile.
        self.plugin.BridgePanel.onRefresh(panel, None)
        self.assertTrue(panel.autoReturn.value)
        panel.onSave()
        self.assertTrue(self.settings["autoReturn"])

    def test_saving_diagnostics_preference_applies_it_at_once(self):
        panel = self.panel()
        panel.diagnostics.value = False
        panel.onSave()
        self.assertFalse(self.settings["diagnostics"])
        self.service.refresh_diagnostics_preference.assert_called_once_with()

    def test_disabled_panel_can_save_recovery_preferences_without_connecting(self):
        panel = self.panel()
        panel.active.value = False
        panel.autoReturn.value = True
        panel.onSave()
        self.assertTrue(self.settings["autoReturn"])
        self.service.disable.assert_called_once()
        self.service.ensure_client.assert_not_called()

    def test_failed_selection_restores_disabled_master(self):
        self.settings["active"] = False
        self.client.connected = False
        with self.assertRaises(RuntimeError):
            self.synth.SynthDriver()
        self.assertFalse(self.settings["active"])
        self.service.stop.assert_called_once()

    def test_raising_selection_restores_disabled_master(self):
        self.settings["active"] = False
        self.service.ensure_client.side_effect = OSError("Worker start failed")
        with self.assertRaises(OSError):
            self.synth.SynthDriver()
        self.assertFalse(self.settings["active"])

    def test_empty_catalog_does_not_crash_mirroring(self):
        self.settings["mirrorVoice"] = ""
        self.client.voice_snapshot.return_value = ({}, {})
        plugin = self.plugin.GlobalPlugin.__new__(self.plugin.GlobalPlugin)
        plugin.onSpeech(["No voices"])
        self.client.enqueue.assert_not_called()

    def test_save_supports_nvda_mapping_without_update(self):
        self.panel().onSave()
        self.assertEqual(self.settings["mirrorRate"], 60)
        self.assertEqual(self.settings["mirrorVolume"], 70)
        self.assertFalse(self.settings["mirror"])
        self.client.cancel.assert_called_once()

    def test_route_choice_is_saved_and_applied_to_connected_client(self):
        panel = self.panel()
        panel.speechRoute = Mock()
        panel.speechRoute.GetSelection.return_value = 1
        panel.onSave()
        self.assertEqual(self.settings["speechRoute"], "nvda")
        self.client.set_route.assert_called_once_with("nvda")

    def test_invalid_pipe_has_accessible_validation(self):
        panel = self.panel()
        panel.pipe.value = r"\\remote\pipe\invalid"
        self.assertFalse(panel.isValid())
        self.gui.messageBox.assert_called_once()

    def test_active_synth_cannot_change_pipe(self):
        self.handler.getSynth.return_value.name = "angelLegacyVoiceBridge"
        panel = self.panel()
        panel.pipe.value += "other"
        self.assertFalse(panel.isValid())

    def test_test_button_does_not_interrupt_active_bridge(self):
        self.handler.getSynth.return_value.name = "angelLegacyVoiceBridge"
        self.panel().onTest(None)
        self.client.cancel.assert_not_called()
        self.gui.messageBox.assert_called_once()

    def test_resume_reaches_client_after_mirroring_disabled(self):
        self.settings["mirror"] = False
        plugin = self.plugin.GlobalPlugin.__new__(self.plugin.GlobalPlugin)
        plugin.onPause(False)
        self.client.pause.assert_called_once_with(False)

    def test_plugin_reload_preserves_active_synth_connection(self):
        self.handler.getSynth.return_value.name = "angelLegacyVoiceBridge"
        plugin = self.plugin.GlobalPlugin.__new__(self.plugin.GlobalPlugin)
        plugin.registered = False
        plugin.terminate()
        self.service.stop.assert_not_called()

    def test_cancel_is_not_termination(self):
        synth = self.synth.SynthDriver()
        synth.cancel()
        self.assertFalse(getattr(synth, "base_terminated", False))
        synth.terminate()
        self.assertTrue(synth.base_terminated)
        self.assertEqual(self.service.listeners, [])

    def test_initial_handshake_is_bounded(self):
        self.synth.SynthDriver()
        self.service.ensure_client.assert_called_once_with(wait=2)

    def test_output_format_is_in_ring_and_changes_without_reconnect(self):
        synth = self.synth.SynthDriver()
        setting = next(item for item in synth.supportedSettings if getattr(item, "id", None) == "format")
        self.assertTrue(setting.availableInSettingsRing)
        self.assertFalse(setting.useConfig)
        formats = synth._get_availableFormats()
        self.assertEqual(list(formats), ["0", "16000", "22050", "44100", "48000"])
        synth._set_format("44100")
        self.assertEqual(self.settings["quality"], 44100)
        self.assertEqual(self.client.quality, 44100)
        self.assertEqual(synth._get_format(), "44100")
        self.client.cancel.assert_not_called()
        self.service.stop.assert_not_called()

    def test_invalid_ring_format_leaves_current_format_unchanged(self):
        synth = self.synth.SynthDriver()
        with self.assertRaises(ValueError):
            synth._set_format("123")
        self.assertEqual(self.settings["quality"], 0)

    def test_unexpected_disconnect_restores_espeak(self):
        synth = self.synth.SynthDriver()
        self.handler.getSynth.return_value = synth
        self.client.connected = False
        synth._event("disconnected", "Test failure")
        self.handler.setSynth.assert_called_once_with("espeak")
        self.cancel_speech.assert_called_once()

    def test_fallback_clears_abandoned_indexes_before_changing_synth(self):
        synth = self.synth.SynthDriver()
        self.handler.getSynth.return_value = synth
        self.client.connected = False
        pending = [object()] * 30000
        self.cancel_speech.side_effect = pending.clear
        def select(name):
            self.assertEqual(pending, [])
            return True
        self.handler.setSynth.side_effect = select
        synth._event("disconnected", "Test engine failure")
        self.handler.setSynth.assert_called_once_with("espeak")

    def test_reconnected_session_still_clears_lost_indexes(self):
        synth = self.synth.SynthDriver()
        self.handler.getSynth.return_value = synth
        synth._event("disconnected", "Test engine failure")
        self.cancel_speech.assert_called_once()
        self.handler.setSynth.assert_not_called()

    def test_disabled_fallback_does_not_replace_synth(self):
        synth = self.synth.SynthDriver()
        self.handler.getSynth.return_value = synth
        self.client.connected = False
        self.settings["fallback"] = False
        synth._event("disconnected", "Test failure")
        self.handler.setSynth.assert_not_called()
        self.cancel_speech.assert_called_once()

    def test_voice_refresh_updates_ring(self):
        synth = self.synth.SynthDriver()
        self.handler.getSynth.return_value = synth
        synth._event("voices", {})
        self.variables.settingsRing.updateSupportedSettings.assert_called_once_with(synth)

    def test_removed_selected_voice_falls_back(self):
        synth = self.synth.SynthDriver()
        self.handler.getSynth.return_value = synth
        self.client.voice_tokens = {}
        synth._event("voices", {})
        self.handler.setSynth.assert_called_once_with("espeak")

    def test_failed_selection_stops_unwanted_worker(self):
        self.settings["enabled"] = False
        self.settings["mirror"] = False
        self.client.connected = False
        with self.assertRaises(RuntimeError):
            self.synth.SynthDriver()
        self.service.stop.assert_called_once()

    def test_late_disconnect_does_not_cancel_another_synth(self):
        synth = self.synth.SynthDriver()
        synth._event("disconnected", "Old connection dropped")
        self.cancel_speech.assert_not_called()
        self.handler.synthDoneSpeaking.notify.assert_not_called()
        self.handler.setSynth.assert_not_called()

    def test_voice_removed_after_refresh_has_accessible_error(self):
        panel = self.panel()
        panel.voice_tokens = ["removed-token"]
        panel.onTest(None)
        self.gui.messageBox.assert_called_once()
        self.client.enqueue.assert_not_called()

    def test_secure_desktop_rejects_bridge(self):
        self.variables.appArgs.secure = True
        self.assertFalse(self.synth.SynthDriver.check())
        with self.assertRaises(RuntimeError):
            self.synth.SynthDriver()
        self.service.ensure_client.assert_not_called()

    def test_mirrored_speech_keeps_newest_when_xp_falls_behind(self):
        plugin = self.plugin.GlobalPlugin.__new__(self.plugin.GlobalPlugin)
        plugin.onSpeech(["Busy server event"])
        self.assertTrue(self.client.enqueue.call_args.kwargs["drop_oldest"])
        self.client.cancel.assert_not_called()

    def test_missing_configured_mirror_voice_is_not_replaced(self):
        self.settings["mirrorVoice"] = "not-installed"
        plugin = self.plugin.GlobalPlugin.__new__(self.plugin.GlobalPlugin)
        plugin.onSpeech(["Do not change my voice silently"])
        self.client.enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
