# Open questions

Living list of questions that are flagged but not yet designed or decided.
Not numbered — when one resolves, fold the resolution into the relevant
numbered record (or write a new one) and delete or update the entry here,
the same way [docs/0000-TRACKER.md](../0000-TRACKER.md) folds resolved
`docs/tasks/` notes into records.

<!-- migrated verbatim from docs/BACKLOG.md lines 3568-3648 -->

- ~~**MSYS2 and ESP-IDF orchestration for usermod (D18, D19).**~~ **Closed,
  and the question's own premise is gone with it.** It asked how MSYS2 and
  ESP-IDF fit "the existing `host`/`download`/`docker` toolchain-strategy
  shape" — there is no such shape any more: [0050] deleted the host
  toolchain resolver and the `--toolchain` flag outright, and every build of
  either family now runs in a pulled image ([0030]/[0033]/[0058]). Windows
  cross-builds inside the `windows` image with apt `mingw-w64`, no MSYS2 at
  build time at all; `esp32` installs ESP-IDF into `esp_idf_base` at build
  time, from each row's own `idf_version` ([0028]).
- **Windows/macOS hosts.** The download strategy makes a macOS host plausible
  for the arm/riscv/xtensa arches; `x86`'s multilib and the whole
  `docker` strategy are Linux-only. Decide whether phase 1 claims anything
  beyond Linux, or explicitly does not. **Both halves of the framing have
  moved since**: there is no download strategy left to make a macOS host
  plausible ([0050] — every build is a pulled image now), so the real
  question is narrower and only about reaching a Docker daemon. A real
  `windows-latest` CI run (in `usermod-dev.yml`, a workflow that has since
  been deleted) surfaced two concrete data points either way this gets
  decided, both fixed on sight rather than left for whenever that decision
  happens:
  - `tests/test_build.py`'s `test_pre_build_command_runs_in_module_root`
    used `touch marker` as its example `pre-build-command` -- `touch` has
    no `cmd.exe` equivalent, so it failed there, not because
    `run_pre_build_command()` itself is Windows-broken (`subprocess.run(...,
    shell=True)` correctly uses whatever shell the host has), but because
    the test's own example command happened to be Unix-only when the
    behaviour under test (does it run in `module_root`, with the given
    `env`) doesn't require that. Fixed to `echo hi > marker`, which
    `/bin/sh -c` and `cmd.exe /c` both understand identically.
  - `unix_make_command()`/`run_unix_deplibs()`/`qemu_make_command()`/
    `webassembly_make_command()` (now split across `usermod/build_unix.py`/
    `build_qemu.py`/`build_webassembly.py`) all embedded `Path`
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
  Linux-only, unchanged.

  **There is no stated answer for a Windows end user right now.** This
  paragraph used to give one — run `cibuildmp` inside Docker under WSL2,
  using the repo's own root `Dockerfile` — and then negated it in its own
  final sentence, because [0033] deleted that `Dockerfile` once usermod
  needed to launch sibling containers (Docker-in-Docker was ruled out).
  What is true today: `cibuildmp` is a Python package that needs a
  reachable Docker daemon, so WSL2 with Docker Desktop is the shape that
  should work, and nobody has run it that way and reported back. Until
  someone does, this is the open question, not a recommendation.
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
- **Pin staleness** moved out of this file and into its own record, [0046] --
  it had grown from a question into a work item with an inventory and a decided
  shape. Short version: `bin/update_docker.py` ([0044]) covers both container
  image tables and nothing else does, for anything else.

- ~~**The musllinux half of D31.**~~ **Built** ([0044]). Seven
  `musllinux_1_2_<arch>` cells declared, Dockerfile-backed on pypa's own
  Alpine images, published, and the identifier axis threaded through.
  Proven on one cell, `musllinux_1_2_x86_64`: `libc.musl-x86_64.so.1` in
  `NEEDED`, zero `GLIBC_` symbol references, and both a usermod C module
  and a frozen Python module running. The other six have never been
  built. What remains open is narrower than the original question: how
  far the glibc column's behaviour carries over — and Alpine's own
  `community/micropython` excludes `ppc64le` and `s390x` outright, which
  is the strongest available hint about which two to expect trouble from.

- ~~**Whether a non-native build should be attempted at all when emulation
  is absent.**~~ **Answered** ([0044]): attempted, but it fails legibly
  first. `dockerrun._probe_platform()` runs one throwaway `uname -m` for
  any non-native target and turns `exec format error` into a message
  naming the missing binfmt and how to install it — and separately
  distinguishes "this image is not published for that platform", which is
  a pin problem rather than a host one. cibuildwheel's stance is kept
  otherwise: cibuildmp still neither probes for nor installs emulation as
  a precondition, it only refuses to fail incomprehensibly.

- **Whether emulated `unix` builds are fast enough to be the default —
  now with a real measurement, and it is not close.** [0043] asked for
  one before fixing the default; [0044] has it, on the same machine and
  the same example project: native `manylinux_2_28_x86_64` **46s**,
  native `musllinux_1_2_x86_64` **50s**, emulated
  `manylinux_2_28_aarch64` **1041s** — roughly 20x. The default axis is
  five cells of which three are emulated on an amd64 host, so a plain
  local `cibuildmp` run is tens of minutes where a native-only one would
  be under a minute.
  What is still open is the *decision*, not the number: cibuildwheel's
  answer is `CIBW_ARCHS=auto`, native-only by default with everything
  else opt-in. cibuildmp cannot say that yet — usermod has no `--archs`
  and no `auto`/`all`/`native` vocabulary at all ([0045]). And it has a
  wrinkle upstream does not: a cell is (arch × libc), so a "native" arch
  yields two cells, one of which is musl and therefore native for
  *building* but not for running on a glibc host. That has to be decided
  explicitly rather than inherited by analogy.

- ~~**A real glibc-floor checker for `unix` (the `auditwheel`-equivalent
  PEP 600/656 work).**~~ **Built** ([0044]). `verify_unix_floor()` reads
  the finished binary's own highest required `GLIBC_x.y` symbol version
  via `pyelftools` — `auditwheel`'s `elf_find_versioned_symbols` job,
  reimplemented because that CLI only accepts a `.whl` and `unix`
  produces a bare executable — and fails when it exceeds the floor the
  identifier claims. Verified against a real binary: a
  `manylinux_2_28_x86_64` build requires exactly `GLIBC_2.28`, the check
  accepts that target and rejects a `manylinux_2_17_x86_64` claim on the
  same file. The PEP 656 half is deliberately not symmetrical: musl has
  no symbol versioning, so a musl build's guarantee comes from its pinned
  base rather than from inspection.

[0018]: ../records/0018-windows-provisioning-fourth-story.md
[0019]: ../records/0019-esp-idf-provisioning-heaviest.md
[0028]: ../records/0028-container-per-port-migration-plan.md
[0030]: ../records/0030-container-approach-natmod-and-docker-vs-qemu.md
[0031]: ../records/0031-unix-musllinux-libc-axis.md
[0033]: ../records/0033-cibuildmp-never-builds-docker-image-itself.md
[0042]: ../records/0042-windows-docker-wiring-and-resolver-removal.md
[0043]: ../records/0043-unix-adopts-cibuildwheel-native-image-model.md
[0044]: ../records/0044-unix-native-images-landed.md
[0045]: ../records/0045-only-is-a-filter-not-a-forced-identifier.md
[0046]: ../records/0046-pin-staleness-checker.md
[0050]: ../records/0050-natmod-is-docker-only.md
[0058]: ../records/0058-image-groups-are-toolchains-not-ports.md
