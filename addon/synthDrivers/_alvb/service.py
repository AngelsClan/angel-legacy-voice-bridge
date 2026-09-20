"""NVDA-facing connection ownership. All NVDA callbacks run on its UI thread."""
import config
import queueHandler
import time
import threading
from collections import deque
from logHandler import log
from .client import BridgeClient, DEFAULT_PIPE
from .dispatch import MainThreadDispatch
from .diagnostics import DiagnosticLog, DisabledDiagnosticLog, speech_backlog_counts

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
}
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
last_backlog_counts = None
diagnostic_failure_reported = False


def _diagnostic_tick(event, data):
    """Called on NVDA's main thread even when local speech is selected."""
    global last_backlog_log, last_backlog_sample, last_backlog_counts, diagnostic_failure_reported
    now = time.monotonic()
    sink = diagnostics()
    if sink.failed and not diagnostic_failure_reported:
        diagnostic_failure_reported = True
        log.warning("Legacy Voice Bridge diagnostic output failed; evidence may be incomplete")
    elif not sink.failed:
        diagnostic_failure_reported = False
    if now - last_backlog_sample >= 5:
        last_backlog_sample = now
        pending, indexes, callbacks = speech_backlog_counts()
        counts = (pending, indexes, callbacks)
        if counts != last_backlog_counts or any(count > 0 for count in counts) or now - last_backlog_log >= 60:
            last_backlog_log = now
            last_backlog_counts = counts
            sink.info("NVDA backlog: pending_sequences=%d indexes_active=%d callbacks=%d event_queue=%d dropped_diagnostics=%d",
                      pending, indexes, callbacks, queueHandler.eventQueue.qsize(), sink.dropped)
    if client is not None:
        _deliver(client, "health", None)


def start_diagnostics():
    """Observe responsiveness without enabling the bridge or changing speech."""
    global monitor_stopped
    if monitor_stopped is not None:
        return
    monitor_stopped = threading.Event()
    stopped = monitor_stopped
    dispatch = MainThreadDispatch(
        lambda function, *args: queueHandler.queueFunction(queueHandler.eventQueue, function, *args),
        lambda event, data: _diagnostic_tick(event, data) if not stopped.is_set() else None,
        diagnostics())
    try:
        dispatch.start_monitor(monitor_stopped)
    except Exception:
        monitor_stopped.set()
        monitor_stopped = None
        raise


def stop_diagnostics():
    global monitor_stopped
    if monitor_stopped is not None:
        monitor_stopped.set()
        monitor_stopped = None
    # Keep the single writer until process exit: a plugin reload must not close
    # the logger still owned by an active synthesizer's transport worker.


def diagnostics():
    global diagnostic_log
    if diagnostic_log is None:
        try:
            from NVDAState import WritePaths
            from pathlib import Path
            diagnostic_log = DiagnosticLog(Path(WritePaths.configDir) / "angelLegacyVoiceBridge-diagnostics.log")
            diagnostic_log.info("Bridge diagnostics started; speech text and window titles are never recorded")
        except Exception as error:
            diagnostic_log = DisabledDiagnosticLog()
            log.warning("Legacy Voice Bridge diagnostics unavailable: %s", type(error).__name__)
    return diagnostic_log


def clear_recovery(**kwargs):
    """A deliberate synth/profile change or disable cancels pending return."""
    global recovery
    recovery = None


def arm_recovery(source, fallback_synth, voice_settings):
    global recovery
    values = settings()
    if values["active"] and values["autoReturn"] and fallback_synth and fallback_synth.name == "espeak":
        now = time.monotonic()
        while automatic_returns and now - automatic_returns[0] > 60:
            automatic_returns.popleft()
        if len(automatic_returns) >= 3:
            log.warning("Legacy Voice Bridge automatic return paused after repeated failures; select it manually when ready")
            return
        recovery = (source, fallback_synth, voice_settings, getattr(fallback_synth, "voice", None))


def try_recovery():
    import synthDriverHandler
    global recovery
    if recovery is None:
        return
    source, fallback_synth, voice_settings, fallback_voice = recovery
    values = settings()
    if (not values["active"] or not values["autoReturn"] or client is not source
            or synthDriverHandler.getSynth() is not fallback_synth
            or getattr(fallback_synth, "voice", None) != fallback_voice):
        clear_recovery()
        return
    if not source.connected or voice_settings["voice"] not in source.voice_tokens.values():
        return
    # Consume before switching: failure must not cause an endless synth loop.
    clear_recovery()
    automatic_returns.append(time.monotonic())
    if synthDriverHandler.setSynth("angelLegacyVoiceBridge"):
        restored = synthDriverHandler.getSynth()
        try:
            synthDriverHandler.changeVoice(restored, voice_settings["voice"])
            for key in ("rate", "volume", "pitch"):
                setattr(restored, key, voice_settings[key])
            restored.saveSettings()
            log.info("Legacy Voice Bridge automatically restored after recovery")
        except Exception:
            log.warning("Legacy Voice Bridge recovery settings failed; restoring local speech")
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
    if event == "index" and data[0] != source.generation:
        return
    if event == "done" and data != source.generation:
        return
    if event in ("connected", "disconnected"):
        log.info("Legacy Voice Bridge: %s", event)
        diagnostics().info("Lifecycle: %s", event)
    global testing
    if event in ("done", "disconnected"):
        finish_test()
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
        source = BridgeClient(values["pipe"], wait_for=retiring_worker, quality=values["quality"], logger=diagnostics())
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
        if not synthDriverHandler.setSynth("espeak"):
            log.error("Bridge stopped, but local eSpeak could not be restored")
            raise RuntimeError("Bridge stopped, but local eSpeak could not be restored")
    log.info("Legacy Voice Bridge disabled; mirror off, reconnect stopped")


def reconnect():
    stop()
    return ensure_client()
