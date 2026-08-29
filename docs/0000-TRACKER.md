# Tracker

Index and current state for the project's engineering records. These are working notes
that span multiple sessions — **not** user-facing docs (see `README.md` and
`CHANGELOG.md` for those). The structure itself is decided in
[record 0041][0041], adapted directly from `o-murphy/rp2040py`'s own
`docs/0000-TRACKER.md`/`docs/records/` scheme.

## Conventions

- **`records/NNNN-*.md`** — numbered, immutable, append-only. For records `0001`-`0033`
  the number is the decision's own pre-existing `D`-number (`D9` is `0009`, `D25` is
  `0025`, …) — kept as-is during the split specifically so every in-text cross-reference
  ("supersedes D9", "closing D28's own gap") still resolves without rewriting. Records
  `0034`-`0038` are the `M0`-`M5` build-phase write-ups (no `M4` — folded into `M3`, see
  `0037`); `0039`/`0040` are the usermod-status and deferred-tests notes; `0041` is this
  restructure itself. The number is a stable ID, **not** a claim about implementation
  order — `D32` appears before `D29`/`D30`/`D31` in the original document, for instance.
- **Status** line at the top of each record: `Accepted` for a locked design decision,
  `Implemented` / `Implemented (done)` for a build phase that shipped, `In progress` where
  real work remains, `Proposed` for a record that scopes work and names what is in the way
  without deciding it (`0054`-`0057`), `Not scheduled` for explicitly deferred work.
