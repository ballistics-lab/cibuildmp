# 0062 — test-platforms split into a per-port orchestrator

Status: Implemented
Related: [0060], [0061]

## What this closes

Landing [0060]'s `rp2` driver pushed `test-platforms.yml`'s own single amd64 matrix to
211/256 identifiers — real headroom, not a hypothetical one, with nine more usermod ports
([0053]) and zephyr ([0022]) still queued. GitHub's own 256-configuration cap applies per
`strategy.matrix` instantiation, so the next port with a wide board list (any of `stm32`/
`nrf`/`samd`) would have overflowed it outright, silently dropping identifiers from the
CI sweep rather than erroring loudly.

## The split

`test-platforms.yml` becomes a reusable workflow (`workflow_call`), holding the exact
`build-matrix`/`test-amd64`/`test-arm64`/`test-emulated` logic it already had — moved,
not rewritten. A new `test-all-platforms.yml` is the orchestrator: `on: pull_request`/
`workflow_dispatch` (test-platforms.yml's own former triggers), with one `strategy.matrix`
job (`test-port`) whose seven legs each `uses: ./.github/workflows/test-platforms.yml`
with their own `build`/`skip`/`label`. Each leg's own nested `strategy.matrix` jobs get an
independent 256 cap, since the cap is enforced per literal instantiation of a `matrix:`
block, not per top-level workflow file — adding an eighth port later means one more
`matrix.include` row in `test-all-platforms.yml`, not a new job block or a shared-ceiling
risk.

`test-platforms.yml` also **keeps its own `workflow_dispatch`** trigger alongside
`workflow_call`, deliberately: a maintainer can still dispatch it directly against one
target set (just `rp2`, or just the six emulated unix cells) without fanning out through
the orchestrator's full seven-port matrix. `build` has no default on that path — an
unconfigured `build` selects nothing, the same discipline `build`/`CIBMP_BUILD` already
hold everywhere else in this project.

## Per-port glob parity, verified not assumed

Each port's own `build` glob in `test-all-platforms.yml`'s matrix was checked to union
back to *exactly* what the old single `v1.29.0-* v1.28.0-* mpy6.3-v1.29.0-*
mpy6.3-v1.28.0-*` selected — 231 identifiers either way, confirmed by running a real
`--print-build-identifiers` against every per-port glob and diffing the sets, not assumed
from the glob shapes. `unix`'s own `*linux*` (matching both `manylinux`/`musllinux`) reuses
the exact idiom `examples/template/cibuildmp.toml`'s own `build` already uses.

## Live-caught: an omitted `skip` is not an empty `skip`

The first version of this split scoped each port's own `build` glob narrowly (e.g.
`v1.29.0-manylinux* v1.29.0-musllinux*` for `unix`) but did not pass `skip` on every call.
Result: the twelve ppc64le/s390x/riscv64 identifiers (both libc floors) silently vanished
from the `unix` call's own selection — not because the `build` glob excluded them (it
doesn't; `manylinux_2_28_ppc64le` matches `v1.29.0-manylinux*` fine), but because
`examples/template/cibuildmp.toml`'s own config carries `skip = "*_ppc64le *_s390x
*_riscv64"`, and `cibuildmp`'s CLI only overrides a config's own `skip` when `--skip` is
passed *at all* — an omitted flag falls through to the config's own value, an explicit
`--skip ""` does not. Caught by diffing the per-port union against the old single-glob
selection (231 vs 219, twelve missing, all matching this exact pattern) before this ever
reached CI, not after. Fixed by declaring `workflow_call`'s own `skip` input with
`default: ""` and having the `run:` step always pass `--skip "${{ inputs.skip }}"`
unconditionally — every caller now sends a real string, empty or not, never nothing at
all.

## Not changed

Native/emulated routing inside each call (regex on identifier suffix, matched against
`_aarch64$|_armv7l$|_ppc64le$|_s390x$|_riscv64$`) stays exactly as it was — confirmed
empty for every non-`unix` port's own call, since no other port's identifiers ever carry
one of those suffixes, so this needed no per-port awareness to stay correct.
`aggregate-results` (the combined pass/fail table on the orchestrator's own Summary page)
also carries over unchanged in shape, now downloading artifacts uploaded by every port's
own nested call rather than by three sibling jobs directly — reusable-workflow jobs share
the same top-level run's artifact storage, so this needed no new plumbing through
`test-port`'s own outputs.

[0060]: 0060-rp2-build-driver.md
[0061]: 0061-usermod-build-drivers-split-per-port.md
