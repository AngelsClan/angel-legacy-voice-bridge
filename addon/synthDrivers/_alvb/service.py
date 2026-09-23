"""NVDA-facing connection ownership. All NVDA callbacks run on its UI thread."""
import config
import queueHandler
import time
import threading
from collections import deque
from logHandler import log
from .client import BridgeClient, DEFAULT_PIPE
from .dispatch import MainThreadDispatch
from .diagnostics import DiagnosticLog, DisabledDiagnosticLog, SwitchableLog, speech_backlog_counts

SECTION = "angelLegacyVoiceBridge"
SPEC = {
    "active": "boolean(default=False)",
    "enabled": "boolean(default=False)",
    "pipe": f"string(default='{DEFAULT_PIPE}')",
    "mirror": "boolean(default=False)",
    "mirrorVoice": "string(default='')",
    "mirrorRate": "integer(default=50, min=0, max=100)",
    "mirrorVolume": "integer(default=100, min=0, max=100)",
    "fallback": "boolean(default=True)",
    "autoReturn": "boolean(default=False)",
    "fullXPVolume": "boolean(default=False)",
    "quality": "integer(default=0)",
    "speechRoute": "string(default='xp')",
    "diagnostics": "boolean(default=True)",
}
diagnostics_enabled = True
client = None
retiring_worker = None
retiring_workers = []
listeners = []
testing = False
recovery = None
automatic_returns = deque()
diagnostic_log = None
last_backlog_log = 0
last_backlog_sample = 0
monitor_stopped = None
monitor_thread = None
last_backlog_counts = None
diagnostic_failure_reported = False


def _diagnostic_tick(event, data):
    """Called on NVDA's main thread even when local speech is selected."""
    global last_backlog_log, last_backlog_sample, last_backlog_counts, diagnostic_failure_reported
    now = time.monotonic()
    refresh_diagnostics_preference()
    sink = diagnostics()
    if sink.failed and not diagnostic_failure_reported:
        diagnostic_failure_reported = True
        log.warning("Legacy Voice Bridge diagnostic output failed; evidence may be incomplete")
    elif not sink.failed:
        diagnostic_failure_reported = False
    if now - last_backlog_sample >= 5:
        import synthDriverHandler
        last_backlog_sample = now
        pending, indexes, callbacks = speech_backlog_counts()
        selected = synthDriverHandler.getSynth()
        bridge_selected = getattr(selected, "name", None) == "angelLegacyVoiceBridge"
        counts = (pending, indexes, callbacks, bridge_selected)
        # Only real backlog is "busy". Counting bridge_selected as a nonzero
        # number logged every five seconds for as long as the bridge was the
        # selected synthesizer, filling and rotating the log during exactly the
        # sessions whose evidence matters most.
        busy = pending > 0 or indexes > 0 or callbacks > 0
        if counts != last_backlog_counts or busy or now - last_backlog_log >= 60:
            last_backlog_log = now
            last_backlog_counts = counts
            sink.info("NVDA backlog: pending_sequences=%d indexes_active=%d callbacks=%d event_queue=%d dropped_diagnostics=%d bridge_selected=%s",
                      pending, indexes, callbacks, queueHandler.eventQueue.qsize(), sink.dropped, bridge_selected)
    if client is not None:
        _deliver(client, "health", None)


def start_diagnostics():
    """Observe responsiveness without enabling the bridge or changing speech.

    Returns a token identifying this monitor. Pass it back to stop_diagnostics
    so that a retired plugin instance can only stop the monitor it started.
    """
    global monitor_stopped, monitor_thread
    if monitor_stopped is not None and monitor_thread is not None and monitor_thread.is_alive():
        return monitor_stopped
    # A half-dead predecessor (its thread gone, its flag still set) would
    # otherwise leave diagnostics silent for the rest of the session.
    if monitor_stopped is not None:
        monitor_stopped.set()
    refresh_diagnostics_preference()
    monitor_stopped = threading.Event()
    stopped = monitor_stopped
    dispatch = MainThreadDispatch(
        lambda function, *args: queueHandler.queueFunction(queueHandler.eventQueue, function, *args),
        lambda event, data: _diagnostic_tick(event, data) if not stopped.is_set() else None,
        diagnostics())
    try:
        monitor_thread = dispatch.start_monitor(monitor_stopped)
    except Exception:
        monitor_stopped.set()
        monitor_stopped = None
        monitor_thread = None
        raise
    return monitor_stopped


