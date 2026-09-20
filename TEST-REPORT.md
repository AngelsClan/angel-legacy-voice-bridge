# Beta qualification

## 0.1.1 queue fixes — 2026-09-20

- 91 unit/contract tests pass. Before the fix, regressions for missing bookmarks
  and deliberately slow packet preparation failed. Both now pass, along with
  60-request backlog recovery, cancellation, duplicate/stale indexes, and
  pause/resume while packet preparation is in progress.
- The hidden real-wx settings/control smoke passed again; no window was shown
  and no active NVDA configuration was loaded or changed by that test.
- Live offline XP/headless baseline: two 40-request muted queues completed at
  default and 48 kHz. The original full-computer freeze was not reproduced.
- Updated client: two 60-request muted queues completed with all 120 bookmarks
  in order. Maximum consecutive bookmark gap was 0.594 seconds (default) and
  0.563 seconds (48 kHz). These include synthetic speech duration and are not
  measurements of input latency. Probe used 0.98 host-process CPU seconds over
  68.48 wall seconds; this does not measure the VM's CPU use.
- Actual XP tests also passed all three installed voices at all five output
  formats, long-utterance assembly, cancellation and worker/pipe release.
- A second 120-request real-XP run deliberately filtered out every third INDEX
  reply: all 120 completions remained ordered and 40 indexes were recovered.
  Repeated cancellation's maximum caller wait was 0.0001 seconds in that probe.
  Bookmark-only and empty-text utterances passed. Each probe released the pipe.
- Local application logs confirmed a dense event stream overlapping NVDA
  watchdog freezes. They did not capture the blocked stack. No production
  server connection, active NVDA replacement, XP reboot or settings change was
  used to investigate. Private logs are not included in the release.
- Existing XP helper and wire protocol are unchanged. Install only the new
  add-on, then restart NVDA when ready. Listening under the original workload
  remains necessary; do not claim the entire reported freeze is proven fixed.

The completion recovery follows the same principle as NVDA's SAPI5 driver's
end-of-stream bookmark handling, implemented here for session/generation-scoped
bridge requests. Reference: https://github.com/nvaccess/nvda/blob/master/source/synthDrivers/sapi5.py

## Previous 0.1.0 qualification — 2026-09-19

Angel Legacy Voice Bridge **0.1.0 beta** is suitable for controlled user testing,
not advertised as a universally qualified primary screen reader. Keep local
speech available. All test speech used synthetic phrases, never personal text.

## Environment

- Windows host; Python 3.13 and Visual Studio 2022 x86 build tools; no WSL.
- 32-bit Windows XP 5.1.2600, VirtualBox 7.2.18, visible GUI and offline guest.
  Exact service pack was not independently established; SP1/SP2/SP3 are not
  separately qualified.
- Virtual COM1, 16550A, local host-server named pipe; all guest NICs disabled.
- Existing licensed Microsoft Sam and AT&T DTNV 1.4 Mike16/Crystal16 engines.
  No engine, voice data or license is included with this project.
- Tests did not restart or replace the active host NVDA. NVDA adapter tests use
  isolated API doubles; Windows named-event tests use an isolated test process.

## Verified checks

The initial automated suite contained 84 passing unit/contract tests, including
the isolated Windows event round trip. Four measured unchanged-catalog idle
scans on the three-voice XP guest took approximately 13–34 milliseconds each
(host polling resolution applies). These are scan round trips, not end-to-end
speech latency measurements or a guarantee for larger catalogs.

A separate hidden-frame test constructs actual wxPython settings widgets and
checks connection-state labels, the empty voice list, test button states, and
saving recovery preferences while disabled. No window is shown and the active
NVDA instance is untouched. This is not a full interactive NVDA acceptance test.

