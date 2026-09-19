"""Same-session, disable-only maintenance signal. No network or command server."""
import ctypes
from ctypes import wintypes
import os
import logging


def event_name(pid, action):
    return f"Local\\AngelLegacyVoiceBridge.{int(pid)}.{action}"


def windows_api():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateEventW.restype = wintypes.HANDLE
    api.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    api.OpenEventW.restype = wintypes.HANDLE
    for name in ("SetEvent", "ResetEvent", "CloseHandle"):
        function = getattr(api, name)
        function.argtypes = [wintypes.HANDLE]
        function.restype = wintypes.BOOL
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    return api


class DisableControl:
    """Polled by NVDA's UI timer; acknowledgement follows worker shutdown."""
    def __init__(self, api=None, pid=None):
        self.api = api or windows_api()
        self.request = None
        self.acknowledged = None
        self.pending = False
        pid = os.getpid() if pid is None else pid
        try:
            self.request = self.api.CreateEventW(None, False, False, event_name(pid, "disable"))
            self.acknowledged = self.api.CreateEventW(None, True, False, event_name(pid, "disabled"))
            if not self.request or not self.acknowledged:
                raise OSError("Cannot create bridge maintenance events")
        except Exception:
            self.close()
            raise

    def poll(self, disable, is_stopped):
        if self.api.WaitForSingleObject(self.request, 0) == 0:
            self.api.ResetEvent(self.acknowledged)
            self.pending = True
            try:
                disable()
            except Exception:
                # Never acknowledge successful maintenance if local-speech
                # restoration failed. The caller times out and can retry safely.
                self.pending = False
                logging.getLogger(__name__).exception("Bridge maintenance disable could not complete")
        if self.pending and is_stopped():
            self.api.SetEvent(self.acknowledged)
            self.pending = False

    def close(self):
        for handle in (self.request, self.acknowledged):
            if handle:
                self.api.CloseHandle(handle)
        self.request = self.acknowledged = None


def request_disable(pid, timeout_ms=10000):
    api = windows_api()
    request = api.OpenEventW(0x0002, False, event_name(pid, "disable"))
    acknowledged = api.OpenEventW(0x100002, False, event_name(pid, "disabled"))
    try:
        if not request or not acknowledged:
            raise OSError("No accessible bridge control for this NVDA process; install the updated add-on first")
        if not api.ResetEvent(acknowledged) or not api.SetEvent(request):
            raise OSError("Cannot signal bridge disable")
        if api.WaitForSingleObject(acknowledged, timeout_ms) != 0:
            raise TimeoutError("Disable was requested but worker shutdown was not confirmed")
    finally:
        for handle in (request, acknowledged):
            if handle:
                api.CloseHandle(handle)
