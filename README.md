# Angel Legacy Voice Bridge

Use an older Windows speech voice with NVDA on your current PC. The voice stays
inside your Windows XP virtual machine. The bridge sends it text and brings
speech back to NVDA, or lets XP play the sound.

**This is a development build (`0.1.2-dev5`), not a public release.** An
earlier NVDA freeze has not been conclusively explained. Keep another NVDA
voice available while testing. [Read the test results](TEST-REPORT.md) and
[what to do if a voice fails](docs/ADVANCED-GUIDE.md#what-happens-when-the-voice-fails).

**Looking for a download?** The [0.1.1 beta release](https://github.com/AngelsClan/angel-legacy-voice-bridge/releases/tag/v0.1.1)
is public, but it is older than the `0.1.2-dev5` source described on this
page. There is no installer release for this development build. The
[build instructions](docs/ADVANCED-GUIDE.md#building-from-source) produce its
matching XP helper and NVDA add-on. Do not mix a beta helper with a newer
development add-on; wait for a matching release if you do not build from source.

Dev5 changes only the host add-on. It divides unusually long uninterrupted
text spans into separate SAPI utterances before sending them to XP. This is a
targeted response to two observed AT&T Mike silent completions with the same
1,500-character span. Ordinary paragraphs retain their previous batching.
The existing dev4 XP helper binary is unchanged and can be used with dev5.

**Choosing a route:** This bridge is for a SAPI 5 voice that already works in
XP. Native Mac voice add-ons and native Eloquence run on the current Windows PC
without XP. If you want to read a document *inside XP*, use XP's NVDA and its
local SAPI synthesizer; the host bridge is not required for that task.

The October 16 maintenance update retains valid serial handles through helper
timeouts and canceled I/O instead of provoking a stuck VirtualBox reopen. It
also removes interactive synth-selection waiting and blocks unsafe live UART
resets. Tests include real XP pause/resume recovery; see TEST-REPORT.md.
Maintenance launchers must allow NVDA settings windows to display normally.

## Before you start

You need:

- NVDA on your current Windows PC.
- NVDA 2026.1 or later (this build declares compatibility through 2026.2).
- A working **32-bit Windows XP** virtual machine in VirtualBox, with sound.
- A **SAPI 5** voice installed and speaking inside XP. SAPI 4-only voices do
  not work with this bridge.
- The bridge's XP helper program and NVDA add-on from the same build.

The project does not supply XP, voices, or voice licenses. XP does not need an
internet connection; the two programs talk through a local virtual serial
connection.

Temporary helper timeouts and canceled writes now keep a valid pipe handle
open and negotiate a fresh session. Pending speech is discarded and local
fallback remains available. Broken-pipe errors still close the handle normally.
This avoids the close/reopen sequence that left VirtualBox 7.2.18 returning
WinError 231 after a pause. It does not fix VirtualBox's own implementation.

Automatic live UART/backend replacement is disabled: previous tests reproduced
a VirtualBox shutdown crash after that operation. A pipe already stuck busy
with no client handle may require an operator-controlled headless save/resume
to recreate the VM process. A guest-only Windows reboot does not recreate it.
The add-on never automatically saves, pauses, reboots or stops a VM.

Ordinary new pipe opens wait for known Guest Additions startup levels 1 or 2
to reach level 3. Without readiness metadata there is only the existing bounded
cold-start grace period. Retained-handle retries perform no VBoxManage query.
Interactive synthesizer selection does not wait for the VM; connect in bridge
settings first. Only pre-GUI NVDA startup retains a bounded two-second handshake.

You will change one VirtualBox setting while XP is shut down, then start one
program inside XP and install one add-on on your current PC. Nothing sets up
the VM, installs voices, or changes NVDA's synthesizer automatically.

**Using the Lion, Snow Leopard, Leopard, or Tiger Mac voice add-on?** Those
add-ons run voices on your current PC and do **not** require XP or this bridge.
Use this bridge for voices installed as SAPI 5 voices inside XP.

## Get speech working

There are two small programs: `AngelLegacyVoiceBridge.exe` runs **inside XP**;
`AngelLegacyVoiceBridge-<version>.nvda-addon` installs in **NVDA on your current
PC**. Use both files from the same build, even if an update keeps the same
version number.

1. **Connect the VM.** With XP shut down, set VirtualBox's first serial port
   to COM1, **Host Pipe**, and **create** the pipe. The example name is
   `\\.\pipe\AngelLegacySpeech-XP`. Then start XP. [Exact VirtualBox fields
   and a command are in the setup guide](docs/ADVANCED-GUIDE.md#step-1-add-a-virtual-serial-port-to-the-vm).
2. **Start the XP helper.** Copy `AngelLegacyVoiceBridge.exe` into XP and run it.
   Leave its window open. It should say that it is waiting for the host. [Ways
   to copy it and common XP errors](docs/ADVANCED-GUIDE.md#step-2-put-the-helper-program-in-xp-and-run-it).
3. **Install the NVDA add-on.** Open the `.nvda-addon` file on your current PC,
   approve it in NVDA, and restart NVDA when you are ready. Keep a familiar
   local voice selected until you have tested the bridge.
4. **Hear a test.** Open NVDA's **Preferences > Settings > Legacy Voice Bridge**.
   Check the pipe name, select **Enable bridge now**, and connect. Choose an XP
   voice under **Mirror/test voice**, then press **Test speech through XP**. If
   you hear the test, you can select **Angel Legacy Voice Bridge** as NVDA's
   synthesizer with NVDA+Control+S. [Detailed first-test steps](docs/ADVANCED-GUIDE.md#step-4-connect-and-hear-your-first-test).

You can instead keep your usual NVDA voice and turn on **Mirror local NVDA
speech to XP** to hear both voices. If the test fails, leave your usual voice
selected and use the [troubleshooting guide](docs/ADVANCED-GUIDE.md#troubleshooting).

The add-on can detect a single running bridge pipe for you. If it finds more
than one, use **Detect running VM pipes** and choose the right one. The pipe
name shown in NVDA must match the one in VirtualBox.

## Choose where speech plays

In **Legacy Voice Bridge** settings, **Where XP bridge speech plays** offers:

| Choice | What you hear |
| --- | --- |
| XP speakers | The XP virtual machine plays the voice. |
| Send to NVDA | XP makes the voice audio; NVDA plays it on its selected output device. |
| Both XP and NVDA | Both play it, a little out of step. |

The voice engine still runs inside XP for every choice. Other XP sounds stay
on XP's sound card. If speech works on one output but not another, check that
output's device and volume. **Shift pauses or resumes** bridge speech; **Control
cancels** it. XP-only pause timing also depends on the XP voice and its audio
buffer.

You can also **mirror** speech: keep your normal NVDA voice and hear XP alongside
it. [The guide explains mirror and synthesizer modes](docs/ADVANCED-GUIDE.md#step-5-choose-how-you-want-to-use-the-voices).

## If the test fails

| What you see or hear | First thing to check |
| --- | --- |
| No running bridge pipe found | Start XP and confirm its VirtualBox serial port is a Host Pipe in **create** mode. |
| XP helper cannot open COM1 | Check the VM serial settings and close any second helper using COM1. |
| Connected, but no voices listed | Confirm the voice speaks in XP and is registered as **SAPI 5**. |
| Connected, voice listed, but silent | Use the Test button; check the selected XP or NVDA output device and volume. |
| NVDA and Both unavailable | Update the XP helper to the matching build. |

A connection proves that the two programs can talk; **the test phrase proves
that a selected voice and audio route actually work**. The [full troubleshooting
guide](docs/ADVANCED-GUIDE.md#troubleshooting) covers other errors. The bridge
never needs your XP network connection or server credentials.

An optional XP NVDA companion can announce connection changes and remind you
when the bridge remains disconnected. Those messages play through the
synthesizer selected **inside XP**. They do not run through this host add-on.
The XP helper also exposes a local counter when its SAPI engine fails, so the
companion can announce that error after XP NVDA finishes speaking.
In this development build, the XP helper and XP NVDA must run under the same
Windows account to share this local status.

## More information

## VirtualBox serial recovery and shutdown diagnostics

The October 9 development update blocks automatic live UART/backend resets.
A diskless test reproduced VirtualBox 7.2.18's shutdown access violation at
VBoxVMM.dll +0xf1312 after the old disconnect/reconnect sequence. Direct
replacement also crashed with an old connection held open, so it is not shipped
as a fix. Ordinary pipe reconnects and the XP startup readiness checks remain.
A pipe that remains stuck after saved-state resume may need a normal XP
shutdown and cold boot. This avoids the bridge's reproduced trigger; it does
not repair VirtualBox itself. Do not change UART backends while a VM is running.

Default lifecycle diagnostics go to NVDA's log (normally `%TEMP%/nvda.log`).
Set NVDA's logging level to Debug under General settings to increase detail
without rebuilding. Look for `Unsafe VirtualBox serial reset blocked` with
its UART. The existing bridge settings connection status remains the runtime check.
No spoken content or pipe address is included in these new messages.

From the project directory, run `python -m unittest discover -s tests -q`.
The serial-reset rejection regression exercises the warning diagnostic and
verifies no mutating VirtualBox command is issued. Updating a loaded host add-on requires a coordinated
NVDA restart before the new recovery function becomes active.

- [Detailed setup, updates, settings, and troubleshooting](docs/ADVANCED-GUIDE.md)
- [What has been tested and what remains uncertain](TEST-REPORT.md)
- [Changes between development builds](CHANGELOG.md)
- [Removing the add-on](docs/ADVANCED-GUIDE.md#removing-it)
- [Why a bridge can help](RATIONALE.md)
- [Privacy, safety, and known limits](docs/ADVANCED-GUIDE.md#privacy-and-security)
- [Report a problem](https://github.com/AngelsClan/angel-legacy-voice-bridge/issues)

The bridge is GPL-2.0-or-later; see [LICENSE](LICENSE). Development used AI
assistance.
