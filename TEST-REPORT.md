# Beta qualification

## Output format and volume quality — 2026-09-22

On the development XP VM, Pipe Organ, Alex and Fred (Leopard XP; the Panthera
engine reports 22,050 Hz mono) rendered one ordinary English sentence to files
at the engine's own 22.05 kHz and through SAPI conversion to 44.1 and 48 kHz,
at XML volume 100 and 20. Nothing was played.

| Voice | Energy above 11.025 kHz at 44.1 / 48 kHz | Volume 20 vs 100 at 22.05 kHz |
| --- | --- | --- |
| Pipe Organ | −25.4 / −25.4 dB | 62.9 dB SNR after rescaling |
| Alex | −21.2 / −21.1 dB | 63.2 dB |
| Fred | −26.7 / −26.6 dB | 64.4 dB |

The native files have no energy above 11.025 kHz, so everything there is
conversion artefact (imaging), easily audible as harshness. Voice default avoids
SAPI's conversion. Volume 20 loses about 30 dB of dynamic range compared with
16-bit full scale. The labels now recommend Voice default. The VM's host audio
driver was separately switched from DirectSound to Windows Audio Session (the
AC97 controller is unchanged); listening comparison is pending.

## Heavy announcement traffic — 2026-09-22

Isolated NVDA 2026.2 (fresh profile, unseen desktop, eSpeak volume 0) against
the private fake helper speaking two utterances per second, while five
announcements per second plus a 200-event burst arrived, as on a busy server.
NVDA's own queue is expected to grow in that situation; the bridge must not
fail because of it.

- Bridge selected, 180 s: 1,090 announcements, 346 spoken, NVDA queue peak
  1,492, bridge queue peak 1, no fallback, no reconnect, no failed utterance,
  no memory growth. NVDA's cancel cleared everything in 0.20 s and new speech
  completed immediately.
- Mirroring with local eSpeak, 120 s: 1,885 announcements, bridge queue capped
  at 64, local synth unchanged, cancel cleared in 0.19 s. The old behaviour
  cancelled all mirrored speech seven times. Rerun with drop-oldest mirroring:
  1,885 announcements, 241 spoken, bridge queue capped at 64, zero cancel-all
  events, no fallback, reconnect or memory growth, cancel cleared in 0.20 s.
  The bridge-selected phase repeated its earlier result. Fake helper only; not
  a measurement of real XP voices or of the Qt client itself.

## Verified automatic return — 2026-09-22

Automatic return previously switched back as soon as the pipe reconnected and
the original voice token was listed. A crashed engine host can leave both intact.
The return now requires a completed render of a fixed check phrase, sent at
volume zero in the original voice, confirmed by its final bookmark.

Volume-zero measurement on the XP VM (2026-09-22): every installed SAPI 5
voice (29) rendered the exact check phrase to 22 kHz WAV files with XML volume
100 and 0; no audio was played. Microsoft Sam and all 26 Panthera voices gave
peak 0 (all-zero samples) at volume 0. AT&T DTNV 1.4 Mike16 and Crystal16 gave
peak about 5,060 at volume 0 versus about 28,450 at 100 (about 18%), and the same
with SpVoice.Volume = 0, so their check phrase is audible. A future helper
option could render check utterances to a memory stream instead of the audio
device, making them silent for every vendor; not implemented. Other limits: backoff from 5 to
60 seconds, 12 checks or 15 minutes maximum, three returns per ten minutes,
cancellation on profile switch, and spoken outcomes.

- 138 unit tests pass (122 previous plus 16 recovery tests: handshake-only,
  volume-0 fixed check request, delayed recovery, bounded failing checks, timeouts,
  cancelled checks, stale callbacks, total window, idle wait, lost connection,
  profile change, return cap with announcement, escalating first wait, repeated
  failure cycle, disabling during a check, another local synth, plus plugin
  registration of the profile-switch handler).
- Real NVDA 2026.2, isolated on an unseen desktop with a fresh profile (eSpeak
  volume 0) and a private fake helper that fails or succeeds on command:
  A delayed recovery (one failed check, verified return in about 16.5 s, voice
  and rate restored, notice spoken through the bridge); B manual eSpeak during
  fallback respected, no further checks; C another local synth respected;
  D profile switch keeping eSpeak cancels the return; E turning auto-return off
  respected; F return cap enforced after repeated failures. The fake helper is
  not the XP engine; this verifies NVDA-side behaviour only.
