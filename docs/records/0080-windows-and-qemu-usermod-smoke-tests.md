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

[0069]: 0069-upstream-usercmodule-narrow-ci-slice.md
[0079]: 0079-collected-artifact-is-more-than-one-file.md
