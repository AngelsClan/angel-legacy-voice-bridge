"""Bounded Windows named-pipe I/O, used only on the bridge worker thread."""
import ctypes
import os
from ctypes import wintypes

kernel = ctypes.WinDLL("kernel32", use_last_error=True)
INVALID_HANDLE = ctypes.c_void_p(-1).value
ERROR_IO_PENDING = 997
ERROR_OPERATION_ABORTED = 995
WAIT_TIMEOUT = 258


def discover_pipes():
    """List local bridge pipes only; never boot or reconfigure a VM."""
    try:
        return sorted("\\\\.\\pipe\\" + name for name in os.listdir("\\\\.\\pipe\\")
                      if name.startswith("AngelLegacySpeech-"))
    except OSError:
        return []


class Overlapped(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]


def declare(name, arguments, result):
    function = getattr(kernel, name)
    function.argtypes = arguments
    function.restype = result
    return function


create_file = declare("CreateFileW", [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE)
create_event = declare("CreateEventW", [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE)
close_handle = declare("CloseHandle", [wintypes.HANDLE], wintypes.BOOL)
wait = declare("WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD)
read_file = declare("ReadFile", [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(Overlapped)], wintypes.BOOL)
write_file = declare("WriteFile", read_file.argtypes, wintypes.BOOL)
cancel_io = declare("CancelIoEx", [wintypes.HANDLE, ctypes.POINTER(Overlapped)], wintypes.BOOL)
get_result = declare("GetOverlappedResult", [wintypes.HANDLE, ctypes.POINTER(Overlapped),
                                           ctypes.POINTER(wintypes.DWORD), wintypes.BOOL], wintypes.BOOL)


class Pipe:
    def __init__(self, name):
        if not name.startswith("\\\\.\\pipe\\AngelLegacySpeech-"):
            raise ValueError("Use a local pipe beginning \\\\.\\pipe\\AngelLegacySpeech-")
        # OVERLAPPED | SECURITY_SQOS_PRESENT | SECURITY_ANONYMOUS prevents the
        # pipe server from impersonating the screen reader's Windows token.
        self.handle = create_file(name, 0xC0000000, 0, None, 3, 0x40100000, None)
        if self.handle == INVALID_HANDLE:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle != INVALID_HANDLE:
            close_handle(self.handle)
            self.handle = INVALID_HANDLE

    def _transfer(self, data, writing, timeout):
        buffer = ctypes.create_string_buffer(data) if writing else ctypes.create_string_buffer(4096)
        size = len(data) if writing else 4096
        event = create_event(None, True, False, None)
        if not event:
            raise ctypes.WinError(ctypes.get_last_error())
        operation = Overlapped(hEvent=event)
        transferred = wintypes.DWORD()
        try:
            function = write_file if writing else read_file
            started = function(self.handle, buffer, size, ctypes.byref(transferred), ctypes.byref(operation))
            if not started:
                error = ctypes.get_last_error()
                if error != ERROR_IO_PENDING:
                    raise ctypes.WinError(error)
                status = wait(event, timeout)
                if status == WAIT_TIMEOUT:
                    cancel_io(self.handle, ctypes.byref(operation))
                elif status != 0:
                    cancel_io(self.handle, ctypes.byref(operation))
                # The buffers must remain alive until Windows acknowledges cancellation.
                if not get_result(self.handle, ctypes.byref(operation), ctypes.byref(transferred), True):
                    error = ctypes.get_last_error()
                    if error == ERROR_OPERATION_ABORTED and not writing:
                        return b""
                    raise ctypes.WinError(error)
            if writing:
                if transferred.value != size:
                    raise OSError("Incomplete pipe write; reconnect required")
                return b""
            return buffer.raw[:transferred.value]
        finally:
            close_handle(event)

    def write(self, data):
        return self._transfer(data, True, 500)

    def read(self):
        return self._transfer(None, False, 20)
