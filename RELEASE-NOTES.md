# Angel Legacy Voice Bridge 0.1.1 beta

## Queue responsiveness fix

This add-on-only update recovers missing trailing bookmarks after XP confirms
the current utterance has finished. NVDA uses indexes to advance queued speech;
reporting completion alone is insufficient. Duplicate and canceled indexes are
not replayed. Long speech packet preparation no longer holds the state lock
needed by cancel, pause and enqueue. Added text-free progress diagnostics.

The reported full-computer freeze was not reproduced in live tests. Logs showed
NVDA freezes during a dense event stream, but did not identify the blocking
call. This release fixes demonstrated failure cases; user listening validation
under the original workload is still needed.

Use licensed SAPI5 voices installed in an offline 32-bit Windows XP VM with
modern NVDA. Audio plays through XP. Voices and Windows are not included.

## Download and install

- On modern Windows: open `AngelLegacyVoiceBridge-0.1.1.nvda-addon`, accept
  replacement/installation, and restart NVDA when convenient.
- Inside XP: put `AngelLegacyVoiceBridge.exe` in a folder such as
  `C:\AngelLegacyVoiceBridge` and run it after configuring the VirtualBox serial
  pipe. Existing public 0.1.0 helpers are unchanged and can stay running; no XP
  reboot or helper update is required for this fix.
- `AngelLegacyVoiceBridge-0.1.1-source.zip` includes the Python and C++ source,
  build script, tests and full setup/operations documentation.
- SHA-256 sidecars are supplied for each artifact. The binaries are not signed.

Follow README.md for setup and OPERATIONS.md for Guest Additions launch and
maintenance. No passwords, personal VM identifiers or saved NVDA settings are
included. Existing settings on your computer are retained when replacing the
add-on.

## Included

- Bridge synthesizer and optional mirrored speech.
- State-aware Connect / Cancel connection / Disconnect control.
- Live voice discovery, cancellation, pause and settings-ring output formats.
- Local eSpeak fallback and optional automatic return that respects manual choices.
- Optional XP playback mixer adjustment, off by default; affects other XP sounds.
- Local disable-only maintenance tool and NVDA+Shift+F11 emergency shortcut.

91 automated unit/contract tests and the hidden real-widget check pass. Live XP
tests cover all installed test voices, supported output formats, protocol faults,
cancellation/reconnection, live voice registration changes, and playback mixer
readback. See TEST-REPORT.md for precise evidence and limitations.

This is a **pre-release**, not an NVDA Add-on Store submission or a universally
qualified primary screen reader. Keep local speech available. VirtualBox is the
only currently supported hypervisor; VMware is not qualified. The offline XP
helper passed muted headless backlog and format tests; audible quality remains
a user check. Complete interactive NVDA acceptance and broader hardware testing
remain. Licensed SAPI5 engines only; no SAPI4, network listener or Windows service.

License: GNU GPL version 2 or later, matching Angel Audio Keeper.
