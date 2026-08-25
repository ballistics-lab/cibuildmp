# 0024. unix/armhf and unix/mipsel are real, verified-live cross-compiles

- Status: Implemented
- Related: [0020], [0022], [0025]

<!-- migrated verbatim from docs/BACKLOG.md lines 1567-1616 -->

**D24 — `unix/armhf` and `unix/mipsel` are real, verified-live cross-compiles
now, closing M8's own acknowledged gap; the missing piece was never the
cross-compiler.** `UNIX_ARCH_SETTINGS["armhf"]`/`["mipsel"]` had been
pinned since **M8**'s first `build_unix()` slice, with `build_unix()`
deliberately raising `"not buildable yet"` rather than pretending —
both need a glibc-hosted cross-toolchain natmod's own bare-metal
`arm-none-eabi-`/`riscv64-unknown-elf-` pins don't cover, plus
`MICROPY_STANDALONE=1`'s own static-link `deplibs` pre-step (already
implemented, `run_unix_deplibs()`, but never actually run against a
real toolchain before now).

Both `gcc-arm-linux-gnueabihf` and `gcc-mipsel-linux-gnu` are plain
apt packages — confirmed live, no `ports.ubuntu.com` mirror dance at
all, unlike `aarch64`'s own `libffi-dev:arm64` (**D20**'s own
addendum): these are cross-compilers that *run* on `amd64`, not
target-arch libraries multiarch has to resolve. Wired the same
`shutil.which()`-plus-named-`apt_package` probe `aarch64`/`windows`
already use.

The one real, non-obvious blocker: `run_unix_deplibs()` failed on a
real host with `autoreconf: error: ... possibly undefined macro:
LT_SYS_SYMBOL_USCORE` — `deplibs`' own `./autogen.sh` regenerates
vendored `lib/libffi`'s `configure` from `configure.ac`, and that
macro is `ltdl.m4`'s, not `libtool.m4`'s. `autoconf`/`automake`/
`libtool` alone (all present on this project's own dev host already)
do **not** ship `ltdl.m4` — only the separate `libltdl-dev` package
does. Not documented anywhere upstream this was checked against
(neither `.github/actions/build-usermod-unix`'s own comments nor
libffi's own `README`/`INSTALL` mention it); found only by actually
running `deplibs` for real against a genuine cross-toolchain, exactly
the kind of gap that stays invisible until someone tries the real
thing rather than trusting the pinned settings table alone. Once
installed, both `deplibs` and the main build ran clean end to end —
verified twice: once calling `usermod/build.py`'s own functions
directly, once through the full `cibuildmp` CLI (`[usermod.unix]
archs = ["armhf"]`), each producing a genuine linked `ARM`/`EABI5` (or
`MIPS32`) ELF with a real custom C module built in and callable.

`UNIX_RUNNABLE_ARCHS` now equals every key `UNIX_ARCH_SETTINGS` pins
(`x64`/`x86`/`aarch64`/`armhf`/`mipsel`) — the `"not buildable yet"`
branch `build_unix()` used to raise is gone rather than left
unreachable; `usermod/targets.py`'s own default `unix` axis values
grew to include both, the same "default = everything currently
provable" rule `windows`/`arm64` and `unix`/`aarch64` already
followed once each was proven simple enough, not left as an opt-in
special case. `action.Dockerfile` does not yet bake in either
toolchain (same open gap **D23**'s own note already has for
`aarch64`) — a real, separate, still-open item for whoever tackles
that Docker-action gap next.
