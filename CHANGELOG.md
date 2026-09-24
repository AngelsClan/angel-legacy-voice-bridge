# Changelog

## 0.1.2-dev4 — XP status signal and speech admission follow-up, release still on hold

- Publish connection state and a heartbeat tick locally in XP for an optional
  XP NVDA companion. Speech announcements come from XP NVDA, not the host
  bridge add-on. A stale heartbeat counts as disconnected.
- Split unusually large NVDA speech requests into bounded bridge utterances
  without discarding words or bookmarks. Record item and character counts if
  an admission limit is still reached, without logging speech content.
- Preserve leading periods for XP voices without making SAPI XML speak the
  word “period” before the following text. Other sentence periods retain their
  existing timing. Verify the behavior directly with an XP SAPI voice and
  install the updated helper in XP.
- Accept a measured two-millisecond terminal bookmark lead when XP sends
  Eloquence audio to NVDA. A 97-byte lead at 48 kHz had exceeded the former
  96-byte limit by one byte and caused a false disconnect. Larger missing
  audio tails still fail.
- Keep the public release on hold pending normal-use listening.

## 0.1.2-dev4 — XP SAPI input and routed-audio correction, release still on hold

- Preserve literal exclamation marks in generated SAPI XML using isolated CDATA
  text nodes. A repeated Pipe Organ phrase beginning with a raw `!` made XP's
  SAPI engine report an asynchronous failure even in a direct SAPI test; the
  CDATA form completed 100 direct requests and 100 bridge speaker requests.
- Wait for SAPI completion after the input stream ends, and record numeric
  failure state in the XP helper diagnostics without logging speech text.
- Apply legacy SPEAK volume in XML while keeping SAPI's master volume open.
  This avoids the engine failure seen when master volume was set to zero.
- Permit a measured sub-millisecond terminal bookmark lead after 48 kHz
  resampling. Larger missing PCM tails still fail the NVDA audio route.
- Test the updated helper on XP with both speaker and NVDA-captured routes,
  mixed punctuation, voice changes, cancellation, and bookmarks. Keep the
  public release on hold pending normal-use listening and the earlier freeze.

## 0.1.2-dev4 — flush final bridge audio, release still on hold

- Flush NVDA's audio player after XP completes a speech segment so the final
  bookmark and completion reach NVDA's speech manager. This fixes reproduced
  indefinite silence after labels such as "list" and "main landmark".
- Verify final callbacks, cancellation during flush, a real XP segmented
  sequence, and an isolated NVDA speech-manager run connected to XP.
- At the time of this earlier dev4 update, the XP helper was unchanged. A
  later dev4 source revision above updates both components without a version bump.

## 0.1.2-dev3 — selectable bridge audio route, release still on hold

- Keep XP as the SAPI voice host and add `XP speakers`, `Send to NVDA`, and
  `Both XP and NVDA` routes for bridge speech. Other XP audio stays on XP.
- Capture bounded 16-bit PCM across the serial link with per-utterance format,
  bookmark offsets, cancel/pause handling, playback completion and capability
  gates for older helpers. Fix two guest capture deadlocks/rebinding failures
  found by real XP multi-utterance tests.
- Require a real bookmark and non-silent captured PCM for optional automatic
  return after fallback. XP captures and discards the check without local
  playback, including for SAPI voices audible at volume zero. Older helpers
  cannot run the check. Automatic return remains off by default.
- Add audio-route protocol tests, real XP matrix results and updated help.
  Retain the public release hold pending owner listening and freeze review.

## 0.1.2-dev2 — completion recovery, release still on hold

- Clear abandoned NVDA speech/index queues before falling back to local speech,
  automatically returning to the bridge, or disabling an active bridge synth.
  A reconnect does not make lost indexes valid again. Preserve deliberate local
  synth/profile changes. Add numeric failure snapshots and recovery diagnostics.
- Reproduced the old fallback leaving 602 pending sequences in isolated NVDA;
  the candidate clears them and completes subsequent local speech. The separate
  Pipe Organ asynchronous E_FAIL trigger is not yet reproduced or proven fixed.
- Automatic return now requires a verified render: a fixed check phrase, sent
  at volume zero in the original voice, must reach its final bookmark. It is
  inaudible only on voices that honour SAPI volume; some XP voices do not, and
  real XP audibility of the check is untested. A reconnected pipe or a
  listed voice is no longer enough. Checks back off from 5 to 60 seconds and
  stop after 12 attempts or 15 minutes. Returns are limited to three per ten
  minutes (was per minute). Profile switches cancel a pending return. Stopping
  and recovering are announced. Verified in an isolated NVDA with an injected
  failing helper; this does not fix any engine crash.
- Add **Write text-free diagnostics log** to the settings (on by default during
  the release hold). It applies immediately after OK or Apply, from every
  thread, without a restart; with it off from the start no log file is
  created. This was a stated prerequisite for lifting the release hold.
- Documentation: explain that the Pipe Organ failures and the brief Alex
  silence after switching were Mac voice-pack issues (text encoding, one-frame
  first render) fixed in those packs, add troubleshooting for per-voice output
  format and start-up silence, and correct the claim that volume 0 mutes every
  voice.
