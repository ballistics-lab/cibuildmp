# 0020. Usermod runner selection is structural (revisits D9)

- Status: Accepted
- Related: [0009], [0018], [0024]

<!-- migrated verbatim from docs/BACKLOG.md lines 1088-1142 -->

**D20 (revisits D9) — usermod runner selection is structural, confirmed
live, not a hypothetical "different targets need different runners."**
`mp-usermod.yml`'s matrix already needs four distinct `runs_on:` values
(`ubuntu-latest`, `ubuntu-24.04-arm` ×2 rows, `windows-latest` ×2,
`windows-11-arm`), and unlike natmod's ten-cross-compiles-on-one-host,
several of these are load-bearing rather than a preference: aarch64 and
armhf both need to *execute* what they build (a native run, not qemu), so
the wrong runner doesn't just cost time, it silently stops proving
anything. `Target.default_runner` and `--print-build-matrix` (**M0**)
already exist for exactly this; usermod is the build mode where per-target
fan-out should probably be the default rather than **D9**'s opt-in, not
because sharing the fetch-MicroPython/mpy-cross cost stops mattering, but
because the runner constraint dominates it the way it does for
cibuildwheel's own OS axis.

**D20 addendum — `windows` no longer needs `windows-latest` at all, for
any of its three arches — a deliberate divergence from `a7p`'s own matrix
above, not an oversight.** **D18**'s own two-stage supersession (MSYS2 →
Linux-hosted cross-compiles: apt-gcc for `x64`/`x86`, a downloaded
`llvm-mingw` for `arm64`) means `build_windows()` runs on the same host
every other usermod port here does — `ubuntu-latest`, all three arches,
no ARM host needed either (the `llvm-mingw` resolver is itself pinned to
a `linux-x64`-hosted release tarball, `usermod/llvmmingw.py`'s own
`_host_platform_key()`). The `runs_on:` table above still accurately
describes what `a7p`'s own workflow needs, matched target-for-target; it
does not describe what this project's own `--print-build-matrix` should
emit for the `windows` identifiers once **M10** wires this up — that
table should list `ubuntu-latest` for all three, not `windows-latest`/
`windows-11-arm`. Left as a note for whoever implements **M10**, not
acted on here.

Does not generalize to "usermod needs only `ubuntu-latest`" quite as far
as it might first look: `unix`'s own `aarch64` arch used to assume a
native ARM64 host too (`UNIX_ARCH_SETTINGS["aarch64"]` had an *empty*
`cross_compile`) — corrected the same way `windows` was, once actually
tested rather than assumed. A real `ubuntu-latest` run (this project's
own `usermod-dev.yml`, its `unix-aarch64-cross-check` job before it was
folded in and removed) showed `apt install gcc-aarch64-linux-gnu
libffi-dev:arm64` cross-compiles cleanly from x86_64, no native ARM64
host needed after all — the only real wrinkle was that `libffi-dev:arm64`
needs `dpkg --add-architecture arm64`'s own sources pointed at
`ports.ubuntu.com` first (Ubuntu's default `archive.ubuntu.com`/
`security.ubuntu.com` mirrors only carry `amd64`/`i386`; this is real for
any Ubuntu host, not specific to this project's own dev sandbox or to
GitHub's runners). `UNIX_ARCH_SETTINGS["aarch64"]` now has a real
`cross_compile="aarch64-linux-gnu-"` and `apt_package` for it.
`armhf`/`mipsel` were the same story a second time (**D24**): apt
cross-compilers, no execution-host constraint, no special runner
needed — just a genuinely new host dependency (`libltdl-dev`) neither
`aarch64` nor `windows` needed, found only by actually running the
build rather than assuming the pinned settings alone were enough.
`windows` and now `unix/aarch64`/`armhf`/`mipsel` are what stopped
needing a special-case runner; the runner matrix as a whole still has real,
load-bearing entries beyond `ubuntu-latest` for what's left.
