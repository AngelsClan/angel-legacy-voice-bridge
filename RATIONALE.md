# Why this project exists

A reasonable question about this project is why anyone would run a speech
synthesizer inside a virtual machine when Windows can host speech engines
perfectly well on its own. This document answers that with specifics, including
the cases where you should **not** use a bridge.

Nothing here is an argument that virtual machines are good. It is an argument
that a particular class of problem has no better answer today.

## The short version

Modern Windows and modern screen readers have moved on from the environment
that 2000s-era SAPI 5 speech engines were written for. Four things changed:
the screen reader became 64-bit, the registry stopped mirroring 32-bit and
64-bit registrations, the installer rules tightened, and the audio stack
changed underneath. Each is individually surmountable. Together they mean a
licensed engine you legally own can become unusable, and the failure mode is
loss of speech.

A bridge sidesteps all four at once by running the engine on the operating
system it was built for, and by making the screen reader's synthesizer a piece
of software you control rather than the vendor's engine itself.

## 1. A 64-bit screen reader cannot load a 32-bit engine in-process

SAPI 5 engines are in-process COM servers. A 64-bit process cannot load a
32-bit DLL — this is an operating-system rule, not a bug. When a 64-bit client
asks for a class that is only registered in the 32-bit view, it gets
`REGDB_E_CLASSNOTREG` (0x80040154).

This is not hypothetical for screen-reader users: NVDA moved to 64-bit in
version 2026.1, and many commercially licensed English voices from the 2000s
were only ever built as 32-bit.

