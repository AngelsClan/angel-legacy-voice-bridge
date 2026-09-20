"""Muted backlog/cancellation checks against an already running offline helper.

Only synthetic text is used. Does not touch NVDA, guest settings or VM power.
Reports timing/counts, never speech payloads. Run after disconnecting NVDA's bridge.
"""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient, DEFAULT_PIPE
from _alvb.protocol import Speech, Bookmark
from _alvb.pipe import Pipe
from integration import wait_until


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--drop-index-every", type=int, default=0,
                        help="Fault injection: omit every Nth received INDEX line")
    args = parser.parse_args()
    if not 2 <= args.count <= 60 or args.drop_index_every < 0:
        parser.error("Use count 2..60 and a nonnegative drop interval")
    events = []
    class ProbePipe(Pipe):
        def __init__(self, name):
            super().__init__(name)
            self.pending = bytearray()
            self.index_count = 0

        def read(self):
            self.pending.extend(super().read())
            delivered = bytearray()
            while b"\n" in self.pending:
                end = self.pending.index(10) + 1
                line = bytes(self.pending[:end])
                del self.pending[:end]
                if line.startswith(b"INDEX\t"):
                    self.index_count += 1
                    if args.drop_index_every and self.index_count % args.drop_index_every == 0:
                        continue
                delivered.extend(line)
            return bytes(delivered)

    client = BridgeClient(args.pipe, lambda event, data: events.append((event, data, time.monotonic())), ProbePipe)
    client.start()
    cpu_start = time.process_time()
    started = time.monotonic()
    try:
        wait_until(lambda: client.connected)
        voice = next((i for i, name in client.voices.items() if "Mike" in name), next(iter(client.voices)))
        for quality in (0, 48000):
            client.quality = quality
            events.clear()
            for index in range(args.count):
                client.enqueue([Speech("Test.", voice, rate=20, volume=0), Bookmark(index)])
            wait_until(lambda: any(e == "done" for e, d, t in events), 120)
            indexes = [d[1] for e, d, t in events if e == "index"]
            assert indexes == list(range(args.count)), (len(indexes), client.status)
            times = [t for e, d, t in events if e == "index"]
            gaps = [b - a for a, b in zip(times, times[1:])]
            print(f"PASS backlog format={quality}: {len(indexes)} ordered completions; max gap={max(gaps):.3f}s", flush=True)
        if args.drop_index_every:
            assert client._recovered_indexes > 0
            print(f"PASS recovered {client._recovered_indexes} deliberately omitted bookmarks", flush=True)
        # Cancellation must work even while a large utterance is being prepared.
        worst_cancel = 0
        for iteration in range(20):
            client.enqueue([Speech("A queued event. " * 900, voice, volume=0), Bookmark(999)])
            time.sleep(.005)
            before = time.monotonic()
            client.cancel()
            worst_cancel = max(worst_cancel, time.monotonic() - before)
        events.clear()
        client.enqueue([Speech("Recovered.", voice, rate=20, volume=0), Bookmark(1000)])
        wait_until(lambda: any(e == "done" for e, d, t in events), 20)
        assert [d[1] for e, d, t in events if e == "index"] == [1000]
        assert worst_cancel < .1, worst_cancel
        print(f"PASS repeated backlog cancellation: max caller wait={worst_cancel:.4f}s", flush=True)
        # An NVDA utterance may contain only an index, or empty strings and indexes.
        for items in ([Bookmark(2000)], [Speech("", voice, volume=0), Bookmark(2000)]):
            events.clear()
            client.enqueue(items)
            wait_until(lambda: any(e == "done" for e, d, t in events), 15)
            assert [d[1] for e, d, t in events if e == "index"] == [2000]
        print("PASS bookmark-only and empty-text utterances", flush=True)
        assert not any(e == "disconnected" for e, d, t in events), client.status
    finally:
        client.close(wait=False)
        assert client.closed_event.wait(3), "Test worker did not release pipe"
        print(f"Probe elapsed={time.monotonic()-started:.2f}s CPU={time.process_time()-cpu_start:.2f}s", flush=True)


if __name__ == "__main__":
    main()
