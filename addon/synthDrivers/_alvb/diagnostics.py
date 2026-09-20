"""Bounded, asynchronous diagnostics. Callers must never pass speech content."""
import atexit
import logging
import os
from pathlib import Path
from queue import Empty, Full, Queue
import threading
import time


class DisabledDiagnosticLog:
    """Construction failure degrades diagnostics, never speech or controls."""
    failed = True
    dropped = 0

    def info(self, message, *args):
        pass

    def warning(self, message, *args):
        pass


class DiagnosticLog:
    """Only the writer thread opens, rotates, writes and flushes log files.

    A slow/full disk must not block NVDA's input or the bridge transport. If the
    bounded queue fills, records are dropped and counted rather than waiting.
    """
    def __init__(self, path, max_bytes=1024 * 1024, capacity=512):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.records = Queue(maxsize=capacity)
        self.stopping = threading.Event()
        self.closed = threading.Event()
        self.failed = False
        self.dropped = 0
        self.stream = None
        self.thread = threading.Thread(target=self._run, name="LegacyBridgeDiagnostics", daemon=True)
        self.thread.start()
        atexit.register(self.close)

    def info(self, message, *args):
        self._record(logging.INFO, message, args)

    def warning(self, message, *args):
        self._record(logging.WARNING, message, args)

    def _record(self, level, message, args):
        if self.stopping.is_set():
            return
        record = (time.time(), level, message, args)
        try:
            self.records.put_nowait(record)
        except Full:
            self.dropped += 1

    def _run(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            while not self.stopping.is_set() or not self.records.empty():
                try:
                    timestamp, level, message, args = self.records.get(timeout=.1)
                except Empty:
                    continue
                label = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
                milliseconds = int((timestamp - int(timestamp)) * 1000)
                message = message % args if args else message
                text = f"{label}.{milliseconds:03d} {logging.getLevelName(level)} {message[:8192]}\n"
                try:
                    self._write_line(text)
                    self.failed = False
                except OSError:
                    # File viewers/AV can temporarily prevent rotation. Drop
                    # this record, close stale state and retry on later records.
                    self.failed = True
                    self.dropped += 1
                    if self.stream is not None:
                        try:
                            self.stream.close()
                        except OSError:
                            pass
                        self.stream = None
                    self.stopping.wait(.1)
        except Exception:
            # A diagnostic failure must never take speech down with it.
            self.failed = True
            self.stopping.set()
        finally:
            if self.stream is not None:
                try:
                    self.stream.close()
                except OSError:
                    pass
            self.closed.set()

    def _write_line(self, text):
        # Packaged NVDA does not include logging.handlers. Keep rotation small
        # and explicit, and only ever replace our own two numbered log files.
        if self.stream is None:
            self.stream = self.path.open("ab")
        encoded = text.encode("utf-8", errors="replace")
        if self.stream.tell() and self.stream.tell() + len(encoded) > self.max_bytes:
            self.stream.close()
            self.stream = None
            previous = self.path.with_name(self.path.name + ".1")
            oldest = self.path.with_name(self.path.name + ".2")
            if previous.exists():
                os.replace(previous, oldest)
            os.replace(self.path, previous)
            self.stream = self.path.open("ab")
        self.stream.write(encoded)
        self.stream.flush()

    def close(self, wait=.2):
        self.stopping.set()
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=wait)


def speech_backlog_counts():
    """Read counts on NVDA's main thread; never inspect or copy the text.

    These are optional private NVDA internals, not part of the speech path.
    Future NVDA changes yield unknown counts, never a broken synthesizer.
    """
    try:
        from speech import speech
        manager = speech._manager
        pending = sum(len(queue.pendingSequences) for queue in manager._priQueues.values())
        return pending, len(manager._indexesSpeaking), len(manager._indexesToCallbacks)
    except Exception:
        # Optional private internals must not break the speech event pump.
        return -1, -1, -1
