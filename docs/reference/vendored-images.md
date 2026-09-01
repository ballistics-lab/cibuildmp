# cibuildmp — vendored container images

Living reference for how cibuildmp resolves a container image for a build.
This is not a decision history — [0043], [0044], [0050] and [0058] are, and
this file cross-links back to them for *why*; keep this file itself current
with *what is true today*. Every build cibuildmp runs — natmod, every usermod
port, `qemu` — runs inside one of these ([0030], [0033], [0050]). The one
thing that still runs on the host is `qemu`'s own `mpy-cross`, built before
its container starts (`_HOST_MPY_CROSS_PORTS`, `usermod/orchestrate.py`);
that port alone needs a host C compiler, and nothing else in either family
does.

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
names. Its cross-toolchain is a **pinned Bootlin tarball** (gcc 14.3.0,
glibc 2.41, sha256-checked) as of [0068]'s toolchain pass, not the apt
`gcc-mipsel-linux-gnu` it used until then: Debian 13 "Trixie" dropped the
mipsel port outright, taking those packages out of Ubuntu's archive with it.
Two consequences that are *not* done yet, both in [0068]: the published
digest in `pinned_docker_images.toml` still points at the last apt-built
image (nothing changes for callers until that image is republished), and
`2_39` no longer names the glibc this image carries, so the rename [0068]
decided (to the same tag with a 2_41 floor) has to land before a republish
rather than after. It is deliberately not written as a code span anywhere in
this file: it is not an image group yet, and
`test_vendored_images_reference_names_real_image_groups` is right to fail on
one that does not exist.

**2. `windows`** — one shared image for all three arches (`x64`/`x86` plain
apt `gcc-mingw-w64-*`, `arm64` a pinned `llvm-mingw` tarball; no Debian/Ubuntu
package targets `aarch64-w64-mingw32` at all). No per-arch split like `unix`'s
— there is no second Windows libc a binary could be built against, so the
isolation argument that drives `unix`'s split does not apply.

**3. `webassembly`** — one shared image, no per-build axis.

**4. Six toolchain-group images ([0058]).** Five of the six cover natmod's
own ten arches; `ppc64le_linux` is `qemu`-only and reaches no natmod arch,
which is why README counts five and this file counts six. Before [0058], `natmod.Dockerfile`
baked all ten `dynruntime.mk` toolchains into one image, and `qemu.Dockerfile`
carried one board's worth of `arm-none-eabi`. Both are gone: an **image group
is a toolchain, not a port** — ten of the fifteen usermod ports and four of
natmod's ten arches share one of these across port boundaries, so a group is
routinely pulled in by more than one (port, target) pair.

| Group | Holds | Named for |
| --- | --- | --- |
| `arm_embedded` | `arm-none-eabi-` | nine usermod ports (`rp2`, `mimxrt`, `samd`, `stm32`, `psoc-edge`, `alif`, `cc3200`, `renesas-ra`, `nrf`) + natmod's four Cortex-M arches + six `qemu` boards |
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
*at build time*, not baked in, since this port's own config table carries
eight distinct `idf_version`s across its rows. `esp32` names it directly
(`image = "esp_idf_base"`).

The host/container split for this port, exactly:

| step | where | what |
| --- | --- | --- |
| `git clone` ESP-IDF + submodules | **host** | `espidf.py`'s `fetch_esp_idf()`, into `<cache>/esp-idf/<version>` — source, not binaries, the same rule `mpy_dir` follows |
| `idf_tools.py install --targets=<target>` | container | downloads the compilers for that MCU |
| `idf_tools.py install-python-env` | container | ESP-IDF's own venv |
| `idf_tools.py export` + `idf.py` | container | the build itself |

The three container steps are guarded by a `.installed` marker inside the
tools directory (`build_esp32.py`'s own script), which lives on the host
through the mount — so the tool download is paid once per
(`idf_version`, `idf_target`) and reused by every later build, including
ones in a fresh container.

## Full port/arch → group mapping

Generated from `resources/build-platforms.toml` by `bin/refresh_docs.py`,
not maintained by hand — the previous version of this section promised it was
"current as of this file's own last edit", which is exactly the promise that
goes stale without anyone noticing. `tests/test_docs.py` fails the build if
the block below is out of date, and a group named here that
`resources/pinned_docker_images.toml` does not carry is marked inline rather
than quietly resolving to nothing at build time.

<!-- generated: image-group-mapping -- bin/refresh_docs.py, do not edit by hand -->
**natmod (`images.<arch>`)**

| Arch | Group |
| --- | --- |
| `armv6m` | `arm_embedded` |
| `armv7emdp` | `arm_embedded` |
| `armv7emsp` | `arm_embedded` |
| `armv7m` | `arm_embedded` |
| `rv32imc` | `riscv_embedded` |
| `rv64imc` | `riscv_embedded` |
| `x64` | `natmod_host` |
| `x86` | `natmod_host` |
| `xtensa` | `xtensa_lx106` |
| `xtensawin` | `xtensa_esp` |

**usermod, one image for the whole port (`image = "..."`)**

| Port | Group |
| --- | --- |
| `alif` | `arm_embedded` |
| `cc3200` | `arm_embedded` |
| `esp32` | `esp_idf_base` |
| `esp8266` | `xtensa_lx106` |
| `mimxrt` | `arm_embedded` |
| `nrf` | `arm_embedded` |
| `psoc-edge` | `arm_embedded` |
| `renesas-ra` | `arm_embedded` |
| `rp2` | `arm_embedded` |
| `samd` | `arm_embedded` |
| `stm32` | `arm_embedded` |
| `webassembly` | `webassembly` |
| `windows` | `windows` |

**usermod `qemu` (`images.<target>`)**

| Board | Group |
| --- | --- |
| `MICROBIT` | `arm_embedded` |
| `MPS2_AN385` | `arm_embedded` |
| `MPS2_AN500` | `arm_embedded` |
| `MPS3_AN547` | `arm_embedded` |
| `NETDUINO2` | `arm_embedded` |
| `POWERNV9` | `ppc64le_linux` |
| `SABRELITE` | `arm_embedded` |
| `VIRT_RV32` | `riscv_embedded` |
| `VIRT_RV64` | `riscv_embedded` |

**usermod `unix` (`images.<target>`)**

| Target | Group |
| --- | --- |
| `manylinux_2_28_aarch64` | `manylinux_2_28_aarch64` |
| `manylinux_2_28_i686` | `manylinux_2_28_i686` |
| `manylinux_2_28_ppc64le` | `manylinux_2_28_ppc64le` |
| `manylinux_2_28_s390x` | `manylinux_2_28_s390x` |
| `manylinux_2_28_x86_64` | `manylinux_2_28_x86_64` |
| `manylinux_2_31_armv7l` | `manylinux_2_31_armv7l` |
| `manylinux_2_39_mipsel` | `manylinux_2_39_mipsel` |
| `manylinux_2_39_riscv64` | `manylinux_2_39_riscv64` |
| `musllinux_1_2_aarch64` | `musllinux_1_2_aarch64` |
| `musllinux_1_2_armv7l` | `musllinux_1_2_armv7l` |
| `musllinux_1_2_i686` | `musllinux_1_2_i686` |
| `musllinux_1_2_ppc64le` | `musllinux_1_2_ppc64le` |
| `musllinux_1_2_riscv64` | `musllinux_1_2_riscv64` |
| `musllinux_1_2_s390x` | `musllinux_1_2_s390x` |
| `musllinux_1_2_x86_64` | `musllinux_1_2_x86_64` |
<!-- /generated: image-group-mapping -->

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
