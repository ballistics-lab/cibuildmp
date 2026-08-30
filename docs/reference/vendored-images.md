# cibuildmp — vendored container images

Living reference for how cibuildmp resolves a container image for a build.
This is not a decision history — [0043], [0044], [0050] and [0058] are, and
this file cross-links back to them for *why*; keep this file itself current
with *what is true today*. Every build cibuildmp runs — natmod, every usermod
port, `qemu` — runs inside one of these; there is no bare-host build path left
at all ([0030], [0033], [0050]).

## Two tables, two different questions

- **`resources/pinned_pypa_images.toml`** — a faithful mirror of upstream
  cibuildwheel's own `pinned_docker_images.cfg`, refreshed by
  `bin/update_docker.py`. **Base images only.** Nothing runs a build in them
  directly, and cibuildmp's own code never reads this file at build time —
  only `bin/update_docker.py` does, to keep the mirror current and to check
  the *other* table (below) for drift.
- **`resources/pinned_docker_images.toml`** — the images cibuildmp itself
  publishes and actually runs builds in, one flat `[image_group]` table keyed
  by **group name**, not by port. Most unix groups are a thin `FROM` over a
  `pinned_pypa_images.toml` base plus the handful of dev packages `ports/unix`
  needs (`pkg-config --libs libffi` fails to resolve on a stock
  `manylinux_2_28` image — [0043] has the full argument); the rest (the six
  toolchain groups, `windows`, `webassembly`, `esp_idf_base`) have no pypa
  counterpart at all.

## Resolving an image: `dockerrun.image_for()`

In order, first match wins:

1. **`CIBMP_<PORT>_<TARGET>_DOCKER_IMAGE`** env override (`TARGET` omitted for
   a port with no per-build image axis) — always wins, for local testing
   against a freshly-built image or a fork's image, no source/resource edit
   needed.
2. **`resources/build-platforms.toml`**'s own `image = "..."` (scalar, one
   group for the whole port) or `images.<target> = "..."` (a map, one group
   per arch/board/platform-tag) at that port's table level.
3. **`resources/pinned_docker_images.toml`**'s `[image_group]` table, keyed
   by the group name step 2 produced.

