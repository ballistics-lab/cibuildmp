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
  without deciding it, `Not scheduled` for explicitly deferred work, `Accepted` for a
  decision or an incident with no code of its own. **No examples here on purpose** — a
  list of which records are which goes stale the moment one closes, and this bullet
  carried `0054`-`0057` as "Proposed" after two of them shipped.
- **"In progress / Proposed" means "not closed", whatever a record's own `Status:` says.**
  Several of its rows are `Not scheduled` or `Accepted`. The checkbox is the claim; the
  heading is only where unclosed rows live.
- **A record whose code landed is not automatically fully closed.** Some records
  document a decision that shipped and still carry their own "still open" items
  inside. The checkbox says whether the record is closed; what is left inside it
  is in the record, not here. **Do not put examples in this bullet** — it used to
  name `0022`'s "unstarted `rp2` build driver" and `0031`'s "unbuilt musllinux
  half", both of which had shipped ([0060], [0044]), and `CLAUDE.md` records the
  first of those being repeated downstream as fact.
- **Supersession is noted, not deleted.** `0018`'s MSYS2 approach was superseded by a
  Linux cross-compile approach *within the same record* (kept as dated addenda); `0028`'s
  local-Docker-build mechanism was later superseded by `0033`'s pull-only design — `0028`
  itself carries a preface note saying so and stays as the historical account of how the
  container-per-port migration actually happened. Nothing is deleted or rewritten in place.
- **`reference/`** — living, unnumbered design docs and open questions. Not a decision
  history; kept current with what is true today, cross-linking back to the records that
  explain *why*.
- **A row is its record's own title, verbatim — not an essay, not a summary.**
  The checkbox carries the status; everything else, including how the work
  went and what is still open inside it, lives in the record. A row that
  needs a sentence to explain itself is a record whose title needs fixing.
  Rows had grown past 1700 characters and then gone stale independently of
  the records they summarised, which is why this is now a rule and why
  `tests/test_docs.py` checks every row against its record's own `# ` line.
  *(Exception: **Rejected** rows name the rejected proposal, since several
  are different proposals inside one record — `[0052]` appears twice.)*

## Ideas

### In progress / Proposed

- [ ] [0085] `arm_embedded` thins out: the toolchain version stops being the image's name and becomes a row fact
- [ ] [0084] per-identifier toolchain tarballs (Bootlin, uniformly), the end of shared/floating compilers, and what it does to the identifier and to CI cost
- [ ] [0083] replace `windows.Dockerfile`'s apt `gcc-mingw-w64` split with one fully prebuilt llvm-mingw toolchain
- [ ] [0082] nine MicroPython tags fail `mpy-cross` under gcc 15, on every image whose native compiler is unpinned — bisected exactly
- [ ] [0047] the run output works, but it is not cibuildwheel's
- [ ] [0046] nothing notices when a pin goes stale, except container images
- [ ] [0022] zephyr is a third selector axis, not a board-based port that just needs its boards added
- [ ] [0040] usermod's own test-runner axis, deferred
- [ ] [0053] usermod ports with verified facts but no build driver
- [ ] [0056] building upstream MicroPython through the usermod path with no user C module at all
- [ ] [0057] more than one module per build, in both modes

### Implemented

