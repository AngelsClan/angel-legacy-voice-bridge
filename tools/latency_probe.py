"""Measure where the delay before speech goes. Muted; run with the bridge disconnected.

Speech feeling late is easy to notice and hard to attribute, and guessing is
how a week gets spent optimising the wrong thing.

It measures ONSET: from handing an utterance over to the engine reporting that
it has reached the start of the audio. A bookmark is placed BEFORE the text so
that it fires at the beginning rather than the end, and the utterance is
cancelled as soon as it arrives rather than listened to in full.

Reading it: run several lengths. A flat column means the wire is not the
problem and what remains is fixed overhead. A column that grows with length
means text transfer matters, because text is sent as hex of UTF-16 -- four
bytes per character -- in packets of CHUNK_CHARACTERS acknowledged one at a
time.

Measured on one XP guest over a VirtualBox host-pipe serial port, across
several runs: roughly 0.10 to 0.22 s, with no consistent growth from 20
characters to 1200 -- sixty times the text for nothing outside run-to-run
variation. The link is therefore not paced at its configured baud rate, and a
denser text encoding would buy almost nothing. That was worth knowing before
building one.

What this CANNOT see is the audio path after SAPI, because that plays inside
the guest and never crosses the link. Treat onset as a floor for what you
actually hear, not the whole of it.

Volume is zero throughout. Some engines ignore that and stay audible, so do
not assume silence.
"""
import argparse
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alvb.client import BridgeClient, DEFAULT_PIPE
from _alvb.protocol import Bookmark, CHUNK_CHARACTERS, Speech
from integration import wait_until

#: Fixed, ordinary text, repeated and cut to length. Lengths are chosen around
#: the packet size so that the cost of one more packet is visible rather than
#: averaged away.
SENTENCE = ("The quick brown fox jumps over the lazy dog while the rain falls "
            "steadily on the old tin roof and nobody says anything at all. ")

LENGTHS = (20, 120, 240, 600, 1200)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--voice", default=None,
                        help="Substring of the voice name; default is the first listed")
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()

    marks, dones = [], []

    def listen(event, data):
        if event == "index":
            marks.append(time.perf_counter())
        elif event == "done":
            dones.append(time.perf_counter())

    client = BridgeClient(args.pipe, listen)
    client.start()
    try:
        wait_until(lambda: client.connected, timeout=30)
        chosen = next((index for index, name in sorted(client.voices.items())
                       if args.voice is None or args.voice.lower() in name.lower()), None)
        if chosen is None:
            raise SystemExit("No matching voice")
        print("voice: %s" % client.voices[chosen])
        print("wire: 4 bytes per character (hex of UTF-16), %d characters per packet,"
              % CHUNK_CHARACTERS)
        print("      each packet acknowledged before the next is sent.\n")
        print(" chars  packets   onset")

        for characters in LENGTHS:
            onsets = []
            for round_number in range(args.rounds):
                text = (SENTENCE * 40)[:characters]
                marks.clear()
                dones.clear()
                start = time.perf_counter()
                #: The bookmark goes BEFORE the text, not after. A trailing
                #: bookmark only fires once the whole utterance has been
                #: spoken, which measures how long the sentence takes to say
                #: -- a first version of this probe did exactly that and
                #: reported 75 seconds for 1200 characters, which is a
                #: speaking rate, not a latency.
                client.enqueue([Bookmark(4000 + round_number),
                                Speech(text, chosen, volume=0)])
                wait_until(lambda: marks, timeout=60)
                if marks:
                    onsets.append(marks[0] - start)
                #: Stop immediately rather than listening to the whole thing.
                client.cancel()
                time.sleep(0.4)
            print("%6d %7d   %10s"
                  % (characters, max(1, -(-characters // CHUNK_CHARACTERS)),
                     ("%.3f s" % statistics.median(onsets)) if onsets else "none"))

        print("\nOnset is the time from handing the utterance over to the engine"
              "\nreporting that it has reached the start of the audio."
              "\n\nA flat column means the wire is not the problem and the cost is"
              "\nfixed overhead. A column that grows with length means the text"
              "\ntransfer matters and a denser encoding would help.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
