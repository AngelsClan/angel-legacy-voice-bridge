"""XP regressions for skipped text, voice switching and queue progress.

Muted by default. Explicit --volume plays only synthetic test phrases in XP.
"""
import argparse
import logging
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient, DEFAULT_PIPE
from _alvb.protocol import Bookmark, Speech
from integration import wait_until


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--quality", type=int, default=0)
    parser.add_argument("--rounds", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--volume", type=int, choices=range(101), default=0)
    parser.add_argument("--rate", type=int, choices=range(21), default=10)
    parser.add_argument("--expect-polled", action="store_true",
                        help="Require completion polling (only with the fault-injection helper)")
    args = parser.parse_args()
    events = []
    class PollLog(logging.Logger):
        completions = 0

        def info(self, message, *args, **kwargs):
            if message.startswith("XP completion confirmed by SAPI polling"):
                self.completions += 1

    logger = PollLog("unicode-probe")
    client = BridgeClient(args.pipe, lambda event, data: events.append((event, data)), logger=logger)
    client.quality = args.quality
    client.start()
    failures = 0
    try:
        wait_until(lambda: client.connected)
        for voice, name in list(client.voices.items()) * args.rounds:
            for label, text in (("English", "Bridge check."),
                                ("unsupported sample", "!В саду🌳⛅"),
                                ("symbols only", "🌳⛅"),
                                ("blank", " "),
                                ("empty", ""),
                                ("recovery English", "Still speaking.")):
                events.clear()
                started = time.monotonic()
                client.enqueue([Speech(text, voice, volume=args.volume, rate=args.rate), Bookmark(7)])
                try:
                    wait_until(lambda: any(event == "done" for event, data in events), 12)
                    assert [data[1] for event, data in events if event == "index"] == [7], events
                    assert not any(event == "disconnected" for event, data in events), client.status
                    print(f"PASS {name}: {label}; {time.monotonic() - started:.2f}s", flush=True)
                except AssertionError:
                    failures += 1
                    print(f"FAIL {name}: {label}; status={client.status}; events={events}", flush=True)
                    client.cancel()
                    time.sleep(.3)
        assert not failures, f"{failures} speech completion failures"
        if args.expect_polled:
            assert logger.completions == len(client.voices) * 6 * args.rounds, logger.completions
            print(f"PASS {logger.completions} completions recovered with end events suppressed", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
