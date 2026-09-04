# 0096 — `arm_embedded` and `riscv_embedded` collapse into one `embedded_base` image

Status: Implemented — code, config and CI wiring land in this record; the real
`ghcr.io/ballistics-lab/embedded_base` publish is still pending (see "What this does not
solve").
Related: [0044], [0058], [0085], [0086], [0087], [0089], [0090]

## The question this record answers was asked once already, and then lost

[0044]'s own addendum named this directly, as an open, undecided resolver-shape question:

> ...whether `dockerrun.py`'s own per-port resolution logic ... should instead be driven by
> `resources/build-platforms.toml`'s own per-row `cross` fact — grouping many natmod arches
> and usermod ports onto a small number of shared toolchain images (the
> `arm_embedded`/`riscv_embedded`/`xtensa_lx106`/`esp_idf` consolidation sketched but not
> built this session). That is a resolver-shape redesign, not a data cleanup, and stays open.

It never got a number of its own, never entered `docs/0000-TRACKER.md`'s own "Ideas" list, and
[0085] — which reshaped `arm_embedded`/`riscv_embedded` more than any record since — did not
pick it up either: [0085]'s own question was whether the toolchain *version* baked into each
image should become a per-row fact, not whether the two images themselves still needed to be
two. Both questions happen to touch the same two Dockerfiles, but they are not the same
question, and closing one did not close the other. The result is exactly the class of drift
CLAUDE.md's own opening section warns about: an idea sketched once, correctly, then never
tracked anywhere a later reader — human or agent — would find it without already knowing to
look inside [0044]'s prose.

## What changed underneath it, without anyone revisiting the sketch

[0085] decided the toolchain version stops being baked into either image and becomes a
per-row `toolchain_version` fact, fetched at container run time instead
(`toolchain_fetch.py`, [0086]). [0087]/[0089] landed that for `arm_embedded`/`riscv_embedded`
on both `usermod` and `natmod`. Once both landed, `docker/arm_embedded.Dockerfile` and
`docker/riscv_embedded.Dockerfile` no longer had a toolchain-specific build step at all —
checked directly, byte for byte: both `RUN apt-get install` layers were identical but for one
package, `cmake` (`rp2`-only, since `ports/rp2/Makefile` shells out to it). [0044]'s own
"sketched but not built" consolidation was, by the time [0087]/[0089] landed, no longer a
redesign that would have to reconcile two different build-time recipes — there was nothing
left to reconcile. Nobody went back and noticed.

## The merge

`docker/arm_embedded.Dockerfile` and `docker/riscv_embedded.Dockerfile` are deleted.
`docker/embedded_base.Dockerfile` replaces both: the shared apt layer (now including `cmake`
unconditionally — one extra package on the RISC-V-only builds costs less than a second image
existing only to withhold it), same `ubuntu:26.04` base, same "no cross compiler baked in"
design [0087] already established. `toolchain_fetch.py`'s own per-row `cross` resolution is
what still tells the two toolchain families (`arm-none-eabi-`/`riscv64-unknown-elf-`) apart
inside the one image — the image itself no longer does, and after this record never claimed
to.

Every place that named the two groups separately now names one, `embedded_base`:
`resources/build-platforms.toml`'s 23 `image`/`images.<arch/board>` fields, `resources/
pinned_docker_images.toml`'s `[image_group]` table, `publish-docker-images.yml`'s and
`verify-docker-images.yml`'s own matrices, `docs/reference/vendored-images.md`'s generated
mapping table (`bin/refresh_docs.py`) and its own hand-written toolchain-group table, `README.md`'s
own group counts (six groups drops to five; the three usermod-shared groups the "three of
those five" sentence counted — `arm_embedded`, `riscv_embedded`, `xtensa_lx106` — drop to two,
`embedded_base` and `xtensa_lx106`), and `docs/reference/design.md`'s own "one of six" line.

## The one real functional break the merge caused, and its fix

Every other caller of the old `arm_embedded`/`riscv_embedded` names used them as literal
constant *labels* for the two cross-prefix strings (`toolchain_fetch.IMAGE_CROSS_PREFIX`,
renamed here to `TOOLCHAIN_CROSS_PREFIX` — the dict keys are unchanged, since every caller
already names them this way, but the docstring's own claim that they are Docker image-group
names is no longer true and is corrected). `usermod/targets.py`'s `rp2_toolchain()`/
`qemu_toolchain()` only ever compare against those two literal strings — merging the images
underneath them changes nothing they do.

`natmod/targets.py`'s `natmod_toolchain()` was different, and genuinely broken by a naive
rename: it resolved which cross family an arch needs by looking up
`build_platforms_data()["natmod"]["images"].get(arch)` — the row's own image-group name — and
using *that* as the key into `IMAGE_CROSS_PREFIX`. That only worked because, before this
record, `images["armv6m"]` and `images["rv32imc"]` resolved to two different names. Once both
resolve to `"embedded_base"`, the same lookup collapses two toolchain families onto one image
name that can no longer tell them apart — a real, live bug a naive find-and-replace would have
shipped silently (an RISC-V arch would have resolved `arm-none-eabi-` or vice versa, depending
on dict ordering).

The fix: `natmod/targets.py` now carries `_NATMOD_ARCH_TOOLCHAIN_FAMILY`, a direct
`arch -> toolchain family` table (`armv6m`/`armv7m`/`armv7emsp`/`armv7emdp` -> `arm_embedded`,
`rv32imc`/`rv64imc` -> `riscv_embedded`) — a fixed, closed set checked directly against
`build-platforms.toml`'s own `images` map at the time of this merge, the same shape
`usermod/build_qemu.py`'s own `QEMU_BOARD_CROSS` already uses to resolve a board's cross
prefix without going through the image name at all. `natmod_toolchain()` no longer reads
`images` for this purpose; the image group is now purely a Docker-packaging fact, decoupled
from which compiler a row needs, matching what `pinned_toolchains.toml`'s own header already
argued for `cross` over `image` before this record existed.

## Live-verified, both toolchain families through the one merged image

`docker build -f docker/embedded_base.Dockerfile .` — clean, one layer, `cmake` and
`python3-pyelftools` both present. Then, against that one real local image (no digest
substitution, `CIBMP_RP2_DOCKER_IMAGE`/`CIBMP_NATMOD_RV32IMC_DOCKER_IMAGE` pointed at it
directly):

- **`rp2`, real firmware, real link.** `v1.29.0-rp2-RPI_PICO` through the real `cibuildmp` CLI:
  fetched `arm-none-eabi-` `15.2.1-1.1` (sha256-verified) from inside the merged image, built
  `mpy-cross`, then a full `ports/rp2` CMake build against the real Pico SDK — produced
  `firmware-v1.29.0-rp2-RPI_PICO.uf2`, **681984 bytes**, matching [0060]'s own byte count for
  this exact identifier against the pre-merge `arm_embedded` image bit for bit.
- **`natmod` `rv32imc`, real fetch and rename.** `mpy6.3-v1.29.0-rv32imc`: fetched
  `riscv-none-elf-` `14.3.0-1` (sha256-verified) from the same merged image, then
  `rename_prefix_script()` symlinked every `riscv-none-elf-*` tool to its `riscv64-unknown-elf-*`
  name inside the fetched cache directory — the exact mechanism [0087]/[0089] moved off
  `riscv_embedded.Dockerfile`'s own build-time loop, now proven to still work with no
  `riscv_embedded.Dockerfile` to have moved it *from*. `make` itself then failed on this
  particular fixture (`No rule to make target 'dist'`, `examples/natmod/features0/natmod`'s own
  Makefile shape) — unrelated to the image, the toolchain fetch, or this record: both the fetch
  and the `PATH`/rename wiring the RISC-V family needs had already completed by that point,
  which is what this check exists to prove.

Both families resolving correctly out of the same image, in the same session, is the actual
claim [0096] makes — not simulated, not inferred from the diff.

## What this does not solve

- **The digest in `pinned_docker_images.toml`'s new `embedded_base` entry is provisional.**
  `docker/embedded_base.Dockerfile`'s own content is exactly the old `arm_embedded` image plus
  `cmake` folded in from `riscv_embedded`'s superset relationship — real and already published,
  just not under the name `embedded_base` in this repo's own GHCR namespace yet, since nothing
  has run `publish-docker-images.yml` for it. The pin is correct in *content* (a real, pullable
  image that already serves every row this merge points at it), not yet in *provenance*. A
  maintainer running that workflow for real replaces it with the genuine digest GitHub prints.
- **`bin/refresh_toolchain_pins.py`'s `DOCKERFILE_PIN` and `bin/update_toolchains.py`'s `PINS`
  both already read nothing useful from either former Dockerfile**, since [0087]/[0089] deleted
  the `ARG TOOLCHAIN_URL=` line their regexes need — a pre-existing gap, not one this record
  opens. Both now point at `embedded_base.Dockerfile` so they fail the same graceful way
  (`SystemExit`, not `FileNotFoundError`) rather than a new, harder one; the real fix (reading
  `pinned_toolchains.toml`'s own per-cross pin) is [0090]'s own scope.
- **`bin/plan_test_matrix.py`'s per-second weight for the merged group is an arithmetic
  estimate, not a fresh measurement.** The old `arm_embedded: 55`/`riscv_embedded: 26` entries
  (measured separately, each against its own image, from a real batched CI run) collapse to one
  `embedded_base: 50`, the real identifier-count-weighted average of the two
  (140 arm + 26 riscv non-`rp2` identifiers at the time of this merge). A real re-measurement
  from a batched run against the merged image would still be worth more than this estimate.