def stop_diagnostics(token=None):
    global monitor_stopped, monitor_thread
    if monitor_stopped is None:
        return
    if token is not None and token is not monitor_stopped:
        # An earlier instance shutting down after its replacement started must
        # not silence the live monitor.
        token.set()
        return
    monitor_stopped.set()
    monitor_stopped = None
    monitor_thread = None
    # Keep the single writer until process exit: a plugin reload must not close
    # the logger still owned by an active synthesizer's transport worker.


def _open_diagnostic_log():
    try:
        from NVDAState import WritePaths
        from pathlib import Path
        opened = DiagnosticLog(Path(WritePaths.configDir) / "angelLegacyVoiceBridge-diagnostics.log")
        opened.info("Bridge diagnostics started; speech text and window titles are never recorded")
        return opened
    except Exception as error:
        log.warning("Legacy Voice Bridge diagnostics unavailable: %s", type(error).__name__)
        return DisabledDiagnosticLog()


def refresh_diagnostics_preference():
    """Main thread only: copy the preference into a flag any thread can read."""
    global diagnostics_enabled
    try:
        diagnostics_enabled = bool(settings()["diagnostics"])
    except Exception:
        diagnostics_enabled = True


def diagnostics():
    global diagnostic_log
    if diagnostic_log is None:
        diagnostic_log = SwitchableLog(_open_diagnostic_log, lambda: diagnostics_enabled)
    return diagnostic_log


# Automatic return after an unexpected fallback. A connected pipe and a listed
# voice token are not proof: a crashed engine host can leave both intact. Only
# a completed silent render in the original voice, confirmed by its final
# bookmark, allows the return. Every limit below keeps retries bounded.
RETURN_LIMIT = 3
RETURN_WINDOW = 600
FIRST_PROBE_DELAY = 5
MAX_PROBE_DELAY = 60
MAX_PROBES = 12
RECOVERY_WINDOW = 900
PROBE_TIMEOUT = 15
IDLE_WAIT = 8
# Fixed synthetic text only; never user speech. The capable XP helper captures
# and discards its PCM on every route, so ordinary volume proves the engine
# can produce audible samples without sending them to a sound device.
PROBE_TEXT = "Voice check, one two three."
PROBE_INDEX = 2147483000


class Recovery:
    def __init__(self, source, fallback_synth, voice_settings, profile, now, delay):
        self.source = source
        self.fallback_synth = fallback_synth
        self.voice_settings = voice_settings
        self.fallback_voice = getattr(fallback_synth, "voice", None)
        self.profile = profile
        self.started = now
        self.delay = delay
        self.next_probe = now + delay
        self.probes = 0
        self.probe_generation = None
        self.probe_started = 0
        self.verified_at = None
        self.bookmark_verified = False
        self.audio_verified = False


def _profile_identity():
    """Names of the active configuration profile stack; None if unavailable."""
    try:
        return tuple(getattr(profile, "name", None) for profile in config.conf.profiles)
    except Exception:
        return None


def _announce(text):
    try:
        import ui
        ui.message(text)
    except Exception:
        log.warning("Legacy Voice Bridge announcement unavailable")


def clear_recovery(**kwargs):
    """A deliberate synth/profile change or disable cancels pending return."""
    global recovery
    recovery = None


def arm_recovery(source, fallback_synth, voice_settings):
    global recovery
    values = settings()
    if values["active"] and values["autoReturn"] and fallback_synth and fallback_synth.name == "espeak":
        now = time.monotonic()
        while automatic_returns and now - automatic_returns[0] > RETURN_WINDOW:
            automatic_returns.popleft()
        if len(automatic_returns) >= RETURN_LIMIT:
            log.warning("Legacy Voice Bridge automatic return paused after repeated failures; select it manually when ready")
            diagnostics().warning("Automatic return paused: recent_returns=%d", len(automatic_returns))
            _announce("Bridge failed repeatedly. Staying on eSpeak.")
            return
        # Each recent failed return doubles the first wait: 5, 10, 20 seconds.
        delay = FIRST_PROBE_DELAY * 2 ** len(automatic_returns)
        recovery = Recovery(source, fallback_synth, voice_settings, _profile_identity(), now, delay)
        diagnostics().info("Automatic return armed: first_check_seconds=%d", delay)


