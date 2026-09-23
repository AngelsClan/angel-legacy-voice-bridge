# Angel Legacy Voice Bridge

Hear older Windows speech voices through modern NVDA without installing those
voices on your main Windows computer.

The bridge has two parts. An **NVDA add-on** runs on your main computer. A small
**helper** runs inside a Windows XP virtual machine, where you install your own
licensed SAPI 5 voices. The add-on sends speech requests through a local
virtual serial connection. The XP helper asks the selected voice to speak and
reports speech progress back to NVDA. XP does not need an internet connection.

**Development status:** `0.1.2-dev4` is for testing. The public release is on
hold while an earlier NVDA freeze remains unexplained. Keep a dependable local
NVDA synthesizer available. [What has been tested](TEST-REPORT.md) and
[known limits](docs/ADVANCED-GUIDE.md#known-limits) are documented separately.

## Which voice add-on do I need?

| If your voice... | Use... | Where the voice runs |
| --- | --- | --- |
| Is an older **Windows SAPI 5** voice that needs XP | Angel Legacy Voice Bridge | Inside the XP virtual machine |
| Is a **Mac OS X MacinTalk** voice in a Lion, Snow Leopard, Leopard or Tiger Voices add-on | That generation's Mac voice add-on | Locally on the modern Windows computer |

These are independent ways to use older voices. **The Mac voice add-ons do not
need XP or this bridge.** The bridge can also use a MacinTalk voice *if that
voice was separately installed as a SAPI 5 voice inside XP*, but the normal
Mac voice add-ons run it locally. You can install both approaches if you want
to compare them. Neither project includes a license for the voices.

Angel Audio Keeper is a third, separate [NVDA add-on](https://github.com/AngelsClan/angel-audio-keeper).
It keeps selected sound outputs active between sounds; it does not provide a
voice or carry speech between computers.

## What you need

- NVDA on a modern Windows computer.
- A working 32-bit Windows XP virtual machine with sound and a virtual serial
  port. VirtualBox is the platform tested here.
- Your own licensed SAPI 5 voices installed inside XP. SAPI 4-only voices do
  not work with this bridge.
- The XP helper program and the NVDA add-on from this project.

The project supplies **no voices, Apple files, XP image, or voice licenses**.
Nothing in the bridge needs XP networking. The serial connection stays on your
computer; it is not an internet service.

## Set it up

1. Make sure XP and the voice you want to use can already produce sound.
2. Add a virtual serial port to XP and connect it to a Windows named pipe on
   the main computer.
3. Copy the bridge helper into XP and start it there.
4. Install the bridge NVDA add-on on the main computer, then restart NVDA.
5. In NVDA's **Preferences > Settings > Angel Legacy Voice Bridge**, enter
   your own pipe name, connect, refresh the voice list, and use the fixed test
   phrase before selecting the bridge as your synthesizer.

The [step-by-step setup guide](docs/ADVANCED-GUIDE.md#installation) explains
the virtual serial port, both programs, each setting, and troubleshooting.
The pipe name and VM settings are chosen locally; no personal configuration is
required by this repository.

## Where does the sound play?

In bridge settings, choose one speech route:

- **XP:** speech plays through the virtual machine's sound output. This is the
  usual starting point.
- **NVDA:** the helper returns voice audio to NVDA, which plays it through
  NVDA's selected output.
- **Both:** speech plays on both outputs. The two copies can arrive at slightly
  different times.

Other sounds made inside XP stay in XP. A successful connection only proves
the two programs can talk; it does not prove that the voice or sound output is
working. The test phrase checks the voice before you depend on it.

**Shift pauses and resumes** speech; **Control cancels** it. On the NVDA and
Both routes, host playback pause reaches NVDA's audio player directly. On the
XP route, audible pause timing also depends on the XP voice and sound buffer.
If the bridge fails while selected, it tries to switch NVDA to local eSpeak,
sounds a short tone, and announces the change. Settings retain the last
interruption reason. A failed sound device may also make a warning inaudible.

## Privacy and safety

Speech text goes to the XP voice engine because that is how the bridge works.
The bridge uses a local pipe, not a network account. Its own diagnostics are
designed to omit speech text and window titles; they record timings, counters,
error codes, and limited text shape. Review logs before sharing them. XP and
its installed voice software remain your responsibility. Keeping an unsupported
XP system offline is strongly recommended.

The current source fixes measured terminal bookmark rounding after audio
resampling and a host-side pause delay. Neither fix proves that every
intermittent speech loss or the earlier NVDA freeze is resolved. Please report
a problem with its approximate time, route, voice family, NVDA version and a
redacted diagnostic log. You do not need to publish your pipe name or VM paths.

## More information

- [Detailed setup, settings and troubleshooting](docs/ADVANCED-GUIDE.md)
- [Technical rationale](RATIONALE.md)
- [Test evidence and limits](TEST-REPORT.md)
- [Wire protocol](PROTOCOL.md)
- [Report an issue](https://github.com/AngelsClan/angel-legacy-voice-bridge/issues)

Panthera speech and other MacinTalk work are separate projects. This bridge
is GPL-2.0-or-later; see [LICENSE](LICENSE). Development used AI assistance.
