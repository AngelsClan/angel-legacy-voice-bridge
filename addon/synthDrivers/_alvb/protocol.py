"""Bounded serial frames; version 2 assembles one utterance before speaking."""
import base64
import binascii
from dataclasses import dataclass, replace

MAX_LINE = 8191
CHUNK_CHARACTERS = 120
MAX_AUDIO_BYTES = 2048
XML_REPLACEMENTS = {value: " " for value in range(1, 32) if value not in (9, 10, 13)}
XML_REPLACEMENTS.update({0: None, 0xFFFE: " ", 0xFFFF: " "})


@dataclass(frozen=True)
class Speech:
    text: str
    voice: int = 0
    rate: int = 10
    volume: int = 100
    pitch: int = 10
    spell: bool = False


@dataclass(frozen=True)
class Bookmark:
    index: int


@dataclass(frozen=True)
class Silence:
    seconds: float


def bounded_utterances(items, max_items=200, max_characters=8000):
    """Preserve every item while dividing a large NVDA request for XP.

    The transport accepts at most 256 items and 16,000 characters per
    utterance. Keep well inside both limits so a large say-all item cannot
    turn into an admission error and an unnecessary synth fallback.
    """
    batch = []
    characters = 0
    for item in items:
        if isinstance(item, Speech) and item.text:
            remaining = item.text
            while remaining:
                if len(batch) >= max_items or characters >= max_characters:
                    yield tuple(batch)
                    batch, characters = [], 0
                allowance = max_characters - characters
                count = min(len(remaining), allowance)
                if count < len(remaining):
                    boundary = remaining.rfind(" ", 0, count)
                    if boundary >= count // 2:
                        count = boundary + 1
                batch.append(replace(item, text=remaining[:count]))
                characters += count
                remaining = remaining[count:]
        else:
            if len(batch) >= max_items:
                yield tuple(batch)
                batch, characters = [], 0
            batch.append(item)
    if batch:
        yield tuple(batch)


@dataclass(frozen=True)
class AudioFormat:
    rate: int
    bits: int
    channels: int


def _audio_number(value):
    if not value or len(value) > 10 or not value.isascii() or not value.isdecimal():
        raise ValueError("Invalid audio frame number")
    number = int(value)
    if number > 2147483647:
        raise ValueError("Audio frame number outside bounds")
    return number


def parse_audio_format(fields):
    """Validate the fixed PCM format sent before routed audio."""
    if len(fields) != 7 or fields[0] != "AUDIOFORMAT":
        raise ValueError("Invalid audio format frame")
    generation, request, rate, bits, channels = map(_audio_number, fields[2:])
    if (not 8000 <= rate <= 48000
            or bits != 16 or channels not in (1, 2)):
        raise ValueError("Unsupported audio format")
    return generation, request, AudioFormat(rate, bits, channels)


def parse_audio_frame(fields):
    """Decode one bounded PCM chunk; never accept an ambiguous base64 spelling."""
    if len(fields) != 6 or fields[0] != "AUDIO":
        raise ValueError("Invalid audio frame")
    try:
        generation, request, sequence = map(_audio_number, fields[2:5])
        if len(fields[5]) > 2732:
            raise ValueError("Oversized audio frame")
        data = base64.b64decode(fields[5], validate=True)
        if base64.b64encode(data).decode("ascii") != fields[5]:
            raise ValueError("Noncanonical audio encoding")
    except (ValueError, binascii.Error) as error:
        raise ValueError("Invalid audio frame data") from error
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise ValueError("Audio frame outside bounds")
    return generation, request, sequence, data


def utterance_frames(session, generation, request_id, items, quality=0, probe=False):
    """Small acknowledged packets build one SAPI utterance, not many snippets."""
    if quality not in (0, 16000, 22050, 44100, 48000):
        raise ValueError("Unsupported output format")
    voice = next((item.voice for item in items if isinstance(item, Speech)), 0)
    prefix = f"{session}\t{generation}\t{request_id}"
    # The seventh field is understood only by helpers advertising silent-probe.
    # Normal speech retains the six-field frame for older helpers.
    probe_field = "\t1" if probe else ""
    frames = [f"BEGIN\t{prefix}\t{voice}\t{quality}{probe_field}\n".encode("ascii")]
    for item in items:
        if isinstance(item, Speech):
            if item.voice != voice:
                raise ValueError("One utterance must use one voice")
            validate_speech(item)
            for text in chunks(item.text):
                encoded = text.encode("utf-16-le", errors="replace").hex()
                frames.append(f"PART\t{prefix}\t{item.rate}\t{item.volume}\t{item.pitch}\t{int(item.spell)}\t{encoded}\n".encode("ascii"))
        elif isinstance(item, Bookmark):
            if not 0 <= item.index <= 2147483647:
                raise ValueError("Invalid bookmark")
            frames.append(f"MARK\t{prefix}\t{item.index}\n".encode("ascii"))
        elif isinstance(item, Silence):
            milliseconds = round(max(0, min(item.seconds, 10)) * 1000)
            frames.append(f"BREAK\t{prefix}\t{milliseconds}\n".encode("ascii"))
        else:
            raise ValueError("Unsupported utterance item")
    frames.append(f"COMMIT\t{prefix}\n".encode("ascii"))
    return frames


def chunks(text):
    """Bound serial write size so cancellation cannot sit behind a giant frame."""
    text = text.translate(XML_REPLACEMENTS)
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARACTERS)
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary >= start + CHUNK_CHARACTERS // 2:
                end = boundary + 1
        yield text[start:end]
        start = end


def validate_speech(item):
    if not 0 <= item.voice < 128 or not 0 <= item.rate <= 20 or not 0 <= item.pitch <= 20 or not 0 <= item.volume <= 100:
        raise ValueError("Speech setting outside supported range")


def speech_frame(session, generation, request_id, item):
    """Legacy version 1 frame, retained for compatibility regression tests."""
    validate_speech(item)
    encoded = item.text.encode("utf-16-le", errors="replace").hex()
    fields = ["SPEAK", session, str(generation), str(request_id), str(item.voice), str(item.rate),
              str(item.volume), str(item.pitch), str(int(item.spell)), "TEXT", encoded]
    return ("\t".join(fields) + "\n").encode("ascii")


class LineReader:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        lines = []
        while b"\n" in self.buffer:
            end = self.buffer.index(10)
            if end > MAX_LINE:
                raise ValueError("Oversized bridge response")
            line = bytes(self.buffer[:end]).decode("ascii")
            del self.buffer[:end + 1]
            lines.append(line.rstrip("\r").split("\t"))
        if len(self.buffer) > MAX_LINE:
            raise ValueError("Oversized incomplete bridge response")
        return lines