- [x] [0068] docker Dependabot grouping, and what the first grouped bump exposed
- [x] [0081] `output-dir` gets its own `.gitignore` the first time cibuildmp writes into it
- [x] [0080] `windows` and `qemu` get real smoke tests, live-verified before being wired in
- [x] [0079] a collected artifact is not always one file, and only the port knows
- [x] [0078] handing the repo to an uncontexted reader is the docs test the suite cannot be
- [x] [0077] docs drift is a failing test, not a discipline problem
- [x] [0076] the `unix-mipsel` holdout is `micropython-bclibc` and `micropython-wasm3`, not `a7p`
- [x] [0075] an unrecognised top-level scalar key is an error, not a silent default
- [x] [0074] `[usermod]` removed outright; the six other retired tables lose their dedicated migration message too
- [x] [0073] the legacy composite actions are a permanent fallback, not a usage path being absorbed
- [x] [0055]/[0072] a `{micropython}` placeholder for natmod, and a real `examples/natmod` slice
- [x] [0071] `{micropython}` — a placeholder in `user-c-modules` for a path inside the pinned checkout
- [x] [0070] the collected `unix` binary shipped without its own repaired `lib/` sidecar
- [x] [0069] a narrow, real CI slice of [0054]'s upstream `examples/usercmodule` fixture
- [x] [0054] an `examples/` usermod fixture built on upstream's own `examples/usercmodule`
- [x] [0038] M5 — adopt in the three repos
- [x] [0067] `resolve_user_c_modules()` auto-detects the flat make-module shape
- [x] [0066] `extra-cmake-args` — the cmake-side `extra-make-args`
- [x] [0065] bucketed test-matrix planning: ≤20 concurrent jobs, ordered by plan
- [x] [0063] `--keep-going` and a JSON build report, for coverage sweeps
- [x] [0062] test-platforms split into a per-port orchestrator
- [x] [0061] usermod build drivers split per port, cibuildwheel-style
- [x] [0060] rp2 build driver, live-verified
- [x] [0028] Full migration plan: container-per-port for usermod
- [x] [0058] the image axis is the toolchain, not the port
- [x] [0059] GHCR's "untagged version" cleanup deletes referenced multi-arch/attestation children
- [x] [0051] one selector for both modes, and an identifier that names what a build is compatible with
- [x] [0052] cibuildmp's config space is a tree, not a selector matrix; the divergence from cibuildwheel is deliberate
- [x] [0048] `build`/`skip` live in opposite tables in the two modes, and a misplaced one is silent
- [x] [0031] unix usermod builds are glibc-only; there is no musllinux-equivalent, and identifiers carry no libc axis
- [x] [0045] `--only` is a filter, not a forced identifier: selector parity with cibuildwheel
- [x] [0042] `windows` wired to Docker; the last two host-side toolchain resolvers deleted
- [x] [0050] natmod builds in a container; the bare-host path and its toolchain resolver are deleted
- [x] [0049] cibuildmp generates no matrix and chooses no host; `--archs auto` does the work instead
- [x] [0032] Closing D28's own gap: unix usermod now defaults to Docker via ensure_image()
- [x] [0044] landing [0043]: pypa-based native images, the full arch × libc matrix, and the two things it broke
- [x] [0043] `unix` adopts cibuildwheel's model in full: native per-target images, PEP 600/656
- [x] [0042] `windows` wired to Docker; the last two host-side toolchain resolvers deleted
- [x] [0041] Documentation restructure — numbered records
- [x] [0033] cibuildmp never builds a Docker image itself; it only resolves a reference and pulls it
- [x] [0030] Extending the container approach to natmod too, and "Docker or QEMU" answered directly
- [x] [0029] A real GitHub Actions job summary, like cibuildwheel's
- [x] [0027] The sixth Dockerfile fix got real CI past every unix arch, surfacing two genuine orchestrate.py bugs
- [x] [0026] usermod moves to one Docker image per port, not one combined image
- [x] [0025] Both Dockerfiles now bake in every unix cross toolchain — six real apt/gcc bugs
- [x] [0024] unix/armhf and unix/mipsel are real, verified-live cross-compiles
- [x] [0023] usermod's own identifier scheme, config shape, and output convention are each genuinely different from natmod's
- [x] [0021] Execution, not just linking, is central to usermod's value
- [x] [0020] Usermod runner selection is structural (revisits D9)
- [x] [0019] ESP-IDF provisioning is the heaviest, least locally-reproducible step of any target here
- [x] [0018] Windows provisioning is a fourth story, not a variant of download/docker/host
- [x] [0017] Combining FROZEN_MANIFEST with the port's own default manifest is real, per-port, and explicitly not solved by the action layer
- [x] [0016] USER_C_MODULES is a directory on Make-driven ports, a single .cmake file on CMake-driven ones
- [x] [0015] rv32imc's ARCH_FLAGS= is part of the identifier, not an invisible extra-make-args string
- [x] [0014] cibuildmp itself writes one self-contained mip package per identifier as part of the normal build
- [x] [0013] micropython accepts a list, deduped by ABI, not by tag
- [x] [0012] pyelftools and ar are cibuildmp's own dependencies, not something it installs at build time
- [x] [0011] One repository: cibuildmp absorbed micropython-native-ci
- [x] [0010] Pinned data lives in resources/, not in Python
- [x] [0009] One job looping over targets is the default; fan-out is opt-in
- [x] [0008] Distribution of the tool itself is deferred
- [x] [0007] usermod vendors mpbuild's board database, not depends on the package
- [x] [0006] No test runners in phase 1
- [x] [0005] One identifier namespace, one override mechanism
- [x] [0004] Config lives in cibuildmp.toml at the repo root
- [x] [0003] Toolchain resolution is per-target, chosen by the tool (variant C)
- [x] [0002] Delegate the compile, own the environment
- [x] [0001] natmod first, and natmod is the wheel-shaped half
- [x] [0039] usermod: existing composite-action layer, and the two selector axes
- [x] [0037] M3 — the build itself
- [x] [0036] M2 — toolchain resolver
- [x] [0035] M1 — MicroPython + mpy-cross provisioning
- [x] [0034] M0 — skeleton

