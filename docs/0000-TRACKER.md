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
  real work remains, `Not scheduled` for explicitly deferred work.
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

## Ideas

### In progress / Proposed

- [ ] [0045] `--only` is a filter, not a forced identifier -- selector parity with cibuildwheel | `--only` half landed and verified live in both modes (resolves against the full matrix, overrides `archs`/`build`/`skip`, names what exists on error); the `--archs`/`auto`/`all` vocabulary for usermod is still design only
- [ ] [0048] `build`/`skip` live in opposite tables in the two modes, and a misplaced one is silent | natmod reads them top-level, usermod from `[usermod]`; `archs` accepts both for natmod, which makes the trap look like a rule. Cost a vacuously-passing test that was the only coverage of `--only` vs `skip`
- [ ] [0046] nothing notices when a pin goes stale, except container images | `bin/update_docker.py` covers both image tables (and found the pypa bases nine days stale on first run); the toolchain tarballs, emsdk build hash, llvm-mingw, the mipsel apt libc pin, and the MicroPython/ESP-IDF tags have no checker at all
- [ ] [0047] run output should look exactly like cibuildwheel's | mostly a missing mechanism, not styling: no log folding at all (`::group::`/`##[group]`/`travis_fold`), no colour or `✓`/`✕`; the Actions job summary ([0029]) already has parity
- [ ] [0022] zephyr as a third usermod selector axis (epic) | phase outline M6-M9b mostly landed (boards.py, manifests, five of six build drivers, CLI wiring); zephyr itself and `rp2`'s own build driver not started
- [ ] [0028] full container-per-port migration plan (epic) | steps 1-3 substantially landed, `PORT_IMAGES` populated for 8 images via [0033]; `esp32.Dockerfile` still explicitly not started, no Docker path for that port at all
- [ ] [0043] `unix` adopts cibuildwheel's model in full: native per-target images, PEP 600/656, full arch x libc matrix (epic) | implemented by [0044] -- read that record for what actually landed and what is still unverified; this one stays as the design argument
- [ ] [0044] landing [0043]: pypa-based native images, full 15-cell matrix, pins moved to `resources/` | code/tests/tooling landed, `manylinux_2_28_x86_64` verified live end to end; **no image published yet** (every `[image.*]` cell empty), most cells and both workflows unverified
- [ ] [0031] unix usermod builds are glibc-only; no musllinux equivalent yet | musllinux column now declared and Dockerfile-backed by [0044] (Alpine base per arch, identifier axis threaded through), and the glibc-floor checker is built and verified -- nothing in that column has been built or run yet
- [ ] [0032] unix usermod defaults to Docker via `ensure_image()`; webassembly wired next | end-to-end proof green for unix+webassembly on real CI; superseded in part by [0033]; `windows` wired by [0042], leaving `qemu` as the one port whose `PORT_IMAGES` entry is still dead code
- [ ] [0038] M5 — adopt cibuildmp in the three consuming repos | repos migrated and repinned; archiving the old `micropython-native-ci` repo and reducing `build-natmod` to a `cibuildmp --only` wrapper still open
- [ ] [0040] usermod test-runner axis (native/qemu-user/qemu-system/node/rp2040py/mpremote/none) | not scheduled ([0006] holds); four of seven runners already proven by `mp-usermod.yml`, not yet owned by cibuildmp

### Implemented

- [x] [0042] `windows` wired to `ensure_image()`; `emsdk.py`/`llvmmingw.py` deleted | all three arches verified live, including an anonymous pull of the published digest; that image was pushed by hand rather than by `publish-docker-images.yml` — see the record
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
- [x] [0013] `micropython` accepts a list, deduped by ABI not by tag | verified live against a real second ABI
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