NV Access addressed this upstream in 2026.1 by adding a 32-bit child process,
`nvda_synthDriverHost.exe`, that hosts SAPI 4 and 32-bit SAPI 5 engines out of
process ([PR #19432](https://github.com/nvaccess/nvda/pull/19432)). **If your
engine installs and behaves, use that.** It is simpler than anything here.

Points 2 to 5 are about what happens when it does not.

## 2. Out-of-process hosting protects the screen reader, not your speech

Running an engine in a separate process means a crash no longer takes the
screen reader's process down with it. That is a real improvement over the
in-process era. But isolation is not recovery, and for someone who cannot see
the screen, the distinction matters enormously.

As shipped, NVDA's 32-bit host has no health monitoring, no restart, and no
runtime fallback. Its child process is wrapped only so that it exits when NVDA
does. NVDA's fallback to another synthesizer runs when a driver fails to
**load**; nothing re-enters that path when a loaded driver dies. Open issues
document the consequences:

- [#20875](https://github.com/nvaccess/nvda/issues/20875) — the host crashes on
  wake from sleep, the dead process cannot be killed, and NVDA does not fall
  back to another synthesizer.
- [#19723](https://github.com/nvaccess/nvda/issues/19723) — a 32-bit
  synthesizer produces silence with no error message, including on a braille
  display.
- [#19578](https://github.com/nvaccess/nvda/issues/19578) — 32-bit voices freeze
  NVDA for roughly 30 seconds, ending in a communication timeout.

By contrast, a bridge owns the recovery path, because the thing NVDA loads is
the bridge's own driver rather than the vendor's engine. This project detects
failure, announces it, switches to a local synthesizer automatically, and
optionally verifies that the original voice can genuinely render again before
returning to it. Those behaviours are implementable precisely because the
failing component is on the other side of a protocol boundary.

## 3. Some engines do not follow the SAPI 5 specification

Screen readers need to know how far through an utterance the engine has got, in
order to advance queued speech and to track the reading position. SAPI 5
defines this: the engine raises a bookmark event in response to bookmark
fragments in the text.

Not every engine implements it. NVDA issue
[#16691](https://github.com/nvaccess/nvda/issues/16691) documents several
commercial SAPI 5 engines where continuous reading has been broken since NVDA
2019.3, because the engine sends no bookmark notifications and the screen
reader waits indefinitely. Some engines support only word-boundary events.
NV Access's stated position is that these are design faults in the
synthesizers, some last updated over a decade ago, and are unlikely to be
fixed.

A bridge can guarantee progress reporting regardless of what the engine does,
by tracking position itself, checking real completion without blocking, and
applying its own timeouts. An adapter that promises correct behaviour is
strictly more reliable than one that forwards whatever the engine happens to
send.

## 4. Old installers increasingly fail on modern Windows

Three documented changes work against installers written for Windows XP:

- **Registry reflection was removed in Windows 7.** On XP and Vista the system
  mirrored COM registrations between the 32-bit and 64-bit views. It no longer
  does, so an installer that registered a voice once now registers it somewhere
  only half the system looks.
  ([Registry reflection](https://learn.microsoft.com/en-us/windows/win32/winprog64/registry-reflection))
- **Registry virtualization silently redirects some writes and not others.** A
  legacy 32-bit installer's writes to `HKLM\SOFTWARE` can be redirected to a
  per-user store, where the installer reads them back successfully and reports
  success — while writes to `HKLM\Software\Classes` are excluded from
  redirection and simply fail. The result is a voice that appears in lists but
  cannot start.
  ([Registry virtualization](https://learn.microsoft.com/en-us/windows/win32/sysinfo/registry-virtualization))
- **Self-registration is discouraged by Microsoft**, and packages that rely on
  it fail when an auxiliary library is missing or the wrong version.
  ([SelfReg table](https://learn.microsoft.com/en-us/windows/win32/msi/selfreg-table))

None of these apply inside a guest running the original operating system.

## 5. Modern Windows sometimes breaks legacy engines outright

In 2024, Windows 11 24H2 shipped a 32-bit `MMDevApi.dll` with a calling
convention mismatch that corrupted a processor register when the audio device
list changed, crashing 32-bit SAPI 5 applications. A Microsoft engineer
confirmed the mechanism, 64-bit applications were unaffected, and it was fixed
in June 2025.
([Microsoft Q&A discussion](https://learn.microsoft.com/en-us/answers/questions/2119242/how-to-fix-the-problem-with-mmdevapi-dll-in-text-t))

That is one confirmed example of the class: the host operating system changing
underneath an engine that is no longer maintained and cannot be recompiled. A
guest running a frozen operating system does not receive those changes.

## 6. The guest runs the system the engine was written for

Inside the virtual machine there is no User Account Control, no registry
virtualization, no 32/64-bit registry split, and no Windows Resource
Protection. Installers behave as their authors intended because the
environment is the one they targeted.

This also gives fault isolation at machine level rather than process level: an
engine that corrupts memory, deadlocks or exhausts a resource cannot reach the
host at all.

## 7. A smaller, screen-reader-specific benefit

NVDA 2026.1 and later document that audio ducking is not available when using
SAPI 4 or 32-bit SAPI 5 voices. Speech delivered through a bridge is not a SAPI
voice as far as the screen reader is concerned, so that particular restriction
does not apply. This is a side effect rather than a design goal, but it is a
real one.

## What you give up

Honesty requires the other column:

- **A virtual machine costs real resources** — memory, CPU, disk, and the
  maintenance of a guest operating system that no longer receives security
  updates. That is why the guest must have no network adapter.
- **More moving parts.** A serial transport, a protocol, a helper program and a
  driver, each of which can fail, versus one DLL loaded directly.
- **Latency and scheduling.** Speech crosses a process and a virtual machine
  boundary. This project is careful about it, but it cannot be faster than
  loading the engine in-process.
- **Audio routing.** Sound comes from the guest's audio device, so it sits
  outside the host screen reader's own output selection and volume handling.
- **It is not a general solution.** It transports SAPI 5 requests. It cannot
  make an unsupported or unlicensed engine work, and it is not a substitute for
  a maintained modern voice.

## When you should not use this

Use the simpler option whenever it works:

- Your voice is 64-bit, or ships its own maintained screen-reader driver.
  Nothing here helps you.
- Your 32-bit voice installs cleanly on modern Windows and behaves. Use your
  screen reader's own 32-bit hosting.
- You want a modern neural voice. Use one; they are better than anything this
  project can reach.
- You do not already run a virtual machine and do not want to. The cost is only
  reasonable when weighed against losing a voice entirely.

The honest summary is that a bridge is worth it when an engine you are licensed
to use cannot be made to run correctly on the host, and when losing that voice
is not an acceptable outcome.

## Is SAPI 5 going away?

Not on the evidence available, but it is frozen rather than growing.

- **It is not deprecated.** SAPI 5 text to speech does not appear on Microsoft's
  [deprecated features list](https://learn.microsoft.com/en-us/windows/whats-new/deprecated-features).
  The only speech entry there is Windows Speech Recognition, which is
  recognition, not synthesis.
- **Its documentation is archived.** The SAPI 5.4 reference is flagged as
  archived content and carries a 2012 date. No new work is happening on it.
- **New voices arrive elsewhere.** Microsoft's modern path is the OneCore and
  `Windows.Media.SpeechSynthesis` stack, whose voices live in a different
  registry location and are not visible to SAPI 5 applications by default.

So the realistic risk is not removal — it is that SAPI 5 stays exactly where it
is while everything around it moves, which is roughly what has happened for the
last decade. It also remains the only interface through which a third-party
voice can be used by *every* Windows application rather than one specific
program, which is why adapters that expose a voice through SAPI 5 remain
worthwhile even when a screen-reader-specific driver already exists.

## Further reading

- [README.md](README.md) — installation and use.
- [PROTOCOL.md](PROTOCOL.md) — the transport, which is deliberately simple
  enough to reimplement.
- [TEST-REPORT.md](TEST-REPORT.md) — what has actually been verified, and what
  has not.
