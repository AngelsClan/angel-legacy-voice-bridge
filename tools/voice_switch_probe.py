"""Exercise real bridge voice transitions without touching the active NVDA.

Disconnect the add-on first and mute VM output externally. Volume zero alone
is not guaranteed silent for every third-party engine. Only test text is sent.
"""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient
from _alvb.protocol import Speech, Bookmark
from integration import wait_until


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", required=True)
    parser.add_argument("--quality", type=int, default=48000)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--volume", type=int, default=80)
    parser.add_argument("--rate", type=int, default=16)
    parser.add_argument("--interrupt", action="store_true")
    args = parser.parse_args()
    events = []
    client = BridgeClient(args.pipe, lambda event, data: events.append((event, data)))
    client.quality = args.quality
    client.start()
    try:
        wait_until(lambda: client.connected)
        voices = list(client.voices.items())
        for turn in range(args.rounds):
            for slot, name in voices if turn % 2 == 0 else reversed(voices):
                events.clear()
                client.cancel()
                text = "Voice switch check. " * (20 if args.interrupt else 1)
                client.enqueue([Speech(text, slot, rate=args.rate, volume=args.volume), Bookmark(7)])
                if args.interrupt:
                    # busy alone becomes true before BEGIN is even written. Wait
                    # for COMMIT acknowledgement, not merely queue admission.
                    wait_until(lambda: (client._active and not client._frames and not client._waiting_ack)
                               or any(event in ("done", "disconnected") for event, data in events), 25)
                    time.sleep(.15)
                else:
                    wait_until(lambda: any(event in ("done", "disconnected") for event, data in events), 25)
                errors = [data for event, data in events if event == "disconnected"]
                if errors:
                    raise RuntimeError(f"FAIL slot={slot} voice={name} quality={args.quality}: {errors}")
                if not args.interrupt:
                    assert [data[1] for event, data in events if event == "index"] == [7], events
                print(f"PASS round={turn+1} slot={slot} voice={name} quality={args.quality}", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