| Area | Evidence |
| --- | --- |
| Native build | x86 console EXE targeting subsystem 5.01; no modern CRT dependency |
| Protocol | Fragmented commands, malformed/oversized input recovery, stale-generation rejection, heartbeat expiry |
| Voices | All three installed voices complete muted SAPI requests |
| Formats | Default, 16/22.05/44.1/48 kHz; explicit formats read back as requested, 16-bit mono |
| Utterance assembly | Long text uses multiple PART packets but exactly one COMMIT; bookmark and completion arrive |
| Stop and reconnect | Paused cancellation, repeated connections, helper termination/restart, stale queue discarded, close rejects new speech |
| Live discovery | Added a disposable alias of an existing SAPI5 token, spoke through it, removed only the alias; same helper and connection, stable original indexes |
| XP playback volume | Opt-in MIXER request sets and reads back master and Wave maxima; muted speech completes afterward; no mute-control writes |
| Local maintenance | Real Windows event request/acknowledgement with isolated process; acknowledgement waits for worker shutdown in contract test |
| NVDA contracts | Settings mapping, ring registration, fallback on/off, optional return, manual override, return-attempt cap, disabled-panel preferences, control states and secure-mode rejection |
| Privacy | Curated source/package allowlists exclude local history, credentials, VM files, voice assets, personal settings and logs |

The user reported good listening results on the earlier same-version bridge.
That is useful feedback, not a numerical latency/audio measurement or acceptance
of every change in this beta. SAPI completion does not prove speakers are audible.

## Review-driven hardening

Source review identified weaknesses in live voice refresh and recovery. The
implementation now builds a complete temporary SAPI catalog before replacing the
last good one, caches names/IDs, and sends a short unchanged reply instead of
retransmitting every voice on every scan. Incomplete enumeration retains the old
catalog and backs off. A scan timeout with a responsive link pauses scanning,
not the whole connection. A completely stalled helper still triggers fallback.

Queued requests for removed voices are rejected before sending an invalid BEGIN.
Automatic returns are limited to three per rolling minute. Failed synth loading
does not enable a previously disabled master switch. Empty catalogs and malformed
requests do not justify reassigning one voice's index to another.

Intentional limits: local speech overflow/errors use the existing fallback path
rather than silently discarding arbitrary document text; stale generations are
ignored; the initial synth handshake has a bounded wait. These are beta design
tradeoffs, not guarantees of zero delay or identical behavior across voice engines.

One immediate back-to-back probe initially encountered a VirtualBox pipe-busy
error. A later retry succeeded and the full integration passed. Tests and tools
must release the single pipe before another client connects; do not run them
while NVDA owns it. The runtime client retries transient pipe availability.

## Remaining user and platform acceptance

1. Install the new `.nvda-addon`, replace the XP helper, and restart NVDA when
   convenient. Do not uninstall first if retaining existing settings.
2. Check the single connection button: Connect while stopped, Cancel connection
   while retrying, Disconnect while connected. Disconnect must stop retries.
3. Try test speech, stop, mirror on/off, synth voice/rate/pitch/volume and output
   format from the settings ring. Listen for pauses and cancellation behavior.
4. Enable fallback and automatic return. Close/restart only the helper: eSpeak
   should take over, then the previous bridge voice should return. Choose another
   synth deliberately during recovery and verify it is not overridden.
5. Optionally enable XP mixer adjustment at a comfortable host speaker volume.
   It raises other XP sounds too, leaves mute unchanged, and does not restore old
   mixer levels when disabled. Verify actual audibility, not just reported levels.
6. Confirm settings persist through a later normal NVDA restart.

Not qualified: the full new release's interactive NVDA UI/keyboard workflow,
detached/headless audio, VMware, independent XP service packs, every commercial
voice installer, multiple XP output devices, large real installed-voice catalogs,
long-duration reading, or automatic pipe switching through NVDA profiles.
No network transport, secure-login use, Windows service or host SAPI5 adapter.

## Reproduction

See OPERATIONS.md for commands, scope and safety. Unit tests never require a
running VM. Live probes require an idle helper and a free pipe; they close their
client afterward. The live voice probe needs an operator-controlled disposable
registration; the mixer probe requires explicit permission to change XP volume.
