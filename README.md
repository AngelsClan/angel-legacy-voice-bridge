# Angel Legacy Voice Bridge

Use an older Windows speech voice with NVDA on your current PC. The voice stays
inside your Windows XP virtual machine. The bridge sends it text and brings
speech back to NVDA, or lets XP play the sound.

**This is a development build (`0.1.2-dev4`), not a public release.** An
earlier NVDA freeze has not been conclusively explained. Keep another NVDA
voice available while testing. [Read the test results](TEST-REPORT.md).

**Looking for a download?** There is no public installer release yet. This
repository contains the source; the [build instructions](docs/ADVANCED-GUIDE.md#building-from-source)
produce the matching XP helper and NVDA add-on. Wait for a tested release if
you are not comfortable building a development copy.

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

## More information

- [Detailed setup, updates, settings, and troubleshooting](docs/ADVANCED-GUIDE.md)
- [What has been tested and what remains uncertain](TEST-REPORT.md)
- [Why a bridge can help](RATIONALE.md)
- [Privacy, safety, and known limits](docs/ADVANCED-GUIDE.md#privacy-and-security)
- [Report a problem](https://github.com/AngelsClan/angel-legacy-voice-bridge/issues)

The bridge is GPL-2.0-or-later; see [LICENSE](LICENSE). Development used AI
assistance.