- A harness defect in the first runs held a settings section across a profile
  switch; writes through it did not reach the live configuration. The add-on
  itself always fetches settings fresh.
- No XP, voice-pack, helper or installed add-on change. The owner's NVDA was not
  touched. This does not fix or explain the native MacinTalk crash.

## Further XP engine investigation — 2026-09-22

The updated bridge was already installed for the latest reported failure.
Its log confirms reset-before-fallback ran and eSpeak loaded. Separately, the
voice host recorded a native access violation during phoneme/stress processing;
the exact triggering input and underlying compatibility defect remain unresolved.

An independent 1,200-request, nonplaying Pipe Organ session passed. A real-bridge
180-interruption run exposed XP's legacy SPERR_AUDIO_STOPPED in the engine log:
the voice adapter had mistaken normal cancellation for engine failure. The
Classic voice pack, maintained separately, now accepts both normal stop codes.
A targeted actual-XP regression failed twice before the change and passed after;
the unexpected-stop code still fails, and subsequent speech recovers. All 26
registered Panthera voice renders produced nonzero PCM after installation.
The installed Classic fix then passed 180 varied-timing interruptions plus next
speech; its final 181 engine records contain 180 cancellations and zero failures.
This is not evidence that the separate native crash is fixed. No NVDA restart,
automatic bridge activation, or accessibility release approval was performed.

## Pipe Organ failure and abandoned fallback queue — 2026-09-22

The host and XP logs correlate an asynchronous SAPI failure (stage 7,
HRESULT 0x80004005, Pipe Organ, 48000 Hz) with local eSpeak fallback. NVDA's
process stayed running. The XP helper accepted a new session afterward. This
does not prove a native process crash, nor establish what caused E_FAIL.

The host log showed roughly 15,000 pending NVDA sequences at fallback, later
over 31,000, while the bridge itself was idle. Source review found that changing
synthesizers without cancelling NVDA speech leaves old indexes outstanding.
DONE alone is insufficient. NVDA's normal profile-change path explicitly
cancels speech before changing synths; the bridge now follows that contract.

- Real NVDA 2026.2, fresh muted profiles on a separate, never-shown desktop:
  old installed add-on plus injected session failure left 602 pending sequences
  and one active index after eSpeak loaded. The corrected candidate left zero
  pending sequences/indexes and completed a subsequent local-speech request.
- The first harness attempt omitted synth selection because Python optimization
  removes assert expressions. It was invalid and is not counted. The corrected
  harness uses explicit checks and verified bridge selection in both runs.
- Real XP Pipe Organ: ten completed synthetic punctuation, apostrophe,
  Cyrillic/emoji and longer-message cases at 48000 Hz, rate 16, volume 20.
- Follow-up: five mixed-control utterances also passed. Each changed rate,
  volume and pitch inside one accepted stream and completed both bookmarks in
  order. This did not reproduce the asynchronous E_FAIL either. A final helper
  connection/catalog check passed; VM audio output was verified on afterward.
- Real XP Pipe Organ: sixty queued requests across default/48000 Hz formats;
  all bookmarks completed in order, twenty deliberately omitted bookmarks were
  recovered. Twenty rapid cancellations and empty/bookmark-only speech passed.
  Largest inter-completion gaps were 0.938 and 1.016 seconds respectively.
- 122 unit/adapter tests passed, including reset-before-switch, already
  reconnected failure, fallback disabled, profile-change preservation, and
  failure diagnostics that never contain the queued speech text.

The exact Pipe Organ E_FAIL has not recurred in these synthetic tests. Numeric
XP engine diagnostics were enabled on the test installation (Diagnostics=1,
not text-recording level 2); the historical event predates those deeper engine
records. Do not infer the original engine cause from a generic HRESULT.

Only the isolated test children were closed by the bounded harness. The user's
NVDA was neither restarted nor replaced. The bridge remains disabled, the VM
remains running, and its audio output is restored after testing. This candidate
does not lift the accessibility release hold or require user reproduction.

## Voice-pack reinstall / immediate fallback — 2026-09-21

The user log recorded `batch-speak-failed` twice while changing from Alex to
Agnes, followed by bridge disconnects. It did not contain the original HRESULT;
this does not establish an NVDA process crash. An isolated real-XP reproduction
using one disposable copy of a voice registration returned the same fixed error
with HRESULT 0x800703FA at Speak: registry key marked for deletion. Installers
can delete/recreate a token while the long-running helper or SpVoice retains it.
This is a demonstrated cause consistent with the incident, not a recovered
historical HRESULT or proof that every previously reported freeze is resolved.

