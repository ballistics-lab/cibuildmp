# 0058 — the image axis is the toolchain, not the port

- Status: Accepted for the data half (the keys are in `build-platforms.toml` as of this
  record). Not started for the rest: no Dockerfile is written, `pinned_docker_images.toml`
  still has its `[port]` table, and `dockerrun.image_for()` still branches per port
- Related: [0010], [0012], [0026], [0033], [0044], [0046], [0050], [0052]

## What this decides

`dockerrun.image_for()` resolves an image from the port name today, via
`_pins()["port"].get(port)`, with a hardcoded `if port == "unix"` branch above it. That
mapping is one-image-per-port. This record replaces the *key*: a build's image is chosen
by **which toolchain it needs**, not by which port it is building.

Ten of the fifteen usermod ports compile with the same `arm-none-eabi` GCC. Under
one-image-per-port each of them needs its own Dockerfile holding an identical toolchain.
Under this record they name one shared group and there is one Dockerfile.

The mapping itself lives in `resources/build-platforms.toml`, at the table level of each
port, beside `identifier_format` / `artifacts_dir_name` / `post_checkout`.

## Where this came from, and what it corrects

[0044] and [0052] both carry the same paragraph, in the same words: a consolidation onto
`arm_embedded` / `riscv_embedded` / `xtensa_lx106` / `esp_idf`, "sketched but not built",
driven by "`resources/build-platforms.toml`'s own per-row `cross` fact". [0052] adds the
open design question — a new stored field (`toolchain` / `image_group`) versus a pure
function computed from `cross` at resolution time — and leans to the latter, on the
grounds that `build-platforms.toml` should describe only verified upstream facts.

That sketch is right about the shape and wrong about the key, in two ways this record
found by reading the table rather than the sketch.

### `cross` is a per-tag fact, and it is absent exactly where it would mislead

`bin/refresh_natmod_archs.py` derives `cross` by parsing `py/dynruntime.mk`. Tags that
declare no prefix produce no value. Counting the real rows:

```
armv6m     {'': 7,  'arm-none-eabi-': 17}        empty on v1.12-v1.18
rv32imc    {'': 2,  'riscv64-unknown-elf-': 7}   empty on v1.24.0, v1.24.1
rv64imc    {'': 1,  'riscv64-unknown-elf-': 3}   empty on v1.27.0
x86        {'': 22, 'i686-linux-gnu-': 2}
x64        {'': 22, 'x86_64-linux-gnu-': 2}
```

An empty `cross` means *this tag declared no prefix*, not *native*. [0044] says as much
in its own words already ("`cross` is genuinely absent (not "") through v1.18") without
drawing the consequence: a function keyed on `cross` routes `armv6m` at v1.12 to the
host image and compiles a Cortex-M0 target with the host GCC. The failure is silent at
resolution time and only shows up as a build error, or worse, an `.mpy` for the wrong
architecture.

**`arch` is the stable key for `[natmod]`.** It is present on every row, identical
across every tag, and it is the axis natmod is actually built along.

### The image axis is not single-valued for every port either

The sketch assigns one image per port. Two ports do not fit, and both were found by
grouping the rows rather than by reading the port list:

- **`qemu` spans three toolchains.** Six Cortex-M/A boards on `arm-none-eabi-`, two
  RISC-V boards, and `POWERNV9` on `powerpc64le-linux-gnu-`. It needs a per-board map.
  This is the same "qemu's move to per-board resolution" that [0052] left open; it is
  answered here.
- **`esp32` spans two instruction sets** — Xtensa (`esp32`, `esp32s2`, `esp32s3`) and
  RISC-V (`esp32c2`, `esp32c3`, `esp32c6`) — and neither compiler belongs in the image
  at all; see below.

## Why the key lives at the table level, not in the rows

Decided by the user, and the mechanism is exact. `bin/refresh_usermod_boards.py` prints

```
[tags]
[usermod.<port>]
identifiers = [ ... ]
```

and nothing else. `bin/refresh_natmod_archs.py` is the same, and says so in its own
docstring ("This script does not write build-platforms.toml itself"). The four existing
table-level keys — `identifier_format`, `artifacts_dir_name`, `pre_checkout`,
`post_checkout` — are hand-maintained and are not emitted by either script.

