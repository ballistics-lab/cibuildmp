# Open questions

Living list of questions that are flagged but not yet designed or decided.
Not numbered — when one resolves, fold the resolution into the relevant
numbered record (or write a new one) and delete or update the entry here,
the same way [docs/0000-TRACKER.md](../0000-TRACKER.md) folds resolved
`docs/tasks/` notes into records.

<!-- migrated verbatim from docs/BACKLOG.md lines 3568-3648 -->

- **MSYS2 and ESP-IDF orchestration for usermod (D18, D19).** Neither fits
  the existing `host`/`download`/`docker` toolchain-strategy shape as-is —
  MSYS2 is an environment a caller sets up around the job, not a toolchain
  `cibuildmp` fetches into a cache directory, and ESP-IDF's own install is
  heavy enough that it may need its own strategy rather than reusing
  `download` unmodified. Not designed yet; flagged so M6+ doesn't rediscover
  the gap from scratch. (Largely resolved in practice — see [0018] and
  [0019] — kept here as the original framing.)
- **Windows/macOS hosts.** The download strategy makes a macOS host plausible
  for the arm/riscv/xtensa arches; `x86`'s multilib and the whole
  `docker` strategy are Linux-only. Decide whether phase 1 claims anything
  beyond Linux, or explicitly does not. A real `windows-latest` CI run
  (`usermod-dev.yml`, added for M9's own D18 work) already surfaced two
  concrete data points either way this gets decided, both fixed on sight
  rather than left for whenever that decision happens:
  - `tests/test_build.py`'s `test_pre_build_command_runs_in_module_root`
    used `touch marker` as its example `pre-build-command` -- `touch` has
    no `cmd.exe` equivalent, so it failed there, not because
    `run_pre_build_command()` itself is Windows-broken (`subprocess.run(...,
    shell=True)` correctly uses whatever shell the host has), but because
    the test's own example command happened to be Unix-only when the
    behaviour under test (does it run in `module_root`, with the given
    `env`) doesn't require that. Fixed to `echo hi > marker`, which
    `/bin/sh -c` and `cmd.exe /c` both understand identically.
  - `usermod/build.py`'s `unix_make_command()`/`run_unix_deplibs()`/
    `qemu_make_command()`/`webassembly_make_command()` all embedded `Path`
    objects via bare `str()`, which is backslash-separated on Windows --
    real breakage, not a test artifact, since GNU Make (native or MSYS2)
    wants forward slashes regardless of host OS. This is the exact bug
    **D18** already documented for `a7p`'s own hand-written workflow
    (`$GITHUB_WORKSPACE`'s native form, mangled by MSYS2 bash's own
    escaping) -- caught here before it shipped instead of after. Fixed to
    `.as_posix()` everywhere a `Path` reaches a `make` command line.

  Partially answered since, not closed: **D18**'s own windows-usermod
  story ended up needing no Windows host at all (all three arches
  cross-compile from Linux — see **D18**'s own addenda), so `cibuildmp`
  itself running natively on Windows stopped being a real question for
  usermod specifically. `x86`'s multilib and `docker` (D3) are still
  Linux-only, unchanged. The repo's own root `Dockerfile` + README's own
  "Target support" tables are the answer for an actual Windows end user
  today: run `cibuildmp` inside Docker under WSL2, not natively on
  Windows Python — not verified with a real `docker build`/`docker run`
  in this project's own dev sandbox (Docker does not run there at all,
  the same finding **D19**'s own addendum already recorded), but every
  ingredient in it was checked directly: each `apt install` package
  live-installed and used for a real build earlier in this same session,
  and `uv tool install .` → `cibuildmp --dry-run` run for real outside
  the container. (The root `Dockerfile` itself was later deleted — see
  [0033].)
- **Old tags vs. a modern host `gcc`.** Found while verifying **D13** live:
  `v1.21.0` fails to build `mpy-cross` under a recent `gcc`
  (`-Werror=unterminated-string-initialization` on upstream's own
  `py/emitinlinethumb.c`/`emitinlinextensa.c`). `mpy-cross` is a host
  build, so this is not a cross-toolchain problem the resolver can route
  around. Unclear yet how far back tags stay buildable, or whether that
  is worth a documented "known good" floor, a suggested
  `CFLAGS=-Wno-error` escape hatch, or just something a user hits and
  works around per-project.
- **Toolchain pinning vs. reproducibility.** Pinned tarball versions make
  builds reproducible but drift from what a contributor has on `PATH`. The
  `host` strategy running first means a laptop and CI can silently use
  different compilers — acceptable, but the summary output must always say
  which toolchain was actually used.
- **Nothing checks whether a pinned version is stale.** Dependabot already
  watches this repo's own `uv`/Actions dependencies (the "Graph Update"/
  "github_actions ... Update" runs in Actions history), but it has no
  visibility into the pins that actually matter here: every toolchain
  version + sha256 in `resources/natmod.toml`/`resources/usermod.toml`
  (arm-none-eabi, xtensa-esp, riscv-none-elf, and now emsdk), and the
  MicroPython release tag each `examples/*/cibuildmp.toml` builds against.
  All of that goes stale on an upstream's own schedule, same as **D10**
  already says about the toolchain table specifically — but nothing here
  today notices *when*, for any of it, MicroPython tag included. Not
  designed yet: could be a periodic job that diffs each pin against
  upstream's latest release and opens an issue/PR, a documented manual
  review cadence, or something narrower per pin (e.g. a script that
  re-derives the emsdk hash for a given alias and flags drift). Flagged so
  a real staleness incident (a build that quietly stops matching upstream)
  doesn't become the way this gap gets found.
- **The musllinux half of D31.** An Alpine-based `unix-musllinux-<arch>`
  Dockerfile per arch, plus the identifier axis to name it, is designed but
  not built — see [0031].
- **A real glibc-floor checker for `unix` (the `auditwheel`-equivalent PEP
  600/656 work).** Designed, not built — see [0031]'s own closing section.

[0018]: ../records/0018-windows-provisioning-fourth-story.md
[0019]: ../records/0019-esp-idf-provisioning-heaviest.md
[0031]: ../records/0031-unix-musllinux-libc-axis.md
[0033]: ../records/0033-cibuildmp-never-builds-docker-image-itself.md