- Before the fix: replacing the unselected catalog token reproduced fallback.
- Fresh token selection fixed that case, but was insufficient for an engine
  already cached inside SpVoice. A fresh SpVoice on this specific synchronous
  rejection, with a single retry, fixed the selected-voice case too.
- Replacement with the voice already selected passed; recovery NOTICE count,
  bookmark 7, DONE and 48000 Hz output were verified.
- Pause injected immediately before COMMIT survived replacement recovery.
  There was no bookmark/completion during six seconds paused, and exactly one
  expected recovery followed by successful completion after resume.
- 58 completed voice transitions passed: all 29 installed voices forward and
  backward at fixed 48000 Hz, protocol rate 16 and volume 80.
- The currently installed, unchanged add-on transport passed 29 interrupted
  voice transitions with the new helper. Tests waited for COMMIT acknowledgement
  before cancellation; early queue-only attempts are not counted as that test.
- 118 host unit/adapter/contract tests passed, including numeric-only SAPIERROR
  logging and recovery notices that cannot complete speech or revive old indexes.
- All 29 real voices passed the five output-format checks on the recovery
  candidate. That initial overall quality probe then timed out on an obsolete
  disposable alias, not one of the real voices. The reinstall probe cleanup
  now deletes its one alias AND waits for catalog removal; subsequent 29-voice
  tests passed. Do not describe the first overall quality run as a clean pass.
- Two independent read-only code reviews were performed. The first caught missing
  pause preservation and insufficient diagnostic detail; those were addressed.
  The second found no serious correctness issue and recommended the longer
  pause observation used above. No claim of acoustic quality is made.

VM audio output was disabled only during automated tests; active NVDA was
neither restarted nor replaced. Only the XP helper was replaced. The helper
repair is compatible with the installed protocol-2 add-on; the optional rebuilt
add-on adds diagnostic detail. No voice data, credentials, VM or personal
profile is packaged. No GitHub release is authorized by these test results;
the separate accessibility-critical freeze investigation remains on hold.

## Skipped text / Microsoft Sam investigation — 2026-09-21

Status: development 0.1.2-dev2, release hold unchanged. The exact intermittent
user incident was not reproduced; do not call this a proven cure or ask the user
to risk losing their only speech. No active NVDA restart was performed.

- Baseline real-XP tests completed the reported `!В саду🌳⛅` example with Sam,
  AT&T Mike and Crystal, including normal English afterward. Blank/symbol-only
  and empty input also completed at 48 kHz and protocol rate 16, volume 30.
- Candidate normal helper passed 36 cases across two rounds of all three voices
  at 48 kHz, rate 16, volume 30. This includes returning to Sam after the other
  engines. Completion was roughly 0.25–1.18 seconds for these short phrases;
  this is whole-request duration, not speech-onset latency or an acoustic audit.
- All three voices passed all five output formats, long multi-packet utterances
  with one SAPI commit, and immediate close/cancel with the normal helper.
- A separate hidden-desktop NVDA session using a fresh, muted profile passed
  the real speech-manager path with all three XP voices and the example,
  symbols, whitespace, empty text and following English. It returned to local
  speech afterward. Initial harness runs did not select the bridge and were
  discarded; the corrected run explicitly verified the selected driver. No
  personal profile, real-user navigation or live TeamTalk traffic was used.
  The isolated test process was closed by the harness's bounded process cleanup;
  the user's running NVDA process was not replaced or restarted.
- Fault-injection helper deliberately suppressed END_INPUT_STREAM handling.
  All 18 Unicode/empty/English cases recovered through actual SAPI completion
  polling, with exactly one recovery notice per request.
- The faulted helper also passed protocol-1/2 handshakes, malformed-input
  recovery, heartbeat expiry, and three paused-cancellation/reconnection runs.
- With end events suppressed and every third received bookmark deliberately
  omitted, 60 queued requests in two formats completed in order. Twenty missing
  bookmarks were recovered; the largest inter-completion gap was 0.565 seconds.
  Twenty rapid cancellations and bookmark-only/empty utterances also passed.
- 116 Python unit/contract tests passed. New checks cover numeric diagnostics, fixed-code error
  reporting without arbitrary guest content, and notices that cannot complete
  speech or resurrect canceled indexes. Engine-error handling is tested with
  injected host replies, not a naturally failing commercial engine.

