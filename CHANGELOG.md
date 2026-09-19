# Changelog

## 0.1.0 beta — 2026-09-19

First public beta preparation: state-aware Connect/Cancel connection/Disconnect
button, disable-only local maintenance signal with shutdown acknowledgement,
optional XP playback volume normalization, and a complete operator guide.
Voice scanning now preserves the last good catalog on partial enumeration,
avoids unchanged catalog retransmissions, and cannot silently remap a queued
voice. Automatic return attempts are bounded to prevent repeated switching.

Recovery/live-voice follow-up: optional automatic return after eSpeak fallback,
respecting manual synth/voice changes and disable. Restores the previous bridge
voice, rate, volume and pitch. Capability-negotiated idle SAPI5 scans detect
new/removed voices without restarting the helper; stable indexes prevent voice
mix-ups. Added recovery/catalog regressions and a live XP registration probe.
Added a curated source ZIP and documented manual startup, optional XP Startup
shortcuts, and VirtualBox detachable GUI. Version remains 0.1.0 beta.

Settings-ring follow-up: XP output format is now available in the bridge synth's
NVDA settings ring and Speech settings. Changes apply to the next utterance
without reconnecting, using the same saved setting as the bridge panel. Added
fallback-on/off regressions and publication/headless/new-voice instructions.

Same-version follow-up: real master disable/emergency stop, immediate mirror
cancellation, test-aware buttons, automatic voice updates and generic pipe
discovery. Protocol 2 assembles packets into complete SAPI utterances to remove
artificial fragment pauses; adds real SAPI bookmarks and acknowledged framing.
Output format controls support voice default or 16/22.05/44.1/48 kHz 16-bit mono.
New fault, catalog and lifecycle regressions plus actual XP output-format tests.
Replace both helper and add-on; listening/UI acceptance remains necessary.

Initial local release: offline XP SAPI5 console helper, virtual-serial pipe
transport, NVDA synth and optional mirroring, configurable voice/rate/volume,
normal synth pitch, connection tests, fallback and emergency local-speech
shortcut. Includes source, build script, tests, protocol documentation, README
and bundled NVDA help. See TEST-REPORT for qualification limits.
