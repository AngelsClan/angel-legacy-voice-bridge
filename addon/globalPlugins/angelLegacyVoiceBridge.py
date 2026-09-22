"""Accessible connection controls, optional mirroring, and a real off switch."""
import config
import globalPluginHandler
import globalVars
import gui
from gui import guiHelper
from gui.settingsDialogs import SettingsPanel, NVDASettingsDialog
from scriptHandler import script
from speech import extensions
import synthDriverHandler
import ui
import wx
from logHandler import log
from synthDrivers._alvb import service
from synthDrivers._alvb.protocol import Speech
from synthDrivers._alvb.formats import OUTPUT_FORMATS
from synthDrivers._alvb.sequence import translate

QUALITY_VALUES = tuple(OUTPUT_FORMATS)
QUALITY_LABELS = tuple(OUTPUT_FORMATS.values())


class BridgePanel(SettingsPanel):
    title = "Legacy Voice Bridge"

    def makeSettings(self, sizer):
        helper = guiHelper.BoxSizerHelper(self, sizer=sizer)
        values = service.settings()
        self.active = helper.addItem(wx.CheckBox(self, label="&Enable bridge now"))
        self.active.SetValue(values["active"])
        self.active.Bind(wx.EVT_CHECKBOX, self.onEnable)
        self.enabled = helper.addItem(wx.CheckBox(self, label="Connect automatically when NVDA &starts"))
        self.enabled.SetValue(values["enabled"])
        helper.addItem(wx.StaticText(self, label="Enable bridge controls current use. Startup controls the next launch only. Disconnect stops speech, mirroring and automatic reconnect together."))
        self.pipe = helper.addLabeledControl("Local bridge &pipe:", wx.TextCtrl)
        self.pipe.SetValue(values["pipe"])
        helper.addItem(wx.StaticText(self, label="Any configured local VM can be used. Detect looks for running AngelLegacySpeech named pipes; it never starts or changes a VM."))
        self.mirror = helper.addItem(wx.CheckBox(self, label="&Mirror local NVDA speech to XP"))
        self.mirror.SetValue(values["mirror"])
        self.mirror.Bind(wx.EVT_CHECKBOX, self.onMirror)
        self.voice = helper.addLabeledControl("Mirror/test &voice:", wx.Choice, choices=[])
        self.voice_tokens = []
        self._catalog = None
        self.rate = helper.addLabeledControl("Mirror/test &rate (0–100):", wx.SpinCtrl, min=0, max=100)
        self.rate.SetValue(values["mirrorRate"])
        self.volume = helper.addLabeledControl("Mirror/test vo&lume (0–100):", wx.SpinCtrl, min=0, max=100)
        self.volume.SetValue(values["mirrorVolume"])
        self.fullXPVolume = helper.addItem(wx.CheckBox(self, label="Set XP playback &mixer to 100% when adjusting bridge volume"))
        self.fullXPVolume.SetValue(values["fullXPVolume"])
        helper.addItem(wx.StaticText(self, label="Optional; off by default. Connect, Apply or Test can immediately raise XP master and Wave playback levels, including other XP sounds. Does not unmute XP or change host volume. Bridge volume still controls speech. Turning this off or canceling the dialog does not restore old mixer levels."))
        self.quality = helper.addLabeledControl("XP output &format:", wx.Choice, choices=list(QUALITY_LABELS))
        selected = values["quality"]
        self._quality_value = selected
        self.quality.SetSelection(QUALITY_VALUES.index(selected) if selected in QUALITY_VALUES else 0)
        helper.addItem(wx.StaticText(self, label="Applies to bridge and mirrored speech after Apply. Higher sample rates cannot restore detail missing from an old voice. Output comes from XP, not NVDA's audio device."))
        self.fallback = helper.addItem(wx.CheckBox(self, label="Restore local eSpeak if bridge speech &disconnects"))
        self.fallback.SetValue(values["fallback"])
        self.autoReturn = helper.addItem(wx.CheckBox(self, label="Automatically return to the bridge after &recovery"))
        self.autoReturn.SetValue(values["autoReturn"])
        self._autoReturn_value = values["autoReturn"]
        helper.addItem(wx.StaticText(self, label="Optional: after automatic eSpeak fallback, check the previous voice with a short phrase at volume zero and return only after it renders again. Some XP voices stay audible at volume zero, so the check phrase may be heard. Checks back off and stop after 15 minutes. Manual synth or profile changes and Disconnect cancel the pending return."))
        self.diagnostics = helper.addItem(wx.CheckBox(self, label="Write text-free dia&gnostics log"))
        self.diagnostics.SetValue(values["diagnostics"])
        helper.addItem(wx.StaticText(self, label="Records timings, queue counts and error codes in angelLegacyVoiceBridge-diagnostics.log in NVDA's configuration folder, never speech text or window titles. Helps diagnose speech loss. Takes effect immediately after OK or Apply."))
        helper.addItem(wx.StaticText(self, label="Emergency: NVDA+Shift+F11 disables the bridge now and restores local speech if necessary. Voice discovery updates automatically after connection."))
        self.status = helper.addLabeledControl("Connection status:", wx.TextCtrl, style=wx.TE_READONLY)
        self.buttons = {}
        for label, handler in (("Detect running VM pipes", self.onDetect), ("&Connect", self.onToggleConnection),
                               ("&Refresh voices and status", self.onRefresh), ("&Test speech through XP", self.onTest),
                               ("Stop test speech", self.onStop), ("&About", self.onAbout)):
            button = helper.addItem(wx.Button(self, label=label))
            button.Bind(wx.EVT_BUTTON, handler)
            self.buttons[handler.__name__] = button
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onRefresh, self.timer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.onDestroy)
        self.timer.Start(350)
        if values["active"]:
            service.ensure_client()
        self.onRefresh(None)

    def onDestroy(self, event):
        if event.GetEventObject() is self:
            self.timer.Stop()
        event.Skip()

    def onEnable(self, event):
        if not self.active.GetValue():
            self.onDisable(None)
        else:
            self.onConnect(None)

    def onMirror(self, event):
        wanted = self.mirror.GetValue()
        service.settings()["mirror"] = wanted
        if wanted:
            service.settings()["active"] = True
            self.active.SetValue(True)
            service.ensure_client()
        elif service.client:
            service.client.cancel()
        self.onRefresh(None)

    def onRefresh(self, event):
        saved_quality = service.settings()["quality"]
        if saved_quality != self._quality_value:
            # A ring change while this panel is open must not be overwritten by
            # Apply. Otherwise leave the user's pending panel selection alone.
            self.quality.SetSelection(QUALITY_VALUES.index(saved_quality) if saved_quality in QUALITY_VALUES else 0)
            self._quality_value = saved_quality
        saved_return = service.settings()["autoReturn"]
        if saved_return != self._autoReturn_value:
            # The toggle command can change this while the panel is open.
            self.autoReturn.SetValue(saved_return)
            self._autoReturn_value = saved_return
        # An emergency shortcut can disable the service while this panel is open.
        # Do not let a later Apply silently turn it back on from stale controls.
        if not service.settings()["active"]:
            self.active.SetValue(False)
            self.enabled.SetValue(False)
            self.mirror.SetValue(False)
        client = service.client
        active = synthDriverHandler.getSynth()
        bridge_active = active and active.name == "angelLegacyVoiceBridge"
        connected = bool(client and client.connected)
        status = client.status if client else "Disabled / disconnected"
        if connected:
            voices, tokens = client.voice_snapshot()
            status += f"; {len(voices)} voices; output: {client.output_format}"
            if client.full_xp_volume:
                status += f"; XP mixer: {client.mixer_status}"
            catalog = tuple((index, name, tokens[index]) for index, name in voices.items())
            if catalog != self._catalog:
                selected = self.voice.GetSelection()
                saved = self.voice_tokens[selected] if selected >= 0 else service.settings()["mirrorVoice"]
                self.voice.Clear()
                self.voice_tokens = []
                for index, name, token in catalog:
                    self.voice.Append(name)
                    self.voice_tokens.append(token)
                self.voice.SetSelection(self.voice_tokens.index(saved) if saved in self.voice_tokens
                                        else (0 if self.voice_tokens else wx.NOT_FOUND))
                self._catalog = catalog
        if service.testing and (not client or not client.busy):
            service.finish_test()
        if self.status.GetValue() != status:
            self.status.ChangeValue(status)
        self.buttons["onStop"].Enable(bool(service.testing and client and client.busy))
        self.buttons["onTest"].Enable(connected and not bridge_active and not service.testing)
        label = "&Disconnect" if connected else ("Cancel &connection" if client else "&Connect")
        button = self.buttons["onToggleConnection"]
        if button.GetLabel() != label:
            button.SetLabel(label)

    def onToggleConnection(self, event):
        if service.client:
            self.onDisable(event)
        else:
            self.onConnect(event)

    def onDetect(self, event):
        from synthDrivers._alvb.pipe import discover_pipes
        candidates = discover_pipes()
        if len(candidates) == 1:
            self.pipe.SetValue(candidates[0])
        elif not candidates:
            gui.messageBox("No running bridge pipes found. Start the configured VM, or enter its pipe manually.", "Bridge detection")
        else:
            dialog = wx.SingleChoiceDialog(self, "Choose the VM pipe", "Bridge detection", candidates)
            try:
                if dialog.ShowModal() == wx.ID_OK:
                    self.pipe.SetValue(dialog.GetStringSelection())
            finally:
                dialog.Destroy()

    def onConnect(self, event):
        if not self.isValid():
            return
        active = synthDriverHandler.getSynth()
        if active and active.name == "angelLegacyVoiceBridge":
            gui.messageBox("Switch to a local synthesizer before reconnecting.", "Bridge settings")
            return
        values = service.settings()
        values["active"] = True
        values["pipe"] = self.pipe.GetValue().strip()
        values["quality"] = QUALITY_VALUES[self.quality.GetSelection()]
        values["fullXPVolume"] = self.fullXPVolume.GetValue()
        self.active.SetValue(True)
        service.reconnect()
        self.pipe.SetValue(values["pipe"])
        self.onRefresh(None)

    def onDisable(self, event):
        service.disable()
        self.active.SetValue(False)
        self.enabled.SetValue(False)
        self.mirror.SetValue(False)
        self.onRefresh(None)

    def onTest(self, event):
        active = synthDriverHandler.getSynth()
        if active and active.name == "angelLegacyVoiceBridge":
            gui.messageBox("Use a local synthesizer for this test.", "Bridge test")
            return
        client = service.client
        if not client or not client.connected or self.voice.GetSelection() < 0:
            gui.messageBox("Connect the XP helper first; the voice list updates automatically.", "Bridge test")
            return
        token = self.voice_tokens[self.voice.GetSelection()]
        index = next((index for index, value in client.voice_tokens.items() if value == token), None)
        if index is None:
            gui.messageBox("That voice is no longer available. Refresh voices and status.", "Bridge test")
            return
        service.testing = True
        client.cancel()
        client.quality = QUALITY_VALUES[self.quality.GetSelection()]
        client.full_xp_volume = self.fullXPVolume.GetValue()
        client.request_full_volume()
        if not client.enqueue([Speech("Angel Legacy Voice Bridge is ready. This sound comes from Windows XP.", index,
                                      round(self.rate.GetValue() / 5), self.volume.GetValue())]):
            service.finish_test()
        self.onRefresh(None)

    def onStop(self, event):
        if service.testing and service.client:
            service.client.cancel()
        service.finish_test()
        self.onRefresh(None)

    def onAbout(self, event):
        gui.messageBox("Angel Legacy Voice Bridge 0.1.2-dev2\nAngels Clan\n\nDiagnostic development build. Release is on hold after an unresolved NVDA freeze; keep reliable local speech selected. Use installed SAPI 5 voices in an offline XP VM. Audio comes from XP, not NVDA's output device. Disconnect stops bridge speech and retries. Bounded text-free diagnostics also operate with the bridge disabled. No voices, network listener or Windows service are included. GPL version 2 or later. See help for safety, privacy and limitations.", "About Angel Legacy Voice Bridge")

    def isValid(self):
        name = self.pipe.GetValue().strip()
        if not name.startswith("\\\\.\\pipe\\AngelLegacySpeech-"):
            gui.messageBox("Use a local pipe beginning \\\\.\\pipe\\AngelLegacySpeech-", "Bridge settings")
            return False
        active = synthDriverHandler.getSynth()
        if active and active.name == "angelLegacyVoiceBridge" and name != service.settings()["pipe"]:
            gui.messageBox("Switch to a local synthesizer before changing the pipe.", "Bridge settings")
            return False
        return True

    def onSave(self):
        wanted_active = self.active.GetValue()
        values = service.settings()
        name = self.pipe.GetValue().strip()
        changed = name != values["pipe"]
        if values["mirror"] and not self.mirror.GetValue() and service.client:
            service.client.cancel()
        for key, value in (("active", wanted_active), ("enabled", self.enabled.GetValue()), ("pipe", name),
                           ("mirror", self.mirror.GetValue()), ("mirrorRate", self.rate.GetValue()),
                           ("mirrorVolume", self.volume.GetValue()), ("fallback", self.fallback.GetValue()),
                           ("autoReturn", self.autoReturn.GetValue()),
                           ("diagnostics", self.diagnostics.GetValue()),
                           ("fullXPVolume", self.fullXPVolume.GetValue()),
                           ("quality", QUALITY_VALUES[self.quality.GetSelection()])):
            values[key] = value
        if self.voice.GetSelection() >= 0:
            values["mirrorVoice"] = self.voice_tokens[self.voice.GetSelection()]
        service.refresh_diagnostics_preference()
        if not wanted_active:
            service.disable()
            return
        if changed:
            service.stop()
        client = service.ensure_client()
        client.quality = values["quality"]
        client.full_xp_volume = values["fullXPVolume"]
        client.request_full_volume()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "Angel Legacy Voice Bridge"

    def __init__(self):
        super().__init__()
        self.registered = False
        self.control = None
        self.controlTimer = None
        if globalVars.appArgs.secure:
            return
        values = service.settings()
        NVDASettingsDialog.categoryClasses.append(BridgePanel)
        extensions.pre_speechQueued.register(self.onSpeech)
        extensions.speechCanceled.register(self.onCancel)
        extensions.post_speechPaused.register(self.onPause)
        synthDriverHandler.synthChanged.register(service.clear_recovery)
        # A profile switch that keeps eSpeak does not fire synthChanged. A later
        # return must not write the bridge into that other profile.
        self.profileSwitch = getattr(config, "post_configProfileSwitch", None)
        if self.profileSwitch is not None:
            self.profileSwitch.register(service.clear_recovery)
        self.registered = True
        self.monitorToken = None
        try:
            # Keep the token: only the instance that started a monitor may stop
            # it, so a late terminate cannot silence its own replacement.
            self.monitorToken = service.start_diagnostics()
        except Exception as error:
            log.warning("Legacy Voice Bridge monitor unavailable: %s", type(error).__name__)
        try:
            from synthDrivers._alvb.control import DisableControl
            self.control = DisableControl()
            self.controlTimer = wx.PyTimer(self.pollControl)
            self.controlTimer.Start(250)
        except Exception:
            if self.controlTimer:
                self.controlTimer.Stop()
            if self.control:
                self.control.close()
                self.control = None
            log.exception("Legacy Voice Bridge maintenance control unavailable")
        if values["active"] and (values["enabled"] or values["mirror"]):
            try:
                service.ensure_client()
            except Exception as error:
                # Keep settings and the emergency controls registered even if
                # creating the transport worker fails under resource pressure.
                log.warning("Legacy Voice Bridge startup connection unavailable: %s", type(error).__name__)

    def pollControl(self):
        if self.control:
            self.control.poll(service.disable, service.is_stopped)

    def mirroring(self):
        active = synthDriverHandler.getSynth()
        values = service.settings()
        return values["active"] and values["mirror"] and not service.testing and active and active.name != "angelLegacyVoiceBridge"

    def onSpeech(self, speechSequence, **kwargs):
        client = service.client
        if not self.mirroring() or not client or not client.connected:
            return
        values = service.settings()
        voices, tokens = client.voice_snapshot()
        token = values["mirrorVoice"]
        voice = next((index for index, value in tokens.items() if value == token), None)
        if voice is None:
            if token:
                return
            voice = next(iter(voices), None)
            if voice is None:
                return
        try:
            # A busy server can announce faster than XP speaks: keep the newest.
            client.enqueue(translate(speechSequence, voice, values["mirrorRate"], values["mirrorVolume"]),
                           drop_oldest=True)
        except Exception:
            client.cancel()
            log.warning("Legacy Voice Bridge mirror request rejected; queued speech cleared")

    def onCancel(self, **kwargs):
        if self.mirroring() and service.client:
            service.client.cancel()

    def onPause(self, switch, **kwargs):
        if service.client and (self.mirroring() or not switch):
            service.client.pause(switch)

    @script(description="Turn automatic return to the bridge after recovery on or off")
    def script_toggleAutoReturn(self, gesture):
        # No default gesture: assign one in NVDA's Input gestures if wanted.
        values = service.settings()
        values["autoReturn"] = not values["autoReturn"]
        if values["autoReturn"]:
            ui.message("Automatic return to the bridge on")
        else:
            service.clear_recovery()
            ui.message("Automatic return to the bridge off")

    @script(description="Disable the bridge now and keep or restore local speech", gesture="kb:NVDA+shift+f11")
    def script_localSpeech(self, gesture):
        service.disable()
        ui.message("Bridge disabled. Local speech only.")

    def terminate(self):
        service.stop_diagnostics(getattr(self, "monitorToken", None))
        if getattr(self, "controlTimer", None):
            self.controlTimer.Stop()
        if getattr(self, "control", None):
            self.control.close()
        if self.registered:
            extensions.pre_speechQueued.unregister(self.onSpeech)
            extensions.speechCanceled.unregister(self.onCancel)
            extensions.post_speechPaused.unregister(self.onPause)
            synthDriverHandler.synthChanged.unregister(service.clear_recovery)
            if self.profileSwitch is not None:
                self.profileSwitch.unregister(service.clear_recovery)
            if BridgePanel in NVDASettingsDialog.categoryClasses:
                NVDASettingsDialog.categoryClasses.remove(BridgePanel)
        active = synthDriverHandler.getSynth()
        if not active or active.name != "angelLegacyVoiceBridge":
            service.stop()
        super().terminate()