So the table level is already this file's established home for cibuildmp's own policy,
and the rows are already established as regenerated upstream facts. A toolchain group is
policy: it names an image this project publishes, which no MicroPython tag has an opinion
about. Putting it in a row would mean either losing it the next time a refresh block is
pasted in, or teaching a refresh script to emit infrastructure policy.

This also rules out the alternative [0052] leaned toward. A pure function computed in
`dockerrun.py` keeps the rows clean but puts the mapping in Python, and [0010] is a record
about exactly that: pinned data lives in `resources/`, not in code. The table level
satisfies both rules at once — out of the regenerated rows, out of Python.

### Dotted keys, because TOML 1.0 has no multi-line inline table

`images = {\n  x86 = "natmod_host",\n}` is a `TOMLDecodeError` under `tomllib`, which
implements TOML 1.0; multi-line inline tables are a 1.1 feature. A single-line inline
table parses (266 characters for natmod's ten arches, against a 356-character longest
line already in this file) but is unreadable. A `[natmod.images]` header parses too, and
must then sit *after* `identifiers` — TOML forbids reopening `[natmod]` once a subtable
of it is opened — putting the policy two hundred lines below the rest of the policy.

Dotted keys (`images.x86 = "natmod_host"`) build the subtable incrementally, stay inside
the parent table, and sit exactly where the other policy sits. That is what shipped.

One shape was tried and rejected for a reason worth recording: writing
`natmod.identifiers = [...]` after a `[natmod.images]` header **parses without error** and
silently produces `natmod.images.natmod.identifiers`. It is the same class of bug [0048]
is entirely about — a misplaced key that no error catches.

## The four groups are six

| group | who pulls it | note |
|---|---|---|
| `arm_embedded` | natmod `armv6m`/`armv7m`/`armv7emsp`/`armv7emdp`; usermod `rp2`, `stm32`, `samd`, `mimxrt`, `nrf`, `renesas-ra`, `cc3200`, `alif`, `psoc-edge`; `qemu`'s six ARM boards | the overwhelming majority — 2090 of 2315 `[natmod]` rows carry this prefix |
| `riscv_embedded` | natmod `rv32imc`/`rv64imc`; `qemu`'s `VIRT_RV32`/`VIRT_RV64` | |
| `xtensa_lx106` | natmod `xtensa`; usermod `esp8266` | |
| `xtensa_esp` | natmod `xtensawin` **only** | *not* usermod `esp32` — see below |
| `natmod_host` | natmod `x86`/`x64` | not in the sketch. `gcc-13-multilib`, `gcc-i686-linux-gnu`, `linux-libc-dev:i386` are natmod's own 32-bit host cross and belong to no toolchain group |
| `ppc64le_linux` | `qemu`'s `POWERNV9` | not in the sketch; one board |

`unix` gets fifteen keys of its own, one per (arch, libc) cell, and they are an identity
map — `images.manylinux_2_28_x86_64 = "manylinux_2_28_x86_64"`. That is not a tautology
but the honest statement of [0043]/[0044]'s model: `unix` is the one port whose image axis
and target axis coincide, because every cell is built natively for itself under emulation.

Writing them out rather than leaving `unix` special-cased was the user's call, and it buys
three concrete things beyond symmetry:

- **`image_for()` loses its last branch.** The `if port == "unix"` block and its
  two-level `_pins()["image"][arch][floor]` lookup collapse into the same single rule the
  other fourteen ports use.
- **`pinned_docker_images.toml` flattens.** Today it is `[image.<arch>].<floor>` (fifteen
  cells, two levels) plus `[port]` (four entries). It becomes one `[image_group]` table of
  twenty-one entries at one level.
- **`split_tag()` leaves the image path.** It stays necessary for the OCI platform, the
  `linux32` check and `UNIX_ARCH_SETTINGS`, but stops being part of choosing an image.

### `esp_idf_base` is not a toolchain image