def _abandon(reason, announce=True):
    clear_recovery()
    diagnostics().warning("Automatic return stopped: reason=%s", reason)
    if announce:
        _announce("Bridge voice did not recover. Staying on eSpeak.")


def _probe_failed(state, reason):
    state.probe_generation = None
    state.verified_at = None
    state.bookmark_verified = False
    state.audio_verified = False
    state.delay = min(MAX_PROBE_DELAY, state.delay * 2)
    state.next_probe = time.monotonic() + state.delay
    diagnostics().info("Recovery check failed: reason=%s checks=%d next_seconds=%d",
                       reason, state.probes, state.delay)


def recovery_event(source, event, data):
    """Worker events for the pending check; stale sources/generations ignored."""
    state = recovery
    if state is None or state.source is not source or state.probe_generation is None:
        return
    if event == "disconnected":
        _probe_failed(state, "disconnected")
        return
    if event == "observedIndex" and tuple(data) == (state.probe_generation, PROBE_INDEX):
        state.bookmark_verified = True
    elif (event == "audioProduced" and data[0] == state.probe_generation
          and data[1] > 0 and data[2]):
        state.audio_verified = True
    if state.bookmark_verified and state.audio_verified:
        state.probe_generation = None
        state.verified_at = time.monotonic()
        diagnostics().info("Recovery check rendered: checks=%d", state.probes)


def _start_probe(state, now):
    source = state.source
    voice = state.voice_settings
    index = next((index for index, token in source.voice_tokens.items() if token == voice["voice"]), None)
    if index is None:
        return
    from .protocol import Bookmark, Speech
    state.probes += 1
    state.bookmark_verified = False
    state.audio_verified = False
    state.probe_started = now
    generation = source.generation
    items = [Speech(PROBE_TEXT, index, max(0, min(20, round(voice["rate"] / 5))), 100,
                    max(0, min(20, round(voice["pitch"] / 5)))), Bookmark(PROBE_INDEX)]
    try:
        accepted = source.enqueue(items, probe=True)
    except ValueError:
        accepted = False
    if accepted:
        state.probe_generation = generation
    else:
        _probe_failed(state, "not-accepted")


def try_recovery():
    import synthDriverHandler
    import speech
    state = recovery
    if state is None:
        return
    values = settings()
    if (not values["active"] or not values["autoReturn"] or client is not state.source
            or synthDriverHandler.getSynth() is not state.fallback_synth
            or getattr(state.fallback_synth, "voice", None) != state.fallback_voice
            or _profile_identity() != state.profile):
        clear_recovery()
        return
    now = time.monotonic()
    source = state.source
    if state.probe_generation is not None:
        if source.generation != state.probe_generation:
            _probe_failed(state, "interrupted")
        elif now - state.probe_started > PROBE_TIMEOUT:
            _probe_failed(state, "timeout")
        return
    if state.verified_at is None:
        if now - state.started > RECOVERY_WINDOW:
            _abandon("window")
        elif state.probes >= MAX_PROBES:
            _abandon("checks")
        elif (now >= state.next_probe and source.connected
              and state.voice_settings["voice"] in source.voice_tokens.values()):
            if not getattr(source, "_silent_probe_supported", False):
                # Volume zero is audible in some XP SAPI engines. Never run a
                # recovery check through an older helper that cannot capture
                # and discard the PCM independently of the normal audio route.
                _abandon("silent-probe-unsupported")
            else:
                _start_probe(state, now)
        return
    # Verified. Prefer not to cut off eSpeak mid-sentence, but do not wait long.
    pending, indexes, callbacks = speech_backlog_counts()
    if (pending > 0 or indexes > 0) and now - state.verified_at < IDLE_WAIT:
        return
    if source.busy:
        return
    if (not source.connected
            or state.voice_settings["voice"] not in source.voice_tokens.values()):
        _probe_failed(state, "lost-after-check")
        return
    voice_settings, fallback_synth = state.voice_settings, state.fallback_synth
    # Consume before switching: failure must not cause an endless synth loop.
    clear_recovery()
    automatic_returns.append(now)
    speech.cancelSpeech()
    # Cancellation can restore a speech-triggered configuration profile.
    if synthDriverHandler.getSynth() is not fallback_synth:
        return
    if synthDriverHandler.setSynth("angelLegacyVoiceBridge"):
        restored = synthDriverHandler.getSynth()
        try:
            synthDriverHandler.changeVoice(restored, voice_settings["voice"])
            for key in ("rate", "volume", "pitch"):
                setattr(restored, key, voice_settings[key])
            restored.saveSettings()
            log.info("Legacy Voice Bridge automatically restored after recovery")
            diagnostics().info("Automatic return completed after verified render")
            _announce("Bridge voice recovered.")
        except Exception:
            log.warning("Legacy Voice Bridge recovery settings failed; restoring local speech")
            speech.cancelSpeech()
            synthDriverHandler.setSynth("espeak")
    else:
        log.warning("Legacy Voice Bridge recovery selection failed; keeping local speech")


