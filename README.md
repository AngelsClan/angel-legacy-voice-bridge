# Angel Legacy Voice Bridge

Use old SAPI 5 voices that only work on 32-bit Windows XP as if they were
installed in your modern NVDA.

You keep a Windows XP virtual machine on your own computer, with your licensed
voices installed inside it. This project sends NVDA's text into that virtual
machine, and the voice speaks there. You can choose whether bridge speech plays
through XP's sound output, NVDA's selected output device, or both. For example,
you can select AT&T Natural Voices Mike in NVDA on
Windows 11 while Mike is really running in XP.

Everything stays on your computer. XP needs no internet connection, no network
adapter, and no copy of NVDA inside it. **No voices are included** with this
project; you supply your own licensed voices.

Wondering why this exists at all, when Windows can host speech engines by
itself? [RATIONALE.md](RATIONALE.md) answers that with specifics, including the
cases where you should not use a bridge.

This project was made with the help of AI.
[Report a problem or ask a question](https://github.com/AngelsClan/angel-legacy-voice-bridge/issues).

## Current status: please read before installing

**This is a development build (0.1.2-dev4) and the public release is on hold.**

A serious NVDA freeze was reported against version 0.1.1 and the exact cause is
still unconfirmed. Several real defects have been found and fixed since, but
none of them has been proven to be *the* cause.

So, for now:

- Keep a dependable local synthesizer, such as eSpeak NG or a OneCore voice,
  selected as your normal NVDA speech.
- Leave the bridge disabled unless you are deliberately testing it.
- Do not try to reproduce a freeze if losing speech would leave you stranded.

Fixes and diagnostics in this build are not a promise that the problem is gone.
When the hold is lifted, this section will say so.

## Contents

- [How it works](#how-it-works)
- [What you need](#what-you-need)
- [Installation](#installation)
  - [Step 1: Add a virtual serial port to the VM](#step-1-add-a-virtual-serial-port-to-the-vm)
  - [Step 2: Put the helper program in XP and run it](#step-2-put-the-helper-program-in-xp-and-run-it)
  - [Step 3: Install the NVDA add-on](#step-3-install-the-nvda-add-on)
  - [Step 4: Connect and hear your first test](#step-4-connect-and-hear-your-first-test)
  - [Step 5: Choose how you want to use the voices](#step-5-choose-how-you-want-to-use-the-voices)
- [Everyday use](#everyday-use)
- [Every setting explained](#every-setting-explained)
- [What happens when the voice fails](#what-happens-when-the-voice-fails)
- [Troubleshooting](#troubleshooting)
- [Removing it](#removing-it)
- [Other virtual machines and emulators: contributions welcome](#other-virtual-machines-and-emulators-contributions-welcome)
- [Known limits](#known-limits)
- [Privacy and security](#privacy-and-security)
- [Building from source](#building-from-source)
- [License and references](#license-and-references)

## How it works

There are two programs, one on each side:

```
Your Windows computer                 Windows XP virtual machine
---------------------                 --------------------------
NVDA
  + Angel Legacy Voice Bridge  ---->  AngelLegacyVoiceBridge.exe
    (NVDA add-on)                       (small console program)
                                              |
       a local named pipe,                    v
       pretending to be a                   SAPI 5 voice
       serial cable                           |
                                              v
                                       XP's sound output  ))) by default
```

The add-on sends text over a virtual serial port that
your virtualization software presents to the host as a Windows named pipe. The
helper inside XP hands that text to the SAPI 5 voice, and the voice plays
through the virtual machine's own sound card by default. With **Send to NVDA**
or **Both**, the helper also sends the rendered PCM back over that serial port.
Other XP sounds stay on XP's sound card. Nothing is sent over a network,
and the add-on never has to know a password for XP.

This means one thing worth remembering: **a successful connection does not
prove you will hear anything.** On the default XP route, XP's volume, sound
device and virtual machine audio settings matter. On the NVDA route, check
NVDA's selected output device. Both routes need a working voice in XP.

## What you need

- **A current Windows computer running NVDA.** This add-on is built for
  NVDA 2026.1 and later, and is declared compatible through NVDA 2026.2.
- **A 32-bit Windows XP virtual machine** that already works, with sound.
  It does not need networking, and it should not have it.
- **Your own licensed SAPI 5 voices installed inside XP.** SAPI 4-only voices
  are not supported. No voice data or license is distributed with this project.
- **VirtualBox.** VirtualBox is the only platform tested so far. See
  [Other virtual machines and emulators](#other-virtual-machines-and-emulators-contributions-welcome)
  if you would like to help change that.
- **A free COM port in XP** (COM1 is used by default) for the virtual serial
  connection described below.

Tested here: Windows XP 5.1.2600 under VirtualBox 7.2.18, with Microsoft Sam,
AT&T DTNV 1.4 Mike16 and Crystal16, and 26 Panthera Classic Mac and Alex voices.
The exact XP service pack was not recorded, and SP1, SP2 and SP3 have not each
been separately qualified.

## Installation

You install two things in two different places, plus one virtual hardware
change. Take them in order; each step ends with something you can check.

The release page provides:

| File | Where it goes |
| --- | --- |
| `AngelLegacyVoiceBridge-<version>.nvda-addon` | Your modern Windows, installed into NVDA |
| `AngelLegacyVoiceBridge.exe` (from the XP Bridge folder) | Inside the XP virtual machine |
| `AngelLegacyVoiceBridge-<version>-source.zip` | Only if you want to read or build the source |

Nothing installs itself. The add-on is never installed inside XP, and the XP
helper is never installed into NVDA.

### Step 1: Add a virtual serial port to the VM

This is a one-time change to the virtual machine's hardware, so XP must be shut
down first.

1. Inside XP, save your work and shut Windows XP down normally. Do not use
   "Save the machine state": virtual hardware must not be changed on a saved VM.
2. In VirtualBox Manager, select the XP machine and choose **Settings**, then
   **Serial Ports**.
3. On the **Port 1** tab, set:

   | Field | Value |
   | --- | --- |
   | Enable Serial Port | checked |
   | Port Number | COM1 |
   | I/O APIC / IRQ | 4 |
   | I/O Port (address) | 0x3F8 |
   | Port Mode | Host Pipe |
   | Connect to existing pipe/socket | **unchecked** |
   | Path/Address | `\\.\pipe\AngelLegacySpeech-XP` |

4. Click OK.

Leaving "Connect to existing pipe" unchecked is important: it tells VirtualBox
to *create* the pipe. The add-on is the side that connects to it.

If you prefer the command line, with the VM powered off (substitute your own
machine name for `Windows XP`):

```powershell
& 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe' modifyvm 'Windows XP' `
    --uart1 0x3F8 4 `
    --uart-mode1 server '\\.\pipe\AngelLegacySpeech-XP' `
    --uart-type1 16550A
```

To confirm it afterwards:

```powershell
& 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe' showvminfo 'Windows XP' | Select-String 'UART'
```

You should see UART 1 enabled at I/O base `0x03f8`, IRQ 4, in server mode on
your pipe path.

**About the pipe name.** `\\.\pipe\AngelLegacySpeech-XP` is a generic default,
not tied to any particular computer. You may choose a different name as long as
it begins with `\\.\pipe\AngelLegacySpeech-`; a unique ending is useful if you
run more than one XP machine. Whatever you choose, type exactly the same name
into the add-on. Only one program at a time can use a pipe.

Now start XP normally, with its window visible, and check that its ordinary
sounds still play.

### Step 2: Put the helper program in XP and run it

1. Copy `AngelLegacyVoiceBridge.exe` into XP. Any folder will do;
   `C:\AngelLegacyVoiceBridge` is a good choice. Ways to copy it in:
   - VirtualBox Guest Additions (shared folders or drag and drop), or
   - an ISO image attached to the VM, or
   - any other offline transfer you already use.

   Guest Additions are convenient but are not part of the speech connection. Do
   not switch XP's networking on just to copy a file.
2. Run it. In XP, press Windows+R, type the full path, and press Enter:

   ```text
   C:\AngelLegacyVoiceBridge\AngelLegacyVoiceBridge.exe
   ```

3. A console window opens and prints:

   ```text
   Angel Legacy Voice Bridge 0.1.2-dev3. Waiting for the host. Ctrl+C exits.
   ```

   Leave it open and Alt+Tab away, or minimize it. Control+C closes it. Later,
   when NVDA connects, it also prints `Bridge connected. Audio plays through
   the XP default output.`

That is all XP needs. There is no driver to install, no service, and no reboot.
COM1 is the default; if you deliberately configured a different port, start the
helper with `--com2`, `--com3` or `--com4`. Those are the only arguments it
accepts:

```text
Usage: AngelLegacyVoiceBridge.exe [--com1 | --com2 | --com3 | --com4]
```

If instead it prints `Cannot open configured COM port. Check VM serial settings
and other bridge instances.`, the port is missing or something else already has
it. `No SAPI 5 voices registered yet; waiting for voice installation and idle
scan.` means XP has no usable voice yet, so install one inside XP first.

If you start a second copy it will fail, because the first one already owns the
COM port. That is expected.

**Starting it automatically.** The program does not add a shortcut or a startup
entry for you. If you want it to run after XP logs in, put a shortcut to the EXE
in that XP user's Start Menu > Programs > Startup folder. It needs a logged-in
user with a working audio session, which is exactly why it is an ordinary
console program and not a Windows service.

### Step 3: Install the NVDA add-on

Do this on your modern Windows, not in XP.

1. Make sure a local synthesizer you trust is selected in NVDA first.
2. Open `AngelLegacyVoiceBridge-<version>.nvda-addon` and approve NVDA's
   installation prompt.
3. Restart NVDA **when you are ready**. Nothing restarts NVDA for you, and the
   add-on does not take effect until that restart.

Your existing NVDA settings are kept when you replace the add-on with a newer
build. The add-on is not available on secure login desktops.

### Step 4: Connect and hear your first test

With XP running and its helper console open:

1. Open the NVDA menu, **Preferences**, **Settings**, and select the
   **Legacy Voice Bridge** category.
2. Check the pipe name in **Local bridge pipe**. If you kept the default name
   there and exactly one bridge pipe is running under a different name, the
   add-on adopts that one for you. Otherwise press **Detect running VM pipes**
   and choose yours. If nothing is found it says: "No running bridge pipes
   found. Start the configured VM, or enter its pipe manually."
3. Check **Enable bridge now**, or press the **Connect** button. The
   **Connection status** field should end up reading something like
   "Connected; audio plays through XP; 14 voices; output: 22050 Hz, 16-bit,
   1 channel(s)". The voice list fills in by itself; you do not need to press
   Refresh.
4. Choose one of your XP voices in **Mirror/test voice**.
5. Leave **Where XP bridge speech plays** on **XP speakers** for the first
   test. Press **Test speech through XP** and listen for the fixed test phrase.
   With the matching updated XP helper, you can then choose **Send to NVDA**
   or **Both XP and NVDA** and test again. An older helper keeps audio on XP
   and reports that the requested route is unsupported.

If you hear it, the bridge works. If the status says connected but you hear
nothing, go to [Troubleshooting](#troubleshooting) and check the chosen output.

### Step 5: Choose how you want to use the voices

There are two ways to use the bridge, and they suit different people.

**A. Mirroring — keep your normal voice and hear XP as well.**

Check **Mirror local NVDA speech to XP**, then press OK. NVDA keeps speaking
with your usual synthesizer, and the same speech is also sent to XP. Two voices
speak at once, slightly out of step with each other. This is the safe way to
try the bridge, because your normal speech never depends on it. Do not select
NVDA's "No speech" synthesizer for this; mirroring is designed to accompany a
working local voice, not to replace it.

**B. As your synthesizer — choose XP, NVDA, or both as the output.**

Press NVDA+Control+S to open Select Synthesizer, and choose **Angel Legacy
Voice Bridge**. Then set the voice, rate, pitch and volume
in NVDA's ordinary Speech settings, exactly as you would for any other
synthesizer. Mirroring switches itself off while the bridge is your
synthesizer, so you never hear the same words twice.

Finally, save your NVDA configuration with NVDA+Control+C (or let NVDA save on
exit) if you want these choices remembered.

### Updating an existing installation

Replace **both** parts. The two halves are released together and are meant to
match, even when the version number has not changed:

1. In NVDA, switch to a local synthesizer and press Disconnect.
2. In XP, press Control+C in the helper console, replace
   `AngelLegacyVoiceBridge.exe` with the new one, and start it again. XP does
   not need to reboot.
3. Install the new `.nvda-addon` and restart NVDA when it is safe to do so.

Your saved settings are kept. Building the source does not update or restart a
running NVDA.

## Everyday use

**Starting up.** The helper in XP has to be running before NVDA can connect.
**Connect automatically when NVDA starts** makes NVDA reconnect at startup, but
it cannot boot the virtual machine or launch the helper for you.

**Stopping the bridge quickly.** Press **NVDA+Shift+F11**. NVDA answers "Bridge
disabled. Local speech only." That one command disables bridge speech,
mirroring, automatic startup and any retries, and keeps your current local
synthesizer (or switches to eSpeak if the bridge itself was selected). The same
thing happens if you uncheck **Enable bridge now** or press **Disconnect**. You
can reassign the shortcut in NVDA's Input Gestures dialog, under the **Angel
Legacy Voice Bridge** category.

**Changing the sound quality on the fly.** With the bridge selected as your
synthesizer, press NVDA+Control+Right Arrow until you reach **XP output
format**, then NVDA+Control+Up or Down Arrow to change it. The next thing
spoken uses the new setting; nothing has to reconnect or restart. **Voice
default is recommended** and usually sounds best. The other choices make XP's
SAPI convert the voice's own output, which can add a harsh or metallic edge:
measured on XP, converting the 22.05 kHz Mac voices to 44.1 or 48 kHz added
false high frequencies only 21 to 27 dB below the voice itself.

**Installing new voices in XP.** You do not have to restart the helper or
reconnect. NVDA asks XP to re-examine its SAPI 5 registrations about every five
seconds while speech is idle, and new voices appear in the list on their own. A
voice installer may still ask XP to reboot for its own reasons. Three details
are worth knowing:

- A scan that XP could not finish is not used at all; the previous list is kept
  and the next attempt waits an extra 25 seconds.
- If a scan gets no answer within four seconds while the connection otherwise
  looks alive, scanning is switched off until you reconnect. Your existing
  voices keep working; press Disconnect and Connect again to resume scanning.
- A helper run tracks up to 128 different voices, and if XP ever reports more
  than 128 at once the list is left unchanged rather than truncated. Restart
  the helper in XP if you reach that.

**Volume.** Prefer a higher bridge volume and turn the sound down elsewhere: a
low bridge volume, such as 20, throws away detail in the voice. Note that
volume 0 is not a reliable mute. Some engines, AT&T Natural Voices among them,
keep speaking at roughly 18% of their normal loudness at volume zero, and they
do the same in plain XP without this project. To stop bridge speech, use
Disconnect or NVDA+Shift+F11.

## Every setting explained

These are in NVDA menu > Preferences > Settings > **Legacy Voice Bridge**.

| Setting or button | What it does |
| --- | --- |
| Enable bridge now | The master switch for the current session. Checking it connects and discovers voices; unchecking it stops bridge speech, mirroring and retries at once. Off by default. |
| Connect automatically when NVDA starts | Reconnects at the next NVDA start, if the master switch is on. It does not boot XP or start the helper. Turning it off does not stop speech that is running now. Off by default. |
| Local bridge pipe | The exact pipe name your VM creates. No IP address and no guest password are involved. Switch to a local synthesizer before you change this. |
| Detect running VM pipes | Lists the matching pipes that exist right now, so you can pick one. It does not start, change or inspect a virtual machine. It can only find a pipe that is already configured. |
| Mirror local NVDA speech to XP | Sends your speech to XP as well as to your normal synthesizer. Turning it off cancels mirrored speech immediately. The two voices can overlap and drift apart in timing. Off by default. |
| Where XP speech plays | XP speakers (default), Send to NVDA, or Both. Applies to bridge speech and the Test button. NVDA and Both require the matching updated XP helper. Other XP sounds remain on XP's sound card. |
| Mirror/test voice | Which XP voice mirroring and the Test button use. It is saved by the voice's SAPI token ID, so it survives changes in list order. |
| Mirror/test rate (0–100) | 50 by default, which is SAPI's normal speed. Engines interpret speed differently. |
| Mirror/test volume (0–100) | 100 by default. Independent of the Windows and VM mixers. Zero silences most voices but not all of them (see above). |
| Set XP playback mixer to 100% when adjusting bridge volume | Optional, off by default. Asks XP to put its preferred output's master and Wave levels at maximum when you connect, test, apply or change the bridge volume. Bridge volume still controls the speech. It affects other XP sounds, never unmutes anything, does not touch recording levels or your host's volume, and does not put the old levels back when you turn it off. The status line reports whether XP supported it fully, partly or not at all. |
| XP output format | Five choices, listed below this table. All bridge speech is 16-bit mono. Apply affects later speech; Test uses the current choice. A higher rate cannot add detail that an old voice never had, and a fixed rate makes XP convert the audio, which can sound harsher. The status line shows what SAPI actually reported once speech starts. An unsupported format can fail and trigger fallback. |
| Restore local eSpeak if bridge speech disconnects | Brings local speech back after a failure is detected, announcing "Legacy bridge unavailable. Switched to local eSpeak." On by default. Detection takes a few seconds; it is not instant. |
| Automatically return to the bridge after recovery | Off by default. After an automatic fallback to eSpeak, go back to the bridge, but only once the voice has proved it can still speak. See [What happens when the voice fails](#what-happens-when-the-voice-fails). |
| Write text-free diagnostics log | On by default while the release is on hold. Records timings, queue counts and error numbers, never the words you hear, in `angelLegacyVoiceBridge-diagnostics.log` in your NVDA configuration folder. Takes effect as soon as you press OK or Apply, with no restart. If you turn it off before anything is written, no log file is created at all. Existing log files are never deleted for you. |
| Connection status | Read-only. Reports the connection, the number of voices found and the audio format XP reported, and the XP mixer result when that option is on. |
| Connect / Cancel connection / Disconnect | One button that changes with the state. Connect applies the pipe name immediately and starts retrying. Cancel connection stops a connection attempt; Disconnect ends an established one. Both stop mirroring, automatic startup and retries, and keep local speech working. |
| Refresh voices and status | Updates what is displayed. It is a convenience: the list already updates by itself. |
| Test speech through XP | Speaks one fixed sentence using the mirror/test voice, rate and volume. Use it while a local synthesizer is selected. Mirroring pauses during the test so that settings announcements do not pile up behind it. |
| Stop test speech | Only available while test speech is playing or queued. It cancels **the test only**, not the bridge, and mirroring may resume afterwards. It never mutes local NVDA. To stop everything, use Disconnect or NVDA+Shift+F11. |
| About | A short summary of what the add-on does, where the audio comes from, and how recovery works. |

The five **XP output format** choices, exactly as NVDA reads them out:

| Choice | When to use it |
| --- | --- |
| Voice default (recommended, best quality) | Almost always. The voice's own rate, with no conversion. |
| 16 kHz, converted by XP (lower quality) | Rarely; only if a device rejects everything else. |
| 22.05 kHz, converted by XP unless the voice already uses it | Free of conversion for voices that are natively 22.05 kHz. |
| 44.1 kHz, converted by XP (can sound harsher) | If a sound device insists on this rate. |
| 48 kHz, converted by XP (can sound harsher) | Likewise. |

A few notes that apply to the whole panel:

- Enable, Mirror, Connect, Test and Disconnect take effect immediately, even if
  you close the dialog with Cancel afterwards. Everything else applies on
  Apply or OK.
- The bridge synthesizer's own voice, rate, pitch and volume are separate from
  the mirror/test controls above. Pitch runs 0 to 100 and maps to SAPI's XML
  pitch of -10 to +10. Not every legacy engine honours pitch or spelling
  identically.
- Use one pipe across all your NVDA profiles for now. Switching transports
  automatically when a profile changes has not been qualified.

### Turning on automatic return

Automatic return is off by default. Turn it on in either of these ways:

- NVDA menu > Preferences > Settings > **Legacy Voice Bridge**, check
  **Automatically return to the bridge after recovery**, then press OK; or
- the command **Turn automatic return to the bridge after recovery on or off**.
  It has no key assigned by default. Give it one in NVDA menu > Preferences >
  Input gestures, in the **Angel Legacy Voice Bridge** category. It announces
  "Automatic return to the bridge on" or "off" when you press it, and turning
  it off also cancels any return that was pending.

**Restore local eSpeak if bridge speech disconnects** must also be on,
since automatic return only ever follows that automatic fallback.

## What happens when the voice fails

If the bridge is your synthesizer and the connection or the voice engine fails,
NVDA does not go silent: **Restore local eSpeak if bridge speech disconnects**
is on by default, and once the failure is detected NVDA says "Legacy bridge
unavailable. Switched to local eSpeak." and carries on in eSpeak. In mirror
mode your local voice was speaking all along anyway.
Anything that was queued when the failure happened is thrown away rather than
replayed later.

By default you then choose for yourself when to go back to the bridge.

**If you turned automatic return on**, the add-on does not trust appearances. A
pipe that reconnects, or a voice that still appears in the list, proves
nothing; a crashed engine can leave both looking perfectly healthy. Instead,
while eSpeak is speaking normally, it sends a short fixed check phrase to the
original voice. A capable XP helper captures and discards the PCM on every
route, so the phrase is never played. The check needs a real final bookmark
and non-silent audio before it can return. An older helper cannot run this
check and automatic return stops; local eSpeak remains selected.

- The first check is after 5 seconds, then the wait doubles up to one minute.
  Any single check that has not produced its bookmark within 15 seconds counts
  as a failure, and the next one is scheduled.
- Checks stop after 12 attempts or 15 minutes, and NVDA says
  "Bridge voice did not recover. Staying on eSpeak."
- When a check succeeds, your bridge voice, rate, volume and pitch are
  restored, and NVDA says "Bridge voice recovered." through that voice.
- If eSpeak is in the middle of a sentence when the check succeeds, the return
  waits up to 8 seconds for it to finish before interrupting.
- At most three automatic returns happen in ten minutes, and each recent return
  makes the first wait longer (5, then 10, then 20 seconds). After that NVDA
  says "Bridge failed repeatedly. Staying on eSpeak." and leaves the choice to
  you.
- Changing synthesizer or local voice yourself, switching NVDA configuration
  profile, disabling the bridge, or turning the option off all cancel a pending
  return. A return that is pending is not remembered across an NVDA restart.

**Will you hear the check phrase?** Only on voices that ignore SAPI's volume
setting. Measured on the test XP machine, the check was completely silent for
Microsoft Sam and for all 26 Panthera (Classic Mac and Alex) voices, while
AT&T Natural Voices Mike16 and Crystal16 stayed at about 18% of their normal
peak, so with those two you will briefly hear it from the VM. Other vendors
have not been measured.

A successful check proves the engine rendered that one phrase. It cannot
promise that the next paragraph will not fail.

## Troubleshooting

**The voice list is empty, or it will not connect.**
Check that the helper console is still open in XP, that COM1 exists in XP's
Device Manager, that the pipe name in NVDA matches the one in the VM settings
exactly, and that no other copy of the helper or a test script already owns the
pipe. XP's own Speech control panel is a good way to confirm the voices work
inside XP at all. NVDA's log (NVDA menu > Tools > View log) and the helper
console both report what went wrong.

**NVDA says "Connect and test the XP helper in Legacy Voice Bridge settings
first."**
You tried to select the bridge as your synthesizer before it had a working
connection and a voice list. Start XP and its helper, connect in the Legacy
Voice Bridge settings, confirm the test speech, and then select the
synthesizer.

**It says connected, but I hear nothing.**
First check **Where XP speech plays**. On XP speakers, check XP's default
playback device, volume and VM audio output. On Send to NVDA, check NVDA's
selected output device and the connection status for an unsupported route.
Both routes need a SAPI 5 voice that renders inside XP; try another voice.

**A voice is silent for a moment right after I switch to it, then fine.**
That is the voice engine starting up, not the bridge. It was seen with the Mac
Alex voice packs, whose engine sometimes answered its very first utterance with
a single silent frame and no error at all. Those voice packs now render such an
utterance a second time.

**The sound is harsh, metallic or hissy.**
Set **XP output format** to Voice default. A fixed sample rate makes XP convert
the voice's own output and that conversion is audible. The format is shared by
every bridge voice, so if one voice prefers a different setting, change it from
the synthesizer settings ring as you switch voices. Also check your bridge
volume: a low volume such as 20 costs real detail.

**Speech is slow, or it gets stuck.**
Select a local synthesizer, stop any test speech, close the helper in XP with
Control+C, start it again and press Connect. Virtual machine CPU load, the VM's
audio driver and slow legacy engines all affect responsiveness. Never turn XP's
networking on as a workaround, and never run the developer integration tests
while the bridge is your only speech.

**NVDA froze.**
Use your emergency speech, keep the diagnostics log, and please
[open an issue](https://github.com/AngelsClan/angel-legacy-voice-bridge/issues)
describing what was being read at the time. Include your NVDA, VirtualBox and
XP versions, the 32-bit SAPI 5 engine's name, the connection status and the
output format you had selected. Do not attach anything containing private
speech text or voice licenses; the diagnostics log deliberately contains
neither.

Operator-level details, maintenance commands and the disable-only tool are in
[OPERATIONS.md](OPERATIONS.md).

## Removing it

1. Select a local synthesizer, and turn off mirroring and automatic connection.
2. Remove the add-on in NVDA's Add-on Store or add-ons manager, and restart
   NVDA when it suits you.
3. In XP, press Control+C in the helper console and delete its folder.
4. Optionally, with the VM powered off, disable the serial port again in
   VirtualBox Settings.

Removing this project never requires deleting your virtual machine or your
voices.

## Other virtual machines and emulators: contributions welcome

VirtualBox is the only platform that has actually been tested, so it is the
only one currently supported. That is a matter of testing effort, not of
design: the transport is deliberately plain. It is one local Windows named pipe
carrying short tab-separated ASCII lines, described in
[PROTOCOL.md](PROTOCOL.md). Anything that can present a guest serial port to
the Windows host as a named pipe ought to be able to run this bridge.

**If you would like to add or qualify support for another platform, please open
a pull request. We would be happy to review it, and to test it ourselves where
we have the platform available.** Issues describing what worked or failed are
just as welcome as code. Platforms we would like to see covered include:

- VMware Workstation, VMware Player and VMware Fusion
- QEMU, including QEMU/KVM builds for Windows
- Microsoft Hyper-V (its COM ports can be pointed at a named pipe with
  `Set-VMComPort`)
- 86Box and PCem, which many people use for genuinely old Windows installations
- Microsoft Virtual PC
- Any other emulator or hypervisor with a serial port and working sound

A different **guest** is also a fair contribution: Windows 98, Windows 2000 or
32-bit Vista all have SAPI 5 voices of their own, and the helper only needs a
COM port and an audio session.

Because NVDA itself runs on Windows, the hypervisor has to be on the same
Windows computer today. Adding a different transport, such as a Unix domain
socket or a loopback socket, would open the door to other hosts. That is a
welcome idea but a larger change: the project deliberately has no network
listener, so such a contribution needs a careful look at what it exposes, and
it must stay off by default.

What a platform port should demonstrate before it is called supported:

1. The pipe is created by the hypervisor and the add-on can connect to it.
2. Voices are discovered and speak audibly through the guest's sound output.
3. Cancellation and pausing behave, including interrupting long speech.
4. Disconnecting, reconnecting and the eSpeak fallback all work.
5. The guest and hypervisor versions you tested are written down.

### VMware notes to start from

These have not been tested here; they are a starting point, not a recipe.
With the VM powered off, add a Serial Port, choose "Use named pipe", enter the
same pipe path you configure in the add-on, set **this end as the server** and
**the other end as an application**, and connect the device at power on. Match
the guest's COM number to the helper's `--com` option. If your version of
Workstation offers "Yield CPU on poll", turning it on may help. Keep guest
networking off, and do not use a remote pipe or expose this unencrypted local
protocol to a network. VMware's own user interface naming varies between
versions, so check its serial-port documentation for the version you have.

## Known limits

- The bridge carries SAPI 5 requests. It cannot make an unsupported or
  unlicensed voice work, and it does not support SAPI 4-only engines.
- It is not a system-wide SAPI 5 voice, a Windows service or a network service.
  Only NVDA speaks through it.
- XP needs a logged-in user with a working audio session. That is why the
  helper is a console program you can see and close.
- An English-only voice still cannot pronounce every language or emoji. The
  bridge does not strip non-English text; voices that support it must receive
  it.
- Limits per utterance are 16,000 characters and 256 sequence items, with up to
  64 utterances queued. Larger requests fail cleanly instead of growing without
  bound.
- Output-format conversion is not audio restoration. A 16 kHz voice is still a
  16 kHz voice when rendered at 48 kHz, and no setting here repairs a poor
  virtual audio driver.
- Mirroring follows NVDA's queued speech. It is not a recording of your local
  voice and it does not reproduce NVDA's interruption timing exactly.
- Pronunciation, spelling behaviour, pitch handling, long reading and real
  perceived responsiveness are all still matters for user testing.
- Timings such as the retry interval, the roughly four-second failure detection
  and the guest's six-second purge are safety limits, not promised response
  times. A busy computer or virtual machine can stretch them.
- Running XP without a visible window works: at the VM's next normal start use
  VirtualBox's **Start with detachable GUI** (`VBoxManage startvm 'Windows XP'
  --type separate`), then Machine > Detach GUI to hide it, and Show in
  VirtualBox Manager to get it back. XP keeps running and does not reboot.
  Detached and headless audio have not been qualified here, though, so the
  listening tests were all done with a visible window.

## Privacy and security

- Everything is local. There is no account, no telemetry, no online voice
  service and no automatic updater.
- The named pipe is **not encrypted and is not a security boundary** against
  other software already running on your computer as you. Trust the virtual
  machine, the helper and anything else using that pipe.
- Your text goes into XP and into the voice engine on purpose. That is the
  whole point of the project.
- This project's own logs never contain spoken text, window titles, document
  contents or credentials. The diagnostics log holds timings, counters, error
  numbers, code locations and, when speech fails, a "text shape": counts of
  digits, letters, spaces, punctuation, non-ASCII characters, `[[` and `]]`
  pairs, words and the longest word's length, never the words themselves. The
  XP helper keeps a similar text-free log, `bridge-sapi-errors.log`, beside its
  own executable; it holds a timestamp, a numeric stage, an error number, a
  voice slot and a format number per line, and is emptied when it reaches 1 MiB.
  NVDA's own log settings and other add-ons may behave differently.
- Writing diagnostics happens on a separate thread with a bounded queue, so a
  slow disk drops records instead of delaying your speech. The current log and
  two rotated copies come to roughly 3 MiB in total. Nothing is uploaded.
- A native crash, an abrupt process kill or a full disk can still stop evidence
  from being recorded. This is a diagnostic aid, not a guaranteed crash
  recorder, and it cannot rescue speech while NVDA itself is hung.
- Bridge operation is disabled in NVDA's secure mode, and the add-on should not
  be copied into secure login settings.
- Keep XP offline, and keep a backup of the virtual machine.

## Building from source

You need Python 3.13, the Visual Studio 2022 C++ **x86** build tools and a
Windows 10 SDK. No internet access and no WSL are needed once those are
installed.

```powershell
python -m unittest discover -s tests -v
python build.py
```

Output lands under `dist`, in separate folders for the helper and the add-on,
with documentation, license and SHA-256 sidecar files. The add-on contains its
Python source in readable form, and the separate source ZIP contains the XP
helper's C++ source and the build script, so no part of this is an opaque
binary blob.

Optional checks:

```powershell
python tools/ui_smoke.py          # hidden real-widget check; needs wxPython
python tools/smoke.py             # against a running helper, no speech
python tools/smoke.py --speak     # audible phrase
python tools/integration.py       # framing, all voices, cancellation (muted)
python tools/quality_probe.py     # output formats and utterance assembly
```

Add `--pipe '\\.\pipe\AngelLegacySpeech-your-name'` if you did not use the
default pipe name. Run these with the bridge **disconnected** in NVDA, and
never while the bridge is your only speech. None of them launches, installs
over or restarts your running NVDA.

`python tools/mixer_probe.py --allow-volume-change` changes XP's playback
levels, so only run it deliberately. The live voice-registration probe uses a
disposable test token; it is not for installing or removing real voices.

The XP helper is built without the modern C runtime and with the compiler's
stack cookie disabled so that it runs on XP. Buffers have explicit bounds, but
that is a legacy compatibility trade-off: do not expose this helper to
untrusted input or strangers.

[PROTOCOL.md](PROTOCOL.md) describes the wire protocol and state machine.
[TEST-REPORT.md](TEST-REPORT.md) records what has actually been tested and what
has not. [OPERATIONS.md](OPERATIONS.md) covers maintenance and automation.
[PUBLICATION.md](PUBLICATION.md) is the checklist that must be followed before
anything is published.

## License and references

Copyright 2026 Angels Clan. This project's original code is licensed under the
GNU General Public License, version 2 or, at your option, any later version.
See [LICENSE](LICENSE). NVDA, VirtualBox, VMware and the voice engines all have
their own licenses, and no voice data is redistributed here.

- [VirtualBox serial ports](https://docs.oracle.com/en/virtualization/virtualbox/6.0/user/serialports.html)
- [VirtualBox separate/detachable mode](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/remotevm.html)
- [NVDA user guide](https://download.nvaccess.org/documentation/userGuide.html)
- [NVDA synthesizer API source](https://github.com/nvaccess/nvda/blob/master/source/synthDriverHandler.py)
- [Microsoft SAPI speech flags](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms720892(v=vs.85))
