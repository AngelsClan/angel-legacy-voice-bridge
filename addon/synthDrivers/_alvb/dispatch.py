"""Deliver worker events on NVDA's core queue and diagnose delayed delivery.

Diagnostics contain code locations and timings only: no frame locals, source
lines, exception messages, speech text, window names, or document contents.
"""
import sys
import threading
import time
from pathlib import PurePath


def main_thread_locations(thread_id):
    frame = sys._current_frames().get(thread_id)
    locations = []
    try:
        while frame is not None and len(locations) < 32:
            code = frame.f_code
            locations.append(f"{PurePath(code.co_filename).name}:{frame.f_lineno}:{code.co_name}")
            frame = frame.f_back
    finally:
        del frame
    return " <- ".join(locations) or "Unavailable"


class MainThreadDispatch:
    def __init__(self, schedule, deliver, logger, clock=time.monotonic):
        self.schedule = schedule
        self.deliver = deliver
        self.log = logger
        self.clock = clock
        self.main_thread = threading.main_thread().ident
        self._health_pending_since = None
        self._last_warning = float("-inf")

    def start_monitor(self, stopped):
        # Independent of the serial reader: a blocked helper/transport must not
        # prevent a main-thread freeze from being captured.
        thread = threading.Thread(target=self._monitor, args=(stopped,),
                                  name="LegacyBridgeMainMonitor", daemon=True)
        thread.start()

    def _monitor(self, stopped):
        while not stopped.wait(1):
            try:
                self("health", None)
            except Exception as error:
                self.log.warning("Bridge monitor scheduling failed: error_type=%s", type(error).__name__)

    def __call__(self, event, data):
        if event == "health":
            now = self.clock()
            pending = self._health_pending_since
            if pending is not None:
                age = now - pending
                if age >= 3 and now - self._last_warning >= 15:
                    self._last_warning = now
                    self.log.warning(
                        "Bridge main-thread delivery delayed: seconds=%.2f locations=%s",
                        age, main_thread_locations(self.main_thread))
                # A frozen main thread needs one heartbeat, not an ever-growing
                # backlog of identical callbacks. Speech/index events are kept.
                return
            self._health_pending_since = now
        try:
            self.schedule(self._deliver, event, data)
        except Exception:
            if event == "health":
                self._health_pending_since = None
            raise

    def _deliver(self, event, data):
        if event == "health":
            pending = self._health_pending_since
            self._health_pending_since = None
            if pending is not None and self.clock() - pending >= 3:
                self.log.info("Bridge main-thread delivery recovered: seconds=%.2f", self.clock() - pending)
        self.deliver(event, data)