The first immediate transition between independent probe processes hit a
temporary pipe-busy error; rerunning after release passed. One helper deployment
attempt used an unsupported relative source path; no successful test result is
claimed for that attempt. Corrected absolute-path transfer and launch succeeded.

Claudius supplied a limited patch review. Suggestions about stale end events and
uncaught ValueError did not apply to the surrounding stream guards and existing
exception handler; those were checked directly. The broader follow-up review
did not complete and was stopped. There is no claim of a full independent sign-off.

Completion polling is nonblocking and follows bookmark-event draining. It uses
[Microsoft's documented WaitUntilDone contract](https://learn.microsoft.com/en-us/previous-versions/office/developer/speech-technologies/jj149387(v=msdn.10)):
success means pending speech calls have completed, not that a guessed timeout
has expired. Text is not stripped solely because it is non-English. More
diagnostics cannot guarantee capturing every engine or native-process failure.

## Emergency investigation — 2026-09-20, release HOLD

The user reported loss of NVDA speech during window switching under heavy
TeamTalk events, requiring forced restart. **Not reproduced and not proven
fixed.** Do not ask a speech-dependent user to reproduce this incident.

- Existing logs show startup callback failures before wx.App initialization;
  this is corrected with NVDA's core event queue but is not established as the
  cause of the later window-switching freeze.
- 113 unit/contract tests pass, including bounded logging, rotation, slow/full
  diagnostic queues, inaccessible paths, callback ownership, and stale delivery.
  Added startup-failure isolation and transient-write recovery after review.
- Real NVDA 2026.2 runs used a separate Windows desktop and isolated, muted
  configuration. No foreground switch, real-user input, live server connection,
  active NVDA restart or personal profile copy was used.
- A 900-tick real-NVDA/XP run queued 60,000 synthetic speech requests in addition
  to background controller events. NVDA's pending sequence count exceeded
  113,000. It then processed 50 synthetic focus events and cancellation. The
  longest 100-ms test-timer interval was 0.176 seconds; the test exited normally.
  This is not an end-to-end speech-latency measurement or a real Chrome Alt-Tab
  reproduction. Focus events were explicitly queued for hidden test controls.
- The released 0.1.1 baseline also passed the same isolated 60,000-request/focus
  scenario (longest timer interval 0.177 seconds). This is important negative
  evidence: this harness does not distinguish or reproduce the reported bug,
  and its passing result cannot validate a cure for the original incident.
- The final candidate, after separating diagnostics from bridge lifetime, also
  completed a 900-tick real-NVDA/XP run with 76 synthetic focus events, normal
  exit and a longest timer interval of 0.120 seconds. Hidden real-wx settings
  construction and state/control checks passed separately.
- A deliberately injected six-second main-thread stall was detected after
  three seconds, including the blocking test-function location and recovery.
  The same detection passed using local eSpeak with the bridge disabled and
  no XP connection. No speech text or window title was recorded.
- TeamTalk's local session log contains over 53,000 status events across about
  six and a half hours. Events continued near the reported NVDA restart. It
  contains no fatal record establishing which process failed first. Force-close
  may leave no final log; absence of a crash record is not proof of no crash.
- Separate Qt source review found an indefinite screen-reader-worker shutdown
  wait. A bounded-exit fix passes fake-backend tests for healthy shutdown, stuck
  speech with 1,000 queued messages, and stuck backend cleanup. This could explain
  why closing the client failed after speech was stuck, not the original trigger.
- A second Qt risk was found: long-label formatting performed live screen-reader
  feature probes on the GUI thread. Detection now runs on the worker and label
  formatting reads a conservative cached result. Fault tests verify 100,000 UI
  reads do not probe or wait even while detection is blocked. This is a plausible
  contributing path, not proof it caused the user's incident.
- Claudius performed a read-only review. Startup diagnostic failures can no
  longer prevent safety-control registration; stopped monitors are generation
  guarded, transient file locks are recoverable, and private NVDA counter API
  changes are isolated. Synchronous disk flushing on NVDA's main thread was
  deliberately rejected because it would introduce another blocking path.
  A second review found missing detection when Prism speech was not selected
  and excessive sampling of unavailable counters. Both are corrected and
  regression-tested. The full Qt client also compiles with native Windows/Qt
  tools and real Prism; compilation alone is not runtime acceptance.

The XP helper is unchanged. Candidate diagnostics are not installed into the
user's active NVDA and no new public binary release is approved by these tests.

The sections below are historical qualification records, not current clearance
to use the bridge as a primary synthesizer.

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
