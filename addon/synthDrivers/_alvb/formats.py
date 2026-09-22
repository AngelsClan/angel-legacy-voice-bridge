"""Shared output-format choices for the synth ring and bridge settings panel.

A fixed rate makes XP's SAPI convert the voice's own output. Measured on XP,
that conversion adds audible false high frequencies, so the labels say so.
"""
OUTPUT_FORMATS = {
    0: "Voice default (recommended, best quality)",
    16000: "16 kHz, converted by XP (lower quality)",
    22050: "22.05 kHz, converted by XP unless the voice already uses it",
    44100: "44.1 kHz, converted by XP (can sound harsher)",
    48000: "48 kHz, converted by XP (can sound harsher)",
}
