"""Muted XP output-format, full-utterance and immediate-close regression tests."""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient, DEFAULT_PIPE
from _alvb.pipe import Pipe
from _alvb.protocol import Bookmark, Speech
from integration import wait_until


class CountingPipe(Pipe):
    def __init__(self, name):
        super().__init__(name)
        self.commands = []

    def write(self, data):
        # Record command names only, never speech content.
        self.commands.extend(line.split(b"\t", 1)[0] for line in data.splitlines())
        return super().write(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    args = parser.parse_args()
    events, transports = [], []

    def transport(name):
        result = CountingPipe(name)
        transports.append(result)
        return result

    client = BridgeClient(args.pipe, lambda event, data: events.append((event, data)), transport)
    client.start()
    try:
        wait_until(lambda: client.connected)
        for voice, name in client.voices.items():
            for rate in (0, 16000, 22050, 44100, 48000):
                events.clear()
                client.quality = rate
                client.enqueue([Speech("Format check.", voice, volume=0), Bookmark(7)])
                wait_until(lambda: any(event == "done" for event, data in events), 20)
                assert not any(event == "disconnected" for event, data in events), client.status
                assert [data[1] for event, data in events if event == "index"] == [7]
                if rate:
                    assert client.output_format == f"{rate} Hz, 16-bit, 1 channel(s)", client.output_format
                print(f"PASS {name}: requested {rate or 'default'}; {client.output_format}", flush=True)

        events.clear()
        commands = transports[-1].commands
        commands.clear()
        client.quality = 0
        text = "A continuous test of words across serial packet boundaries without added pauses. " * 5
        client.enqueue([Speech(text, voice=1, rate=20, volume=0), Bookmark(8)])
        wait_until(lambda: any(event == "done" for event, data in events), 40)
        assert commands.count(b"BEGIN") == commands.count(b"COMMIT") == 1, commands
        assert commands.count(b"PART") > 1, commands
        assert [data[1] for event, data in events if event == "index"] == [8]
        print("PASS long text: multiple transport packets, one committed utterance", flush=True)

        events.clear()
        client.enqueue([Speech("Closing must cancel this request. " * 100, volume=0), Bookmark(99)])
        wait_until(lambda: client.busy)
        client.close(wait=False)
        assert client.closed_event.wait(2), "Worker did not close promptly"
        assert not client.enqueue([Speech("Must not restart", volume=0)])
        time.sleep(.1)
        assert not any(event == "index" and data[1] == 99 for event, data in events)
        print("PASS close purges queue, rejects new speech and stops worker", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
