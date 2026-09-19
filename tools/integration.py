"""Exercise the real XP helper over its pipe, without loading/restarting NVDA.

Only synthetic test phrases are sent. Most checks use volume zero. This verifies
protocol/SAPI completion, not audible quality or end-to-end screen-reader delay.
"""
import argparse
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient, DEFAULT_PIPE
from _alvb.pipe import Pipe
from _alvb.protocol import Bookmark, LineReader, Speech, speech_frame


def wait_until(condition, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(.01)
    raise AssertionError("Timed out waiting for test condition")


class Probe:
    def __init__(self, name):
        self.pipe = Pipe(name)
        self.reader = LineReader()
        self.session = uuid.uuid4().hex
        self.lines = []

    def send(self, line):
        self.pipe.write((line + "\n").encode("ascii"))

    def expect(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.lines.extend(self.reader.feed(self.pipe.read()))
            for index, fields in enumerate(self.lines):
                if predicate(fields):
                    return self.lines.pop(index)
        raise AssertionError("Expected response not received")

    def hello(self):
        self.lines.clear()
        frame = f"\nHELLO\t1\t{self.session}\n".encode()
        # Deliberately split a command across separate pipe writes.
        for start in range(0, len(frame), 7):
            self.pipe.write(frame[start:start + 7])
        self.expect(lambda f: f == ["READY", "1", self.session])
        self.expect(lambda f: f == ["ENDVOICES"])
        voices = [f for f in self.lines if f[0] == "VOICE"]
        assert voices and all(len(f) == 4 for f in voices)
        assert len({f[3] for f in voices}) == len(voices)
        return voices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    args = parser.parse_args()
    probe = Probe(args.pipe)
    try:
        voices = probe.hello()
        print("PASS fragmented handshake and unique stable voice IDs", flush=True)
        for request, fields in enumerate(voices, 1):
            probe.pipe.write(speech_frame(probe.session, 0, request, Speech("Bridge check.", int(fields[1]), volume=0)))
            probe.expect(lambda f: f == ["DONE", probe.session, "0", str(request)])
        print("PASS SAPI completion for every installed voice (muted)", flush=True)
        probe.send(f"PAUSE\t{probe.session}\tinvalid")
        probe.expect(lambda f: f[0] == "ERROR" and f[-1] == "invalid-pause")
        # A deliberately invalid line exceeds normal speech frames. Pace it so
        # this parser test does not become an emulated UART FIFO-overrun test.
        oversized = b"x" * 8300 + b"\n"
        for start in range(0, len(oversized), 128):
            probe.pipe.write(oversized[start:start + 128])
            time.sleep(.02)
        probe.expect(lambda f: f[0] == "ERROR" and f[-1] == "invalid-line")
        probe.pipe.write(f"PING\t{probe.session}".encode() + b"\x00junk\n")
        probe.expect(lambda f: f[0] == "ERROR" and f[-1] == "invalid-line")
        probe.send(f"PING\t{probe.session}")
        probe.expect(lambda f: f == ["PONG", probe.session])
        print("PASS malformed/oversized input and recovery", flush=True)
        probe.send(f"CANCEL\t{probe.session}\t7")
        probe.expect(lambda f: f == ["CANCELLED", probe.session, "7"])
        probe.pipe.write(speech_frame(probe.session, 0, 99, Speech("Stale request", volume=0)))
        probe.send(f"PING\t{probe.session}")
        probe.expect(lambda f: f == ["PONG", probe.session])
        assert not any(f[0] in ("ACCEPTED", "DONE") and f[2:4] == ["0", "99"] for f in probe.lines)
        print("PASS stale-generation speech rejected", flush=True)
        # No heartbeat: the helper must forget this session, then accept a new one.
        time.sleep(6.5)
        old_session = probe.session
        probe.session = uuid.uuid4().hex
        probe.hello()
        probe.send(f"PING\t{old_session}")
        probe.send(f"PING\t{probe.session}")
        probe.expect(lambda f: f == ["PONG", probe.session])
        assert not any(f == ["PONG", old_session] for f in probe.lines)
        print("PASS heartbeat expiry and fresh-session recovery", flush=True)
    finally:
        probe.pipe.close()

    previous_worker = None
    for iteration in range(3):
        events = []
        client = BridgeClient(args.pipe, lambda event, data: events.append((event, data)), wait_for=previous_worker)
        client.start()
        try:
            wait_until(lambda: client.connected)
            voice = next(iter(client.voices))
            client.enqueue([Speech("Testing pause and cancel. " * 20, voice, volume=0), Bookmark(1)])
            wait_until(lambda: client._active is not None)
            client.pause(True)
            time.sleep(.15)
            client.cancel()
            client.enqueue([Speech("Recovered.", voice, volume=0), Bookmark(2)])
            wait_until(lambda: any(event == "done" for event, data in events))
            assert [data[1] for event, data in events if event == "index"] == [2]
            print(f"PASS connection {iteration + 1}: paused cancellation, new speech, correct bookmark", flush=True)
        finally:
            client.close(wait=False)
            previous_worker = client.closed_event
    assert previous_worker.wait(2), "Last test worker did not stop"
    print("LIVE XP INTEGRATION PASSED", flush=True)


if __name__ == "__main__":
    main()
