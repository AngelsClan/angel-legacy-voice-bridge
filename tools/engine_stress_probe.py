"""Bounded synthetic XP speech checks, independent of the user's NVDA.

The default route speaks on XP; --route nvda captures PCM into a counting sink
without playing it. Disconnect the live add-on and mute VM output before
running. No private text is read or printed. A failure stops the run, retaining
numeric transport evidence.
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


class CountingAudioSink:
    """Complete the routed-audio contract without opening an output device."""

    def __init__(self, client):
        self.client = client
        self.bytes = 0
        self.non_silent = False

    def start(self, _audio_format, probe=False):
        self.bytes = 0
        self.non_silent = False

    def feed(self, data):
        self.bytes += len(data)
        self.non_silent = self.non_silent or any(data)

    def index(self, value):
        self.client.audio_event("index", value)

    def finish(self):
        self.client.audio_event("done", None)

    def cancel(self):
        pass

    def close(self):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", required=True)
    parser.add_argument("--voice", default="Pipe Organ")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--mixed-controls", action="store_true",
                        help="Change pitch/rate/volume inside each utterance")
    parser.add_argument("--case", type=int, choices=range(5), action="append",
                        help="Select synthetic phrases (repeat to combine cases)")
    parser.add_argument("--quality", type=int, choices=(0, 22050, 48000), default=48000)
    parser.add_argument("--alternate-quality", action="store_true",
                        help="Alternate 48 kHz and voice-default between utterances")
    parser.add_argument("--route", choices=("xp", "nvda"), default="xp",
                        help="XP speaker or host PCM capture into a counting sink")
    parser.add_argument("--ascii-case2", action="store_true",
                        help="Replace the Unicode phrase with a similar ASCII phrase")
    parser.add_argument("--case2-kind", choices=("original", "cyrillic", "symbols", "ascii", "ascii-short", "accented", "translit", "ascii-bang", "space-bang", "question", "period"),
                        default="original", help="Isolate the script or symbols in case 2")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    events = []
    client = BridgeClient(args.pipe, lambda event, data: events.append((event, data)), quality=args.quality)
    if args.route == "nvda":
        client.audio = CountingAudioSink(client)
        client.set_route("nvda")
    client.start()
    phrases = [
        "This is a synthetic speech queue test, with a full sentence.",
        "It's Alex's turn. Don't stop; isn't that right?",
        "!\u0412 \u0441\u0430\u0434\u0443\U0001f333\u26c5 channel",
        "Question mode. User joined. Channel updated. Window changed. " * 3,
        "One, two: three! Four? Five (six); seven & eight. ",
    ]
    if args.case2_kind == "cyrillic":
        phrases[2] = "!\u0412 \u0441\u0430\u0434\u0443 channel"
    elif args.case2_kind == "symbols":
        phrases[2] = "!in garden\U0001f333\u26c5 channel"
    elif args.case2_kind == "ascii" or args.ascii_case2:
        phrases[2] = "A visitor is walking past the channel"
    elif args.case2_kind == "ascii-short":
        phrases[2] = "In the garden channel"
    elif args.case2_kind == "accented":
        phrases[2] = "Cafe caf\u00e9 channel"
    elif args.case2_kind == "translit":
        phrases[2] = "!V sadu channel"
    elif args.case2_kind == "ascii-bang":
        phrases[2] = "!In the garden channel"
    elif args.case2_kind == "space-bang":
        phrases[2] = " !In the garden channel"
    elif args.case2_kind == "question":
        phrases[2] = "?In the garden channel"
    elif args.case2_kind == "period":
        phrases[2] = ".In the garden channel"
    try:
        wait_until(lambda: client.connected)
        slot = next(slot for slot, name in client.voices.items() if args.voice in name)
        for turn in range(args.rounds):
            for case, phrase in enumerate(phrases):
                if args.case is not None and case not in args.case:
                    continue
                if args.alternate_quality:
                    client.quality = 48000 if case % 2 else 0
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
                if args.route == "nvda" and (not client.audio.bytes or not client.audio.non_silent):
                    raise RuntimeError("Captured PCM was empty or silent")
                print(f"PASS round={turn} case={case} seconds={time.monotonic()-started:.2f}", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
