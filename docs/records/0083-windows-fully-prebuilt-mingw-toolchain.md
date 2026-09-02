# 0083 — replace `windows.Dockerfile`'s apt `gcc-mingw-w64` split with one fully prebuilt llvm-mingw toolchain

Status: Proposed — a direction, not decided or implemented.
Related: [0018], [0025], [0044], [0046], [0068], [0082]

## What exists today

`docker/windows.Dockerfile` carries two toolchains for three arches:

- `x64`/`x86` — `apt install gcc-mingw-w64-x86-64 gcc-mingw-w64-i686`: Ubuntu's own build, resolved
  against whatever the base image's apt archive currently carries. Not version-pinned anywhere in
  this repo, and outside `bin/update_toolchains.py`'s own coverage (its `PINS` table only tracks
  this file's *other* toolchain, `llvm-mingw`, by GitHub release).
- `arm64` — `mstorsjo/llvm-mingw`, a genuinely prebuilt tarball, version + URL + sha256 pinned in
  the Dockerfile and tracked by `bin/update_toolchains.py`'s `PINS` (the "github" shape, compared
  against that repo's own `releases/latest`). Chosen originally because no Debian/Ubuntu package
  targets `aarch64-w64-mingw32` at all ([0018]).

`PATH="${PATH}:/opt/llvm-mingw/bin"` **appends** rather than replaces, specifically so
`/usr/bin`'s apt-installed `x86_64-w64-mingw32-gcc`/`i686-w64-mingw32-gcc` keep winning over
llvm-mingw's own same-named wrapper binaries (llvm-mingw ships all four Windows targets, Clang
under GCC-shaped names) — a deliberate choice recorded in the Dockerfile's own comment, to keep
`x64`/`x86` on "the exact toolchain upstream MicroPython's own CI uses" (D18).

## Why this is worth reconsidering now

[0082] found, live, that `windows`'s `container_mpy_cross()` build runs on this same image's
**native** `build-essential` gcc (`/usr/bin` wins the same way for the unprefixed `gcc` `make -C
mpy-cross` calls), and that gcc is `ubuntu:26.04`'s own unpinned default — currently 15.2.0,
already confirmed to break 9 of 24 known MicroPython tags on `-Werror=unterminated-string-
initialization`. That specific bug is a `mpy-cross` (native-build) problem, not a `gcc-mingw-w64`
(cross-target) one — switching `x64`/`x86` to llvm-mingw would not touch it by itself, since
`container_mpy_cross()` never invokes either mingw toolchain. But it is the same underlying
pattern [0068] already named twice for `natmod_host`/`ppc64le_linux`: **an apt package resolved
against whatever the base image's archive currently has, with no version recorded anywhere in
this repo, silently rides every `ubuntu:24.04`→`26.04`-shaped bump.** `x64`/`x86`'s
`gcc-mingw-w64-*` packages are the one remaining instance of that shape in `docker/`'s own
Windows story — everything else (`arm_embedded`, `riscv_embedded`, `xtensa_esp`,
`manylinux_2_41_mipsel`, `ppc64le_linux` since [0068]'s own fix, and `windows`'s own `arm64`
already) is a version+URL+sha256 pin, independent of the base OS, and — as important — already
inside `bin/update_toolchains.py`'s own staleness-check coverage ([0046]).

## The proposed direction

Fold `x64`/`x86` onto the same `mstorsjo/llvm-mingw` release `arm64` already pins, dropping the
`gcc-mingw-w64-*` apt packages entirely — one toolchain, one pin, three arches, matching the
shape every other cross-target image in `docker/` already uses. Concretely:

- `docker/windows.Dockerfile` (or a renamed `docker/mingw-64.Dockerfile`, if the rename is judged
  worth the identifier/image-group churn — not decided here) stops installing
  `gcc-mingw-w64-x86-64`/`gcc-mingw-w64-i686`/their `g++` counterparts, and stops needing the
  `PATH`-append ordering trick at all — there is only one toolchain family left, so nothing is
  being shadowed.
- `usermod/build.py`'s `WINDOWS_ARCH_SETTINGS` (the `-Wno-*` suppressions and
  `COMPILER_TARGET=mingw-forced`/`STRIP`/`SIZE` overrides the Dockerfile's own header already
  says are Make-level, arm64-only today) would need auditing for whether `x64`/`x86` now need the
  same Clang-specific handling arm64 already carries — llvm-mingw is genuinely one compiler
  family (Clang) for all three targets once this lands, not "GCC for two, Clang for one".
  Real work, not a Dockerfile-only change.
- `bin/update_toolchains.py`'s `windows` `PINS` entry needs nothing new — it already tracks this
  exact release by URL, and `x64`/`x86` would simply start moving with it instead of floating
  independently against apt.

## What this does not fix by itself

The [0082] gcc-15/`mpy-cross` problem is orthogonal — llvm-mingw's own Clang binaries never build
`mpy-cross` (a native host tool), so this image would still need `build-essential`'s native gcc
for that step regardless of what the Windows-target cross toolchain is. [0082]'s own "not decided"
list (suppress the warning, pin an older native gcc, or document the range) is unaffected by this
proposal and stays open on its own.

## Not decided here

- Whether `x64`/`x86` under llvm-mingw actually produce output MicroPython's own `ports/windows`
  build accepts without new `-Wno-*`/flag work — not tried live in this session, only reasoned
  from the Dockerfile's own existing arm64 comments.
- Whether to rename the file/image group (`mingw-64` or similar) — a real identifier-shape
  question ([0058]'s own image-group-naming precedent applies), not just a `FROM` edit, and would
  touch `resources/build-platforms.toml`'s `image` key, `pinned_docker_images.toml`, and every
  doc/test naming `windows`'s current group.
- Whether dropping the apt packages changes anything about `windows.Dockerfile`'s own build time
  or image size in a way worth measuring before committing to the change.

[0018]: 0018-windows-provisioning-fourth-story.md
[0025]: 0025-dockerfiles-bake-unix-cross-toolchains.md
[0044]: 0044-unix-native-images-landed.md
[0046]: 0046-pin-staleness-checker.md
[0068]: 0068-docker-dependabot-grouping-and-mipsel-ubuntu-26-04.md
[0082]: 0082-natmod-old-tags-fail-mpy-cross-under-gcc-15.md