- Keep the diagnostics heartbeat alive. Observed in real use: diagnostics
  stopped recording mid-session and never resumed, so nothing was captured
  from the hours that mattered, and the main-thread freeze detector stopped
  with it. Two causes are now closed. A queued heartbeat that never runs is
  re-armed after 30 seconds instead of latching the monitor off for the rest
  of the session, and the re-arm is recorded. And a plugin instance now holds
  a token for the monitor it started, so a late shutdown cannot stop its own
  replacement; a monitor whose thread has died is replaced rather than left
  silent.
- Stop the idle backlog record repeating every five seconds while the bridge
  is the selected synthesizer. The selected-synth flag was being counted as a
  nonzero backlog, which filled and rotated the diagnostics log during exactly
  the sessions whose evidence matters most. Idle sampling is once a minute
  again, as documented.
- Documentation rewrite: README.md and the add-on's help are reorganised around
  a single ordered installation path (virtual serial port, XP helper, add-on,
  first test) with a worked VirtualBox example, verified console and status
  messages, symptom-led troubleshooting, and an invitation to contribute
  support for other hypervisors and emulators. Every user-visible label,
  announcement, default and timing was checked against the source: the settings
  table had the fallback checkbox's name wrong ("Use local eSpeak if the bridge
  synthesizer disconnects" instead of "Restore local eSpeak if bridge speech
  disconnects"), the output-format choices did not match the shipped labels,
  and the per-probe 15-second timeout, the 25-second backoff after an
  incomplete voice scan, the scan timeout that pauses scanning until reconnect,
  and the behaviour above 128 voices were undocumented. RELEASE-NOTES.md is
  rewritten around the current build with the older notes kept as history.
  No code, version or behaviour change.
- Output format labels now say that fixed rates are converted by XP and can
  sound harsher, and recommend Voice default. Measured on XP, converting the
  22.05 kHz Mac voices to 44.1 or 48 kHz adds false high frequencies only
  21–27 dB below the voice.
- When bridge speech fails, also log a text-free "shape" of the failed
  utterance (character-class counts, `[[`/`]]` counts, word counts) to help
  identify which kinds of text trigger legacy engine crashes.
- Mirroring under heavy announcement traffic: when XP falls 64 utterances
  behind, drop the oldest waiting mirrored utterance instead of cancelling all
  mirrored speech and logging a warning each time. The periodic progress record
  counts dropped utterances. The bridge synthesizer's own queue is unchanged.
- Automatic return stays off by default. Add an optional command to turn it
  on or off (no default key; assign one in Input gestures), which announces the
  new state; an open settings panel follows it. Document how to enable it.
  Settings text no longer calls the check silent. About shows 0.1.2-dev2.
- Resolve a fresh SAPI token when switching voices. Recreate SpVoice and retry
  once only when speech is synchronously rejected with ERROR_KEY_DELETED after
  an installer replaces the selected registration. Retain local-speech fallback
  for other failures; never replay an accepted utterance.
- Add bounded helper-side, text-free HRESULT diagnostics and optional numeric
  host logging. Add live disposable-token replacement and voice-switch probes.

- Check nonblocking SAPI completion after draining events, so a missing stream
  end event cannot leave an already-finished utterance waiting indefinitely.
- Preserve bookmark order, cancellation generations and paused speech. Check
  asynchronous SAPI engine failure instead of reporting silent success.
- Add fixed-code failure reasons and numeric voice/format/rate/volume/length
  diagnostics; never log spoken text or arbitrary guest error payloads.
- Add repeatable Unicode/empty-text/voice-switching probes and a separately
  built test-only helper that deliberately suppresses end events.
- Both helper and add-on are updated. Intermittent user-reported silence and
  the historical NVDA freeze are not claimed reproduced or conclusively fixed.

## 0.1.2-dev1 — unreleased diagnostics, release on hold

- Preserve the reported speech-loss incident as unresolved; passing isolated
  tests does not establish that the original Alt-Tab freeze has been repaired.
- Dispatch callbacks through NVDA's core event queue, including startup before
  wx.App exists. Avoid unrelated wx callback reentrancy into speech handling.
- Add bounded asynchronous, rotating, text-free diagnostics independent of the
  bridge connection and of NVDA's filtering of external INFO-level log records.
- Record delayed main-thread heartbeats and code locations without recording
  speech, locals, window names or source paths. Add real isolated-NVDA stress
  and fault-injection checks; keep the user's running screen reader untouched.

## 0.1.1 beta — 2026-09-20

- Recover missing trailing bookmarks only after the current utterance reports
  completion. NVDA can then advance its queued speech instead of waiting forever.
- Ignore duplicate/unknown bookmarks and discard canceled-generation completions.
- Prepare speech packets outside the state lock so cancel, pause and enqueue do
  not wait for a busy worker's text encoding. Canceled prepared work is discarded.
- Add text-free progress counters/timings and disconnect reasons to the NVDA log.
- Add queue/fault-injection regressions and an opt-in muted real-XP burst probe.
- Add-on-only update: existing 0.1.0 XP helper remains compatible and unchanged.

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
