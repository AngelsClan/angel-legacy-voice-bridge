# Operator and automation guide

## Boundaries and reasons

Keep XP offline. A local virtual serial pipe carries speech requests, not audio;
audio comes from XP's default output. Guest Additions are useful for launching
and copying the helper, but they are not the speech transport. No guest password
is stored by the add-on. Never publish passwords, voice licenses, VM disks,
personal NVDA profiles, or speech-containing logs.

Use a console in the logged-in XP user's session rather than a service: this
makes sound routing and errors understandable and avoids service-session audio
surprises. The default suggested folder is `C:\AngelLegacyVoiceBridge`, not
the Desktop. Users may choose another folder. The release does not install
shortcuts, change autologon, start XP, or change VM hardware automatically.

## Preflight: establish the actual machine, not assumptions

1. Locate `VBoxManage.exe`, normally under `C:\Program Files\Oracle\VirtualBox`.
2. Run `VBoxManage list vms` and `VBoxManage list runningvms`. Select the intended
   XP VM by its actual name/UUID; never assume the example name matches.
3. Run `VBoxManage showvminfo "Windows XP"`. Verify COM1, host-server pipe, and
   guest network adapters disabled. Do not print private VM configuration in a
   public report. If hardware needs changing, ask before a normal guest shutdown.
4. Confirm a local NVDA synthesizer works. Never replace/restart someone's active
   NVDA or interrupt their only speech path to perform an unattended test.
5. Find the installed helper path and release version. There must be only one
   helper using COM1 and one client using the pipe.

## Manual startup in XP

Press Windows+R and enter:

```text
C:\AngelLegacyVoiceBridge\AngelLegacyVoiceBridge.exe
```

COM1 is the default; an explicitly configured COM2–4 uses `--com2` through
`--com4`. Leave the console running; minimize or Alt+Tab away. Control+C exits.
For autostart, create a shortcut to this EXE in the logged-in XP user's Start
Menu > Programs > Startup folder. This starts after logon, not before it.
The add-on's Connect automatically setting starts only the host connection.

## Launch through VirtualBox Guest Additions

Guest Additions must be functioning, and the operator must obtain valid guest
credentials privately. Prefer `--passwordfile` instead of putting a password
in a command line, script, repository, transcript, or shell history. Store that
temporary file with access restricted to its owner and remove it after use.
It contains the guest password only; examples deliberately contain no password.

From a host PowerShell prompt, after replacing the VM name and private path:

```powershell
$vbox = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
& $vbox guestcontrol 'YOUR_XP_VM_NAME' start --username 'YOUR_XP_USERNAME' --passwordfile 'C:\private\xp-password.txt' --exe 'C:\AngelLegacyVoiceBridge\AngelLegacyVoiceBridge.exe' -- --com1
```

For copying an update, first disconnect the host bridge, close only the old
helper, then:

```powershell
& $vbox guestcontrol 'YOUR_XP_VM_NAME' copyto --username 'YOUR_XP_USERNAME' --passwordfile 'C:\private\xp-password.txt' 'C:\Downloads\AngelLegacyVoiceBridge.exe' 'C:\AngelLegacyVoiceBridge\AngelLegacyVoiceBridge.exe'
```

Check command exit status. Start the helper with the earlier command, then test
the pipe. A successful guest launch is not proof the voice can be heard. If
Guest Additions are unavailable, use an offline attached ISO to copy the EXE and
launch it manually. Do not turn on XP networking as a workaround.

## Disable the host bridge without navigating NVDA

The updated global plugin exposes two Windows named events scoped to the local
session and NVDA process ID. A maintenance tool requests **disable only**. The
UI thread disables the bridge, cancels automatic return/mirroring/retries, keeps
the existing local synth or selects eSpeak, and acknowledges after its transport
worker has closed. It cannot execute commands or enable remote speech. This is
not a security boundary against other software running as the same Windows user.
It is disabled on secure desktops.

The source ZIP includes the tool; Python 3 is required on the host for this
maintenance script only. Install the updated add-on and restart NVDA normally
first. It cannot control an older add-on that lacks these events.

```powershell
Get-Process nvda | Select-Object Id, Path
python tools/disable_bridge.py --pid 12345
```

