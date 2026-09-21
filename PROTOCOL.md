# Local serial protocol, version 2

This is an unencrypted, local-only text protocol. The hypervisor creates a
Windows named pipe; the host opens it; XP reads/writes COM1 (or an explicitly
selected COM2–4). No network listening socket, remote code execution command,
file access command, microphone capture or voice redistribution is included.

## Framing

ASCII, tab-separated fields, one LF-terminated command per line. CR is ignored
by the helper. Text/name/token fields use lowercase hex of UTF-16LE. Empty
lines are ignored; the helper starts catalog replies with an empty line
to terminate a possibly partial preceding response.
Embedded NUL is not allowed. Helper line limit: 8,191 bytes excluding LF. A malformed or
oversized line is discarded through LF; the next complete line can recover.
Normal speech is split into at most 120 Unicode codepoints, far below the
helper's 511 UTF-16-code-unit text limit. Unknown speech markup is never executed:
the helper escapes text before adding its own pitch/spelling XML tags.

The virtual UART is not an unlimited buffer. One small packet is in flight at
a time, acknowledged before the next; do not blast arbitrarily large raw lines.
The oversized-line test paces chunks to test parsing rather than FIFO overflow.
Packets are assembled into one utterance before SAPI speaks. Host bounds:
16,000 text characters/256 sequence items per utterance, 64 queued utterances.
Helper XML storage is 131,072 WCHAR slots, with bounds checked on every append.

## Messages

`session` is a fresh 32-character lowercase hexadecimal UUID per connection.
`generation` increases on cancel/disconnect; old speech/completion is ignored.
Numbers are nonnegative decimal; rate/pitch are 0–20, volume 0–100, spell 0/1.
The helper maps rate and pitch to -10 through +10. Voice index is 0–127.

| Direction | Fields in order |
| --- | --- |
| Host → XP | HELLO, 2, session |
| XP → host | READY, 2, session |
| XP → host, once per voice | VOICE, index, nameHex, tokenIDHex |
| XP → host | ENDVOICES |
| XP → host, optional capability | CAPS, session, voice-refresh |
| XP → host, optional capability | CAPS, session, xp-volume |
| Host → XP, idle only | REFRESH, session |
| XP → host | VOICESUNCHANGED, session |
| XP → host | VOICESRETRY, session |
| Host → XP, explicit volume opt-in | MIXER, session |
| XP → host | MIXER, session, OK-or-PARTIAL-or-UNSUPPORTED |
| Host → XP | PING, session |
| XP → host | PONG, session |
| Host → XP | CANCEL, session, generation |
| XP → host | CANCELLED, session, generation |
| Host → XP | PAUSE, session, 0-or-1 |
| Host → XP | BEGIN, session, generation, requestID, voiceIndex, outputFormat |
| Host → XP | PART, session, generation, requestID, rate, volume, pitch, spell, textHex |
| Host → XP | MARK, session, generation, requestID, index |
| Host → XP | BREAK, session, generation, requestID, milliseconds (0–10000) |
| Host → XP | COMMIT, session, generation, requestID |
| XP → host | ACK, session, generation, requestID |
| XP → host | INDEX, session, generation, requestID, index |
| XP → host | FORMAT, session, sampleRate, bits, channels |
| XP → host | DONE, session, generation, requestID |
| XP → host | ERROR, session, generation, requestID, fixed-error-code |

BEGIN/PART/MARK/BREAK/COMMIT are individually acknowledged. COMMIT submits one
SAPI utterance. Consecutive PARTs with the same settings share surrounding XML
style tags; transport boundaries do not introduce prosody changes. Output format
is 0 for voice default, or 16000/22050/44100/48000 for 16-bit mono PCM. FORMAT is
the format reported by SAPI, not an audio-quality measurement.

