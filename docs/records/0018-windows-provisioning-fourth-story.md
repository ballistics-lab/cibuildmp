# 0018. Windows provisioning is a fourth story, not a variant of download/docker/host

- Status: Accepted — final state: MSYS2 fully superseded, no Windows runner needed
- Related: [0003], [0019], [0020]

<!-- migrated verbatim from docs/BACKLOG.md lines 992-1007, then 1043-1087 (D19 sits between the two in the source file; kept together here as one record since both are dated follow-ups to the same D18 decision) -->

**D18 — Windows provisioning is a fourth story, not a variant of
`download`/`docker`/`host` (**D3**).** `build-usermod-windows` cannot set
up its own MSYS2 environment: its own contract says plainly that a
composite action's `shell: bash` steps "run under plain Git Bash on a
Windows runner, not inside the MSYS2 environment, so this action cannot
set up either one for itself" — `msys2/setup-msys2` has to run as the
caller's own step first, and every path fed into the action has to be a
`$(pwd)`-relative MSYS2 path, never `$GITHUB_WORKSPACE`/`$RUNNER_TEMP`
verbatim (both are native `D:\a\...` paths; MSYS2 bash's own unquoted
backslash-escaping silently mangles them — a real failure hit and fixed in
`mp-usermod.yml`, see its own "Write combined FROZEN_MANIFEST (windows)"
step comment). `cibuildmp`'s toolchain resolver (**M2**) has no MSYS2
awareness at all today; this is real orchestration work, not config, since
it spans installing an environment *and* how every subsequent path is
formed.

**D18 addendum — MSVC investigated and rejected as an alternative to
MSYS2.** `ports/windows` also supports building via `msbuild
micropython.vcxproj`, but neither it nor `msvc/sources.props` references
`USER_C_MODULES`/`FROZEN_MANIFEST` anywhere (confirmed by grep across
the whole `msvc/` tree) — `sources.props`'s file list is fixed at
project-authoring time, so a usermod's C sources could only be added by
hand-editing the `.vcxproj` per module, defeating the point of a driver
that takes them as parameters. Ruled out; MSYS2 (and later, its own
supersession below) is the only one of MicroPython's three Windows build
methods that takes those as parameters at all, and what `a7p`'s own
`mp-usermod.yml` already used in production.

**D18, final state — MSYS2 fully superseded, no Windows runner needed for
any arch.** `usermod/msys2.py` first landed and genuinely worked (a real
`windows-latest` run produced a real `micropython.exe` with a usermod
module linked in), catching four real bugs along the way: `build.py`'s
`Path` handling needed `.as_posix()` everywhere (bare `str()` is
backslash-separated on Windows and breaks GNU Make); two `test_emsdk.py`
tests were silently coupled to the CI host being linux-x64;
`tests/test_build.py`'s `touch`-based test needed a `cmd.exe`-compatible
replacement (`echo hi > marker`); and `ResolvedMsys2.to_posix_path()` had
to trust only the last non-empty stdout line, since MSYS2's own first-login
"Copying skeleton files..." notice was corrupting captured `cygpath -u`
output.

Superseded by two live-verified findings, not a clean first-guess: upstream
MicroPython's own CI (`tools/ci.sh`'s `ci_windows_setup`/`_build`) cross-compiles
`x64`/`x86` from Linux with a plain `apt install gcc-mingw-w64-x86-64`/
`gcc-mingw-w64-i686` and `make CROSS_COMPILE=...`, no Windows host at all;
`llvm-mingw` (`mstorsjo/llvm-mingw`) does the same for `arm64`, needing
three real Clang-vs-GCC diagnostic fixes (`-Wno-double-promotion`,
`-Wno-uninitialized`/`-Wno-default-const-init-var-unsafe`,
`COMPILER_TARGET=mingw-forced`/`STRIP=`/`SIZE=true`). All three verified
live with a real custom C module producing a genuine linked
`micropython.exe`/`.exe` for that arch.

Landed as `build.py`'s current `build_windows()` (`WindowsArchSettings` per
arch) plus `usermod/llvmmingw.py` for `arm64`'s toolchain (`x64`/`x86` need
only an apt-installed cross-gcc, no dedicated resolver). `usermod/msys2.py`
and its own CI jobs were deleted outright, not kept as a fallback: a second
working path to the same Makefile is surface area nothing exercises.
`windows` needs no `windows-latest`/`windows-11-arm` runner at all now, for
any of its three arches — relevant to **D20** below, which had assumed one
for all of them.
