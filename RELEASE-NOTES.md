# Release notes

## Current: 0.1.2-dev4 — development build, release on hold

This host add-on flushes NVDA's output player when XP finishes an utterance.
Without that flush, the last bookmark and completion could remain pending, so
NVDA would announce a structural label such as "list" or "main landmark" and
never continue to its content. The fixed build completed that sequence through
the real XP helper and an isolated NVDA session. The XP helper is unchanged
from dev3; if it is already installed, only the host add-on needs updating.

The owner still needs to listen to the installed build before this issue is
considered closed in normal use. The separate historical freeze and Mac voice
stall remain under review; public release remains on hold.

### Install this development update

1. Keep a reliable local synthesizer selected and disconnect the bridge.
2. Install `AngelLegacyVoiceBridge-0.1.2-dev4.nvda-addon` and approve NVDA's
   restart when ready.
3. Select the bridge and test list and landmark navigation. The existing dev3
   XP helper can stay running.

The packages are unsigned. See `TEST-REPORT.md` for test limits and hashes.

## Previous: 0.1.2-dev3 — development build, release on hold

Bridge speech can now play through XP speakers, NVDA's selected output device,
or both. XP remains the voice host and its other sounds keep using XP audio.
The chosen route is saved in the add-on's settings and is capability-gated, so
an older XP helper continues using XP speakers. Replace the XP helper and
add-on together before selecting an NVDA audio route.

The XP helper captures SAPI PCM while preserving bookmarks, cancellation and
completion. Real XP tests covered all three routes and five engines (Sam,
Mike16, Crystal16, Vicki and Alex), including multiple utterances on one
connection, pause and cancel. PCM was counted and discarded by a test player;
audibility, quality and live NVDA performance still need owner listening.
The isolated host test suite passed 172 tests before packaging.

Optional automatic return after fallback now requires a silent check that
actually produces non-silent PCM plus a real bookmark. The helper captures and
discards that check on every route, including XP speakers: some AT&T voices
remain audible at SAPI volume zero. Older helpers without this capability do
not run the check. Automatic return remains off by default.

**Public release remains on hold.** The original reported NVDA freeze and the
separate Lion Pipe Organ stall are not proved fixed by this audio-routing work.
The owner should install the finished add-on only when ready to test and keep
a dependable local synthesizer available. No installer automatically changes
the live NVDA synthesizer or restarts it.

### Install this development pair

1. In NVDA, select a local synthesizer and disconnect the bridge.
2. In XP, stop the old helper and replace it with the supplied
   `AngelLegacyVoiceBridge.exe`. Start the replacement.
3. Install `AngelLegacyVoiceBridge-0.1.2-dev3.nvda-addon` and approve NVDA's
   restart when it is safe.
4. In the add-on settings, choose where XP bridge speech plays. `XP speakers`
   is the default. Test `Send to NVDA` and `Both` while a local synthesizer
   remains available for recovery.

The packages are unsigned. See `TEST-REPORT.md` for test limits and hashes.

## Previous: 0.1.2-dev2 — development build, release on hold

**This is not a cleared public release.** An accessibility-critical NVDA freeze
reported against 0.1.1 is still unexplained. Keep a dependable local
synthesizer selected and leave the bridge disabled unless you are deliberately
testing it. Nobody is asked to reproduce the freeze. See
[TEST-REPORT.md](TEST-REPORT.md) for what has actually been verified and what
has not.

### What changed since 0.1.1

- **Speech no longer stalls after a failed voice.** Falling back to eSpeak used
  to leave NVDA waiting for bookmarks from the voice that had already died. The
  abandoned queue is now cleared first, so local speech continues. Old
  announcements are discarded rather than replayed or falsely marked as spoken.
  The same reset applies when automatic return fires and when you disable an
  active bridge.
- **Automatic return now requires proof.** A reconnected pipe or a voice that
  still appears in the list is no longer accepted as recovery; a short fixed
  check phrase must actually render, confirmed by its final bookmark. Checks
  back off from 5 to 60 seconds and stop after 12 attempts or 15 minutes, with
  spoken notices either way, and returns are limited to three in ten minutes.
  It stays off by default, and there is now an optional command to turn it on
  or off (no key assigned until you choose one).