def settings():
    if SECTION not in config.conf.spec:
        config.conf.spec[SECTION] = SPEC
    return config.conf[SECTION]


def _deliver(source, event, data):
    if client is not source:
        return
    if event == "connected" and not source.connected:
        return
    if event in ("index", "observedIndex", "audioProduced") and data[0] != source.generation:
        return
    if event == "done" and data != source.generation:
        return
    if event in ("connected", "disconnected"):
        log.info("Legacy Voice Bridge: %s", event)
        diagnostics().info("Lifecycle: %s", event)
    global testing
    if event in ("done", "disconnected"):
        finish_test()
    if event in ("observedIndex", "audioProduced", "disconnected"):
        recovery_event(source, event, data)
    for listener in tuple(listeners):
        try:
            listener(event, data)
        except Exception:
            log.exception("Legacy Voice Bridge event handler failed")
    if event in ("connected", "voices", "health"):
        try_recovery()


def ensure_client(wait=0):
    global client
    if client is None:
        values = settings()
        if values["pipe"] == DEFAULT_PIPE:
            from .pipe import discover_pipes
            available = discover_pipes()
            if DEFAULT_PIPE not in available and len(available) == 1:
                values["pipe"] = available[0]
        from .audio import AudioPlayback
        source = BridgeClient(values["pipe"], wait_for=retiring_worker, quality=values["quality"], logger=diagnostics())
        selected_route = values.get("speechRoute", "xp")
        source.route = selected_route if selected_route in ("xp", "nvda", "both") else "xp"
        source.audio = AudioPlayback(source.audio_event,
                                     lambda: config.conf["audio"]["outputDevice"])
        source.full_xp_volume = values["fullXPVolume"]
        # Saved synthesizers load before wx.App exists. NVDA's event queue is
        # available during startup and delivers inside the core pump, rather
        # than reentering speech handling from an unrelated wx event callback.
        dispatch = MainThreadDispatch(
            lambda function, *args: queueHandler.queueFunction(queueHandler.eventQueue, function, *args),
            lambda event, data: _deliver(source, event, data), diagnostics())
        # The independent monitor owns UI heartbeats. Transport PONGs still
        # update reply freshness, but must not add a second UI heartbeat stream.
        source.callback = lambda event, data: dispatch(event, data) if event != "health" else None
        client = source
        try:
            source.start()
        except Exception:
            source.audio.close()
            client = None
            raise
    if wait:
        client.wait_connected(wait)
    return client


def stop():
    global client, retiring_worker, testing
    testing = False
    clear_recovery()
    old = client
    client = None
    if old is not None:
        retiring_worker = old.closed_event
        retiring_workers[:] = [event for event in retiring_workers if not event.is_set()]
        retiring_workers.append(old.closed_event)
        old.close(wait=False)


def is_stopped():
    retiring_workers[:] = [event for event in retiring_workers if not event.is_set()]
    return client is None and not retiring_workers


def finish_test():
    """Test overrides end with the test, even if the dialog is later canceled."""
    global testing
    if testing and client:
        values = settings()
        client.quality = values["quality"]
        client.full_xp_volume = values["fullXPVolume"]
    testing = False


def disable():
    """Disable now and at next startup; keep an unrelated local synth unchanged."""
    import synthDriverHandler
    values = settings()
    values["active"] = False
    values["enabled"] = False
    values["mirror"] = False
    stop()
    active = synthDriverHandler.getSynth()
    if active and active.name == "angelLegacyVoiceBridge":
        import speech
        speech.cancelSpeech()
        if not synthDriverHandler.setSynth("espeak"):
            log.error("Bridge stopped, but local eSpeak could not be restored")
            raise RuntimeError("Bridge stopped, but local eSpeak could not be restored")
    log.info("Legacy Voice Bridge disabled; mirror off, reconnect stopped")


def reconnect():
    stop()
    return ensure_client()