DONE follows SAPI's end-input-stream event, not a microphone measurement.
SAPI stream IDs reject events belonging to canceled utterances. Error request IDs may
refer to the last request if a new request failed validation. The host treats
a helper error as a session failure, discards its queue and reconnects.

## State and ordering

HELLO purges old audio and starts a fresh session. The host follows it with
CANCEL carrying its current generation. A voice is selected by stable token ID
in configuration, and mapped to the session's numeric index when speaking.
Only one host and one helper should own the pipe/COM port.

Helpers advertising `CAPS session voice-refresh` accept REFRESH while neither
speaking nor assembling an utterance. They re-enumerate SAPI5 and reply with
READY/VOICE/ENDVOICES plus CAPS if changed, or VOICESUNCHANGED otherwise, without
resetting the session, generation or speech state. An incomplete enumeration
keeps the last complete snapshot and returns VOICESRETRY; the host waits about
30 seconds before retrying a scan. The host atomically replaces its catalog at ENDVOICES, including
an empty catalog, and blocks new speech dispatch during the scan. It polls about
every five seconds in idle gaps. If the catalog does not finish in four seconds
but replies still prove the connection alive, it retains the old catalog and
disables scanning until reconnect. A completely unresponsive helper still uses
the normal connection timeout. Older helpers without CAPS are not sent REFRESH.

Voice indexes remain bound to their original token IDs for the helper lifetime.
Removed tokens are unavailable, not reassigned to other voices; reinstalling the
same token restores its old index. The bound is 128 distinct token IDs per run.
REFRESH while busy is an error. No registry-writing command is exposed.

MIXER adjusts the preferred XP playback device's speaker master and Wave source
levels to their reported maxima and reads them back. It never unmutes, changes
recording gain, or adjusts host Windows audio. Unsupported/partial controls
produce status rather than resetting speech. The host sends it only after the
xp-volume capability and user opt-in; repeated volume edits coalesce. The user
must restore earlier mixer levels manually if desired.

The host worker owns I/O. Main-thread enqueue/cancel only change bounded state.
Writes are outside the queue lock; cancellation can race with at most one small
previously selected speech frame. The subsequent CANCEL purges it. New speech
is behind that control message. No claim of instantaneous acoustic cancellation
is made for buffered hardware/legacy voice engines.

Bookmarks and breaks become SAPI bookmark/silence tags within the utterance.
Pause freezes speech dispatch; resume adjusts the speech timeout. Cancellation resumes a
paused SAPI engine before starting the next request.

The host sends PING about once per second and disconnects after approximately
four seconds without replies. XP purges after six seconds without valid-session
contact. An unacknowledged packet times out after four seconds even when PONG
replies continue. Speech completion allows 120 seconds plus half a second per
text character, excluding paused time. Closed/broken
pipes are retried after roughly one second; transport delays are not hard
real-time guarantees. NVDA callbacks also carry generation/source checks so
late events from a replaced connection cannot advance new speech.

## Compatibility

Development helper 0.1.2-dev2 retains protocol 2. It can send
`NOTICE session generation requestID completion-polled` when nonblocking SAPI
polling recovers a missing completion event. This is diagnostic only; the normal
DONE still follows after success. Old hosts ignore NOTICE. The new host logs
only this known notice for the active request. Engine or completion-query failures
produce fixed codes `sapi-engine-failed` or `sapi-completion-failed` through ERROR,
not DONE. Unknown error text is never copied to logs. Normal event completion and
polling both retain stream/generation checks and drain queued bookmarks first.

The new add-on requires protocol 2: replace both helper and add-on when updating
this same-version beta. The helper also retains HELLO/READY version 1 for old
host regression tests. Version 1 SPEAK fields are session, generation,
requestID, voiceIndex, rate, volume, pitch, spell, literal TEXT, textHex. It
returns ACCEPTED then DONE after WaitUntilDone(0). It speaks packets separately;
those extra pauses motivated version 2. Do not mix version 1 and 2 speech in a
single session.