- **Voices that are reinstalled while selected recover.** The helper resolves
  voice registrations afresh when switching and recovers once from SAPI's
  "registry key marked for deletion" error, which previously forced a fallback
  to eSpeak even though the voice was listed.
- **Skipped text no longer hangs an utterance.** The helper checks real SAPI
  completion without blocking, in addition to listening for completion events,
  and preserves bookmarks before reporting completion. Asynchronous engine
  errors are reported as failures instead of as successful silent speech.
- **Mirroring survives heavy announcement traffic.** When XP falls 64
  utterances behind, the oldest waiting mirrored utterance is dropped instead
  of cancelling all mirrored speech.
- **Output quality guidance.** Fixed sample rates make XP convert the voice's
  own output; measured on XP that added false high frequencies only 21 to 27 dB
  below the 22.05 kHz Mac voices. The format labels now say so and recommend
  Voice default.
- **Diagnostics can be turned off.** A new setting, "Write text-free
  diagnostics log", applies immediately after OK or Apply without restarting
  NVDA. It is on by default while the release is on hold. It never records
  speech text, window titles or credentials.
- **Text-free failure shapes.** When a voice fails, the log records counts of
  character classes and words in the failed utterance, never the words. This is
  what identified a text-encoding fault in a third-party Mac voice pack, which
  was fixed in that pack rather than in the bridge.

### Installing this build

Replace **both** parts, and pick your own safe moment:

1. In NVDA, switch to a local synthesizer and press Disconnect.
2. In XP, close the helper with Control+C, replace
   `AngelLegacyVoiceBridge.exe`, and start it again. XP does not need a reboot.
3. Install `AngelLegacyVoiceBridge-0.1.2-dev2.nvda-addon` and restart NVDA when
   it is safe. Nothing restarts NVDA for you, and your settings are kept.

Follow [README.md](README.md) for first-time setup and [OPERATIONS.md](OPERATIONS.md)
for maintenance. SHA-256 sidecar files are supplied for every artifact; the
binaries are not signed.

Passing synthetic and deliberately faulted tests is not confirmation that the
reported freeze, the intermittent Microsoft Sam silence or the unsupported-text
pause is cured.

## Historical: 0.1.1 beta (superseded by the hold above)

An add-on-only update that recovered missing trailing bookmarks after XP
confirmed an utterance had finished, since NVDA relies on those bookmarks to
advance queued speech. Duplicate and cancelled bookmarks were not replayed, and
preparing long speech no longer held the lock that cancel, pause and enqueue
need. Text-free progress diagnostics were added.

The reported full-computer freeze was not reproduced in live testing at that
time. Logs showed NVDA freezing during a dense event stream without identifying
the blocking call.

## Historical: 0.1.0 beta

The first public pre-release: the bridge synthesizer and optional mirrored
speech, a state-aware Connect / Cancel connection / Disconnect control, live
voice discovery, cancellation, pause, output formats in the settings ring,
local eSpeak fallback with optional automatic return, an optional XP playback
mixer adjustment, a local disable-only maintenance tool and the NVDA+Shift+F11
emergency shortcut.

## Standing limitations

These apply to every build so far:

- Licensed SAPI 5 engines only. No SAPI 4, no network transport, no system-wide
  SAPI 5 registration and no Windows service.
- VirtualBox is the only platform tested. VMware, QEMU, Hyper-V and others are
  unqualified; contributions are welcome, and README.md explains what a port
  should demonstrate.
- Separate XP SP1, SP2 and SP3 qualification, headless audio and broad hardware
  testing are all still outstanding.
- Audible quality, pronunciation and real perceived responsiveness remain user
  checks. A completed transport test does not prove anything was heard.
- This is a pre-release, not an NVDA Add-on Store submission and not a
  qualified primary screen reader. Keep local speech available.

License: GNU GPL version 2 or later.
