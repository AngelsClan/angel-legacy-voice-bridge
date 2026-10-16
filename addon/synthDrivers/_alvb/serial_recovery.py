"""VirtualBox readiness checks and safe diagnostics for serial connections.

Never replace a running UART backend. The former repair entry point remains
as a diagnostic-only compatibility hook; it performs no VM mutation.
"""
import os
import logging
import re
import shutil
import subprocess
from datetime import datetime, timezone

try:
    from logHandler import log
except ImportError:
    log = logging.getLogger(__name__)
_deferred_states = {}


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


def matching_serial(pipe_name, runner=subprocess.run, executable=None, require_ready=True):
    """Return the exact UART match; a readiness query also includes VM info."""
    if not pipe_name.lower().startswith(r"\\.\pipe\angellegacyspeech-"):
        return None
    executable = executable or _vbox_executable()
    if not executable:
        return None
    try:
        listed = _run([executable, "list", "runningvms"], runner)
        if listed.returncode:
            log.warning("Serial readiness query failed: operation=list_runningvms exit_code=%s", listed.returncode)
            return None
        for line in listed.stdout.splitlines():
            match = re.search(r"\{([0-9a-fA-F-]{36})\}\s*$", line)
            if not match:
                continue
            vm_id = match.group(1)
            details = _run([executable, "showvminfo", vm_id, "--machinereadable"], runner)
            if details.returncode:
                log.warning("Serial readiness query failed: operation=showvminfo exit_code=%s", details.returncode)
                continue
            if 'VMState="running"' not in details.stdout:
                continue
            # There can be several UARTs. Match the exact configured pipe before
            # consulting readiness, so unrelated VMs do not produce boot logs.
            ports = [re.fullmatch(r'uartmode([1-4])="server,(.*)"', row)
                     for row in details.stdout.splitlines()]
            port = next((value for value in ports if value and value.group(2).lower() == pipe_name.lower()), None)
            if port is None:
                continue
            if not require_ready:
                return executable, vm_id, port.group(1), details.stdout
            # Running describes the VM process, not a ready guest. Replacing a
            # serial backend while XP is loading drivers can stall its startup.
            # Guest Additions reports 3 only after user-session startup. If we
            # cannot establish readiness, normal connection retries remain safe.
            level = re.search(r'^GuestAdditionsRunLevel=(\d+)\s*$', details.stdout, re.M)
            if level is None or int(level.group(1)) != 3:
                value = level.group(1) if level else "unavailable"
                if _deferred_states.get(vm_id) != value:
                    if len(_deferred_states) >= 16:
                        _deferred_states.clear()
                    _deferred_states[vm_id] = value
                    log.info("Serial recovery deferred: guest user session is not ready; run_level=%s", value)
                continue
            _deferred_states.pop(vm_id, None)
            return executable, vm_id, port.group(1)
    except (OSError, subprocess.TimeoutExpired) as error:
        log.warning("Serial readiness query unavailable: error_type=%s error_code=%s", type(error).__name__, getattr(error, "winerror", None) or getattr(error, "errno", None))
        return None
    return None


def connection_ready(pipe_name, runner=subprocess.run, executable=None, now=None):
    """Avoid opening an exact VirtualBox UART while the guest is starting.

    Known Guest Additions startup levels 1 and 2 wait for level 3. A guest with
    no readiness service gets only a bounded 90-second cold-start grace period;
    no new installation requirement is imposed on non-GA or other transports.
    """
    matched = matching_serial(pipe_name, runner, executable, require_ready=False)
    if not matched:
        return True
    details = matched[3]
    level = re.search(r'^GuestAdditionsRunLevel=(\d+)\s*$', details, re.M)
    value = int(level.group(1)) if level else None
    if value == 3:
        return True
    if value in (1, 2):
        return False
    started = re.search(r'^VMStateChangeTime="([^"]+)"\s*$', details, re.M)
    if not started:
        return True  # Old/unsupported metadata: retain normal connections.
    try:
        stamp = datetime.fromisoformat(started.group(1).rstrip('Z')).replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        return (current - stamp).total_seconds() >= 90
    except ValueError:
        return True


def repair(pipe_name, runner=subprocess.run, executable=None):
    """Never hot-detach a serial driver to repair a host connection.

    VirtualBox 7.2.18 reproduced an access violation during shutdown after
    replacement. Even server-to-server changes detach the driver internally.
    The client continues ordinary transport reconnects. A saved-state pipe
    that cannot reconnect may need a normal guest shutdown and cold boot.
    Readiness checks above remain available.
    """
    matched = matching_serial(pipe_name, runner, executable)
    if not matched:
        return False
    _, vm_id, port = matched
    key = (vm_id, "hot_reset_blocked")
    if key not in _deferred_states:
        if len(_deferred_states) >= 16:
            _deferred_states.clear()
        _deferred_states[key] = True
        log.warning("Unsafe VirtualBox serial reset blocked; normal connection retries continue; uart=%s", port)
    return False
