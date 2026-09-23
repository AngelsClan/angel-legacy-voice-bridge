"""Selectable NVDA synthesizer. Audio is rendered by the XP guest, not NVDA."""
from collections import OrderedDict
from autoSettingsUtils.driverSetting import DriverSetting
from autoSettingsUtils.utils import StringParameterInfo
import synthDriverHandler
import globalVars
import ui
import queueHandler
from logHandler import log
from synthDriverHandler import VoiceInfo, synthIndexReached, synthDoneSpeaking
from ._alvb import service
from ._alvb.formats import OUTPUT_FORMATS
from ._alvb.sequence import SUPPORTED_COMMANDS, translate


class SynthDriver(synthDriverHandler.SynthDriver):
    name = "angelLegacyVoiceBridge"
    description = "Angel Legacy Voice Bridge"
    supportedSettings = (
        synthDriverHandler.SynthDriver.VoiceSetting(),
        synthDriverHandler.SynthDriver.RateSetting(),
        synthDriverHandler.SynthDriver.PitchSetting(),
        synthDriverHandler.SynthDriver.VolumeSetting(),
        # The bridge section owns this value, shared with mirroring. Do not load
        # a second, potentially stale copy from the synth's own config section.
        DriverSetting("format", "XP output &format", availableInSettingsRing=True,
                      defaultVal="0", useConfig=False),
    )
    supportedCommands = SUPPORTED_COMMANDS
    supportedNotifications = {synthIndexReached, synthDoneSpeaking}

    @classmethod
    def check(cls):
        return not globalVars.appArgs.secure

    def __init__(self):
        if globalVars.appArgs.secure:
            raise RuntimeError("The bridge is not available on secure desktops")
        previous_active = service.settings()["active"]
        service.settings()["active"] = True
        # NVDA initializes its saved synth before global plugins. Allow a short
        # handshake here only; all normal speech and settings I/O is asynchronous.
        try:
            self.client = service.ensure_client(wait=2)
        except Exception:
            service.settings()["active"] = previous_active
            if not previous_active:
                service.stop()
            raise
        if not self.client.connected or not self.client.voices:
            settings = service.settings()
            if not previous_active or (not settings["enabled"] and not settings["mirror"]):
                service.stop()
                settings["active"] = previous_active
            raise RuntimeError("Connect and test the XP helper in Legacy Voice Bridge settings first.")
        self._voice = next(iter(self.client.voice_tokens.values()))
        self._rate = 50
        self._volume = 100
        self._pitch = 50
        self._dead = False
        super().__init__()
        service.listeners.append(self._event)

    def _get_availableVoices(self):
        voices, tokens = self.client.voice_snapshot()
        return OrderedDict((tokens[index], VoiceInfo(tokens[index], name)) for index, name in voices.items())

    def _get_availableFormats(self):
        return OrderedDict((str(rate), StringParameterInfo(str(rate), label))
                           for rate, label in OUTPUT_FORMATS.items())

    def _get_format(self):
        rate = service.settings()["quality"]
        return str(rate if rate in OUTPUT_FORMATS else 0)

    def _set_format(self, value):
        rate = int(value)
        if rate not in OUTPUT_FORMATS:
            raise ValueError("Unsupported XP output format")
        service.settings()["quality"] = rate
        self.client.quality = rate
        # No cancellation or reconnect: the next dispatched utterance uses it.

    def _get_voice(self):
        return self._voice

    def _set_voice(self, value):
        if value not in self.client.voice_tokens.values():
            raise ValueError("The selected voice is not installed in this XP helper")
        self._voice = value

    def _get_rate(self):
        return self._rate

    def _set_rate(self, value):
        self._rate = max(0, min(100, int(value)))

    def _get_volume(self):
        return self._volume

    def _set_volume(self, value):
        self._volume = max(0, min(100, int(value)))
        self.client.request_full_volume()

    def _get_pitch(self):
        return self._pitch

    def _set_pitch(self, value):
        self._pitch = max(0, min(100, int(value)))

    def speak(self, speechSequence):
        try:
            index = next(index for index, token in self.client.voice_tokens.items() if token == self._voice)
            items = translate(speechSequence, index, self._rate, self._volume, self._pitch)
            if not self.client.enqueue(items):
                self._lost_connection()
        except Exception as error:
            # Exception text may contain the utterance; record its type only.
            service.diagnostics().warning("Speech admission failed: error_type=%s", type(error).__name__)
            self._lost_connection()

    def cancel(self):
        self.client.cancel()

    def pause(self, switch):
        self.client.pause(switch)

    def _event(self, event, data):
        if self._dead:
            return
        if event == "index":
            synthIndexReached.notify(synth=self, index=data[1])
        elif event == "done":
            synthDoneSpeaking.notify(synth=self)
        elif event == "disconnected":
            self._lost_connection(only_if_disconnected=True)
        elif event == "voiceUnavailable":
            self._lost_connection()
        elif event == "voices":
            if self._voice not in self.client.voice_tokens.values():
                self._lost_connection()
            elif synthDriverHandler.getSynth() is self and globalVars.settingsRing:
                globalVars.settingsRing.updateSupportedSettings(self)

    def _lost_connection(self, only_if_disconnected=False):
        # DONE is not a replacement for missing indexes. Defer cancellation
        # until speak() has returned, then reset NVDA's abandoned utterance.
        if not getattr(self, "_failure_pending", False):
            self._failure_pending = True
            queueHandler.queueFunction(queueHandler.eventQueue, self._fallback, only_if_disconnected)

    def _fallback(self, only_if_disconnected=False):
        self._failure_pending = False
        if self._dead or synthDriverHandler.getSynth() is not self:
            return
        import speech
        pending, indexes, callbacks = service.speech_backlog_counts()
        service.diagnostics().warning(
            "Resetting failed bridge speech: pending_sequences=%d indexes=%d callbacks=%d reconnected=%s",
            pending, indexes, callbacks, self.client.connected)
        speech.cancelSpeech()
        # Profile restoration during cancellation can select another synth.
        if self._dead or synthDriverHandler.getSynth() is not self:
            return
        if only_if_disconnected and self.client.connected:
            return
        if service.settings()["fallback"]:
            saved = {"voice": self._voice, "rate": self._rate, "volume": self._volume, "pitch": self._pitch}
            if synthDriverHandler.setSynth("espeak"):
                service.diagnostics().info("Fallback to local eSpeak succeeded; abandoned speech queue cleared")
                service.arm_recovery(self.client, synthDriverHandler.getSynth(), saved)
                ui.message("Legacy bridge unavailable. Switched to local eSpeak.")
            else:
                log.error("Legacy bridge unavailable; local eSpeak restoration failed")

    def terminate(self):
        self._dead = True
        if self._event in service.listeners:
            service.listeners.remove(self._event)
        self.client.cancel()
        super().terminate()
