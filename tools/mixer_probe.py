"""Opt-in XP mixer test; raises guest playback levels but never unmutes them."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient, DEFAULT_PIPE
from _alvb.protocol import Speech
from integration import wait_until


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--allow-volume-change", action="store_true", required=True)
    args = parser.parse_args()
    events = []
    client = BridgeClient(args.pipe, lambda event, data: events.append((event, data)))
    client.start()
    try:
        wait_until(lambda: client.connected)
        wait_until(lambda: client._mixer_supported)
        assert client.mixer_status == "Ready; not adjusted"
        client.full_xp_volume = True
        client.request_full_volume()
        wait_until(lambda: client.mixer_status not in ("Ready; not adjusted", "Helper support not reported"))
        assert client.mixer_status == "Master and Wave at 100%", client.mixer_status
        print("PASS XP master and Wave levels set and read back at 100%; mute untouched", flush=True)
        events.clear()
        client.enqueue([Speech("Muted mixer test.", next(iter(client.voices)), volume=0)])
        wait_until(lambda: any(event == "done" for event, data in events), 20)
        assert not any(event == "disconnected" for event, data in events)
        print("PASS speech still completes on the same connection", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
