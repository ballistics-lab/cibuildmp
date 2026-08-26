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

### Where this actually stands, 2026-08-26

Read this before the list. The branch is **+18.5k lines across 142 files**
against `main`, and that number is misleading about progress in a specific way
worth stating rather than discovering.

Measured against the project's own premise -- *cibuildwheel for MicroPython:
the same behaviour, Docker-only and isolated, no bare-host builds, and a
foreign runner can still build through emulation* -- three of those four are
done and the fourth, the one the whole thing is named after, is not:

| premise | state |
| --- | --- |
| Docker-only, isolated | done, both modes; `esp32` the one exception ([0028]) |
| no bare-host builds | done, same exception |
| a foreign runner still builds | proven live, both directions ([0049]) |
| **behaves like cibuildwheel** | **no** |

The last row is the task, and [0051] is why it fails. Upstream's whole shape is
that **the identifier is the complete description of one build** and
`build`/`skip`/`--only`/`--archs` are one mechanism over it. natmod has that
(`mpy6.3-natmod-x64`). usermod -- half the tool -- has no version axis at all,
so it cannot build two MicroPython releases, cannot select one, and silently
drops every tag after the first.

And the acceptance test has never run. [0038] is "adopt cibuildmp in the three
consuming repos", which is the only thing that answers whether this is
cibuildwheel for MicroPython or infrastructure that resembles it. Its blast
radius grew this session rather than shrinking: every `unix` identifier renamed
([0044]), `--toolchain` and `--print-build-matrix` deleted ([0049]/[0050]),
natmod now requiring Docker -- and [0051] queues one more rename ahead of it.

That ordering is deliberate and is the argument for the list below: finish
changing the identifiers *before* asking three repos to migrate onto them.

**Listed in execution order, and that order is the plan** -- not by record
number, not by age. Each row's note says what is true *now*, so the top row is
where the next session starts. The ordering argument, once, so it can be
disagreed with rather than guessed at: things that are *broken* beat things that
are *missing*; work that unblocks verification beats work that gets verified
later; and cheap-with-strong-evidence beats expensive-and-speculative.