The sketch's fourth group was `esp_idf`. It cannot be a toolchain image, for a reason
that only appears once `idf_version` is counted: this table carries **eight** distinct
IDF versions (`v4.0.2`, `v4.4`, `v5.0.2`, `v5.0.4`, `v5.2.2`, `v5.4.2`, `v5.5.1`,
`v5.5.2`), and `v1.20.0` varies it per *MCU* rather than per tag. Baking the toolchain in
means eight images.

By the user's own decision, **ESP-IDF is installed at build time by the driver, not baked
into an image.** `usermod/espidf.py` already caches a clone plus `install.sh` output by
`(version, target)` under `cache_root()`, and `dockerrun.run()` bind-mounts each of its
`mounts` at its own identical host path — so the cache reaches the container at the path
`IDF_PATH` already expects, with no rewriting. `esp32` therefore names one base image that
IDF is installed *into*, and its two instruction sets stop being an image question at all.

The one thing that must be got right: `install.sh` fetches binaries built for a specific
glibc. The cache must be populated **from inside the container**, not on the host, or an
Ubuntu 24.04 image will consume binaries resolved against whatever the runner had.

## Where this deliberately diverges from cibuildwheel

Read against a real install (`cibuildwheel==4.2.0`, `options.py`). Upstream keys images by
architecture, one option per arch — `manylinux-{build_platform}-image`,
`musllinux-{build_platform}-image` — resolved through `_get_pinned_container_images()`.
There is no grouping mechanism and no reason for one: every cibuildwheel target is built
*natively* for its own architecture, under emulation where the host cannot do it directly,
so the image axis and the target axis are the same axis.

cibuildmp's targets are cross-compiled. Ten ports share one `arm-none-eabi` GCC, and the
image that holds it has nothing to do with which port is being built. Keeping upstream's
one-image-per-target key here would mean ten Dockerfiles with identical contents. The
divergence is in the key, not the mechanism: the pinned table, the digest pinning, the
`CIBMP_*_DOCKER_IMAGE` override and the pull-only rule ([0033]) are all unchanged.

## What is not decided here

- **The Dockerfiles.** None of the six is written. All four cross toolchains currently
  live inline in `docker/natmod.Dockerfile` (moved there by [0050]) as URL + sha256 pairs,
  which [0046] already flags as a fifth pinned thing nothing watches. Splitting them across
  six files is the moment to move those pins into `resources/`, per [0010], rather than
  copy them.
- **`pyelftools` and `ar` go in all of them.** [0012]'s dependencies are `mpy_ld.py`'s, and
  `mpy_ld.py` runs for every natmod arch, not just the host ones. Only the multilib/i386
  packages are `natmod_host`-specific.
- **A full natmod sweep will pull four images instead of one.** `natmod/build.py` calls
  `ensure_image("natmod")` once for the whole loop today. After the split, `--archs armv7m`
  pulls roughly a quarter of the current 4.09 GB and `--archs all` pulls about the same
  total. The narrow case wins; the broad case is a wash. Whether the loop should pull
  lazily per arch or up front is not designed.
- **`unix_targets()` needs a new source.** It builds its fifteen tags by walking
  `_pins()["image"]`, and its docstring is explicit that this is deliberate: a declared
  target with no published image must fail with "no image registered", not "unknown
  architecture". Once the pins table flattens, "what targets exist" comes from
  `build-platforms.toml` and "what has an image" from the pins lookup — which separates
  the two questions the function currently welds together, but the error semantics have
  to be carried across on purpose rather than by accident.
- **Whether `windows`'s single image is right.** Carried over unresolved from [0052]; its
  three arches share one image today and nothing here re-examines that.

[0010]: 0010-pinned-data-in-resources.md
[0012]: 0012-pyelftools-ar-own-deps.md
[0026]: 0026-one-docker-image-per-port.md
[0033]: 0033-cibuildmp-never-builds-docker-image-itself.md
[0043]: 0043-unix-adopts-cibuildwheel-native-image-model.md
[0044]: 0044-unix-native-images-landed.md
[0046]: 0046-pin-staleness-checker.md
[0048]: 0048-build-skip-live-in-opposite-tables.md
[0050]: 0050-natmod-is-docker-only.md
[0052]: 0052-config-is-a-tree-not-a-selector-matrix.md
