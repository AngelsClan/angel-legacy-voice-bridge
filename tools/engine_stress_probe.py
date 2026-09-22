"""Bounded synthetic XP speech checks, independent of the user's NVDA.

Disconnect the add-on and mute VM output before running. No private text is
read or printed. A failure stops the run, retaining numeric transport evidence.
"""
import argparse
import logging
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
    parser.add_argument("--voice", default="Pipe Organ")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--mixed-controls", action="store_true",
                        help="Change pitch/rate/volume inside each utterance")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    events = []
    client = BridgeClient(args.pipe, lambda event, data: events.append((event, data)), quality=48000)
    client.start()
    phrases = [
        "This is a synthetic speech queue test, with a full sentence.",
        "It's Alex's turn. Don't stop; isn't that right?",
        "!\u0412 \u0441\u0430\u0434\u0443\U0001f333\u26c5 channel",
        "Question mode. User joined. Channel updated. Window changed. " * 3,
        "One, two: three! Four? Five (six); seven & eight. ",
    ]
    try:
        wait_until(lambda: client.connected)
        slot = next(slot for slot, name in client.voices.items() if args.voice in name)
        for turn in range(args.rounds):
            for case, phrase in enumerate(phrases):
                events.clear()
                started = time.monotonic()
                items = [Speech(phrase, slot, rate=16, volume=20), Bookmark(7)]
                expected = [7]
                if args.mixed_controls:
                    # A second style forces a separate SAPI rendering run within
                    # one accepted stream, unlike merely changing voices.
                    items += [Speech("Next.", slot, rate=20, volume=30, pitch=14), Bookmark(8)]
                    expected = [7, 8]
                client.enqueue(items)
                wait_until(lambda: any(event in ("done", "disconnected") for event, _ in events), 100)
                failures = [data for event, data in events if event == "disconnected"]
                if failures:
                    raise RuntimeError(f"Engine failed: round={turn} case={case} errors={failures}")
                if [data[1] for event, data in events if event == "index"] != expected:
                    raise RuntimeError("Missing or out-of-order completion indexes")
                print(f"PASS round={turn} case={case} seconds={time.monotonic()-started:.2f}", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