### Rejected

- [x] [0038] `build-natmod` reduced to a thin `cibuildmp --build` wrapper
- [x] [0052] Track B: a tree-addressed config mechanism
- [x] [0052] defaults folded into `[override."*"]` as a built-in entry

## Reference (living, unnumbered)

- [reference/design.md](reference/design.md) — positioning, identifier scheme, phase-1 config
  schema, toolchain map, local-use table, non-goals
- [reference/vendored-images.md](reference/vendored-images.md) — the pypa/vendored base images,
  how an image group is formed, the full port/arch/board → group mapping, publishing flow
- [reference/open-questions.md](reference/open-questions.md) — questions flagged but not yet
  designed or decided

**There is no record 0064.** The number was skipped, not lost — nothing
was written under it and nothing references it. `0034`-`0038` are the
`M0`-`M5` build-phase write-ups, which is why no `M4` appears either.

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
[0066]: records/0066-extra-cmake-args.md
[0067]: records/0067-user-c-modules-flat-shape-autodetect.md
[0068]: records/0068-docker-dependabot-grouping-and-mipsel-ubuntu-26-04.md
[0069]: records/0069-upstream-usercmodule-narrow-ci-slice.md
[0070]: records/0070-unix-collected-binary-missing-repaired-lib-sidecar.md
[0071]: records/0071-micropython-placeholder-in-user-c-modules.md
[0072]: records/0072-natmod-micropython-placeholder-and-upstream-natmod-ci.md
[0073]: records/0073-composite-actions-are-a-permanent-legacy-fallback.md
[0074]: records/0074-usermod-family-table-and-retired-table-messages-removed.md
[0075]: records/0075-top-level-scalar-keys-are-validated.md
[0076]: records/0076-the-mipsel-holdout-is-bclibc-and-wasm3-not-a7p.md
[0077]: records/0077-docs-drift-is-a-failing-test-not-a-discipline-problem.md
[0078]: records/0078-uncontexted-agent-audit-as-a-docs-test.md
[0079]: records/0079-collected-artifact-is-more-than-one-file.md
[0080]: records/0080-windows-and-qemu-usermod-smoke-tests.md
[0081]: records/0081-output-dir-gitignore.md
[0082]: records/0082-natmod-old-tags-fail-mpy-cross-under-gcc-15.md
[0083]: records/0083-windows-fully-prebuilt-mingw-toolchain.md
[0084]: records/0084-per-identifier-toolchain-tarballs-and-the-end-of-shared-images.md
[0085]: records/0085-arm-embedded-thins-out-and-the-toolchain-version-becomes-a-row-fact.md