- **A record whose code landed is not automatically fully closed.** Several records
  document a decision that shipped but still carry their own "still open" / "not started"
  items inside (`0038`'s two open M5 checkboxes, `0022`'s unstarted `rp2` build driver,
  `0031`'s unbuilt musllinux half). Those rows stay in "In progress / Proposed" below, with
  the open items summarized in the row's own note — read the record for the detail.
- **Supersession is noted, not deleted.** `0018`'s MSYS2 approach was superseded by a
  Linux cross-compile approach *within the same record* (kept as dated addenda); `0028`'s
  local-Docker-build mechanism was later superseded by `0033`'s pull-only design — `0028`
  itself carries a preface note saying so and stays as the historical account of how the
  container-per-port migration actually happened. Nothing is deleted or rewritten in place.
- **`reference/`** — living, unnumbered design docs and open questions. Not a decision
  history; kept current with what is true today, cross-linking back to the records that
  explain *why*.
- **A row's own note is a sentence or two, not an essay.** Found live, three times
  now: a premise-table cell, a closed-item row, and an epic's own summary row each
  grew past 1700 characters across repeated same-session edits before being trimmed
  back down. When a new fact needs recording, prefer editing the row's existing note
  down to fit the new fact over just appending another clause — the row should read
  the same length after ten edits as after one.

## Ideas

### In progress / Proposed

- [ ] [0038] M5 -- adopt cibuildmp in the three consuming repos | the only item
      with external blast radius. Archiving `micropython-native-ci` is **done**
      (verified 2026-08-28: `archived: true`, and all three repos' `origin/main`
      carry zero `uses:` of it -- the one a7p hit is a comment). What remains is
      the repin: the repos pin `cibuildmp@v0.3.0`, and since that tag `unix`
      identifiers were renamed by [0044], `--toolchain`/`--print-build-matrix`
      were deleted by [0049]/[0050], and natmod became Docker-only. [0044]'s
      own row is now closed, so nothing is left to wait for -- and the longer
      HEAD moves, the bigger the one migration gets. **`esp32` no longer
      needs to stay on its own composite action** -- [0028] closed
      2026-08-28 (`build_esp32()` went Docker), so the repin can cover all
      five usermod ports now, not four
- [ ] [0038] reduce `.github/actions/build-natmod` to a wrapper over
      `cibuildmp --only <id>` | split out of the row above 2026-08-28 because
      it is this repo's own work, not the consuming repos'. It grew teeth
      since it was written: the action is 133 lines that never mention
      cibuildmp, carrying per-`ARCH` apt packages, an xtensa install and an
      esp-idf install of its own -- and [0050] deleted cibuildmp's bare-host
      toolchain path outright, so this is now the *only* bare-host natmod
      toolchain implementation left in the project, a second implementation
      with no first left to agree with
- [ ] [0047] run output should look exactly like cibuildwheel's | design
      corrected 2026-08-28 against an installed cibuildwheel 4.1.0: the folds
      are per *step* inside a build, not per build identifier -- the
      `[ n/m ] <identifier>` spine stays unfolded, and one active group at a
      time is enforced, not conventional. **`stepsummary.py` half shipped
      2026-08-28**: HTML table (Output/Size/Build identifier/Time/SHA256),
      options `<details>` block, right-aligned footer -- append-not-truncate
      and hand-formatted sizes/durations (no `humanize` dep) kept as
      deliberate departures. Terminal log folding, colour/symbols and
      `::error::`/`::warning::`/`::notice::` annotations still not started
- [ ] [0046] nothing notices when a pin goes stale, except container images |
      independent of everything above, no urgency. `bin/update_docker.py` covers
      both image tables; emsdk is the cheapest thing left (its own
      `emscripten-releases-tags.json` maps version to build hash) and
      `xtensa-lx106` the only genuinely hard one, having no version at all.
      The four toolchain tarballs moved into `docker/natmod.Dockerfile` in
      [0050] and are a fifth thing nothing watches
- [ ] [0022] zephyr as a third usermod selector axis (epic) | phase outline
      M6-M9b mostly landed; `rp2`'s own build driver closed 2026-08-29 by
      [0060], live-verified. Zephyr itself still not started
- [ ] [0040] usermod test-runner axis | not scheduled ([0006] holds); four of
      seven runners already proven by `mp-usermod.yml`, not yet owned by
      cibuildmp
- [ ] [0053] nine usermod ports have verified rows in `build-platforms.toml` but no real `build_<port>()` driver | `mimxrt`, `samd`, `stm32`, `psoc-edge`, `alif`, `esp8266`, `cc3200`, `renesas-ra`, `nrf` -- flagged by the user as the genuinely larger remaining piece. `rp2` closed 2026-08-29 by [0060]
- [ ] [0054] an `examples/` usermod fixture on upstream's own `examples/usercmodule` | `template/`'s usermod side proves a module cibuildmp wrote for itself; upstream's proves the contract. Three things it adds that nothing here covers: C++ (`cppexample` needs `SRC_USERMOD_CXX` and `-lstdc++`, unverified on `windows`/`webassembly`/`qemu`), a separate `qstrdefs*.h`, and a dotted package. Ships both `micropython.mk` and `micropython.cmake` for one tree -- [0016]'s own reference implementation of both halves
- [ ] [0055] an `examples/` natmod fixture on upstream's own `examples/natmod` | checking it first turned up the real finding: **upstream's own natmod modules do not satisfy cibuildmp's contract**. `py/dynruntime.mk` declares only `all`/`clean`, `all` leaves `$(MOD).mpy` at module root, and `BUILD ?= build` is not arch-scoped -- so `dist` plus `build/<arch>*/` is a *downstream* convention inherited from `micropython-native-ci`, not "every natmod Makefile in the wild". Shim, or teach `collect_output()` a fallback, or narrow the contract on purpose
- [ ] [0056] build upstream MicroPython through the usermod path with no user C module | wanted, and the driver work is settled (the five drivers stop passing `USER_C_MODULES=` unconditionally; the mount list is *rebuilt*, not shortened, since the manifest reaches the container only via the `"."` mount; `verify_output()`'s module-symbol assertions become conditional). **How absence is expressed is open** -- (A) `no-user-c-modules = true`, mutually exclusive with `user-c-modules`, both given a load-time error rather than a precedence rule ([0048]'s lesson), checked via `opt("user-c-modules")` with no `default=` since the key always has a value otherwise; or (B) drop the `"."` default outright so unset means none, which removes a key and a rule instead of adding them and makes the key behave like `manifest` -- exactly one config in existence depends on that default, `examples/template`'s own. Upstream needs nothing under either
- [ ] [0057] more than one module per build | **decided, both halves, and both are documentation rather than mechanism.** natmod: one config per module -- `examples/template` and `examples/wasm2mpy` already demonstrate it, and `collect_output()`'s two-`.mpy` refusal becomes the guard for a mis-scoped config. usermod: `user-c-modules` stays one path; N modules live in the consumer's own layout -- subdirectories on Make ports (`py/py.mk` globs `*/micropython.mk`), an aggregating `micropython.cmake` that `include()`s the others on CMake ports. No list, because the aggregator is the consumer's file rather than one cibuildmp generates ([0002]) and one key keeps one meaning ([0052]). The trap the docs must name: upstream's own `examples/usercmodule/micropython.cmake` lists only `cexample`/`cppexample`, so the same directory yields three modules on a Make port and two on a CMake one. [0054]'s fixture is what tests both forms -- neither has ever run here
### Implemented

- [x] [0065] bucketed test-matrix planning | replaces [0062]'s per-port
      `workflow_call` fan-out (which fixed a matrix-*size* ceiling that
      was never the real bottleneck) with `bin/plan_test_matrix.py`:
      resolves the real ordered identifier list and bin-packs it into
      at most 20 buckets, balanced by a real-run-seeded time estimate,
      split by runner class first (unix `aarch64`/`armv7l` on
      `ubuntu-24.04-arm`, everything else `ubuntu-latest`). Each bucket
      runs with `--keep-going` ([0063]) and uploads a JSON report;
      `aggregate-results` renders the summary from those reports, in the
      plan's own identifier order rather than upload order or a sort.
      `test-platforms.yml` is now a thin single-job building block
      (still directly dispatchable); `action.yml` grew a `keep-going`
      input so it can reach `--keep-going` through the real composite
      action rather than a bypass
- [x] [0063] `--keep-going` and a JSON build report | added for
      `test-platforms.yml`-style coverage sweeps: off by default (every
      existing caller's fail-fast behaviour is unchanged), on it lets
      `build_all()`/`orchestrate.build()` survive a target's own failure
      (and a tag group's own fetch failure) and keep attempting the rest.
      A JSON report -- one file per invocation, `{identifier, duration,
      error, output_dir, size, files}` per target -- is written
      unconditionally, `--keep-going` or not, under `cache_root() /
      "reports"` (`CIBMP_REPORT_PATH` to redirect). Checked live against a
      real cibuildwheel 4.2.0 install first: upstream's own `build()` is
      fail-fast unconditionally too, with no keep-going concept at all --
      this is a genuine cibuildmp-only divergence. `test-platforms.yml`
      itself does not use any of this yet -- batching identifiers per
      image group and wiring `--keep-going` in is separate follow-up work
- [x] [0062] `test-platforms.yml` split into a per-port orchestrator | landed
      2026-08-29, closing the real (not hypothetical) 211/256 amd64-matrix
      headroom [0060]'s own 74 rp2 identifiers exposed, with nine more usermod
      ports ([0053]) and zephyr ([0022]) still queued. `test-platforms.yml`
      itself became a reusable `workflow_call` (kept its own `workflow_dispatch`
      too, for single-target-set debugging); new `test-all-platforms.yml`
      orchestrates one call per port, each with its own independent 256 cap.
      Per-port `build` globs verified to union back to exactly the prior
      single-glob selection (231 identifiers, checked directly, not assumed).
      Live-caught mid-design: an omitted `--skip` is not an empty one --
      `examples/template`'s own config-level skip silently re-applied and
      dropped twelve emulated unix cells until every call started passing
      `skip` explicitly
- [x] [0061] usermod build drivers split per port, cibuildwheel-style | `usermod/build.py`
      (1628 lines, seven ports' worth) split into `build_common.py` + one `build_<port>.py`
      each, mirroring cibuildwheel's own `linux.py`/`macos.py`/`windows.py`/`pyodide.py` +
      `util.py` shape -- read directly before choosing it, not recalled. No behavior change;
      `tests/test_usermod_build.py` split the same way, 371 tests passing before and after
- [x] [0060] `rp2` build driver, live-verified | closes [0022]'s own last unstarted item
      ("no Pico SDK resolver, no live verification") and removes `rp2` from [0053]'s list.
      Config/image side was already done; only `build_rp2()` was missing, modeled on
      `build_esp32()`. Live-caught: the port's own `make ... submodules` target cannot run
      against a real release-tarball checkout at all ("fatal: not a git repository") --
      MicroPython's tarball already vendors every `lib/` submodule, so `build_rp2()` runs no
      provisioning step at all; `RP2_SUBMODULES` is threaded into
      `sources.fetch_micropython()` instead, reached only on its clone path (a preview tag
      with no tarball), reusing the exact mechanism natmod's own `micropython-submodules`
      already proved. Live-verified: a real `examples/template` build against
      `v1.29.0-rp2-RPI_PICO` producing a genuine 681984-byte `firmware.uf2` with the
      fixture's own C module linked in
- [x] [0028] full container-per-port migration plan (epic) | **closed 2026-08-28**: `esp32` was the last port still provisioning onto the bare host ([0050] had already taken it out of the default set for exactly that reason); `build_esp32()` now runs entirely inside `esp_idf_base` ([0058]) -- only the ESP-IDF `git clone` itself (source, not a binary) stays host-side, matching `mpy_dir`'s own mount convention. `esp32` also moved out of `orchestrate.py`'s `_HOST_MPY_CROSS_PORTS`, since a host-built mpy-cross is now exactly the "wrong glibc" mismatch `container_mpy_cross()` exists to prevent. Two more real bugs found only by running a genuine build end to end, not by review: `examples/template` had no `micropython.cmake` at all (esp32 had never actually built through this project's own fixture before -- `unix`/`windows`/`webassembly`/`qemu` are all Make ports, whose directory-shaped `USER_C_MODULES` happens to also cover the config's own `manifest = "usermod/manifest.py"` as a mount side effect; esp32's own `USER_C_MODULES` is a single `.cmake` file, so its container never saw that manifest at all until the mount became the file's parent directory instead); and `fetch_esp_idf()`'s plain `--recursive` clone was needlessly slow against MicroPython's own documented advice ("you don't need a full recursive clone" -- `tools/ci.sh`'s `ci_esp32_idf_setup`), fixed to the same two-step `--depth 1` + `submodule update --filter=tree:0` that script uses. Live-verified: a real `examples/template` esp32 build producing a genuine `micropython.bin` with the project's own C module linked in. **Second addendum, same day**: `idf_version`/`idf_target` now threaded from each target's own real row (`targets.py`'s `esp32_idf_info()`) instead of always resolving `Esp32BuildOptions`' dataclass defaults -- live-verified for both Xtensa (`ESP32_GENERIC`) and RISC-V (`ESP32_GENERIC_C3`, confirmed via its own build log resolving the `esp32c3` toolchain, not `esp32`)
- [x] [0058] the image axis is the toolchain, not the port | resolver cutover landed 2026-08-28: `pinned_docker_images.toml` is one flat `[image_group]` table, `image_for()` lost its `unix` special case, `unix_targets()` reads `build-platforms.toml` directly, `natmod`/`qemu` thread `arch`/`board` through to resolve per-target, `natmod.Dockerfile`/`qemu.Dockerfile` deleted, all seven toolchain images (+`esp_idf_base`) published and pinned. Two bugs only running it for real found: natmod/qemu briefly resolving to no image (missing arch/board threading, fixed same session) and `webassembly`'s own row naming a dead group (`emsdk` -> `webassembly`, predates this session -- see the record's own addendum). Still open, carried forward rather than dropped: `resources/pinned_toolchains.toml` not written (four toolchain pins still live as `ARG`s in four Dockerfiles), whether a natmod sweep should pull per-arch or up front, and whether `windows`'s single shared image is right ([0052]'s own open item). **`QEMU_BOARD_CROSS` closed 2026-08-28** (second addendum): all nine qemu boards, not three -- every board live-verified individually, `POWERNV9` the first ever build through `ppc64le_linux`
- [x] [0059] GHCR's "untagged version" cleanup deletes referenced multi-arch/attestation children | incident record, not a design decision -- a registry-side cleanup (manual or automated) that deletes anything without its own tag can delete a live OCI-index child manifest, since only the parent index is ever tagged. Hit seven of fifteen `ghcr.io/ballistics-lab/...` images this session, the pin itself never touched; fixed each by republishing and verifying the new children resolve via a direct `ghcr.io/v2/.../manifests/<digest>` check before pinning. The operating rule: never run that class of cleanup against a `docker/build-push-action`-published package
- [x] [0051] one selector for both modes, and an identifier that names what a build is compatible with (epic, points 1-8, phased E-I) | landed 2026-08-26: both modes' version axes are real lists, `select()`/`matches()` unified in `cibuildmp/selector.py`, config flattened to sibling per-platform tables reached via a `PLATFORM_FAMILY` registry, one shared `[[overrides]]` with `inherit`. Nine addenda; superseded by [0052]'s own later retraction of the table/registry layer itself -- see that record
- [x] [0052] config is build/skip glob + `[override]` only -- no per-platform tables, `--platform`/`--only`/`--archs auto`/`--enable` | Track A (natmod identifier grammar, `{name}-{version}-` filenames, per-tag arch availability) and the table/`[[overrides]]`-retraction addenda all landed 2026-08-27/28; Track B (a tree config mechanism) rejected, see Rejected below; A6 closed the same way
- [x] [0048] `build`/`skip` are top-level in both modes, and a misplaced or misspelt key in a mode table is an error | fixed 2026-08-26; the audit it asked for also found `CIBMP_MICROPYTHON`/`CIBMP_OUTPUT_DIR` silently ignored in usermod mode, and `UsermodConfigError` never caught by the CLI -- both fixed alongside
- [x] [0031] the musllinux column | four of seven cells green, required, and in the default axis -- every musl cell with a runner it is native to. The mechanism is proven end to end and the column is no longer a separate story: its three remaining cells are `ppc64le`/`s390x`/`riscv64`, answered 2026-08-28 by [0044]'s own descope addendum and never a musl question at all
- [x] [0045] `--only` is a filter, not a forced identifier; `--archs auto`/`native`/`all` | both halves done -- `--only` resolves against every identifier that exists, and the vocabulary landed with [0049], which is also where the caution about `--print-build-identifiers` and host-dependence was resolved
- [x] [0042] `windows` wired, verified and required | three arches green three runs running, `verify_windows_output()` reads the COFF machine so a leg asserts something about its output, and the port joined `examples/template`'s own `ports` -- the full lifecycle (`--only` legs allowed to fail -> required -> default axis) that musllinux walked first
- [x] [0050] natmod builds in a container; the bare-host path and its toolchain resolver are deleted | closes [0049]'s own "still open" and, by force, [0032]. Own "still open" (image layering, host mpy-cross, publish/CI, GHCR cleanup) fully closed by five same-topic addenda through 2026-08-28 -- read the record for detail, not this row
- [x] [0049] cibuildmp generates no matrix and chooses no host; `--archs auto`/`native`/`all` does the work instead | `--print-build-matrix`, both `default_runner`s, natmod's `runs-on` key and the `cibuildmp-matrix` action deleted -- cibuildwheel has no equivalent of any of them. Closes [0045]'s open half and [0044]'s "no per-target `runs-on` override", the latter by deletion. Its own "still open" names natmod's bare-host builds, now the top row above
- [x] [0032] `qemu` wired to `ensure_image()`, and actually built | wired by [0050] (`toolchains.resolve()` kept working until that record deleted it, forcing the move) but unexercised for weeks after; `build-examples.yml` gained its own dedicated `v1.29.0-qemu-MPS2_AN385` leg 2026-08-28, confirmed live across two independent runs (33156958747, 33157279355), see [0032]'s own addendum
- [x] [0044] landing [0043]: pypa native images, the full arch x libc matrix, and the two things it broke | the last open question closed 2026-08-28 -- the six emulated-everywhere cells (`ppc64le`/`s390x`/`riscv64`, both libcs) are **descoped from CI, kept in the matrix**: real digests, nameable by any glob, maintained by `bin/update_docker.py`, README-marked ⚠️, and deliberately given no CI leg. Building them is possible (cibuildwheel does it under QEMU), just not worth per-push emulated minutes nobody has asked for. Same answer closes [0031]'s own three remaining cells
- [x] [0043] `unix` adopts cibuildwheel's model in full: native per-target images, PEP 600/656, full arch x libc matrix (epic) | the *decision* shipped -- implemented by [0044], whose own row now sits directly above, closed. Kept here as the design argument, which is still where the reasoning lives
- [x] [0042] `windows` wired to `ensure_image()`; `emsdk.py`/`llvmmingw.py` deleted | all three arches verified live, including an anonymous pull of the published digest; that image was pushed by hand rather than by `publish-docker-images.yml` — see the record. **Still open above:** none of it was ever re-run by CI, which is what the row in "In progress" is about
- [x] [0041] documentation restructure — this scheme | supersedes the monolithic `docs/BACKLOG.md`
- [x] [0033] cibuildmp never builds a Docker image itself, only pulls a published one | separate `docker/` + `publish-docker-images.yml`; `ensure_image()`'s local-build fallback removed
- [x] [0030] extending the container approach to natmod; "Docker or QEMU" answered (both, different jobs) | Docker required for usermod, preferred (not required) for natmod
- [x] [0029] real GitHub Actions job summary (`stepsummary.py`) | implemented and tested; not yet independently confirmed on a live Actions Summary tab
- [x] [0027] `orchestrate.py` output-dir join and exec-bit copy fixes | two real bugs, both regression-tested
- [x] [0026] one Docker image per port, sibling containers not Docker-in-Docker | amended by [0031] to one image per (port, arch, libc) for unix
- [x] [0025] both Dockerfiles bake in every unix cross toolchain | six real apt/gcc bugs found and fixed via real CI builds
- [x] [0024] `unix/armhf` and `unix/mipsel` real, verified-live cross-compiles | closed M8's own acknowledged gap (`libltdl-dev`)
- [x] [0023] usermod's own identifier scheme, config shape, and output convention | deliberately different from natmod's, each difference argued
- [x] [0021] execution (not just linking) is central to usermod's value | does not overturn [0006] for natmod
- [x] [0020] usermod runner selection is structural (revisits [0009]) | `windows` and `unix`/aarch64/armhf/mipsel later stopped needing a special runner
- [x] [0019] ESP-IDF provisioning + caching | `usermod/espidf.py`, `docker` strategy chosen over host caching
- [x] [0018] Windows provisioning — MSYS2, then fully superseded by Linux-hosted cross-compiles | no Windows runner needed for any arch
- [x] [0017] combined `FROZEN_MANIFEST` generation off a per-port/per-variant database | `usermod/manifests.py`, corrected twice against a real consumer workflow
- [x] [0016] `USER_C_MODULES`: directory on Make ports, `.cmake` entry point on CMake ports | `resources/usermod.toml` + `usermod/portinfo.py`
- [x] [0015] `rv32imc`'s `ARCH_FLAGS=` is part of the identifier | fixed a latent header-decode masking bug in the process
- [x] [0014] cibuildmp writes one self-contained mip package per identifier | no separate `publish` command; plain two-element `urls` schema
- [x] [0013] `micropython` accepts a list, deduped by ABI not by tag | verified live against a real second ABI; corrected 2026-08-26 -- the "byte-for-byte identical" reason for dropping same-ABI tags was itself never tested and turned out false (verified live: it is not), the dedup decision stays right for a different, now actually-verified reason (functional interchangeability). See the record's own addendum and [0052]
- [x] [0012] `pyelftools`/`ar` are cibuildmp's own dependencies | resolved via `PYTHON=<sys.executable>` on the `make` command line
- [x] [0011] one repository — cibuildmp absorbed `micropython-native-ci` | `v0.3.0` continues `v0.2.0`'s version line
- [x] [0010] pinned data lives in `resources/`, not in Python | `resources/natmod.toml`, cross-checked at import; the one table that had escaped this rule (`dockerrun.PORT_IMAGES`) moved out in [0044], into `pinned_pypa_images.toml` + `pinned_docker_images.toml`
- [x] [0009] one job looping over targets is the default; fan-out is opt-in | revisited for usermod by [0020]
- [x] [0008] distribution of the tool itself deferred | both actions install from their own checkout, as designed; reserving the PyPI name is a named nice-to-have, not committed work
- [x] [0007] usermod vendors mpbuild's board database, not a dependency | `usermod/boards.py`, MIT header + provenance kept
- [x] [0006] no test runners in phase 1 (natmod) | usermod's own [0021] narrows this, doesn't overturn it
- [x] [0005] one identifier namespace, one override mechanism | `[[overrides]]` collapses three shapes into one
- [x] [0004] config lives in `cibuildmp.toml` at the repo root | `pyproject.toml [tool.cibuildmp]` accepted as a fallback
- [x] [0003] toolchain resolution is per-target, chosen by the tool | `host` → `download`, docker as an escape hatch
- [x] [0002] delegate the compile, own the environment | invokes the project's own `natmod/Makefile`
- [x] [0001] natmod first — the wheel-shaped half | usermod gets a different pipeline, later
- [x] [0039] usermod: existing composite-action layer, two selector axes | context for [0016]-[0033]
- [x] [0037] M3 — the build itself, plus publish folded in (former "M4") | `build.py`, `verify_output()`, `package_target()`
- [x] [0036] M2 — toolchain resolver | `toolchains.py`, prefix reconciliation, picolibc, `x86` multilib probe
- [x] [0035] M1 — MicroPython + mpy-cross provisioning | `sources.py`, cache under `~/.cache/cibuildmp/`
- [x] [0034] M0 — skeleton | CLI, config loader, identifier generation, `--print-build-identifiers`

### Rejected

- [x] [0052] Track B: a tree-addressed config mechanism | designed in detail, then reverted the same record for the build/skip-glob-only model that shipped instead -- [0051]'s own row above
- [x] [0052] defaults folded into `[override."*"]` as a built-in entry | rejected by explicit user call -- "defaults як `[override."*"]` - зайве"; `default=` stays its own `Options.get()` parameter

## Reference (living, unnumbered)

- [reference/design.md](reference/design.md) — positioning, identifier scheme, phase-1 config
  schema, toolchain map, local-use table, non-goals
- [reference/open-questions.md](reference/open-questions.md) — questions flagged but not yet
  designed or decided

## Record links

Reference-style link targets for every `[NNNN]` used above (records are immutable/append-only,
so a number's target never changes). Keep this sorted by number and add a row whenever a new
record is added.

[0001]: records/0001-natmod-first.md
[0002]: records/0002-delegate-compile-own-environment.md
[0003]: records/0003-toolchain-resolution-per-target.md
[0004]: records/0004-config-file-location.md
[0005]: records/0005-one-identifier-namespace.md
[0006]: records/0006-no-test-runners-phase1.md
[0007]: records/0007-usermod-vendors-mpbuild-board-db.md
[0008]: records/0008-tool-distribution-deferred.md
[0009]: records/0009-one-job-loop-fanout-opt-in.md
[0010]: records/0010-pinned-data-in-resources.md
[0011]: records/0011-one-repo-absorbs-micropython-native-ci.md
[0012]: records/0012-pyelftools-ar-own-deps.md
[0013]: records/0013-micropython-list-dedup-by-abi.md
[0014]: records/0014-mip-package-per-identifier.md
[0015]: records/0015-rv32imc-arch-flags-identifier.md
[0016]: records/0016-usermod-user-c-modules-dir-vs-cmake.md
[0017]: records/0017-usermod-frozen-manifest-merge.md
[0018]: records/0018-windows-provisioning-fourth-story.md
[0019]: records/0019-esp-idf-provisioning-heaviest.md
[0020]: records/0020-usermod-runner-selection-structural.md
[0021]: records/0021-usermod-execution-central-value.md
[0022]: records/0022-zephyr-third-selector-axis.md
[0023]: records/0023-usermod-identifier-scheme-config-output.md
[0024]: records/0024-unix-armhf-mipsel-cross-compiles.md
[0025]: records/0025-dockerfiles-bake-unix-cross-toolchains.md
[0026]: records/0026-one-docker-image-per-port.md
[0027]: records/0027-orchestrate-output-dir-and-exec-bit-fixes.md
[0028]: records/0028-container-per-port-migration-plan.md
[0029]: records/0029-github-actions-job-summary.md
[0030]: records/0030-container-approach-natmod-and-docker-vs-qemu.md
[0031]: records/0031-unix-musllinux-libc-axis.md
[0032]: records/0032-unix-docker-default-and-webassembly-wiring.md
[0033]: records/0033-cibuildmp-never-builds-docker-image-itself.md
[0034]: records/0034-m0-skeleton.md
[0035]: records/0035-m1-micropython-mpy-cross-provisioning.md
[0036]: records/0036-m2-toolchain-resolver.md
[0037]: records/0037-m3-the-build-itself.md
[0038]: records/0038-m5-adopt-in-three-repos.md
[0039]: records/0039-usermod-composite-actions-status.md
[0040]: records/0040-usermod-tests-deferred.md
[0041]: records/0041-docs-restructure.md
[0042]: records/0042-windows-docker-wiring-and-resolver-removal.md
[0043]: records/0043-unix-adopts-cibuildwheel-native-image-model.md
[0044]: records/0044-unix-native-images-landed.md
[0045]: records/0045-only-is-a-filter-not-a-forced-identifier.md
[0046]: records/0046-pin-staleness-checker.md
[0047]: records/0047-run-output-parity-with-cibuildwheel.md
[0048]: records/0048-build-skip-live-in-opposite-tables.md
[0049]: records/0049-no-matrix-generation-archs-vocabulary.md
[0050]: records/0050-natmod-is-docker-only.md
[0051]: records/0051-usermod-identifiers-have-no-version-axis.md
[0052]: records/0052-config-is-a-tree-not-a-selector-matrix.md
[0053]: records/0053-usermod-ports-without-a-build-driver.md
[0054]: records/0054-usermod-example-from-upstream-usercmodule.md
[0055]: records/0055-natmod-example-from-upstream-natmod.md
[0056]: records/0056-usermod-with-no-user-c-module.md
[0057]: records/0057-multiple-modules-per-build.md
[0058]: records/0058-image-groups-are-toolchains-not-ports.md
[0059]: records/0059-ghcr-untagged-cleanup-deletes-referenced-manifests.md
[0060]: records/0060-rp2-build-driver.md
[0061]: records/0061-usermod-build-drivers-split-per-port.md
[0062]: records/0062-test-platforms-per-port-orchestrator.md
[0063]: records/0063-keep-going-and-json-build-report.md
[0065]: records/0065-bucketed-test-matrix-planning.md