A group declared in step 2 but missing (or empty) in step 3 resolves to
`None`, and each `build_<port>()` raises its own `UsermodBuildError` ("no
image registered...") immediately — not a slow fallback to building one
locally. **cibuildmp never builds a Docker image itself, only pulls a
published one** ([0033]) — checked directly against cibuildwheel's own
`oci_container.py`, which has no `docker build`/`buildx` call anywhere
either. A user who wants an unpublished or locally-modified image builds it
themselves with a plain `docker build` and reaches it through step 1; nothing
about that requires cibuildmp code to change.

## The five kinds of image group

**1. `unix`/`musllinux` — one native image per (arch, libc floor), identity
keyed.** The group name *is* a real PEP 600/656 platform tag
(`manylinux_2_28_x86_64`, not a private spelling), because [0031]/[0043]
decided the floor belongs in the name, not buried in a `FROM` line nobody
checks. Fifteen cells total, but **only five have a real cibuildmp-published
layer** — the rest are a bare mirror of the pypa base, verified to need
nothing added, so their own Dockerfile and GHCR package were deleted rather
than kept as an idle copy:

| Cell | Reference | Has its own `ghcr.io/ballistics-lab/...` layer? |
| --- | --- | --- |
| `manylinux_2_28_x86_64` / `_i686` / `_aarch64` / `_ppc64le` / `_s390x` | thin layer over pypa | ✅ (adds `libffi-dev` etc.) |
| `manylinux_2_31_armv7l`, `manylinux_2_39_riscv64` | pypa's own image, unmodified | ❌ — pinned reference points straight at `quay.io/pypa/...` |
| `musllinux_1_2_*` (all seven arches) | pypa's own image, unmodified | ❌ — same |
| `manylinux_2_39_mipsel` | cibuildmp's own, cross-compiling | ✅ — but see below |

`manylinux_2_39_mipsel` is the one documented exception to the whole "native
per-arch image" model: pypa publishes no mipsel image, PEP 600 defines the
tag form but not a closed architecture list, and there is no Docker Official
Image for 32-bit mipsel either — there is nothing to be native to. It has no
`pinned_pypa_images.toml` entry at all (that base is not one of pypa's) and
builds as a cross-compile from a plain `ubuntu:24.04` its own Dockerfile
names. See [0068] for why this cell's own toolchain story is currently being
revisited — the apt cross-toolchain it relies on today lost upstream Debian
support entirely.

**2. `windows`** — one shared image for all three arches (`x64`/`x86` plain
apt `gcc-mingw-w64-*`, `arm64` a pinned `llvm-mingw` tarball; no Debian/Ubuntu
package targets `aarch64-w64-mingw32` at all). No per-arch split like `unix`'s
— there is no second Windows libc a binary could be built against, so the
isolation argument that drives `unix`'s split does not apply.

**3. `webassembly`** — one shared image, no per-build axis.

**4. Six toolchain-group images ([0058]).** Before [0058], `natmod.Dockerfile`
baked all ten `dynruntime.mk` toolchains into one image, and `qemu.Dockerfile`
carried one board's worth of `arm-none-eabi`. Both are gone: an **image group
is a toolchain, not a port** — ten of the fifteen usermod ports and four of
natmod's ten arches share one of these across port boundaries, so a group is
routinely pulled in by more than one (port, target) pair.

| Group | Holds | Named for |
| --- | --- | --- |
| `arm_embedded` | `arm-none-eabi-` | ten usermod ports (`rp2`, `mimxrt`, `samd`, `stm32`, `psoc-edge`, `alif`, `cc3200`, `renesas-ra`, `nrf`) + natmod's four Cortex-M arches + six `qemu` boards |
| `riscv_embedded` | `riscv64-unknown-elf-`/`riscv-none-elf-` | natmod's `rv32imc`/`rv64imc` + `qemu`'s `VIRT_RV32`/`VIRT_RV64` |
| `xtensa_lx106` | `xtensa-lx106-elf-` (standalone tarball, micropython.org) | natmod's `xtensa` + usermod's `esp8266` |
| `xtensa_esp` | `xtensa-esp32-elf-`/`xtensa-esp-elf-` (Espressif crosstool-NG) | natmod's `xtensawin` only |
| `natmod_host` | plain host-arch gcc (+ `-m32` multilib for `x86`) | natmod's `x64`/`x86` — a container's own `linux/amd64` *is* amd64 by construction, whatever machine is underneath, which is what frees `x86` from needing an amd64 runner |
| `ppc64le_linux` | `arm-none-eabi-`-equivalent for `qemu`'s one Linux-userspace board | `qemu`'s `POWERNV9` only |

None of these six is a PEP 600 tag, so each is named for what it holds —
there is no upstream naming convention to reuse the way `unix` reuses pypa's.
`xtensa_lx106` and `xtensa_esp` stay two separate images despite sharing an
architecture name: they are two different compilers (a micropython.org
standalone tarball vs. Espressif's own crosstool-NG build), and measured live
one is 106 MB against the other's 565 MB — merging them would make every
`esp8266` build pull 6.3x what it needs.

**5. `esp_idf_base` — not a toolchain image.** ESP-IDF is installed into it
*at build time* by `usermod/espidf.py`, not baked in, since this port's own
config table carries eight distinct `idf_version`s across its rows. `esp32`
names it directly (`image = "esp_idf_base"`).

## Full port/arch → group mapping

From `resources/build-platforms.toml`, current as of this file's own last
edit — the toml file itself is the source of truth if these ever drift apart:

**natmod** (`images.<arch>`):

| Arch | Group |
| --- | --- |
| `x64`, `x86` | `natmod_host` |
| `armv6m`, `armv7m`, `armv7emsp`, `armv7emdp` | `arm_embedded` |
| `rv32imc`, `rv64imc` | `riscv_embedded` |
| `xtensa` | `xtensa_lx106` |
| `xtensawin` | `xtensa_esp` |

**usermod** (`image = "..."` unless noted):

| Port | Group |
| --- | --- |
| `unix` | `images.<tag> = "<tag>"` — identity map, see the table above |
| `windows` | `windows` |
| `webassembly` | `webassembly` |
| `esp32` | `esp_idf_base` |
| `rp2`, `mimxrt`, `samd`, `stm32`, `psoc-edge`, `alif`, `cc3200`, `renesas-ra`, `nrf` | `arm_embedded` |
| `esp8266` | `xtensa_lx106` |

**`qemu`** (`images.<board>`):

| Board | Group |
| --- | --- |
| `MICROBIT`, `MPS2_AN385`, `MPS2_AN500`, `MPS3_AN547`, `NETDUINO2`, `SABRELITE` | `arm_embedded` |
| `VIRT_RV32`, `VIRT_RV64` | `riscv_embedded` |
| `POWERNV9` | `ppc64le_linux` |

## Publishing flow

`docker/*.Dockerfile` live at the repo root (moved out of the installed
package by [0033] — cibuildmp itself never reads them at runtime).
`.github/workflows/publish-docker-images.yml` builds and pushes every image
to GHCR on a push to `main` that touches `docker/**`, or on manual dispatch —
deliberately rare and maintainer-triggered, the same cadence
`bin/update_docker.py` has for the pypa mirror. A maintainer then copies the
real `@sha256:...` digest the workflow prints into
`pinned_docker_images.toml` by hand — the same manual step a cibuildwheel
maintainer takes for its own `pinned_docker_images.cfg`. `bin/update_docker.py`
separately checks (`update_pypa`) whether `pinned_pypa_images.toml` has
drifted from upstream, and (`update_images`) whether a `pinned_docker_images.toml`
cell that is just a bare pypa mirror (the fourteen non-`ghcr.io` unix cells
above) has drifted from the pypa pin it mirrors — it does not, and cannot,
rebuild or republish any of cibuildmp's own `ghcr.io/ballistics-lab/...`
layers.

[0030]: ../records/0030-container-approach-natmod-and-docker-vs-qemu.md
[0031]: ../records/0031-unix-musllinux-libc-axis.md
[0033]: ../records/0033-cibuildmp-never-builds-docker-image-itself.md
[0043]: ../records/0043-unix-adopts-cibuildwheel-native-image-model.md
[0044]: ../records/0044-unix-native-images-landed.md
[0050]: ../records/0050-natmod-is-docker-only.md
[0058]: ../records/0058-image-groups-are-toolchains-not-ports.md
[0068]: ../records/0068-docker-dependabot-grouping-and-mipsel-ubuntu-26-04.md
