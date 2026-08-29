# 0036. M2 — toolchain resolver

- Status: Implemented (done)
- Related: [0003], [0010]

<!-- migrated verbatim from docs/BACKLOG.md lines 643-725 -->

### M2 — toolchain resolver — **done**

`src/cibuildmp/toolchains.py`, with every pin in
`src/cibuildmp/resources/natmod.toml`.

- [x] Resolver returning a `ResolvedToolchain` (strategy, prefix, `bin_dir`
      for `PATH`, and any `make` overrides) or a clear "not available here"
      error naming the apt package.
- [x] Strategies `host` → `download`, `--toolchain=auto|host|download`.
      `host` is tried first so a CI runner with the apt packages installed
      behaves exactly as `build-natmod` does today and downloads nothing.
- [x] Pins verified against the real releases, not assumed: arm-none-eabi
      15.2.1-1.1 and riscv-none-elf 15.2.0-1 from xpack, xtensa-esp-elf
      16.1.0_20260609 from `espressif/crosstool-NG`, xtensa-lx106 from
      micropython.org (the tarball `ci_esp8266_setup` uses).
- [x] sha256 for every download — xpack's own `<asset>.sha` sidecar where it
      exists, a literal pin (computed locally) for Espressif and
      micropython.org, which publish none.
- [x] **Confirmed: `xtensawin` does not need ESP-IDF.** `dynruntime.mk` asks
      only for `xtensa-esp32-elf-` on `PATH`, and the `build-natmod` action's
      own comment already says `install.sh` just downloads the toolchain from
      GitHub releases. Fetching that release directly replaces an
      `esp-idf` clone plus installer — the heaviest step in this repo's CI —
      with an 84 MiB tarball. Measured end to end: 21 s cold, including the
      download.
- [ ] `docker` strategy. Dropped from natmod scope, not forgotten: every
      natmod arch is a cross-compile running on the build host, so a
      container adds isolation but no capability. It belongs to usermod.

**Prefix reconciliation.** `dynruntime.mk` hardcodes `riscv64-unknown-elf-`
(Debian's naming) and `xtensa-esp32-elf-`, while the tarballs ship
`riscv-none-elf-` and a unified `xtensa-esp-elf-`. Rather than symlinking a
fake prefix into the cache, the resolver appends `CROSS=<actual>` to the
`make` command line: `dynruntime.mk` assigns `CROSS` with `=` inside its
per-ARCH `ifeq` chain and never marks it `override`, so a command-line
variable wins — including for the `$(shell $(CROSS)gcc …)` picolibc probe
evaluated while the makefile is parsed.

**picolibc.** Resolved, and it is not the risk it looked like.
`dynruntime.mk` probes `--print-file-name=picolibc.specs` and adds `-specs=`
only when the toolchain has it; the apt path installs
`picolibc-riscv64-unknown-elf` explicitly, and the xpack build falls back to
its own newlib. Worth keeping an eye on: the two paths therefore link
against different libcs, which is invisible until something misbehaves.

**`x86` is the one arch that cannot provision itself.** What it needs is the
host compiler's 32-bit runtime, which no cross-toolchain tarball supplies.
Finding `gcc` on `PATH` proves nothing there, so the resolver compiles
a real translation unit with `-m32` (a `probe-args` entry in the resource
file) and, on failure, errors naming `gcc-multilib` rather than letting the
build fail later with a confusing compiler diagnostic.

**Fixed after M3 caught it live:** the probe originally compiled an
*empty* translation unit (`-xc -c -` on empty stdin). `-m32` alone is
always a valid codegen flag, so that always succeeds even when the 32-bit
glibc headers/libs are entirely absent — the probe never actually touches
a header. `examples/template`'s CI hit exactly this on `ubuntu-latest`
(no 32-bit multilib by default): resolution reported `x86` fine, then the
real build failed deep inside `dynruntime.mk` with `bits/wordsize.h: No
such file or directory`. The probe now compiles *and links* `#include
<stdio.h>\nint main(void) { return 0; }`, which exercises the same header
chain and the 32-bit crt/libc a real natmod build needs.
`build-template.yml` also needed its own `apt-get install gcc-multilib`
step — `.github/actions/build-natmod` already apt-installs it for `ARCH=x86`
in its own "Install cross-compiler" step, but `build-template.yml` goes
through the CLI (`action.yml`) instead of that composite action, so it
does not inherit it.

**Why not just add a `docker` strategy for `x86` and be done with it?**
It would work — `x86` is in fact the *one* natmod arch where a container's
isolation is worth something, since it is not a cross-compile at all but
the host's own `gcc -m32`, which genuinely needs an isolated 32-bit
userland the way the other nine arches' downloaded toolchain tarballs
already carry their own target sysroot without one. Not done anyway: a
container engine dependency, image pulls, and losing "runs on a laptop
with no root and no mutation of the host" (**D3**) is a real cost to pay
for one arch out of ten, when the fix is the one-line `apt-get install
gcc-multilib` every real consumer's CI already runs today (and a laptop
user hits once, not per build). `docker` stays dropped from natmod scope
for the same reason recorded above and revisits only for usermod, where
port builds have real system dependencies a cross-toolchain tarball
cannot express at all — not just x86's narrower one.
