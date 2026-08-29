# BACKLOG.md — moved

Split into numbered records under [docs/records/](records/) during the documentation
restructure (see [0041](records/0041-docs-restructure.md)). Content was relocated
**verbatim** — nothing lost, including negative results, addenda and superseded
approaches. Index: [docs/0000-TRACKER.md](0000-TRACKER.md). Living design reference
(positioning, identifier scheme, config schema, toolchain map) moved to
[docs/reference/design.md](reference/design.md); open questions moved to
[docs/reference/open-questions.md](reference/open-questions.md).

| Old section | Now |
|---|---|
| D1 — natmod first | [0001](records/0001-natmod-first.md) |
| D2 — delegate the compile, own the environment | [0002](records/0002-delegate-compile-own-environment.md) |
| D3 — toolchain resolution per-target | [0003](records/0003-toolchain-resolution-per-target.md) |
| D4 — config file location | [0004](records/0004-config-file-location.md) |
| D5 — one identifier namespace | [0005](records/0005-one-identifier-namespace.md) |
| D6 — no test runners in phase 1 | [0006](records/0006-no-test-runners-phase1.md) |
| D7 — usermod vendors mpbuild's board database | [0007](records/0007-usermod-vendors-mpbuild-board-db.md) |
| D8 — tool distribution deferred | [0008](records/0008-tool-distribution-deferred.md) |
| D9 — one job loop, fan-out opt-in | [0009](records/0009-one-job-loop-fanout-opt-in.md) |
| D10 — pinned data in resources/ | [0010](records/0010-pinned-data-in-resources.md) |
| D11 — one repo absorbs micropython-native-ci | [0011](records/0011-one-repo-absorbs-micropython-native-ci.md) |
| D12 — pyelftools/ar own dependencies | [0012](records/0012-pyelftools-ar-own-deps.md) |
| D13 — micropython list, dedup by ABI | [0013](records/0013-micropython-list-dedup-by-abi.md) |
| D14 — mip package per identifier | [0014](records/0014-mip-package-per-identifier.md) |
| D15 — rv32imc ARCH_FLAGS in the identifier | [0015](records/0015-rv32imc-arch-flags-identifier.md) |
| Identifier scheme / Config schema / Toolchain map / Local use / Non-goals | [docs/reference/design.md](reference/design.md) |
| M0 — skeleton | [0034](records/0034-m0-skeleton.md) |
| M1 — MicroPython + mpy-cross provisioning | [0035](records/0035-m1-micropython-mpy-cross-provisioning.md) |
| M2 — toolchain resolver | [0036](records/0036-m2-toolchain-resolver.md) |
| M3 — the build itself (+ former "M4" publish) | [0037](records/0037-m3-the-build-itself.md) |
| M5 — adopt in the three repos | [0038](records/0038-m5-adopt-in-three-repos.md) |
| Later — usermod (composite-action status, two selector axes) | [0039](records/0039-usermod-composite-actions-status.md) |
| D16 — USER_C_MODULES dir vs. .cmake | [0016](records/0016-usermod-user-c-modules-dir-vs-cmake.md) |
| D17 — combined FROZEN_MANIFEST | [0017](records/0017-usermod-frozen-manifest-merge.md) |
| D18 — Windows provisioning | [0018](records/0018-windows-provisioning-fourth-story.md) |
| D19 — ESP-IDF provisioning | [0019](records/0019-esp-idf-provisioning-heaviest.md) |
| D20 — usermod runner selection | [0020](records/0020-usermod-runner-selection-structural.md) |
| D21 — execution central to usermod's value | [0021](records/0021-usermod-execution-central-value.md) |
| D22 — zephyr third selector axis (+ M6-M9b phase outline) | [0022](records/0022-zephyr-third-selector-axis.md) |
| D23 — usermod identifier scheme, config, output | [0023](records/0023-usermod-identifier-scheme-config-output.md) |
| D24 — unix/armhf, unix/mipsel cross-compiles | [0024](records/0024-unix-armhf-mipsel-cross-compiles.md) |
| D25 — Dockerfiles bake in unix cross toolchains | [0025](records/0025-dockerfiles-bake-unix-cross-toolchains.md) |
| D26 — one Docker image per port | [0026](records/0026-one-docker-image-per-port.md) |
| D27 — orchestrate.py output-dir/exec-bit fixes | [0027](records/0027-orchestrate-output-dir-and-exec-bit-fixes.md) |
| D28 — full container-per-port migration plan | [0028](records/0028-container-per-port-migration-plan.md) |
| D29 — GitHub Actions job summary | [0029](records/0029-github-actions-job-summary.md) |
| D30 — container approach for natmod; Docker vs. QEMU | [0030](records/0030-container-approach-natmod-and-docker-vs-qemu.md) |
| D31 — unix musllinux / libc axis | [0031](records/0031-unix-musllinux-libc-axis.md) |
| D32 — unix Docker default, webassembly wiring | [0032](records/0032-unix-docker-default-and-webassembly-wiring.md) |
| D33 — cibuildmp never builds a Docker image itself | [0033](records/0033-cibuildmp-never-builds-docker-image-itself.md) |
| Later — tests | [0040](records/0040-usermod-tests-deferred.md) |
| Open questions | [docs/reference/open-questions.md](reference/open-questions.md) |