- [ ] [0051] one selector for both modes, and an identifier that names what a
      build is compatible with | **five of six shape points landed
      2026-08-26; only `--platform`-becomes-port (and `--archs` with it)
      did not.** natmod's `mpy-abi` can now state the ABI axis directly
      (list) as well as derive it from tags (string, unchanged); usermod's
      `micropython` is a real list and its identifier leads with the tag
      (`v1.29.0-unix-manylinux_2_28_x86_64`), so two releases no longer
      overwrite each other's output. `select()`/`matches()`/`parse_selector()`
      moved to one `cibuildmp/selector.py`, which also gained brace
      expansion and, in a same-day second pass, `enable`/`groups`
      (upstream's own `EnableGroup`) -- the six emulated-everywhere `unix`
      cells (`ppc64le`/`s390x`/`riscv64`, both libcs) stopped being absent
      from the default axis and became an opt-in group instead
      (`--enable unix-emulated-everywhere`/`enable = [...]`), closing this
      row's own musllinux-adjacent question from [0044] below. usermod also
      gained its own `[[usermod.overrides]]` (nested, not shared with
      natmod's top-level one -- the two modes' override tables take
      different keys). **Still open**, per the record's own addenda:
      `--platform` still means the build mode rather than the port -- no
      `platforms/` tree, config still `[usermod.unix]` not `[unix]` (point
      6) -- and `--archs` still means what it did (point 4, which the
      record argues dissolves once point 6 lands rather than being fixed
      independently). Deferred deliberately: moving `--platform` changes
      the invocation model itself (one usermod run currently builds several
      ports at once, e.g. `examples/template`'s own `ports = ["unix",
      "webassembly", "windows"]`), with knock-on `action.yml`/CI changes --
      a separable epic, not required to close the two live bugs the first
      pass fixed. Still goes **before** [0038] rather than after -- the
      identifier shape is now settled, so telling the three consuming repos
      to migrate once is still the right order
- [ ] [0050] natmod's image needs one more publish, and CI has never been
      green on it | **start here, and it is nearly done.** The image gained
      `gcc-i686-linux-gnu` after v1.29.0 changed `dynruntime.mk`'s `x86` from
      `-m32` to a real cross prefix; verified locally on both tags and on all
      ten arches, but the published digest predates it. Republish, update the
      pin, drop the orphaned `sha256:2389c6fa…` (a hand-push leaves a bare
      manifest, so it really is orphaned -- unlike the untagged versions of
      every workflow-published image, which are index children and must not be
      touched). Only then has any CI run exercised natmod-in-a-container at
      all: the last one failed on `examples/wasm2mpy`'s `sudo apt-get`, since
      fixed
- [ ] [0032] `qemu` has never been built anywhere | wired to `ensure_image()`
      by [0050] and in the default port set, so every `--archs auto` run on an
      amd64 runner now selects it -- and nothing has ever built it, here or by
      hand. It is the only port in that position; `windows` at least had
      [0042]'s by-hand session behind it. Cheap to find out, and the answer is
      binary
- [ ] [0050] natmod still builds mpy-cross on the host, and `action.yml` still
      installs a compiler for it | the two are one item: `sources.build_mpy_cross()`
      compiles outside Docker, which is why `build-essential` survived the apt
      step's cull. usermod hit this in [0044] and answered it with
      `container_mpy_cross()`; natmod has not even been checked for whether its
      `make` reaches that binary. Closing it deletes the apt step entirely --
      37s off every job in the repo
- [ ] [0050] the natmod image's expensive layer is in the wrong place | 3.38GB
      of toolchains sits *after* the apt layer, so adding one package
      re-downloads all of it (measured: ten minutes, for
      `gcc-i686-linux-gnu`). Minimal apt (`curl`, `xz-utils`,
      `ca-certificates`) -> toolchains -> the rest would make that free. Also
      worth deciding whether `xtensa-lx106` (ESP8266, crosstool-NG 4.8.5)
      earns its share of a 3.91GB image
- [ ] [0044] the six emulated-everywhere cells: build them or descope | the
      **decision** landed 2026-08-26, via [0051] point 8: neither, they are
      an opt-in `EnableGroup`-style group now
      (`--enable unix-emulated-everywhere`), reachable without editing a
      config's own `archs`, still absent from a bare `build = "*"`. The
      **work** this row was also about is still open, unchanged by that:
      `ppc64le`, `s390x`, `riscv64` in both columns are native to no runner
      GitHub offers, have never been built, and Alpine's own
      `community/micropython` excludes the first two outright. Nine of
      fifteen cells are in the default axis and green; this is the whole
      remainder. [0031] is the same question for its own three cells and is
      answered by the same sentence
- [ ] [0038] M5 -- adopt cibuildmp in the three consuming repos | the only item
      with external blast radius, and it grew this session: `unix` identifiers
      were renamed by [0044], `--toolchain` and `--print-build-matrix` were
      deleted outright by [0049]/[0050], and natmod now requires Docker. Those
      repos pin cibuildmp and name identifiers and flags in their own
      workflows. *Checking* the breakage is cheap; fixing it wants the rows
      above settled, since telling three repos to migrate twice is worse than
      telling them once. Archiving `micropython-native-ci` and reducing
      `build-natmod` to a wrapper are the original, still-open items
- [ ] [0047] run output should look exactly like cibuildwheel's | the half that
      was actively *wrong* is fixed -- every `print()` was block-buffered and
      landed at interpreter exit, out of order with `make`'s own output. What
      is left is the missing mechanism: log folding, and the fact that a
      `--archs auto` run is now one job printing nine builds in sequence, which
      is precisely the shape folding exists for
- [ ] [0046] nothing notices when a pin goes stale, except container images |
      independent of everything above, no urgency. `bin/update_docker.py` covers
      both image tables; emsdk is the cheapest thing left (its own
      `emscripten-releases-tags.json` maps version to build hash) and
      `xtensa-lx106` the only genuinely hard one, having no version at all.
      The four toolchain tarballs moved into `docker/natmod.Dockerfile` in
      [0050] and are a fifth thing nothing watches
- [ ] [0028] full container-per-port migration plan (epic) | `esp32` is the
      only port without a Dockerfile, and [0050] took it out of the default
      port set for exactly that reason -- it provisions ESP-IDF onto the host,
      the one bare-host build path left in the tool. It is still a real
      identifier and `--only` still reaches it. Genuinely large
- [ ] [0022] zephyr as a third usermod selector axis (epic) | phase outline
      M6-M9b mostly landed; zephyr itself and `rp2`'s own build driver not
      started
- [ ] [0040] usermod test-runner axis | not scheduled ([0006] holds); four of
      seven runners already proven by `mp-usermod.yml`, not yet owned by
      cibuildmp

### Implemented

- [x] [0048] `build`/`skip` are top-level in both modes, and a misplaced or misspelt key in a mode table is an error | fixed 2026-08-26; the audit it asked for also found `CIBMP_MICROPYTHON`/`CIBMP_OUTPUT_DIR` silently ignored in usermod mode, and `UsermodConfigError` never caught by the CLI -- both fixed alongside
- [x] [0031] the musllinux column | four of seven cells green, required, and in the default axis -- every musl cell with a runner it is native to. The mechanism is proven end to end and the column is no longer a separate story: its three remaining cells are `ppc64le`/`s390x`/`riscv64`, which is [0044]'s descope question above and not a musl question at all
- [x] [0045] `--only` is a filter, not a forced identifier; `--archs auto`/`native`/`all` | both halves done -- `--only` resolves against every identifier that exists, and the vocabulary landed with [0049], which is also where the caution about `--print-build-identifiers` and host-dependence was resolved
- [x] [0042] `windows` wired, verified and required | three arches green three runs running, `verify_windows_output()` reads the COFF machine so a leg asserts something about its output, and the port joined `examples/template`'s own `ports` -- the full lifecycle (`--only` legs allowed to fail -> required -> default axis) that musllinux walked first
- [x] [0050] natmod builds in a container; the bare-host path and its toolchain resolver are deleted | closes [0049]'s own "still open" and, by force, [0032] -- `qemu` was the only other thing holding the resolver up. One amd64 image for all ten arches (a `.mpy` is relocatable code, nothing is native to anything); `x86` stops being amd64-host-only; `toolchains.py`, `--toolchain` and `[[toolchain]]` deleted; tarball pins moved into the Dockerfile and became sha256-checked. Its own "still open" names the 3.91GB image, `action.yml`'s now-pointless apt step, and natmod's host mpy-cross
- [x] [0049] cibuildmp generates no matrix and chooses no host; `--archs auto`/`native`/`all` does the work instead | `--print-build-matrix`, both `default_runner`s, natmod's `runs-on` key and the `cibuildmp-matrix` action deleted -- cibuildwheel has no equivalent of any of them. Closes [0045]'s open half and [0044]'s "no per-target `runs-on` override", the latter by deletion. Its own "still open" names natmod's bare-host builds, now the top row above
- [x] [0032] `qemu` wired to `ensure_image()` | closed by [0050] rather than on its own: `qemu` was the last bare-host build path in usermod and survived only because `toolchains.resolve()` kept working, so deleting that resolver forced it. **Still open above:** wiring it is not building it, and nothing ever has
- [x] [0043] `unix` adopts cibuildwheel's model in full: native per-target images, PEP 600/656, full arch x libc matrix (epic) | the *decision* shipped -- implemented by [0044], whose row above carries the work that remains. Kept here as the design argument, which is still where the reasoning lives
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
[0049]: records/0049-no-matrix-generation-archs-vocabulary.md
[0050]: records/0050-natmod-is-docker-only.md
[0051]: records/0051-usermod-identifiers-have-no-version-axis.md
