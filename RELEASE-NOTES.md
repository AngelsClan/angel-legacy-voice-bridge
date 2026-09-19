# Angel Legacy Voice Bridge 0.1.0 beta

Use licensed SAPI5 voices installed in an offline 32-bit Windows XP VM with
modern NVDA. Audio plays through XP. Voices and Windows are not included.

## Download and install

- On modern Windows: open `AngelLegacyVoiceBridge-0.1.0.nvda-addon`, accept
  replacement/installation, and restart NVDA when convenient.
- Inside XP: put `AngelLegacyVoiceBridge.exe` in a folder such as
  `C:\AngelLegacyVoiceBridge` and run it after configuring the VirtualBox serial
  pipe. Update both components if you used an earlier development build.
- `AngelLegacyVoiceBridge-0.1.0-source.zip` includes the Python and C++ source,
  build script, tests and full setup/operations documentation.
- SHA-256 sidecars are supplied for each artifact. The binaries are not signed.

Follow README.md for setup and OPERATIONS.md for Guest Additions launch and
maintenance. No passwords, personal VM identifiers or saved NVDA settings are
included. Existing settings on your computer are retained when replacing the
same-version add-on.

## Included

- Bridge synthesizer and optional mirrored speech.
- State-aware Connect / Cancel connection / Disconnect control.
- Live voice discovery, cancellation, pause and settings-ring output formats.
- Local eSpeak fallback and optional automatic return that respects manual choices.
- Optional XP playback mixer adjustment, off by default; affects other XP sounds.
- Local disable-only maintenance tool and NVDA+Shift+F11 emergency shortcut.

84 automated unit/contract tests and a hidden real-widget check pass. Live XP
tests cover all installed test voices, supported output formats, protocol faults,
cancellation/reconnection, live voice registration changes, and playback mixer
readback. See TEST-REPORT.md for precise evidence and limitations.

This is a **pre-release**, not an NVDA Add-on Store submission or a universally
qualified primary screen reader. Keep local speech available. VirtualBox is the
only currently supported hypervisor; VMware and detached/headless audio are not
yet qualified. Complete interactive NVDA acceptance and broader hardware testing
remain. Licensed SAPI5 engines only; no SAPI4, network listener or Windows service.

License: GNU GPL version 2 or later, matching Angel Audio Keeper.
