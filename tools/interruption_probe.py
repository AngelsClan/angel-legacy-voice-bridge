"""Synthetic cancellation at different render/playback boundaries on real XP.

Run only with NVDA's bridge disabled and VM output muted externally. Stops on
the first disconnect; never changes the active screen reader or voice settings.
"""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient
from _alvb.protocol import Bookmark, Speech
from integration import wait_until


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", required=True)
    parser.add_argument("--count", type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.count <= 300:
        parser.error("count must be between 1 and 300")
    events = []
    client = BridgeClient(args.pipe, lambda event, data: events.append((event, data)), quality=48000)
    client.start()
    started = time.monotonic()
    try:
        wait_until(lambda: client.connected)
        slot = next(slot for slot, name in client.voices.items() if "Pipe Organ" in name)
        delays = (.002, .02, .1, .25, .7, 1.5)
        for index in range(args.count):
            if not client.enqueue([Speech("Another synthetic notification. " * 3,
                                          slot, rate=16, volume=20), Bookmark(index)]):
                raise RuntimeError("Test request refused")
            wait_until(lambda: (client._active and not client._frames and not client._waiting_ack)
                       or any(event == "disconnected" for event, _ in events), 15)
            time.sleep(delays[index % len(delays)])
            failures = [data for event, data in events if event == "disconnected"]
            if failures:
                raise RuntimeError(f"Disconnect before cancellation {index}: {failures}")
            client.cancel()
            # Let the same worker advance its protocol; do not clear diagnostic
            # evidence from the connection while probing a cancellation race.
            if (index + 1) % 20 == 0:
                print(f"PASS cancellations={index + 1} elapsed={time.monotonic()-started:.2f}", flush=True)
        client.enqueue([Speech("Recovered.", slot, rate=20, volume=20), Bookmark(10000)])
        wait_until(lambda: any(event == "index" and data[1] == 10000 for event, data in events)
                   or any(event == "disconnected" for event, _ in events), 25)
        failures = [data for event, data in events if event == "disconnected"]
        if failures:
            raise RuntimeError(f"Disconnected: {failures}")
        print(f"PASS final speech after {args.count} interruptions", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
