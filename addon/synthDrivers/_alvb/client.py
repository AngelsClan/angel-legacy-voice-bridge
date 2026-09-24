"""A single background worker owns the connection and all speech state."""
from collections import deque
import threading
import time
import uuid
import logging

from .protocol import (Bookmark, LineReader, Speech, utterance_frames,
                       parse_audio_format, parse_audio_frame)

DEFAULT_PIPE = r"\\.\pipe\AngelLegacySpeech-XP"
ACK_TIMEOUT = 4
VOICE_REFRESH_INTERVAL = 5
VOICE_REFRESH_TIMEOUT = 4


def text_shape(items):
    """Counts that describe an utterance without revealing it, for finding
    which kinds of text make a legacy engine fail. Never words or characters."""
    text = "".join(item.text for item in items if isinstance(item, Speech))
    words = text.split()
    return ("digits=%d letters=%d spaces=%d ascii_punctuation=%d non_ascii=%d "
            "double_open_brackets=%d double_close_brackets=%d words=%d longest_word=%d" % (
                sum(character.isdigit() for character in text),
                sum(character.isalpha() for character in text),
                sum(character.isspace() for character in text),
                sum(character.isascii() and not character.isalnum() and not character.isspace() for character in text),
                sum(not character.isascii() for character in text),
                text.count("[["), text.count("]]"), len(words),
                max((len(word) for word in words), default=0)))


