"""Opt-in audible test against a running XP helper; does not modify NVDA."""
import argparse
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient, DEFAULT_PIPE
from _alvb.protocol import Bookmark, Speech


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--speak", action="store_true", help="Speak a short test using Mike when available")
    args = parser.parse_args()
    done = threading.Event()
    indices = []

    def event(name, data):
        print(name, data, flush=True)
        if name == "index":
            indices.append(data[1])
        if name == "done":
            done.set()

    client = BridgeClient(args.pipe, event)
    client.start()
    try:
        deadline = time.monotonic() + 12
        while not client.connected and time.monotonic() < deadline:
            time.sleep(.05)
        if not client.connected:
            raise RuntimeError(client.status)
        print("VOICE ENUMERATION PASSED", flush=True)
        if args.speak:
            voice = next((index for index, name in client.voices.items() if "mike" in name.lower()), next(iter(client.voices)))
            assert client.enqueue([Speech("Angel Legacy Voice Bridge test. Mike is ready.", voice=voice), Bookmark(42)])
            if not done.wait(30):
                raise RuntimeError("Speech completion timed out: " + client.status)
            assert indices == [42], indices
            print("SPEECH AND BOOKMARK PASSED", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
