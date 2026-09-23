"""Bounded audio handoff from the serial worker to NVDA's player thread.

No NVDA module is imported until a routed utterance starts. Transport I/O and
NVDA's main thread never wait for sound playback. A generation change invalidates
every queued frame and every delayed playback callback.
"""
from collections import deque
import threading


# A full SAPI utterance can run for minutes. The guest can send faster than
# playback, so a tiny queue would turn ordinary long reading into a disconnect.
# These bounds remain finite and are allocated only as frames arrive.
MAX_QUEUED_AUDIO = 32 * 1024 * 1024
MAX_QUEUED_EVENTS = 32768


def nvda_player(audio_format, output_device):
    import nvwave
    return nvwave.WavePlayer(
        channels=audio_format.channels,
        samplesPerSec=audio_format.rate,
        bitsPerSample=audio_format.bits,
        outputDevice=output_device,
        wantDucking=True,
    )


class AudioPlayback:
    def __init__(self, callback, device_provider, player_factory=nvda_player):
        self.callback = callback
        self.device_provider = device_provider
        self.player_factory = player_factory
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._pending = deque()
        self._queued_bytes = 0
        self._epoch = 0
        self._closed = False
        self._paused = False
        self._player = None
        self._thread = threading.Thread(target=self._run, name="LegacyBridgeAudio", daemon=True)
        self._thread.start()

    def _submit(self, kind, value=None, size=0):
        with self._lock:
            if self._closed:
                raise RuntimeError("Audio playback is closed")
            if (len(self._pending) >= MAX_QUEUED_EVENTS
                    or self._queued_bytes + size > MAX_QUEUED_AUDIO):
                raise BufferError("Bridge audio queue exceeded its bound")
            self._pending.append((self._epoch, kind, value, size))
            self._queued_bytes += size
            self._ready.set()

    def start(self, audio_format, probe=False):
        self.cancel(clear_pause=False)
        self._submit("start", (audio_format, probe))

    def feed(self, data):
        self._submit("audio", data, len(data))

    def index(self, value):
        self._submit("index", value)

    def finish(self):
        self._submit("finish")

    def cancel(self, clear_pause=True):
        with self._lock:
            self._epoch += 1
            self._pending.clear()
            self._queued_bytes = 0
            if clear_pause:
                self._paused = False
            player = self._player
            self._ready.set()
        if player is not None:
            # As in NVDA's own SAPI driver, stop unblocks a worker in feed().
            try:
                player.stop()
            except Exception:
                pass

    def pause(self, paused):
        with self._lock:
            self._paused = bool(paused)
        self._submit("pause", paused)

    def close(self):
        self.cancel()
        with self._lock:
            self._closed = True
            self._ready.set()
        self._thread.join(timeout=1)

    def _run(self):
        probe = False
        produced = 0
        nonzero = False
        while True:
            self._ready.wait()
            with self._lock:
                if self._closed:
                    break
                if not self._pending:
                    self._ready.clear()
                    continue
                epoch, kind, value, size = self._pending.popleft()
                self._queued_bytes -= size
                current = self._epoch
            if epoch != current:
                continue
            try:
                if kind == "start":
                    audio_format, probe = value
                    produced = 0
                    nonzero = False
                    old = self._player
                    self._player = None
                    if old is not None:
                        old.close()
                    if not probe:
                        self._player = self.player_factory(audio_format, self.device_provider())
                        with self._lock:
                            paused = self._paused
                        if paused:
                            self._player.pause(True)
                elif kind == "audio":
                    produced += len(value)
                    nonzero = nonzero or any(value)
                    if not probe:
                        self._player.feed(value)
                elif kind == "index":
                    if probe:
                        self._emit(epoch, "index", value)
                    else:
                        self._player.feed(None, 0, lambda target=value, token=epoch:
                                          self._emit(token, "index", target))
                elif kind == "finish":
                    if probe:
                        self._emit(epoch, "probe", (produced, nonzero))
                        self._emit(epoch, "done", None)
                    else:
                        self._player.feed(None, 0, lambda token=epoch: self._emit(token, "done", None))
                elif kind == "pause" and self._player is not None:
                    self._player.pause(value)
            except Exception as error:
                self._emit(epoch, "error", type(error).__name__)
        player = self._player
        if player is not None:
            try:
                player.close()
            except Exception:
                pass

    def _emit(self, epoch, kind, value):
        with self._lock:
            if epoch != self._epoch or self._closed:
                return
        self.callback(kind, value)
