# 0080 — `windows` and `qemu` get real smoke tests, live-verified before being wired in

- Status: Implemented
- Related: [0069], [0079]

## What was wrong

[0079] gave `webassembly` a real smoke test and left `windows`/`qemu` on the
same "the runner cannot run it" premise `webassembly` itself had been sitting
on until that record checked it and found it false. Both `test-upstream-
usermodule.yml`'s own header comment and `build-windows`/`build-qemu`'s own
`ls`-only steps repeated that premise unchecked: a `.exe` needs `wine`, a qemu
ELF needs `qemu-system-arm`, "neither of which this runner has without a setup
step" -- true as far as it went, but a setup step is not the same claim as
"cannot be done here", and [0079]'s own point was that the difference matters.

## What was checked, live, before touching the workflow

Both cross-compiled outputs were built directly on a plain Ubuntu 24.04 host
(no Docker involved -- the point was proving the *execution* half, which
`docker/{windows,qemu}.Dockerfile` do not touch) against a real v1.29.0
checkout's `examples/usercmodule`, the exact fixture this workflow builds:

- **`windows`/`win_amd64`**: `apt install gcc-mingw-w64-x86-64
  g++-mingw-w64-x86-64` (the C++ compiler package is not pulled in by the C
  one alone -- `cppexample.cpp` fails to preprocess without it, caught live)
  cross-compiled a genuine `micropython.exe` linking `cexample`/`cppexample`/
  `subpackage`. `apt install wine wine64` (`wine64`'s own `wine` dependency is
  only a `Recommends`, not a hard `Depends` -- both named explicitly rather
  than relying on APT's default-recommends behaviour) then ran it unmodified:
  `wine micropython.exe examples/usercmodule/smoke_test.py` printed the same
  output the `unix` job's own smoke step does and exited 0. A deliberately
  broken script (`assert False`) exited 1 through wine the same way a real
  regression would.
- **`qemu`/`MPS2_AN385`**: `apt install gcc-arm-none-eabi qemu-system-arm`
  built a real `firmware.elf` the same way. Unlike `unix`/`webassembly`/
  `windows`, `ports/qemu`'s own port has no CLI that takes a script path --
  upstream's `ports/qemu/README.md` is explicit that the firmware only
  exposes a REPL over an emulated UART, reached by running `qemu-system-arm`
  with `-serial pty` and pointing a serial client at whatever `/dev/pts/N`
  it prints. `pip install mpremote` (the official MicroPython PC-side tool
  for exactly this, not `tools/pyboard.py` out of the pinned checkout --
  see below) then `mpremote connect /dev/pts/N run smoke_test.py` printed
  the same smoke-test output and exited 0; the same deliberately-broken
  script exited 1, `mpremote`'s raw-REPL protocol carrying the real
  `AssertionError` traceback and turning it into a non-zero process exit.

Both failure paths were checked, not assumed -- the class of gap [0079]
itself is about: a step that only ever runs a script that passes would be no
better than the `ls`-only step it replaces.

## The fix

- `build-windows` gains an `apt-get install wine wine64` step and a smoke
  step running `wine "$exe" examples/usercmodule/smoke_test.py` against the
  collected `micropython-<identifier>.exe`, mirroring `build-unix`'s own
  step exactly (same script, same binary-takes-a-path-on-argv shape).
- `build-qemu` gains an `apt-get install qemu-system-arm` + `pip install
  mpremote` step and a smoke step that starts `qemu-system-arm -semihosting
  -machine mps2-an385 -nographic -monitor null -serial pty -kernel "$elf"`
  itself, polls its stdout for the `redirected to /dev/pts/N` line, and runs
  `mpremote connect "$pty" run examples/usercmodule/smoke_test.py` against
  it. The `-machine`/`-semihosting` invocation is hardcoded to this job's one
  board (`MPS2_AN385`) rather than derived from `ports/qemu/Makefile`, which
  lives in the pinned checkout this step has no path to (the same reason
  [0069]'s own record gives for why the workflow never resolves that
  checkout's path itself) -- widening to another board is exactly [0054]'s
  own "widen only if it finds something", not done speculatively here.
  `mpremote` over PyPI rather than the checkout's own `tools/pyboard.py` was
  the deciding choice for the same reason: this step depends on nothing from
  the pinned checkout at all, install included.
- The workflow's own header comment above both jobs is corrected to say what
  is actually true now, rather than repeating the "needs a setup step it
  doesn't have" framing [0079] already showed was the wrong question to ask.

## Not done here

- **`rp2`'s own `firmware.uf2` still has no smoke test.** [0069]'s reasoning
  for it is unchanged by this record: it needs real hardware or a
  board-specific emulator, neither of which either record provides.
- **[0079]'s other two open items are untouched.** `esp32`'s companion file
  is still verified by a unit test and a real build directory's listing, not
  a live ESP-IDF build through this workflow; the three consuming
  repositories are still not migrated onto `mpyhouse/<identifier>/` for
  their `webassembly`/`esp32` uploads.
- **Only `MPS2_AN385` was checked.** `qemu`'s other eight boards
  (`resources/pinned_docker_images.toml`'s own `[usermod.qemu]` table) are
  build-tested by `build-examples.yml`'s broader matrix already, but none of
  them gets a smoke step here -- the same "widen only if it finds something"
  call [0079] itself made for `webassembly`/`esp32`.

**Addendum, 2026-08-31 — the sandbox verification above hid a real GitHub
Actions race.** The first real CI run of `build-qemu` failed immediately:

```
mpremote: failed to access /dev/pts/0 (it may be in use by another program)
```

on the very first `mpremote connect` call, right after the polling loop found
the "redirected to" line -- something this record's own live verification
never hit, because every manual check above had several seconds of human
typing time between starting qemu and connecting to it. `mpremote`'s own
`SerialTransport.__init__` (`transport_serial.py`) has a `wait=` retry loop
built for exactly this class of just-enumerated-device race, but `do_connect`
only uses it for `mpremote connect auto`'s USB-VID/PID auto-detect path;
`mpremote connect <explicit-path>` always constructs it with `wait=0`, one
attempt, no retry, whatever the actual cause of the race turns out to be on a
given runner.

The smoke step was given a retry around the `mpremote` call itself (up to 10
times, 0.5s apart) but only when its output contains that exact "failed to
access" message -- a genuine failure from the script (an assertion, an import
error) still fails the job on the first attempt, verified the same way the
pass/fail paths above were: a fake `mpremote` replaying the busy message
twice before succeeding exits 0 through the retry loop, and one emitting a
real traceback exits 1 immediately, no retry spent on it.

**Addendum, 2026-08-31 -- the retry above treated a symptom whose cause was
not what it looked like.** Pushed and re-run: all 10 attempts failed the same
way, evenly spaced across five-plus seconds, not the one-shot failure a brief
enumeration race would produce. Something on that runner held `/dev/pts/0`
busy for the whole window, not just for the instant right after qemu
allocated it -- the "just-enumerated-device" framing above was itself
guessed from `mpremote`'s own retry-loop comment, not from the runner, and
the guess was wrong.

Rather than keep guessing at what specifically holds a `/dev/pts/N` slot busy
on a GitHub-hosted runner, the design was changed to need no such guess at
all: `-serial "tcp:127.0.0.1:<port>,server=on,wait=off"` makes `qemu-system-arm`
itself the listener on a TCP port nothing else on a fresh runner could
already hold, and `mpremote connect socket://127.0.0.1:<port>` -- a normal
pyserial URL scheme, not something this project added -- connects to it
directly. `exclusive=True` (what made the pty version fail) is simply inert
for a socket transport. Live-verified the same way the pty version was,
including three `mpremote run` calls in a row against the same qemu instance
with no connection issue at all, and the exact YAML step's own script (not
an approximation of it) run standalone against a real collected `.elf` for
both the passing and the deliberately-broken script. The retry loop stayed,
now against connection-refused-while-qemu-is-still-starting instead of a
busy pty -- `mpremote` wraps that in the identical "failed to access ... it
may be in use by another program" message, so the same match still applies,
confirmed by connecting before qemu had opened its listening socket at all.

**Addendum, 2026-08-31 -- neither of the two addenda above was the actual
bug.** The TCP version failed in real CI too, all 20 attempts, the same
generic message -- which could no longer be a pty-specific race, and could
not be reproduced locally either (root or non-root, tight or loose timing,
the identical qemu version): every local attempt connected on the first try.
Rather than guess a third time, the give-up branch was given real
diagnostics -- `qemu.log`'s content, whether the qemu process was still
alive, and a raw `bash`-only `/dev/tcp` connect check independent of
`mpremote`/pyserial entirely -- and the next real failure answered it
outright:

```
examples/usercmodule/mpyhouse/v1.29.0-qemu-MPS2_AN385/micropython-v1.29.0-qemu-MPS2_AN385.elf: No such file or directory
qemu-system-arm: Could not load kernel '...'
```

The smoke step's own `$elf` path was wrong, and had been from the start:
`_dest_name()` (`orchestrate.py`) renames a collected artifact by
`produced.stem`, and `build_qemu()`'s own docstring -- read earlier in this
same record's own investigation, and not connected to this at the time --
says plainly "The output path is `opts.build_dir / firmware.elf`". Every
other port smoke-tested here produces a file literally named `micropython.*`,
so `micropython-<identifier>.elf` was typed by pattern-matching the other
three steps rather than checked against this port's own real output. The
real collected name is `firmware-<identifier>.elf`, confirmed directly from
a real job's own `ls -laR examples/usercmodule/mpyhouse` output. `qemu`
was never failing to bind a port or being held busy at all -- it was exiting
immediately, every single time, because the kernel image it was told to load
did not exist, and both the pty and the TCP-socket versions of this step
faithfully reported the only symptom visible from the client side of a
process that never started: "failed to access", indistinguishable from a
real contention error until something actually printed `qemu.log`.

Fixed by pointing `$elf` at `firmware-${identifier}.elf`, verified live
against the exact fixed YAML step for both the passing and the
deliberately-broken script. The retry loop and the give-up diagnostics both
stay: the loop still covers qemu's real (if brief) startup latency, and the
diagnostics are what actually found this bug rather than the two prior
theories -- removing them now would remove the only thing that worked.

[0069]: 0069-upstream-usercmodule-narrow-ci-slice.md
[0079]: 0079-collected-artifact-is-more-than-one-file.md
