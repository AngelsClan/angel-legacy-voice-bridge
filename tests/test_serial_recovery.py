"""Only a running VM with this exact serial pipe can be reset."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timezone
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
VM = "12345678-1234-4234-8234-123456789abc"


class Runner:
    def __init__(self, pipe=PIPE, state="running", attach_code=0,
                 info_code=0, detach_code=0, run_level=3, changed=None):
        self.calls = []
        self.pipe = pipe
        self.state = state
        self.attach_code = attach_code
        self.info_code = info_code
        self.detach_code = detach_code
        self.run_level = run_level
        self.changed = changed

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if command[1:3] == ["list", "runningvms"]:
            return subprocess.CompletedProcess(command, 0, f'"XP" {{{VM}}}\n')
        if command[1:3] == ["showvminfo", VM]:
            details = (f'VMState="{self.state}"\n' +
                       (f'VMStateChangeTime="{self.changed}"\n' if self.changed else '') +
                       (f'GuestAdditionsRunLevel={self.run_level}\n' if self.run_level is not None else '') +
                       'uartmode2="server,\\\\.\\pipe\\unrelated"\n'
                       f'uartmode1="server,{self.pipe}"\n')
            return subprocess.CompletedProcess(command, self.info_code, details)
        if command[1] == "controlvm":
            return subprocess.CompletedProcess(
                command,
                self.attach_code if command[-2] == "server" else self.detach_code,
                "")
        raise AssertionError(command)


class SerialRecoveryTests(unittest.TestCase):
    def test_worker_repairs_persistently_busy_pipe_before_first_handshake(self):
        repaired = threading.Event()
        attempts = []

        class Transport:
            def __init__(self):
                self.reply = b""

            def write(self, data):
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
                reply, self.reply = self.reply, b""
                return reply

            def close(self):
                pass

        def factory(name):
            attempts.append(name)
            if not repaired.is_set():
                error = OSError("All pipe instances are busy")
                error.winerror = 231
                raise error
            return Transport()

        repair_attempts = []

        def repair_after_save(name):
            repair_attempts.append(name)
            # The first reset occurs while VirtualBox is saving the VM.
            if len(repair_attempts) == 1:
                return False
            repaired.set()
            return True

        client = BridgeClient(PIPE, transport_factory=factory)
        with (patch.object(serial_recovery, "repair", side_effect=repair_after_save) as fix,
              patch("_alvb.client.PIPE_BUSY_REPAIR_DELAY", .1)):
            client.start()
            try:
                self.assertTrue(client.wait_connected(7), client.status)
                self.assertGreaterEqual(len(attempts), 3)
                self.assertEqual(fix.call_count, 2)
                self.assertEqual(repair_attempts, [PIPE, PIPE])
            finally:
                client.close()

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

    def test_exact_running_pipe_repair_is_blocked_without_hardware_mutation(self):
        runner = Runner()
        self.assertFalse(module.repair(PIPE, runner, "VBoxManage.exe"))
        self.assertEqual(len(runner.calls), 2)
        self.assertFalse(any(call[1] == "controlvm" for call in runner.calls))

    def test_blocked_reset_has_safe_warning_and_does_not_repeat_it(self):
        module._deferred_states.clear()
        runner = Runner()
        with self.assertLogs("serial_recovery_test", level="WARNING") as logs:
            self.assertFalse(module.repair(PIPE, runner, "VBoxManage.exe"))
            self.assertFalse(module.repair(PIPE, runner, "VBoxManage.exe"))
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Unsafe VirtualBox serial reset blocked", logs.output[0])
        self.assertNotIn(PIPE, logs.output[0])

    def test_unrelated_pipe_and_stopped_vm_are_left_alone(self):
        for runner in (Runner(pipe=r"\\.\pipe\AngelLegacySpeech-XP-other"),
                       Runner(state="saved")):
            self.assertFalse(module.repair(PIPE, runner, "VBoxManage.exe"))
            self.assertEqual(len(runner.calls), 2)

    def test_other_named_pipe_is_rejected(self):
        runner = Runner()
        self.assertFalse(module.repair(r"\\.\pipe\other", runner, "VBoxManage.exe"))
        self.assertEqual(runner.calls, [])

    def test_booting_or_unknown_guest_is_never_detached(self):
        for level in (None, 0, 1, 2):
            with self.subTest(run_level=level):
                runner = Runner(run_level=level)
                self.assertFalse(module.repair(PIPE, runner, "VBoxManage.exe"))
                self.assertEqual(len(runner.calls), 2)

    def test_connection_waits_for_known_guest_startup_levels(self):
        for level in (1, 2):
            self.assertFalse(module.connection_ready(PIPE, Runner(run_level=level), "VBoxManage.exe"))
        self.assertTrue(module.connection_ready(PIPE, Runner(run_level=3), "VBoxManage.exe"))

    def test_no_guest_additions_has_bounded_cold_start_grace(self):
        for level in (None, 0):
            runner = Runner(run_level=level, changed='2026-10-07T22:00:00.000000000')
            self.assertFalse(module.connection_ready(PIPE, runner, 'VBoxManage.exe', now=datetime(2026,10,7,22,0,20,tzinfo=timezone.utc)))
            self.assertTrue(module.connection_ready(PIPE, runner, 'VBoxManage.exe', now=datetime(2026,10,7,22,1,30,tzinfo=timezone.utc)))

    def test_connection_keeps_other_transports_and_unknown_metadata_working(self):
        self.assertTrue(module.connection_ready(PIPE, Runner(pipe='unrelated',run_level=1), 'VBoxManage.exe'))
        self.assertTrue(module.connection_ready(PIPE, Runner(run_level=None), 'VBoxManage.exe'))
        self.assertTrue(module.connection_ready(PIPE, Runner(run_level=0,changed='invalid'), 'VBoxManage.exe'))

    def test_worker_does_not_open_transport_while_startup_is_pending(self):
        checked=threading.Event();ready=threading.Event();opened=threading.Event()
        def startup(name):
            checked.set();return ready.is_set()
        def factory(name):
            opened.set();raise OSError('Expected fixture open failure')
        client=BridgeClient(PIPE,transport_factory=factory,startup_ready=startup)
        client.start()
        try:
            self.assertTrue(checked.wait(1))
            self.assertFalse(opened.is_set())
            ready.set()
            self.assertTrue(opened.wait(2))
        finally:client.close()

    def test_repair_waits_until_same_guest_session_is_ready(self):
        runner = Runner(run_level=1)
        self.assertFalse(module.repair(PIPE, runner, "VBoxManage.exe"))
        runner.run_level = 3
        self.assertFalse(module.repair(PIPE, runner, "VBoxManage.exe"))
        self.assertEqual([call[1] for call in runner.calls].count("controlvm"), 0)

    def test_failed_attach_is_reported(self):
        runner = Runner(attach_code=1)
        self.assertFalse(module.repair(PIPE, runner, "VBoxManage.exe"))
        self.assertEqual(len(runner.calls), 2)

    def test_vm_access_denied_does_not_detach_anything(self):
        runner = Runner(info_code=1)
        self.assertFalse(module.repair(PIPE, runner, "VBoxManage.exe"))
        self.assertEqual(len(runner.calls), 2)

    def test_repair_never_destroys_char_driver_with_intermediate_disconnect(self):
        runner = Runner(detach_code=1)
        self.assertFalse(module.repair(PIPE, runner, "VBoxManage.exe"))
        self.assertEqual(len(runner.calls), 2)
        self.assertFalse(any("disconnected" in call for call in runner.calls))


if __name__ == "__main__":
    unittest.main()
