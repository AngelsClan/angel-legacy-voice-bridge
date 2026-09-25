"""Only a running VM with this exact serial pipe can be reset."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient
from _alvb import serial_recovery

source = (Path(__file__).resolve().parents[1] /
          "addon/synthDrivers/_alvb/serial_recovery.py")
spec = importlib.util.spec_from_file_location("serial_recovery_test", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

PIPE = r"\\.\pipe\AngelLegacySpeech-XP-test"
VM = "c7fa8dfc-2661-4e37-b7b8-2508ad12edae"


class Runner:
    def __init__(self, pipe=PIPE, state="running", attach_code=0):
        self.calls = []
        self.pipe = pipe
        self.state = state
        self.attach_code = attach_code

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if command[1:3] == ["list", "runningvms"]:
            return subprocess.CompletedProcess(command, 0, f'"XP" {{{VM}}}\n')
        if command[1:3] == ["showvminfo", VM]:
            details = (f'VMState="{self.state}"\n'
                       'uartmode2="server,\\\\.\\pipe\\unrelated"\n'
                       f'uartmode1="server,{self.pipe}"\n')
            return subprocess.CompletedProcess(command, 0, details)
        if command[1] == "controlvm":
            return subprocess.CompletedProcess(
                command, self.attach_code if command[-2] == "server" else 0, "")
        raise AssertionError(command)


class SerialRecoveryTests(unittest.TestCase):
    def test_worker_repairs_silent_pipe_and_opens_new_session(self):
        repaired = threading.Event()
        opened = []

        class Transport:
            def __init__(self, healthy):
                self.healthy = healthy
                self.reply = b""

            def write(self, data):
                if not self.healthy:
                    return
                for line in data.decode().splitlines():
                    fields = line.split("\t")
                    if fields[0] == "HELLO":
                        session = fields[2]
                        self.reply += ("READY\t2\t%s\nVOICE\t0\t%s\t%s\nENDVOICES\n" % (
                            session, "Test voice".encode("utf-16-le").hex(),
                            "test-token".encode("utf-16-le").hex())).encode()
                    elif fields[0] == "PING":
                        self.reply += ("PONG\t%s\n" % fields[1]).encode()

            def read(self):
                time.sleep(.005)
                reply, self.reply = self.reply, b""
                return reply

            def close(self):
                pass

        def factory(name):
            opened.append(name)
            return Transport(repaired.is_set())

        client = BridgeClient(PIPE, transport_factory=factory)
        with patch.object(serial_recovery, "repair", side_effect=lambda name: repaired.set() or True) as fix:
            client.start()
            try:
                self.assertTrue(client.wait_connected(9))
                self.assertEqual(len(client.voices), 1)
                self.assertGreaterEqual(len(opened), 2)
                fix.assert_called_once_with(PIPE)
            finally:
                client.close()

    def test_only_exact_running_pipe_is_repaired(self):
        runner = Runner()
        self.assertTrue(module.repair(PIPE, runner, "VBoxManage.exe"))
        self.assertEqual(runner.calls[-2:], [
            ["VBoxManage.exe", "controlvm", VM, "changeuartmode1", "disconnected"],
            ["VBoxManage.exe", "controlvm", VM, "changeuartmode1", "server", PIPE]])

    def test_unrelated_pipe_and_stopped_vm_are_left_alone(self):
        for runner in (Runner(pipe=r"\\.\pipe\AngelLegacySpeech-XP-other"),
                       Runner(state="saved")):
            self.assertFalse(module.repair(PIPE, runner, "VBoxManage.exe"))
            self.assertEqual(len(runner.calls), 2)

    def test_other_named_pipe_is_rejected(self):
        runner = Runner()
        self.assertFalse(module.repair(r"\\.\pipe\other", runner, "VBoxManage.exe"))
        self.assertEqual(runner.calls, [])

    def test_failed_attach_is_reported(self):
        runner = Runner(attach_code=1)
        self.assertFalse(module.repair(PIPE, runner, "VBoxManage.exe"))
        self.assertEqual(len(runner.calls), 4)


if __name__ == "__main__":
    unittest.main()