class BridgeClient:
    def __init__(self, pipe_name=DEFAULT_PIPE, callback=None, transport_factory=None, wait_for=None, quality=0, logger=None):
        # NVDA filters INFO from third-party loggers. Its adapter supplies the
        # NVDA logger; standalone probes retain normal Python logging.
        self.log = logger if logger is not None else logging.getLogger(__name__)
        if transport_factory is None:
            from .pipe import Pipe
            transport_factory = Pipe
        self.pipe_name = pipe_name
        self.quality = quality
        self.route = "xp"
        self.audio = None
        self._audio_supported = False
        self._both_supported = False
        self._silent_probe_supported = False
        self._route_pending = False
        self._route_started = 0
        self._route_active = "xp"
        self._audio_format = None
        self._audio_sequence = 0
        self._audio_bytes = 0
        self._audio_probe = False
        self._audio_failure = None
        self._route_marks = deque()
        self._caps_deadline = 0
        self.output_format = "Not reported yet"
        self.full_xp_volume = False
        self.mixer_status = "Helper support not reported"
        self._mixer_supported = False
        self._mixer_pending = False
        self._frames = deque()
        self._pending_indexes = deque()
        self._completed_utterances = 0
        self._enqueued_utterances = 0
        self._cancellations = 0
        self._dropped_utterances = 0
        self._recovered_indexes = 0
        self._voice_recoveries = 0
        self._last_diagnostic = 0
        self._waiting_ack = False
        self._ack_started = 0
        self._active_limit = 120
        self.callback = callback or (lambda event, data: None)
        self.transport_factory = transport_factory
        self._catalog = {}
        self._pending_catalog = {}
        self._connected_event = threading.Event()
        self._ready_seen = False
        self._refresh_supported = False
        self._refresh_disabled = False
        self._refresh_pending = False
        self._last_refresh = 0
        self._last_receive = 0
        self.connected = False
        self.status = "Not connected"
        self.last_failure = ""
        self.generation = 0
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self.closed_event = threading.Event()
        self._wait_for = wait_for
        self._queue = deque()
        self._commands = deque()
        self._active = None
        self._active_details = (0, 0, 0, 0, 0)
        self._active_shape = ""
        self._request_id = 0
        self._session = ""
        self._pending_done = False
        self._paused = False
        self._pause_started = 0
        self._thread = threading.Thread(target=self._run, name="LegacyVoiceBridge", daemon=True)

    def start(self):
        try:
            self._thread.start()
        except Exception:
            self.closed_event.set()
            raise

    def request_full_volume(self):
        with self._lock:
            if self.full_xp_volume:
                self._mixer_pending = True

    @property
    def voices(self):
        return self.voice_snapshot()[0]

    @property
    def voice_tokens(self):
        return self.voice_snapshot()[1]

    def voice_snapshot(self):
        # Publish one complete catalogue; readers never see half a handshake.
        with self._lock:
            catalog = self._catalog
        return ({index: pair[0] for index, pair in catalog.items()},
                {index: pair[1] for index, pair in catalog.items()})

    def wait_connected(self, timeout):
        return self._connected_event.wait(timeout)

    def close(self, wait=True):
        self.cancel()
        self._stop.set()
        if wait and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)

    def set_route(self, route):
        if route not in ("xp", "nvda", "both"):
            raise ValueError("Invalid bridge route")
        with self._lock:
            if route == self.route:
                return
            self.route = route
            self.cancel()
            self._route_pending = False
            self._route_started = 0

    def audio_event(self, kind, value):
        """Playback worker events. Never call NVDA directly from this thread."""
        notifications = []
        with self._lock:
            if kind == "index" and self._active:
                if value in self._pending_indexes:
                    while self._pending_indexes.popleft() != value:
                        pass
                notifications.append(("observedIndex", (self._active[0], value)))
                notifications.append(("index", (self._active[0], value)))
            elif kind == "probe" and self._active and self._audio_probe:
                notifications.append(("audioProduced", (self._active[0], value[0], value[1])))
            elif kind == "done" and self._active:
                recovered = list(self._pending_indexes)
                self._pending_indexes.clear()
                self._recovered_indexes += len(recovered)
                self._completed_utterances += 1
                self._active = None
                self._waiting_ack = False
                self._audio_format = None
                self._audio_sequence = 0
                self._audio_bytes = 0
                self._route_marks.clear()
                for index in recovered:
                    notifications.append(("index", (self.generation, index)))
            elif kind == "error":
                self.log.warning("NVDA audio playback failed: error_type=%s", value)
                self._audio_failure = "NVDA audio playback failed"
                return
        for event, data in notifications:
            self._notify(event, data)

    def _notify(self, event, data):
        try:
            self.callback(event, data)
        except Exception as error:
            # A torn-down UI must not kill the transport worker. No payload log.
            self.log.warning("Bridge callback unavailable: event=%s error_type=%s", event, type(error).__name__)

    def enqueue(self, items, drop_oldest=False, probe=False):
        """Queue one utterance. With drop_oldest, a full queue loses its oldest
        waiting utterance instead of refusing, so mirrored speech stays current
        when XP falls behind a busy stream of announcements."""
        items = tuple(items)
        characters = sum(len(item.text) for item in items if isinstance(item, Speech))
        if len(items) > 256 or characters > 16000:
            self.log.warning("Speech admission limit: items=%d characters=%d", len(items), characters)
            raise ValueError("Utterance limit exceeded")
        with self._lock:
            if not self.connected or self._stop.is_set():
                return False
            if probe and not self._silent_probe_supported:
                # An old or still-handshaking helper would treat the check as
                # ordinary audible XP speech. Never let it enter that path.
                return False
            if len(self._queue) >= 64:
                if not drop_oldest:
                    self.log.warning("Speech admission queue full: queued=%d", len(self._queue))
                    raise ValueError("Speech queue limit exceeded")
                self._queue.popleft()
                self._dropped_utterances += 1
            self._queue.append((items, bool(probe)))
            self._enqueued_utterances += 1
            self._pending_done = True
        return True

    @property
    def busy(self):
        with self._lock:
            return bool(self._active or self._queue)

    def cancel(self):
        with self._lock:
            self._cancellations += 1
            self.generation = (self.generation + 1) % 2147483647
            self._queue.clear()
            self._active = None
            self._frames.clear()
            self._pending_indexes.clear()
            self._waiting_ack = False
            self._pending_done = False
            self._paused = False
            self._pause_started = 0
            self._commands.clear()
            self._commands.append(("CANCEL", str(self.generation)))
            self._audio_format = None
            self._audio_sequence = 0
            self._audio_bytes = 0
            self._route_marks.clear()
            self._audio_failure = None
        if self.audio is not None:
            self.audio.cancel()

    def pause(self, paused):
        with self._lock:
            if bool(paused) == self._paused:
                return
            now = time.monotonic()
            if paused:
                self._pause_started = now
            elif self._pause_started:
                elapsed = now - self._pause_started
                if self._active:
                    generation, request, started = self._active
                    self._active = (generation, request, started + elapsed)
                self._pause_started = 0
            self._paused = bool(paused)
            # Coalesce repeated pause toggles so control messages stay bounded.
            self._commands = deque(item for item in self._commands if item[0] != "PAUSE")
            self._commands.append(("PAUSE", "1" if paused else "0"))
        if self.audio is not None and self._route_active != "xp":
            self.audio.pause(bool(paused))

    def _disconnect(self, reason):
        with self._lock:
            was_connected = self.connected
            if was_connected and not self._stop.is_set():
                slot, characters, quality, rate, volume = self._active_details if self._active else (-1, 0, 0, 0, 0)
                elapsed = time.monotonic() - self._active[2] if self._active else 0
                self.log.warning(
                    "Failure snapshot: generation=%d request=%d queued=%d pending_indexes=%d "
                    "active_seconds=%.2f voice_slot=%d characters=%d quality=%d rate=%d volume=%d",
                    self.generation, self._active[1] if self._active else 0,
                    len(self._queue), len(self._pending_indexes), elapsed,
                    slot, characters, quality, rate, volume)
                if self._active and self._active_shape:
                    self.log.warning("Failure text shape: request=%d %s", self._active[1], self._active_shape)
            self.connected = False
            self._connected_event.clear()
            self.status = reason
            if was_connected:
                # Keep the reason available after an automatic reconnect, so
                # the settings status does not hide the interruption.
                self.last_failure = reason[:160]
            self._queue.clear()
            self._commands.clear()
            self._active = None
            self._frames.clear()
            self._pending_indexes.clear()
            self._waiting_ack = False
            self._pending_done = False
            self._paused = False
            self._pause_started = 0
            self.generation += 1
            self._route_pending = False
            self._route_active = "xp"
            self._audio_format = None
            self._route_marks.clear()
            self._audio_failure = None
        if self.audio is not None:
            self.audio.cancel()
        if was_connected:
            logger = self.log
            if self._stop.is_set():
                logger.info("Bridge stopped")
            else:
                logger.warning("Bridge disconnected: %s", reason)
            self._notify("disconnected", reason)

    def _process_line(self, fields):
        command = fields[0]
        if command == "READY" and fields == ["READY", "2", self._session]:
            self._ready_seen = True
            self._pending_catalog = {}
        elif command == "VOICE" and self._ready_seen and len(fields) == 4:
            index = int(fields[1])
            if not 0 <= index < 128:
                raise ValueError("Invalid voice index")
            self._pending_catalog[index] = (bytes.fromhex(fields[2]).decode("utf-16-le"),
                                            bytes.fromhex(fields[3]).decode("utf-16-le"))
        elif fields == ["ENDVOICES"] and self._ready_seen:
            with self._lock:
                was_connected = self.connected
                changed = self._catalog != self._pending_catalog
                self._catalog = dict(self._pending_catalog)
                self._refresh_pending = False
                self._last_refresh = time.monotonic()
                self.connected = True
                self._caps_deadline = time.monotonic() + .5
                self.status = "Connected; audio plays through XP"
                self._connected_event.set()
            if not was_connected:
                self._notify("connected", dict(self.voices))
            elif changed:
                self._notify("voices", dict(self.voices))
        elif fields == ["CAPS", self._session, "voice-refresh"]:
            self._refresh_supported = not self._refresh_disabled
        elif fields in (["VOICESUNCHANGED", self._session], ["VOICESRETRY", self._session]):
            self._refresh_pending = False
            self._last_refresh = time.monotonic() + (25 if command == "VOICESRETRY" else 0)
            if command == "VOICESRETRY":
                self.log.warning("XP voice scan incomplete; retaining last good catalog")
        elif fields == ["CAPS", self._session, "xp-volume"]:
            self._mixer_supported = True
            if self.mixer_status == "Helper support not reported":
                self.mixer_status = "Ready; not adjusted"
                self.request_full_volume()
        elif fields == ["CAPS", self._session, "audio-pcm"]:
            self._audio_supported = True
        elif fields == ["CAPS", self._session, "audio-both"]:
            self._both_supported = True
        elif fields == ["CAPS", self._session, "silent-probe"]:
            self._silent_probe_supported = True
        elif command == "ROUTE" and len(fields) == 3 and fields[1] == self._session:
            with self._lock:
                if self._route_pending and fields[2] == self._target_route():
                    self._route_active = fields[2]
                    self._route_pending = False
                    self._route_started = 0
                    self.status = ("Connected; requested audio route unavailable; playing through XP"
                                   if self.route != self._route_active else
                                   "Connected; audio plays through XP" if self.route == "xp"
                                   else "Connected; bridge speech routes to " +
                                   ("NVDA" if self.route == "nvda" else "XP and NVDA"))
        elif command == "MIXER" and len(fields) == 3 and fields[1] == self._session:
            self.mixer_status = {"OK": "Master and Wave at 100%", "PARTIAL": "Only some playback controls adjusted",
                                 "UNSUPPORTED": "Playback mixer could not be adjusted"}.get(fields[2], "Unknown result")
            if fields[2] != "OK":
                self.log.warning("XP playback mixer adjustment incomplete")
        elif command == "PONG" and fields == ["PONG", self._session]:
            self._notify("health", None)
        elif command == "AUDIOFORMAT" and len(fields) == 7 and fields[1] == self._session:
            generation, request, audio_format = parse_audio_format(fields)
            with self._lock:
                if not self._active or (generation, request) != self._active[:2]:
                    return  # Buffered reply for a canceled utterance.
                valid = (self._audio_supported and self._route_active != "xp"
                         and self._audio_format is None and self.audio is not None)
                if not valid:
                    raise ValueError("Unexpected audio format")
                self._audio_format = audio_format
                self._audio_sequence = 0
                self._audio_bytes = 0
                self.audio.start(audio_format, probe=self._audio_probe)
                self._flush_route_marks()
        elif command == "AUDIO" and len(fields) == 6 and fields[1] == self._session:
            generation, request, sequence, data = parse_audio_frame(fields)
            with self._lock:
                if not self._active or (generation, request) != self._active[:2]:
                    return
                if (self._audio_format is None or sequence != self._audio_sequence
                        or len(data) % (self._audio_format.channels * 2)):
                    raise ValueError("Unexpected audio frame")
                self.audio.feed(data)
                self._audio_sequence += 1
                self._audio_bytes += len(data)
                self._flush_route_marks()
        elif command == "PROBEAUDIO" and len(fields) == 6 and fields[1] == self._session:
            generation, request, byte_count, has_signal = map(int, fields[2:])
            if not (0 <= byte_count <= 64 * 1024 * 1024 and has_signal in (0, 1)):
                raise ValueError("Invalid probe audio evidence")
            with self._lock:
                active_probe = (self._active and (generation, request) == self._active[:2]
                                and self._audio_probe and self._silent_probe_supported)
            if active_probe:
                self._notify("audioProduced", (generation, byte_count, bool(has_signal)))
        elif command == "DONE" and len(fields) == 4 and fields[1] == self._session:
            recovered = []
            with self._lock:
                if self._active and (int(fields[2]), int(fields[3])) == self._active[:2]:
                    if self._route_active != "xp":
                        if self._audio_format is None or self._audio_bytes == 0:
                            raise ValueError("Routed speech produced no audio")
                        if self._route_marks:
                            # SAPI's terminal bookmark can lead the final PCM
                            # after resampling. XP Organ at 48 kHz produced a
                            # measured 32-byte (16-frame, 0.33 ms) lead; eight
                            # frames falsely disconnected the NVDA route.
                            # DONE proves rendering has finished. Allow at most
                            # one millisecond of output frames, keeping a real
                            # missing-audio tail an error.
                            tolerance_frames = max(8, (self._audio_format.rate + 999) // 1000)
                            tolerance = (tolerance_frames * self._audio_format.channels
                                         * (self._audio_format.bits // 8))
                            gap = max(offset - self._audio_bytes for offset, _ in self._route_marks)
                            slot = self._active_details[0]
                            if gap > tolerance:
                                self.log.warning(
                                    "Audio bookmark beyond final PCM: request=%d voice_slot=%d "
                                    "offset=%d pcm_bytes=%d gap=%d tolerance=%d rate=%d frames=%d",
                                    int(fields[3]), slot, max(offset for offset, _ in self._route_marks),
                                    self._audio_bytes, gap, tolerance, self._audio_format.rate,
                                    self._audio_sequence)
                                raise ValueError("Audio ended before bookmark offset")
                            self.log.info(
                                "Terminal audio bookmark aligned to playback end: request=%d "
                                "voice_slot=%d pcm_bytes=%d gap=%d rate=%d frames=%d",
                                int(fields[3]), slot, self._audio_bytes, gap,
                                self._audio_format.rate, self._audio_sequence)
                            while self._route_marks:
                                _, index = self._route_marks.popleft()
                                self.audio.index(index)
                        self.audio.finish()
                        self._last_receive = time.monotonic()
                        return
                    # Some SAPI engines omit bookmarks, especially around empty
                    # text. NVDA advances its queue on indexes, not DONE alone.
                    # Actual completion is the only safe point to recover them.
                    recovered = list(self._pending_indexes)
                    self._pending_indexes.clear()
                    self._recovered_indexes += len(recovered)
                    self._completed_utterances += 1
                    self._active = None
                    self._waiting_ack = False
            for index in recovered:
                self._notify("index", (int(fields[2]), index))
        elif command == "ACK" and len(fields) == 4 and fields[1] == self._session:
            with self._lock:
                if self._active and (int(fields[2]), int(fields[3])) == self._active[:2]:
                    self._waiting_ack = False
        elif command == "INDEX" and len(fields) in (5, 6) and fields[1] == self._session:
            index = int(fields[4])
            with self._lock:
                valid = self._active and (int(fields[2]), int(fields[3])) == self._active[:2]
                valid = valid and index in self._pending_indexes
                if valid and self._route_active != "xp":
                    if len(fields) != 6:
                        raise ValueError("Routed bookmark lacks audio offset")
                    offset = int(fields[5])
                    if offset < 0 or offset > 64 * 1024 * 1024:
                        raise ValueError("Invalid audio bookmark offset")
                    self._route_marks.append((offset, index))
                    self._flush_route_marks()
                elif valid:
                    # NVDA treats a later index as reaching earlier indexes too.
                    # Do not replay them out of order when DONE arrives.
                    while self._pending_indexes.popleft() != index:
                        pass
            if valid and self._route_active == "xp":
                # DONE can recover a missing index for NVDA queue progress.
                # Recovery checks must distinguish a SAPI bookmark we actually
                # received from one reconstructed at completion.
                self._notify("observedIndex", (int(fields[2]), index))
                self._notify("index", (int(fields[2]), index))
        elif command == "FORMAT" and len(fields) == 5 and fields[1] == self._session:
            rate, bits, channels = map(int, fields[2:])
            self.output_format = f"{rate} Hz, {bits}-bit, {channels} channel(s)"
        elif command == "SAPIERROR" and len(fields) == 8 and fields[1] == self._session:
            # Accept numeric metadata only, never arbitrary diagnostic strings.
            if not all(value.isascii() and value.isdecimal() and len(value) <= 10 for value in fields[2:]):
                return
            generation, request, stage, result, slot, quality = map(int, fields[2:])
            if not (1 <= stage <= 7 and result <= 0xFFFFFFFF and slot <= 128 and quality <= 48000):
                return
            self.log.warning("XP SAPI failure: generation=%d request=%d stage=%d HRESULT=0x%08X voice_slot=%d quality=%d",
                             generation, request, stage, result, slot, quality)
        elif command == "ERROR" and len(fields) == 5 and fields[1] == self._session:
            # Fail safely to local speech rather than silently skip document text.
            # Only report known fixed codes: never log arbitrary guest payloads.
            codes = {"sapi-engine-failed", "sapi-completion-failed", "batch-speak-failed",
                     "sapi-speak-failed", "sapi-pause-failed", "invalid-begin",
                     "invalid-batch", "invalid-line", "utterance-too-long",
                     "local-playback-unavailable"}
            code = fields[4] if fields[4] in codes else "unrecognized-error"
            raise OSError(f"XP helper rejected a request ({code}); restarting the session")
        elif command == "NOTICE" and len(fields) == 5 and fields[1] == self._session:
            if fields[4] == "completion-polled":
                with self._lock:
                    current = self._active and (int(fields[2]), int(fields[3])) == self._active[:2]
                if current:
                    self.log.info("XP completion confirmed by SAPI polling; recovering completion notification")
            elif fields[4] == "voice-token-refreshed":
                with self._lock:
                    current = self._active and (int(fields[2]), int(fields[3])) == self._active[:2]
                    if current:
                        self._voice_recoveries += 1
                if current:
                    self.log.info("XP voice registration refreshed; rejected request resubmitted once")
        elif command in ("ACCEPTED", "CANCELLED") and len(fields) in (3, 4) and fields[1] == self._session:
            pass
        else:
            return
        self._last_receive = time.monotonic()

    def _flush_route_marks(self):
        """Queue bookmarks only after their PCM byte offset is available."""
        if self._audio_format is None:
            return
        while self._route_marks and self._route_marks[0][0] <= self._audio_bytes:
            _, index = self._route_marks.popleft()
            self.audio.index(index)

    def _route_supported(self):
        return (self.route == "xp" or
                (self._audio_supported and
                 (self.route == "nvda" or self._both_supported)))

    def _target_route(self):
        return self.route if self._route_supported() else "xp"

    def _prepare_utterance(self):
        """Reserve under the lock, prepare outside it, discard if canceled."""
        unavailable = False
        with self._lock:
            if (not self.connected or self._paused or self._refresh_pending
                    or (self.route != "xp" and not self._route_supported()
                        and time.monotonic() < self._caps_deadline)
                    or self._route_active != self._target_route()
                    or self._active or not self._queue):
                return
            items, probe = self._queue.popleft()
            if probe and not self._silent_probe_supported:
                self._pending_done = False
                return
            generation = self.generation
            if any(isinstance(item, Speech) and item.voice not in self._catalog for item in items):
                self._queue.clear()
                self._pending_done = False
                unavailable = True
            else:
                self._request_id += 1
                active = (generation, self._request_id, time.monotonic())
                self._active = active
                self._audio_probe = probe
                session, quality = self._session, self.quality
        if unavailable:
            self._notify("voiceUnavailable", generation)
            return
        # Encoding/splitting long speech can take time on a busy host. Never
        # make NVDA's enqueue, cancel or pause wait for packet construction.
        if probe:
            frames = deque(utterance_frames(session, generation, active[1], items,
                                            quality, probe=True))
        else:
            frames = deque(utterance_frames(session, generation, active[1], items, quality))
        indexes = deque(item.index for item in items if isinstance(item, Bookmark))
        limit = 120 + sum(len(item.text) * .5 for item in items if isinstance(item, Speech))
        shape = text_shape(items)
        with self._lock:
            if self._active and self._active[:2] == active[:2] and not self._stop.is_set():
                self._frames = frames
                self._pending_indexes = indexes
                self._active_limit = limit
                self._active_shape = shape
                first_speech = next((item for item in items if isinstance(item, Speech)), None)
                self._active_details = (
                    first_speech.voice if first_speech else -1,
                    sum(len(item.text) for item in items if isinstance(item, Speech)),
                    quality,
                    first_speech.rate if first_speech else 0,
                    first_speech.volume if first_speech else 0)

    def _send_work(self, transport):
        self._prepare_utterance()
        frames = []
        notifications = []
        with self._lock:
            if (self.connected and self.route != "xp" and not self._route_supported()
                    and time.monotonic() >= self._caps_deadline):
                self.status = "Connected; XP helper cannot use requested audio route; playing through XP"
            if self.connected and self._mixer_supported and self._mixer_pending:
                if self.full_xp_volume:
                    frames.append(f"MIXER\t{self._session}\n".encode("ascii"))
                self._mixer_pending = False
            target_route = self._target_route()
            if (self.connected and self._audio_supported and not self._route_pending
                    and self._route_active != target_route and not self._active):
                frames.append(f"ROUTE\t{self._session}\t{target_route}\n".encode("ascii"))
                self._route_pending = True
                self._route_started = time.monotonic()
            while self._commands:
                command, value = self._commands.popleft()
                frames.append(f"{command}\t{self._session}\t{value}\n".encode("ascii"))
            if (self.connected and self._refresh_supported and not self._refresh_pending
                    and not self._active and not self._queue and not self._paused
                    and time.monotonic() - self._last_refresh >= VOICE_REFRESH_INTERVAL):
                frames.append(f"REFRESH\t{self._session}\n".encode("ascii"))
                self._refresh_pending = True
                self._last_refresh = time.monotonic()
            if (self.connected and not self._paused and not self._refresh_pending
                    and not self._route_pending
                    and self._route_active == target_route):
                if self._active and self._frames and not self._waiting_ack:
                    frames.append(self._frames.popleft())
                    self._waiting_ack = True
                    self._ack_started = time.monotonic()
                if not self._queue and not self._active and self._pending_done:
                    self._pending_done = False
                    notifications.append(("done", self.generation))
        # Never hold the state lock during I/O: NVDA's cancel/enqueue must not wait
        # for a stalled VM. At most one small old frame can race with cancellation.
        for frame in frames:
            transport.write(frame)
        for event, data in notifications:
            self._notify(event, data)

    def _log_progress(self, now):
        if now - self._last_diagnostic < 10:
            return
        self._last_diagnostic = now
        with self._lock:
            queued, frames = len(self._queue), len(self._frames)
            active_seconds = now - self._active[2] if self._active else 0
            pending_indexes = len(self._pending_indexes)
            paused, waiting_ack = self._paused, self._waiting_ack
            enqueued, cancellations = self._enqueued_utterances, self._cancellations
            dropped = self._dropped_utterances
            voice_slot, characters, quality, rate, volume = self._active_details if self._active else (-1, 0, 0, 0, 0)
        # Counts and elapsed times only; never speech, voice tokens or paths.
        self.log.info(
            "Bridge progress: queued=%d frames=%d active_seconds=%.2f paused=%s "
            "waiting_ack=%s pending_indexes=%d completed=%d recovered_indexes=%d reply_age=%.2f "
            "enqueued=%d cancellations=%d dropped=%d voice_slot=%d characters=%d quality=%d rate=%d volume=%d",
            queued, frames, active_seconds, paused, waiting_ack, pending_indexes,
            self._completed_utterances, self._recovered_indexes, now - self._last_receive, enqueued, cancellations,
            dropped, voice_slot, characters, quality, rate, volume)

    def _session_loop(self, transport):
        with self._lock:
            self._session = uuid.uuid4().hex
            self._pending_catalog = {}
            self._ready_seen = False
            self._refresh_supported = False
            self._refresh_disabled = False
            self._refresh_pending = False
            self._mixer_supported = False
            self._audio_supported = False
            self._both_supported = False
            self._silent_probe_supported = False
            self._route_pending = False
            self._route_started = 0
            self._route_active = "xp"
            self._audio_format = None
            self._route_marks.clear()
            self._audio_failure = None
            self.mixer_status = "Helper support not reported"
            self._last_receive = time.monotonic()
            self._request_id = 0
        transport.write(f"\nHELLO\t2\t{self._session}\n".encode("ascii"))
        transport.write(f"CANCEL\t{self._session}\t{self.generation}\n".encode("ascii"))
        reader = LineReader()
        last_ping = 0
        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_ping >= 1:
                transport.write(f"PING\t{self._session}\n".encode("ascii"))
                last_ping = now
            for fields in reader.feed(transport.read()):
                self._process_line(fields)
            if self._audio_failure:
                raise OSError(self._audio_failure)
            if now - self._last_receive > 4:
                raise TimeoutError("No reply from XP helper")
            refresh_timed_out = False
            with self._lock:
                if self._refresh_pending and now - self._last_refresh > VOICE_REFRESH_TIMEOUT:
                    # PONG may prove the link is healthy even if a catalog was
                    # incomplete. Stop automatic scanning for this connection.
                    self._refresh_pending = False
                    self._refresh_supported = False
                    self._refresh_disabled = True
                    self._ready_seen = False
                    refresh_timed_out = True
                if self._waiting_ack and now - self._ack_started > ACK_TIMEOUT:
                    raise TimeoutError("XP did not acknowledge a speech packet")
                if self._route_pending and now - self._route_started > ACK_TIMEOUT:
                    raise TimeoutError("XP did not confirm the audio route")
                if self._active and not self._paused and now - self._active[2] > self._active_limit:
                    raise TimeoutError("XP speech did not finish")
            if refresh_timed_out:
                # Logging handlers can block on disk or acquire other locks.
                # Do not make cancel/enqueue wait behind those handlers.
                self.log.warning("XP voice refresh timed out; retaining catalog and pausing scans")
            self._send_work(transport)
            self._log_progress(time.monotonic())
        transport.write(f"CANCEL\t{self._session}\t{self.generation + 1}\n".encode("ascii"))

    def _run(self):
        try:
            self._work()
        finally:
            if self.audio is not None:
                self.audio.close()
            self.closed_event.set()

    def _work(self):
        # A replacement worker waits here, never on NVDA's UI thread. Only the
        # owning worker closes its handle, avoiding cross-thread handle reuse.
        deadline = time.monotonic() + 5
        while self._wait_for is not None and not self._wait_for.wait(.02):
            # Even a canceled replacement preserves the barrier for its successor.
            if time.monotonic() >= deadline:
                break  # A stuck predecessor degrades to normal pipe-busy retry.
        while not self._stop.is_set():
            transport = None
            try:
                transport = self.transport_factory(self.pipe_name)
                self.status = "Connecting to XP helper"
                self._session_loop(transport)
            except Exception as error:
                # Error messages contain state/errors only, never speech payloads.
                reason = str(error) if isinstance(error, (OSError, ValueError)) else "Unexpected bridge failure"
                self._disconnect(reason)
            finally:
                if transport is not None:
                    try:
                        transport.close()
                    except OSError:
                        self.log.warning("Bridge transport close failed")
            self._stop.wait(1)
        self._disconnect("Stopped")
