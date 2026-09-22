"""Opt-in XP token replacement regression. Uses one disposable SAPI alias.

Requires ALVB_XP_PASSWORD in the environment, disconnected NVDA bridge and
externally muted VM output. Never modifies real voice registrations.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient
from _alvb.protocol import Speech, Bookmark
from _alvb.pipe import Pipe
from integration import wait_until

BASE = "HKLM\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\"
ALIAS = "ALVB-Disposable-Reinstall-Test"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--pipe", required=True)
    parser.add_argument("--vbox", required=True)
    parser.add_argument("--expect-failure", action="store_true")
    parser.add_argument("--selected-before", action="store_true")
    parser.add_argument("--pause-before-commit", action="store_true")
    args = parser.parse_args()

    def reg(*arguments, required=True):
        result = subprocess.run([args.vbox, "guestcontrol", args.vm, "run", "--username", args.username,
            "--password", os.environ["ALVB_XP_PASSWORD"], "--exe", r"C:\WINDOWS\system32\reg.exe",
            "--wait-stdout", "--wait-stderr", "--", *arguments], capture_output=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if required and result.returncode:
            raise RuntimeError("Disposable registry operation failed")
        return result.returncode

    reg("query", BASE + "PantheraClassicXP_Agnes")
    if reg("query", BASE + ALIAS, required=False) == 0:
        raise RuntimeError("Disposable alias already exists; refusing to touch it")
    created = False
    events = []
    pause_next = [False]

    class PauseAtCommit(Pipe):
        def write(self, data):
            if pause_next[0] and data.startswith(b"COMMIT\t"):
                pause_next[0] = False
                session = data.split(b"\t")[1]
                super().write(b"PAUSE\t" + session + b"\t1\n")
                with client._lock:
                    client._paused = True
                    client._pause_started = time.monotonic()
            return super().write(data)

    client = BridgeClient(args.pipe, lambda event, data: events.append((event, data)), PauseAtCommit)
    try:
        reg("copy", BASE + "PantheraClassicXP_Agnes", BASE + ALIAS, "/s", "/f")
        created = True
        client.start()
        wait_until(lambda: client.connected)
        wait_until(lambda: any(token.endswith(ALIAS) for token in client.voice_tokens.values()), 40)
        slot = next(slot for slot, token in client.voice_tokens.items() if token.endswith(ALIAS))
        # Hold the catalog token while an installer replaces its registry key.
        client._refresh_supported = False
        client._refresh_disabled = True
        if args.selected_before:
            events.clear()
            client.enqueue([Speech("Before reinstall check.", slot, volume=0)])
            wait_until(lambda: any(event in ("done", "disconnected") for event, data in events), 25)
            if any(event == "disconnected" for event, data in events):
                raise AssertionError("Initial voice failed before replacement")
        reg("delete", BASE + ALIAS, "/f")
        reg("copy", BASE + "PantheraClassicXP_Agnes", BASE + ALIAS, "/s", "/f")
        events.clear()
        previous_recoveries = client._voice_recoveries
        client.quality = 48000
        pause_next[0] = args.pause_before_commit
        client.enqueue([Speech("Voice registration replacement check.", slot, volume=0), Bookmark(7)])
        if args.pause_before_commit:
            wait_until(lambda: (client._active and not client._frames and not client._waiting_ack)
                       or any(event == "disconnected" for event, data in events), 25)
            time.sleep(6)
            if any(event in ("done", "index", "disconnected") for event, data in events):
                raise AssertionError("Paused replacement completed or failed before resume")
            client.pause(False)
        wait_until(lambda: any(event in ("done", "disconnected") for event, data in events), 25)
        failures = [data for event, data in events if event == "disconnected"]
        print("Replacement result:", failures or "speech completed", flush=True)
        if bool(failures) != args.expect_failure:
            raise AssertionError("Token replacement result differed from expectation")
        if not failures:
            assert [data[1] for event, data in events if event == "index"] == [7]
            assert client.output_format == "48000 Hz, 16-bit, 1 channel(s)"
            if args.selected_before:
                assert client._voice_recoveries == previous_recoveries + 1
            print("Verified completion, bookmark, format and expected recovery count", flush=True)
    finally:
        try:
            if created:
                reg("delete", BASE + ALIAS, "/f")
                # Remove the disposable entry from the live catalog too. A
                # later probe must not mistake our removed test alias for a
                # real installed voice while waiting for the next idle scan.
                client.cancel()
                client._refresh_disabled = False
                client._refresh_supported = True
                wait_until(lambda: client.connected and
                           not any(token.endswith(ALIAS) for token in client.voice_tokens.values()), 35)
        finally:
            client.close()


if __name__ == "__main__":
    main()
