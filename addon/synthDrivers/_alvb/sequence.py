"""Translate NVDA speech into simple ordered speech, bookmark and pause items."""
from speech.commands import IndexCommand, CharacterModeCommand, BreakCommand, PitchCommand, RateCommand, VolumeCommand
from .protocol import Speech, Bookmark, Silence


SUPPORTED_COMMANDS = {IndexCommand, CharacterModeCommand, BreakCommand, PitchCommand, RateCommand, VolumeCommand}


def translate(sequence, voice, rate, volume, pitch=50):
    spell = False
    current_rate, current_volume, current_pitch = rate, volume, pitch
    result = []
    for item in sequence:
        if isinstance(item, str):
            result.append(Speech(item, voice, round(current_rate / 5), current_volume, round(current_pitch / 5), spell))
        elif isinstance(item, IndexCommand):
            result.append(Bookmark(item.index))
        elif isinstance(item, CharacterModeCommand):
            spell = item.state
        elif isinstance(item, BreakCommand):
            result.append(Silence(item.time / 1000))
        elif isinstance(item, PitchCommand):
            current_pitch = max(0, min(100, round(pitch + item.offset)))
        elif isinstance(item, RateCommand):
            current_rate = max(0, min(100, round(rate + item.offset)))
        elif isinstance(item, VolumeCommand):
            current_volume = max(0, min(100, round(volume + item.offset)))
    return result
