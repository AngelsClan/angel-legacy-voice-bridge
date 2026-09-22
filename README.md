# Angel Legacy Voice Bridge

Development 0.1.2-dev2 — an offline bridge from current Windows NVDA to licensed
SAPI 5 voices installed in a 32-bit Windows XP virtual machine.

**Release hold:** a serious NVDA freeze has been reported with 0.1.1. The exact
cause remains unconfirmed. Do not rely on the bridge for primary speech or try
to reproduce the problem if losing speech would leave you without assistance.
Keep a dependable local synthesizer selected and the bridge disabled. Development
diagnostics are not a claim that this accessibility-critical problem is fixed.

[Report a problem](https://github.com/AngelsClan/angel-legacy-voice-bridge/issues)

This project was made with the help of AI.

For example, select AT&T Natural Voices Mike in modern NVDA while Mike actually
runs in XP. The VM's speakers play the speech. XP does not need NVDA, an internet
connection, a network adapter, or a microphone. Voices are not included.

This is an NVDA add-on plus a small XP console program, not a Windows service or
a system-wide SAPI voice. Start with mirroring/local speech available. It is a
first beta, not yet a replacement for a dependable primary screen reader.

## What is included

### Speech recovery after an engine failure

The September 22 candidate fixes a confirmed fallback defect: changing to eSpeak
alone left NVDA waiting for indexes from the failed voice. The add-on now cancels
the abandoned speech queue before switching. Pending old announcements are
discarded, not replayed or falsely marked spoken. New local speech can proceed.
The same reset applies to automatic return and disabling the active bridge.

This fix requires the updated **add-on**. The already updated XP helper does not
need replacing again. Install only at a safe restart time; development tools must
not restart the user's active NVDA. Failure records include numeric request,
length, queue, voice-slot and HRESULT data, never utterance text. Backlog records
also distinguish bridge-selected from local-synth speech.

A separate asynchronous Pipe Organ engine error remains under investigation.
Passing recovery tests does not establish its original cause or lift the release
hold. Keep dependable local speech available.

### Switching voices after an installation

The updated XP helper resolves voice registrations afresh when switching voices.
It also recovers once from SAPI's specific "registry key marked for deletion"
error when an installer replaces the voice already selected. This error could
previously force a fallback to eSpeak even though the voice appeared in the list.
Other failures still fall back to local speech; accepted speech is never replayed.
This repair is in the XP helper and works with the existing protocol-2 add-on.
Stop only the helper, replace its executable and start it again; no XP reboot or
active NVDA restart is needed for this repair. The optional updated add-on adds
more detailed error logging and should be installed only at a safe restart time.

The helper keeps a bounded, approximately 1 MiB `bridge-sapi-errors.log` next to
its executable, containing numeric error codes, operation stages and voice slots,
not spoken text. A logged registry error may have been recovered successfully;
consult the final request result rather than treating every record as a crash.
This targeted repair does not resolve or lift the separate freeze investigation.

### Skipped text and voice-engine recovery

This development update requires replacing the XP helper as well as the add-on
to obtain all improvements. The helper now checks actual SAPI completion without
blocking, in addition to listening for completion events. It preserves bookmarks
before reporting completion, including when a voice skips unsupported text.
Asynchronous engine errors trigger the existing connection-failure/local-speech
handling instead of being reported as successful silent speech. Keep automatic
local fallback enabled. No timer guesses when a slow voice should have finished.

An English-only voice still cannot pronounce every language or emoji. The bridge
does not delete non-English text; voices that support it must still receive it.
Microsoft Sam and installed third-party voices passed the documented protocol
tests, but the reported intermittent silence was not reproduced. These changes
do not lift the release hold above. Volume zero is not reliable mute for every
legacy voice; use Disconnect or Disable bridge now to stop bridge speech.

### Development diagnostics and privacy

The development add-on writes `angelLegacyVoiceBridge-diagnostics.log` in the
NVDA user-configuration directory. The logger runs even when bridge speech is
disabled, so local-speech operation can be compared without connecting to XP.
It records lifecycle events, numeric backlog/progress counters, and code
locations when NVDA's main thread fails to process a heartbeat for three seconds.
It does **not** record speech text, window titles, document contents, frame locals,
passwords, or full source paths. Heartbeats are coalesced; repeated stall reports
are limited to one every fifteen seconds.
Code locations can include module/function names of other installed add-ons.
This labelled diagnostic build enables logging by default; a public release
needs an explicit diagnostics preference before the release hold is lifted.

Disk writes happen on a separate daemon thread with a bounded 512-record queue.
A slow disk drops diagnostic records instead of blocking speech. Idle backlog
samples are reduced to once a minute. Transient write/rotation failures retry
on later records and NVDA's normal log warns that evidence may be incomplete.
The current log
and two rotated copies use approximately 3 MiB total. This works with packaged
NVDA, which does not include Python's `logging.handlers` module. No log uploads
are automatic. A native call holding Python's GIL, abrupt process termination,
or an unwritable disk can still prevent evidence from being recorded; this is
not a guaranteed crash recorder or an automatic recovery mechanism. Fallback and
emergency keyboard commands also cannot be guaranteed while NVDA itself is hung.

Installing an updated add-on requires an NVDA restart at a safe time. Merely
building this source does not update or restart an already running NVDA instance.

- A selectable NVDA synthesizer with voice, rate, volume and pitch settings.
- Optional mirroring: keep your regular NVDA voice and hear XP too.
- Accessible NVDA settings for connection, voice discovery and a speech test.
- A state-aware Connect/Disconnect button that stops speech and retries.
- An optional XP playback-mixer adjustment and local disable-only maintenance tool.
- Automatic voice-list updates, running-pipe discovery and XP output formats.
- Automatic connection retries, cancellation, pause/resume and completion/index
  notifications. Old speech is discarded on disconnect rather than replayed.
- Local eSpeak fallback, optional automatic return after recovery, and an
  emergency **NVDA+Shift+F11** shortcut.
- An XP helper that lists the installed SAPI 5 voices and speaks through XP's
  default audio device. Close it with Control+C. No driver installation in XP.
- Readable source, build script, unit tests and opt-in live integration tests.

## Requirements and tested compatibility

- A current Windows NVDA host. This package targets NVDA 2026.1 and later, with
  compatibility declared through 2026.2. The UI/user listening test is still
  required; see [TEST-REPORT.md](TEST-REPORT.md) for the precise qualification.
- A working XP **32-bit** VM and installed/licensed **SAPI 5** voices. SAPI 4-only
  engines are not supported. No AT&T voice data or license is redistributed.
- A virtual serial port connected to a **local Windows named pipe**. The host
  is the pipe client; the hypervisor is the pipe server. Only one bridge client
  can use a pipe at a time.
- Working VM sound. Choose the host/VM audio output you want; NVDA's own output
  device selector does not route XP's audio.

The helper has run on a test XP 5.1.2600 VM with VirtualBox 7.2.18, Microsoft
Sam, AT&T DTNV 1.4 Mike16 and Crystal16. The exact XP service pack was not
confirmed. Although the helper avoids a modern C runtime and targets XP APIs,
**SP1, SP2 and SP3 have not each been separately qualified**. VirtualBox is the
only currently supported hypervisor. VMware is an experimental porting target,
not a tested/supported platform; contributors are welcome to qualify it.

## Installation: two separate folders

The build produces:

1. `dist/XP Bridge/AngelLegacyVoiceBridge.exe` — copy this into XP.
2. `dist/NVDA Add-on/AngelLegacyVoiceBridge-0.1.2-dev1.nvda-addon` — diagnostic
   candidate for isolated testing, **not** a cleared primary-speech update.
3. `dist/AngelLegacyVoiceBridge-0.1.2-dev1-source.zip` — readable Python and native
   helper C++ source, build script, tests and documentation. No VM or voices.

Historical GitHub Releases provide the `.nvda-addon`, standalone XP `.exe` and
curated source ZIP. The release hold above supersedes those installation notes.
This diagnostic candidate is not a new public release.

Nothing is installed automatically by the build. Guest Additions/VMware Tools
can help copy the helper, but the speech connection does not depend on them.
An ISO attached to the VM is another offline way to transfer the helper.

### Update safety

Keep the bridge disabled while the speech-loss incident is investigated. If a
diagnostic build is installed at an agreed safe time, saved settings are retained;
select a reliable local synthesizer and keep bridge startup/mirroring off first.
The XP helper and protocol remain unchanged. Building or copying this source
does not update an active NVDA process, and logging is not an automatic cure.

### VirtualBox configuration

Save your work and shut down XP normally before changing virtual hardware.
Do not modify a saved-state VM. In VirtualBox Manager, select the VM and open
Settings, Serial Ports. Enable port 1 with:

- Port number: COM1 (I/O address 0x3F8, IRQ 4).
- Port mode: Host Pipe.
- Path/address: `\\.\pipe\AngelLegacySpeech-XP`.
- Do **not** select Connect to existing pipe: VirtualBox must create the pipe.

This generic default is not tied to a particular computer. You can choose a
different name beginning `\\.\pipe\AngelLegacySpeech-`; use the exact same name
in the add-on. A unique suffix is useful with multiple VMs. With the default
configured, the add-on automatically selects a single matching running pipe.
With multiple matches, use **Detect running VM pipes** and choose the VM.
Detection finds a configured pipe, not an unconfigured VM or an installed voice.
VM names and installation folders in examples are placeholders, not saved
machine configuration. The installer does not contain test credentials or a VM
identifier. An upgrade retains your existing NVDA profile settings on your own
computer; those settings are not part of the distributable package.

For administrators who prefer commands, with the VM powered off:

```powershell
& 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe' modifyvm 'Windows XP' --uart1 0x3F8 4 --uart-mode1 server '\\.\pipe\AngelLegacySpeech-XP' --uart-type1 16550A
```

Do not enable networking for this bridge. Start XP normally with its visible
window. Confirm XP's normal audio works. Inside XP, put the helper in a folder
such as `C:\AngelLegacyVoiceBridge`, then run `AngelLegacyVoiceBridge.exe`.
COM1 is the default. Advanced setups can use `--com2`, `--com3` or `--com4`.
Leave the console open; Alt+Tab away when desired. Running a second copy will
fail because the COM port is already in use.

### VMware Workstation porting notes (experimental, unsupported)

With the VM powered off, add a Serial Port. Choose a named pipe, use the same
local pipe path as the add-on, and configure **this end as the server** and
**the other end as an application**. Connect the device at power on. Match the
guest COM number to the helper argument. Enable “Yield CPU on poll” if your
Workstation version offers it. VMware UI names vary by version; check its
serial-port documentation. Keep guest networking disabled. Do not use a remote
pipe, network redirector, or expose this unencrypted protocol to a network.
These are starting points for contributors, not a qualified installation recipe.
Qualification must cover audio, voice discovery, cancellation, disconnect/recovery
and supported guest versions. No VMware-specific dependency is required by the
protocol itself.

### Install and test the NVDA add-on

1. Keep a working local synthesizer selected. Open the `.nvda-addon` file on the
   host and approve NVDA's installation prompt. Restart **NVDA when you are
   ready**; the installer/build does not restart it for you.
2. Open NVDA menu, Preferences, Settings, **Legacy Voice Bridge**.
3. Confirm or detect the pipe. With XP and the helper running, check **Enable
   bridge now** or activate **Connect**. The voice list updates
   automatically; no additional Refresh click is required.
4. Choose Mike, Crystal or another installed voice under **Mirror/test voice**.
   Use **Test speech through XP**. You should hear one short sentence from XP.
5. For two voices, enable **Mirror local NVDA speech to XP**, then Apply/OK.
   Do not select NVDA's No speech synthesizer for normal mirroring; it is designed
   to accompany a working local voice, not be your only speech path.
6. For XP-only NVDA speech, open Select Synthesizer with **NVDA+Control+S** and
   choose **Angel Legacy Voice Bridge (audio through XP)**. Open NVDA speech
   settings to select the voice, rate, pitch and volume. Mirroring is suppressed
   automatically while the bridge itself is the selected synthesizer.
7. Save NVDA configuration (NVDA+Control+C, or NVDA's normal save-on-exit option)
   if you want these settings remembered.

### Change output format from the synthesizer settings ring

With Angel Legacy Voice Bridge selected as the synthesizer, use
**NVDA+Control+Left/Right Arrow** until you hear **XP output format**, then
**NVDA+Control+Up/Down Arrow** to change it. It is also in NVDA's ordinary Speech
settings. The choices match Legacy Voice Bridge settings: voice default or
16/22.05/44.1/48 kHz, 16-bit mono. The next dispatched utterance uses the change;
audio already playing is not reformatted mid-word. No helper restart or
reconnection. Save NVDA configuration to retain the choice. The ring uses the
same saved bridge setting, not a separate competing setting. With a local synth
and mirroring, use the Legacy Voice Bridge panel instead of that synth's ring.

To stop all bridge use, press **NVDA+Shift+F11**, uncheck **Enable bridge now**,
or press **Disconnect** (or **Cancel connection** during retries). These cancel speech, stop the worker/retries,
and turn off mirroring and automatic startup. Your existing local synthesizer
is kept; eSpeak is selected only if the bridge was your active synthesizer.
You can reassign the shortcut through NVDA's Input
Gestures dialog. The usual NVDA+Control+S synthesizer dialog remains available.

## Settings explained

| Setting/action | Meaning |
| --- | --- |
| Enable bridge now | Master switch for current bridge use. Checking connects and discovers voices. Unchecking disables speech, mirroring and retries immediately. Off by default. |
| Connect automatically when NVDA starts | Connect at the next NVDA start when the master switch is enabled. Does not boot XP or launch its helper. Turning this off alone does not stop current speech. Saved mirror mode or selecting the bridge synth also needs a connection. |
| Local bridge pipe | The exact pipe created by VirtualBox/VMware. Switch to a local synth before changing it. No IP address or guest password needed. |
| Detect running VM pipes | Find matching local pipes; choose if several exist. Does not boot, change, or inspect the disks of a VM. |
| Mirror local NVDA speech to XP | Send speech to XP as well as your active local synth. Turning off cancels mirrored speech immediately. Two voices can overlap and differ in timing. Off by default. |
| Mirror/test voice | A voice discovered from XP; stored using its SAPI token ID, not its changing list position. |
| Mirror/test rate | 0–100, mapped to SAPI's -10 to +10 rate. 50 is SAPI normal. Voice engines interpret speed differently. |
| Mirror/test volume | 0–100; 0 is muted. Independent of Windows/VM mixer volume. |
| Set XP playback mixer to 100% when adjusting bridge volume | Optional, off by default. On connection, Apply/Test, or a bridge synth volume adjustment, request XP's preferred output's master and Wave playback levels at 100%. Speech is still controlled by the bridge volume. Affects other XP sounds; does not unmute, alter recording gain or change the host mixer. Disabling does not restore old levels. Status reports full, partial or unavailable support. |
| XP output format | Voice default (recommended), or 16, 22.05, 44.1 or 48 kHz, 16-bit mono. Apply affects subsequent utterances; Test uses the current selection. Connection status shows the format SAPI reports after speech starts. Higher rates cannot add detail to an old low-rate voice. Unsupported engine/device formats can fail and trigger fallback. |
| Use local eSpeak if the bridge synthesizer disconnects | Restore local speech after a detected failure. On by default. Detection is not instantaneous. |
| Automatically return to the bridge after recovery | Off by default. After automatic eSpeak fallback, return only after a short check phrase, sent at volume zero, renders in the original voice. Some XP voices remain audible at volume zero, so the phrase may be heard. Restore the bridge voice, rate, volume and pitch. A deliberate synth/local voice change, a profile switch, disabling the bridge, or turning this option off cancels the pending return. |
| Connect / Cancel connection / Disconnect | One button, reflecting the current state. Connect applies the pipe immediately and starts retries. Cancel connection stops a pending connection; Disconnect stops an established one. Both stop mirroring, automatic startup and retries, preserving local speech or selecting eSpeak if needed. To reconnect, press Connect afterward. |
| Refresh voices and status | Update the displayed information. The updated helper is scanned automatically about every five seconds while speech is idle; installing/removing SAPI5 voices no longer requires restarting it. Up to 128 distinct voice token IDs per helper run; not limited to Mike/Crystal. |
| Test speech through XP | Send one synthetic phrase using the mirror/test controls. Use a local synth first. Mirroring is suspended during the test, preventing settings announcements from filling its queue. |
| Stop test speech | Enabled only while test speech is queued/active. Cancels the test; configured mirroring may resume afterwards. To stop everything, use Disconnect or NVDA+Shift+F11. Does not mute local NVDA. |
| About | Summary of purpose, audio routing, recovery and help. |

The bridge synth's ordinary speech settings are independent of the mirror/test
rate and volume. Pitch goes from 0–100, mapped to SAPI XML pitch -10 to +10.
Not every legacy engine implements all pitch/spelling behavior identically.
Use one pipe across NVDA profiles for this beta; automatic profile-triggered
transport switching has not been qualified.

Enable, Mirror, Connect, Test and Disconnect are immediate actions, even if you
later cancel the settings dialog. Other settings apply on Apply/OK. Save NVDA
configuration to persist choices. Installing this same-version update requires
replacing **both** the XP helper and host add-on for live voice discovery. The
add-on requires protocol 2; older protocol-2 helpers still speak but do not
advertise the live-refresh capability.

## Reconnection and privacy

If the bridge is the active synthesizer and the connection unexpectedly fails,
**Restore local eSpeak if bridge speech disconnects** is on by default. It
switches to eSpeak after failure is detected, not the instant XP stops responding.
In mirror mode the regular local voice remains active anyway. By default, select
the bridge yourself after recovery.

### Turning on automatic return

Automatic return is off by default. To turn it on, use either:

- NVDA menu → Preferences → Settings → **Legacy Voice Bridge**, check
  **Automatically return to the bridge after recovery**, then OK; or
- the command **Turn automatic return to the bridge after recovery on or off**.
  It has no key by default: assign one in NVDA menu → Preferences → Input
  gestures, category **Angel Legacy Voice Bridge**. It says "Automatic return to
  the bridge on" or "off". Turning it off also cancels any pending return.

Both **Restore local eSpeak if bridge speech disconnects** and automatic return
must be on for the round trip. Save your configuration if NVDA does not save it
on exit.

Transport I/O runs on a worker, not NVDA's UI thread. An unavailable helper is
retried about once a second while connection is enabled. Only selecting/restoring the bridge synthesizer permits
a bounded two-second initial handshake wait; an unavailable VM then falls back
through NVDA's normal synth-loading behavior. A connected session normally fails after about
four seconds without replies. The XP helper discards speech after about six
seconds without host contact. OS/VM stalls can extend these timings. A voice
that fails to finish an utterance is treated as failed after 120 seconds plus
half a second per text character, excluding pauses. Missing packet acknowledgements
time out after about four seconds even if heartbeats still arrive. These are
safety timeouts, not promised response times.

Speech queued before a disconnect/cancel is not replayed after recovery. An
automatic return only follows this add-on's own eSpeak fallback, never an ordinary
manual selection of local speech. Changing synthesizer or local voice cancels
the pending return, as do disabling the bridge, turning automatic return off,
and switching NVDA configuration profile. A missing original XP voice
keeps local speech active until that voice returns. Failed restoration stays on
local speech instead of repeatedly switching. Pending recovery is not saved
across NVDA restarts. The output format remains the shared bridge setting.

A reconnected pipe or a listed voice is not treated as recovery: a crashed
voice engine can leave both intact. While eSpeak speaks normally, the add-on
sends a short fixed check phrase to the original voice at volume zero, first
after 5 seconds, then at doubling intervals up to one minute. Only a completed
render, confirmed by its final bookmark, allows the return. Checks stop after
12 attempts or 15 minutes, and NVDA says "Bridge voice did not recover. Staying
on eSpeak." If eSpeak is mid-sentence when a check succeeds, the return waits
up to 8 seconds for it to finish, then interrupts. A successful return says
"Bridge voice recovered." through the restored voice. The check proves the
engine rendered that phrase, not that later text cannot fail again.

The check is inaudible only on voices that honour SAPI's volume setting. On
the development XP VM, the check phrase rendered to files at volume zero was
completely silent for Microsoft Sam and all 26 Panthera (Classic Mac and Alex)
voices. AT&T Natural Voices Mike16 and Crystal16 ignored both the in-text and
the base SAPI volume and stayed at about 18% of their normal peak, so with
those voices you will briefly hear the check phrase from the VM. Other vendors
are untested.

At most three automatic returns happen in ten minutes, and each recent return
lengthens the first wait (5, 10, then 20 seconds). If another failure follows
those returns, NVDA says "Bridge failed repeatedly. Staying on eSpeak."; select
the bridge manually after correcting the underlying problem.

This is local inter-process communication, **not encryption or a security
boundary against other software on the host**. Only trust the VM/helper and
host programs using the pipe. Text intentionally goes into XP and the voice
engine. Bridge logs omit speech content; NVDA's own logging configuration and
other add-ons may have different policies. Do not copy the add-on to secure
login settings; bridge operation is disabled in NVDA secure mode. Keep XP
offline and use a backup of the VM.

## Limitations and future work

### Newly installed voices

The updated helper re-enumerates 32-bit SAPI5 voice registrations at the host's
request, about every five seconds when speech is idle. Continuous reading defers
the scan until an idle gap. No helper restart or reconnect is needed; a voice
installer may still require its own restart. Only fully registered voices are
offered. The settings panel and bridge synthesizer ring update from the new
catalog. Removing the selected voice triggers the normal failure/fallback path.
Replacing the engine behind an unchanged token ID is different from adding a
voice; restart the helper after an engine upgrade if its installer requires it
or the running engine retains old components.
Incomplete scans keep the last good catalog and retry later. Unchanged catalogs
use a short acknowledgement, not a full retransmission. Speech arriving during
a scan waits for it; this is not a zero-latency system. A scan timeout with a
still-responsive link disables scanning until reconnect rather than repeatedly
replacing the user's synthesizer.

Indexes remain stable for the helper's lifetime, including across removals, so
queued requests never silently switch to another voice. Up to 128 distinct token
IDs are retained per helper run; restart the helper if this lifetime limit is
reached. A controlled XP test added, spoke through, and removed a disposable
SAPI5 registration on the same live connection. This is not a qualification of
every commercial voice installer.

### Running XP without a visible window

Use VirtualBox's **Start with detachable GUI** at the VM's next normal start.
The command-line equivalent, only while powered off, is:

```powershell
& 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe' startvm 'Windows XP' --type separate
```

Then choose **Machine > Detach GUI** to hide the window while XP keeps running.
Select the running VM in VirtualBox Manager and choose **Show** to control it
again. Detaching/reattaching in this mode does not reboot XP. An already-running
ordinary GUI session should simply be minimized; this project does not promise
to convert its launch mode in place. Use detachable mode at its next normal start.
See [Oracle's separate-mode instructions](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/remotevm.html).

XP must still be logged in with working audio and the helper running. Hiding
the VM does not launch the helper. The listening tests used a visible VM;
detached/headless audio has not been qualified here. No VM reboot is needed for
this add-on/helper update.

### Starting the helper manually or automatically

In the local test installation the program is
`C:\AngelLegacyVoiceBridge\AngelLegacyVoiceBridge.exe`. In XP, press Windows+R,
enter that path and press Enter. It opens a console; Alt+Tab or minimize it,
and use Control+C to exit. It is not a Windows service. Other users can choose
their own installation folder. Guest Additions can also launch that same EXE.

The package does **not** create a desktop shortcut or an automatic-start entry.
To start after XP logon, create a shortcut to the EXE in that XP user's Start
Menu > Programs > Startup folder. Automatic Windows logon is separate and is
not configured by the add-on. The helper needs that user's audio session.
NVDA's Legacy Voice Bridge settings provide the GUI for pipe discovery,
connection, voices, format and recovery after the one-time VirtualBox serial
port setup; they do not automatically configure or boot a VM.

- No system-wide SAPI5 adapter, LAN transport, SAPI4 voices, host-side audio
  streaming, automatic hypervisor reconfiguration or Windows service yet.
- XP must have an interactive audio session. A console is the simplest way to
  verify the correct voice/audio user context before considering a service.
- Small transport packets are assembled into one SAPI utterance before playback,
  without inserting prosody tags at packet boundaries. SAPI bookmarks provide
  index notifications. Natural punctuation, requested breaks, separate NVDA
  utterances and VM scheduling can still cause pauses; no zero-latency claim.
- At most 16,000 text characters/256 sequence items per utterance and 64 queued
  utterances. Very large requests fail safely rather than expanding indefinitely.
- Output-format conversion is not audio restoration. A 16 kHz voice remains a
  16 kHz source even when rendered at 48 kHz. This does not fix a faulty VM driver.
- Mirroring follows queued NVDA speech, not a recording of the local voice. It
  is not an exact replica of NVDA's priority/preemption timing.
- Engine-specific pronunciation, spelling, pitch, long reading and actual
  audible responsiveness still need user acceptance testing.
- This transports SAPI5 requests; it does not make unsupported or unlicensed
  voices compatible. A later host SAPI5 adapter could reuse the protocol, but
  would require a separately tested COM voice engine and installers.

## Troubleshooting and removal

For helper startup commands, safe maintenance disconnects, diagnostics, and
step-by-step automation instructions, see [OPERATIONS.md](OPERATIONS.md). The
local maintenance interface can only disable the bridge; it cannot send speech,
execute commands, change settings arbitrarily or connect from another computer.

No voices: confirm the helper console stays open, COM1 exists in XP Device
Manager, the pipe matches, and no other bridge/test process owns it. Check the
helper's lifecycle messages and NVDA Tools, View log. Do not post private speech
logs. XP's Speech control panel can verify that its installed voices work.

Connected but silent: test XP sounds, its default sound device, the hypervisor
audio output, volume/mute, and a different SAPI5 voice. The pipe carries text,
not audio, so a successful connection cannot prove speakers are audible.

Slow/stuck: restore local speech, stop the test, close/reopen the XP helper and
reconnect. VM CPU load, driver quality and legacy engine startup affect delay.
Never turn networking on as a fix. Do not run integration tests while using the
bridge as your only screen reader.

To remove: select local eSpeak, disable mirroring/automatic connect, remove the
add-on through NVDA and restart NVDA when convenient. Close the helper with
Control+C and delete only its own folder if no longer needed. Disabling the
virtual serial port is optional and requires powering down the VM; removing
this program never requires deleting your VM or voices.

## Build and developer tests

Use Python 3.13, Visual Studio 2022 C++ x86 tools and a Windows 10 SDK. No WSL or
internet is required once those build dependencies are installed:

```powershell
python -m unittest discover -s tests -v
python build.py
```

Optional hidden-widget check, with host wxPython installed:
`python tools/ui_smoke.py`. It uses real widgets and isolated NVDA API doubles;
it does not launch, install over, or restart your running NVDA.

Build output goes under `dist`, including separate helper/add-on directories,
documentation, license and SHA-256 sidecars. The add-on contains its Python
source. The separate source ZIP includes `bridge/main.cpp`, `bridge/runtime.cpp`
and `build.py` for building the native XP EXE; it is not an opaque binary-only
component. Local continuity notes and Git history are excluded from that ZIP.

Optional live mixer test: `python tools/mixer_probe.py --allow-volume-change`.
This changes XP playback levels; do not run it without permission. The live
voice-registration probe is for a disposable test token, not proprietary voice
installation/uninstallation; see the operations guide.
The XP helper avoids newer CRT imports using a small freestanding entry point.
It uses explicit bounds, but disabling the compiler's CRT-backed stack cookie
is a legacy compatibility compromise; do not expose this helper to strangers.

Opt-in tests against a running helper, with no active bridge NVDA connection:

```powershell
python tools/smoke.py
python tools/smoke.py --speak
python tools/integration.py
python tools/quality_probe.py
```

Add `--pipe '\\.\pipe\AngelLegacySpeech-your-name'` if not using the generic
default. The smoke test's `--speak` phrase is audible; integration/quality speech
is muted. These command-line probes do not automatically select another pipe.
See [PROTOCOL.md](PROTOCOL.md) for messages/state, and
[TEST-REPORT.md](TEST-REPORT.md) for actual results and remaining checks.

## License and references

Before public release, follow [PUBLICATION.md](PUBLICATION.md). The add-on build
does not bundle personal NVDA configuration, VM disks, passwords or recordings.
Do not publish the entire development workspace or its unreviewed Git history.

Copyright 2026 Angels Clan. This project's original code is licensed under
GNU GPL version 2 or, at your option, any later version. See LICENSE.
NVDA, VirtualBox, VMware and the voice engines have their own licenses.

Primary references: [VirtualBox serial ports](https://docs.oracle.com/en/virtualization/virtualbox/6.0/user/serialports.html),
[NVDA user guide](https://download.nvaccess.org/documentation/userGuide.html),
[NVDA synthesizer API source](https://github.com/nvaccess/nvda/blob/master/source/synthDriverHandler.py),
[Microsoft SAPI speech flags](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms720892(v=vs.85)).
