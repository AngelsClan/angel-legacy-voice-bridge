"""Repair a VirtualBox host pipe after a VM saved-state resume.

Only a running VM whose serial server pipe exactly matches the configured
bridge pipe may be changed. This is called after a failed handshake, never
while a healthy bridge session is speaking. No XP process or VM is restarted.
"""
import os
import re
import shutil
import subprocess


def _vbox_executable():
    found = shutil.which("VBoxManage.exe")
    if found:
        return found
    candidate = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                             "Oracle", "VirtualBox", "VBoxManage.exe")
    return candidate if os.path.isfile(candidate) else None


def _run(command, runner):
    return runner(command, capture_output=True, text=True, timeout=5,
                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def matching_serial(pipe_name, runner=subprocess.run, executable=None):
    """Return (VBoxManage path, VM UUID, UART index) or None."""
    if not pipe_name.lower().startswith(r"\\.\pipe\angellegacyspeech-"):
        return None
    executable = executable or _vbox_executable()
    if not executable:
        return None
    try:
        listed = _run([executable, "list", "runningvms"], runner)
        if listed.returncode:
            return None
        for line in listed.stdout.splitlines():
            match = re.search(r"\{([0-9a-fA-F-]{36})\}\s*$", line)
            if not match:
                continue
            vm_id = match.group(1)
            details = _run([executable, "showvminfo", vm_id, "--machinereadable"], runner)
            if details.returncode or 'VMState="running"' not in details.stdout:
                continue
            for row in details.stdout.splitlines():
                port = re.fullmatch(r'uartmode([1-4])="server,(.*)"', row)
                if port and port.group(2).lower() == pipe_name.lower():
                    return executable, vm_id, port.group(1)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None


def repair(pipe_name, runner=subprocess.run, executable=None):
    """Recreate just the matching serial pipe; caller then opens a new session."""
    matched = matching_serial(pipe_name, runner, executable)
    if not matched:
        return False
    binary, vm_id, port = matched
    try:
        detached = _run([binary, "controlvm", vm_id,
                         "changeuartmode" + port, "disconnected"], runner)
        if detached.returncode:
            return False
        # Always attempt to restore the exact saved pipe, even if VBoxManage
        # reports a failed attach. A later retry can then recover it.
        attached = _run([binary, "controlvm", vm_id,
                         "changeuartmode" + port, "server", pipe_name], runner)
        return attached.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