Replace 12345 with the intended NVDA process ID; do not signal unrelated
instances. Wait for “Bridge disabled; its worker has released the pipe.” A
timeout is **not** confirmation. Verify helper/pipe ownership rather than
killing NVDA or rebooting XP. The request changes current runtime settings;
save NVDA configuration if the disabled state should survive a restart.
The emergency keyboard alternative remains NVDA+Shift+F11.

## Show or hide XP without rebooting it

At the next normal VM startup, use VirtualBox's **Start with detachable GUI**,
or `VBoxManage startvm "Windows XP" --type separate`. Then Machine > Detach GUI
hides the window while XP continues; VirtualBox Manager > Show reattaches it.
An already-running ordinary GUI can be minimized; do not force a power cycle to
change its launch mode. Detached/headless audio needs a listening check on the
actual host. The helper still needs a logged-in audio session.

## Test sequence and interpretation

1. Run `python -m unittest discover -s tests -v`. These include simulated NVDA
   contracts and an isolated real Windows event test, not the user's active NVDA.
2. Run `python build.py`. This compiles the XP helper and packages the add-on and
   curated source; it does not install anything or restart applications.
3. With the bridge disabled, run `python tools/integration.py --pipe PIPE`.
   It tests framing, all installed voices (muted), cancellation and stale data.
4. Run `python tools/quality_probe.py --pipe PIPE` for SAPI output formats and
   one-utterance assembly. Completed SAPI speech does not prove audible quality.
5. Optional `python tools/mixer_probe.py --pipe PIPE --allow-volume-change`
   raises XP master/Wave levels, verifies readback and muted speech completion.
   It leaves mute unchanged and does not restore old levels. Get permission first.
6. `python tools/voice_refresh_probe.py --pipe PIPE` waits for an operator to add
   and remove a disposable SAPI5 token ending `ALVB-Disposable-Voice-Test`.
   Use only a test registration on an owned/disposable guest. Never delete actual
   voice registrations. The script itself does not modify the registry.
7. Stop all test clients before user testing. A transient pipe-busy error directly
   after a test can be a delayed VirtualBox pipe release; retry with a short
   bounded wait. Persistent busy errors require identifying the owner, not
   launching more copies of the helper.
8. Install the replacement add-on only when the user is ready. Check Connect /
   Cancel connection / Disconnect labels, cancel/pause, voice list, volume,
   output format, eSpeak fallback, optional automatic return, and manual override.
   Keep local speech available; do not claim these UI checks passed from mocks.

## Suggested task for an assistant or administrator

> Set up Angel Legacy Voice Bridge using README.md and OPERATIONS.md. Discover
> my actual VM and helper paths. Keep XP offline and preserve local NVDA speech.
> Ask before shutting down XP or changing hardware. Use Guest Additions to copy
> and launch the helper if available; do not store credentials in source or logs.
> Test the connection and report what was actually verified. Do not restart my
> active NVDA or install the add-on without arranging that with me. For future
> maintenance use the disable-only tool and wait for confirmation first.

## Diagnostics and reporting

For a muted backlog test with the bridge disconnected, run
`python tools/burst_probe.py --pipe PIPE --count 60`. The optional
`--drop-index-every 3` deliberately omits some received bookmark notifications
to verify recovery after real XP speech completion. It does not delete speech,
connect to TeamTalk, change guest settings or access private chat text.

Version 0.1.1 reports progress counts/times about every ten seconds in the NVDA
log: queued requests, unsent frames, active duration, pause/acknowledgement
state, pending indexes, completed requests, recovered indexes and reply age.
Speech text, voice tokens and pipe paths are excluded. Disconnect reasons are
also logged. If a freeze recurs, record its time and compare these entries to
NVDA's watchdog messages; a watchdog report alone does not identify its cause.

Report NVDA/VirtualBox/XP versions, 32-bit SAPI5 engine name, connection status,
selected format, and reproducible steps. Do not upload proprietary engine files
or personal speech. The helper console and NVDA log contain lifecycle/error
messages from this project; other add-ons or NVDA debug settings may log more.
No account, telemetry, online voice service, or automatic updater is included.
