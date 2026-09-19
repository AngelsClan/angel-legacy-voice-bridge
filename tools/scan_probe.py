"""Measure idle scans on the real helper without speaking or changing XP."""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient, DEFAULT_PIPE
from _alvb.pipe import Pipe
from integration import wait_until


class ScanPipe(Pipe):
    def __init__(self, name):
        super().__init__(name)
        self.scan_started = None

    def write(self, data):
        if data.startswith(b"REFRESH\t"):
            self.scan_started = time.monotonic()
        return super().write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    args = parser.parse_args()
    pipes = []
    def factory(name):
        pipe = ScanPipe(name)
        pipes.append(pipe)
        return pipe
    client = BridgeClient(args.pipe, transport_factory=factory)
    client.start()
    try:
        wait_until(lambda: client.connected)
        wait_until(lambda: client._refresh_supported)
        for _ in range(4):
            pipe = pipes[-1]
            pipe.scan_started = None
            wait_until(lambda: pipe.scan_started is not None, 10)
            wait_until(lambda: not client._refresh_pending, 5)
            assert client.connected and len(pipes) == 1
            print(f"PASS idle scan round trip: {(time.monotonic() - pipe.scan_started) * 1000:.1f} ms", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
