"""Recovery ownership regressions; no live NVDA or VM is used."""
import ctypes
import sys
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient
from _alvb.pipe import Pipe, INVALID_HANDLE

class TransportRetentionTests(unittest.TestCase):
    def test_failure_logging_cannot_hold_state_lock(self):
        entered=threading.Event();release=threading.Event()
        logger=Mock()
        def warning(*args):entered.set();release.wait(2)
        logger.warning.side_effect=warning
        client=BridgeClient(transport_factory=Mock(),logger=logger)
        client.connected=True
        thread=threading.Thread(target=client._disconnect,args=("test helper unavailable",))
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(client._lock.acquire(timeout=.1))
            client._lock.release()
            client.cancel()
        finally:release.set();thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_previous_session_audio_and_catalog_cannot_enter_new_session(self):
        client=BridgeClient(transport_factory=Mock());client.audio=Mock()
        client._session="new";client._active=(3,1,0)
        frames=[["READY","2","old"],["VOICE","0","bad","bad"],["ENDVOICES"],
                ["AUDIOFORMAT","old","3","1","48000","16","1"],
                ["AUDIO","old","3","1","0","0000"],
                ["INDEX","old","3","1","1"],["DONE","old","3","1"],
                ["ACK","old","3","1"],["CAPS","old","audio-pcm"]]
        for fields in frames:client._process_line(fields)
        self.assertFalse(client.connected)
        self.assertFalse(client._ready_seen)
        self.assertFalse(client._audio_supported)
        client.audio.start.assert_not_called();client.audio.feed.assert_not_called()

    def run_recovery(self, error, reusable):
        transports=[];sessions=[];recovered=threading.Event();release=threading.Event()
        def factory(name):
            transport=Mock()
            transport.can_reuse_after.return_value=reusable
            transports.append(transport)
            return transport
        client=BridgeClient(transport_factory=factory)
        def session(transport):
            sessions.append(transport)
            if len(sessions)==1:raise error
            recovered.set();release.wait(3)
        client._session_loop=session
        client.start()
        try:
            self.assertTrue(recovered.wait(3))
            self.assertEqual(len(transports),1 if reusable else 2)
            if reusable:
                self.assertIs(sessions[0],sessions[1])
                transports[0].close.assert_not_called()
            else:transports[0].close.assert_called_once()
        finally:
            client.close(wait=False);release.set()
            self.assertTrue(client.closed_event.wait(3))
        for transport in transports:transport.close.assert_called_once()

    def test_helper_timeout_rehandshakes_without_reopening(self):
        self.run_recovery(TimeoutError("No reply from XP helper"),True)

    def test_canceled_write_rehandshakes_without_reopening(self):
        self.run_recovery(ctypes.WinError(995),True)

    def test_broken_pipe_still_closes_and_opens_new_transport(self):
        self.run_recovery(ctypes.WinError(109),False)

    def test_reuse_policy_excludes_broken_handles_and_protocol_errors(self):
        pipe=Pipe.__new__(Pipe);pipe.handle=1
        self.assertTrue(pipe.can_reuse_after(TimeoutError("helper unavailable")))
        self.assertTrue(pipe.can_reuse_after(ctypes.WinError(995)))
        for error in [ctypes.WinError(109),ctypes.WinError(232),ctypes.WinError(5),ValueError("bad frame"),OSError("short write")]:
            self.assertFalse(pipe.can_reuse_after(error))
        pipe.handle=INVALID_HANDLE
        self.assertFalse(pipe.can_reuse_after(TimeoutError()))

if __name__ == "__main__":unittest.main()
