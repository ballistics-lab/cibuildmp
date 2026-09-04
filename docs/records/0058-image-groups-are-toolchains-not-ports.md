# 0058 — the image axis is the toolchain, not the port

- Status: Accepted. **Data half and all seven Dockerfiles landed**; every image is built
  and verified by running it, two of them by a real firmware build. Not started:
  `pinned_docker_images.toml` still has its `[port]` table, `dockerrun.image_for()` still
  branches per port, `QEMU_BOARD_CROSS` is still a hardcoded dict, and nothing is
  published — so `natmod.Dockerfile`/`qemu.Dockerfile` stay until the resolver moves
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

## The images, built and verified

Written 2026-08-28 and each one run, not just built. All seven are `ubuntu:24.04`, not a
pypa base: `unix` builds on pypa's own because those targets are genuinely native and need
manylinux's glibc floor ([0043]/[0044]); nothing here is, and `manylinux_2_28_x86_64` is
589 MB compressed before a toolchain is added to it.

| image | size | verified by |
|---|---|---|
| `riscv_embedded` | 2.06 GB | a real `ports/qemu` `VIRT_RV32` build — `firmware.elf`, 247 637 text bytes |
| `arm_embedded` | 1.62 GB | a real `ports/qemu` `MPS2_AN385` build — `firmware.elf`, ELF32/ARM/EXEC |
| `xtensa_esp` | 1.03 GB | gcc 16.1.0, compiles to Tensilica Xtensa, 29 prefixed tools |
| `natmod_host` | 689 MB | `gcc -m32` produces ELF32; `i686-linux-gnu-gcc` works |
| `ppc64le_linux` | 620 MB | PowerPC64 object, and `#include <stdio.h>` resolves |
| `xtensa_lx106` | 558 MB | gcc 4.8.5, compiles to Tensilica Xtensa |
| `esp_idf_base` | 556 MB | git/cmake/ninja/ccache/venv present, **no toolchain** |

The worst case a build now pulls is 2.06 GB against `natmod.Dockerfile`'s 4.09 GB, and
`esp8266` pulls 558 MB where it used to pull all 4.09 GB.

### Three things only running them could have found

- **`esp_idf_base` needs `build-essential`, and ESP-IDF's own prerequisite list omits it.**
  That list assumes a developer machine with a compiler already on it. Built from it
  literally, the image had no `cc`, no `gcc` and no `make` — and this port needs all three
  (`ports/esp32` is Makefile-driven, `mpy-cross` is a host C program built before the
  firmware, IDF's cmake runs host compiler checks). Fixed, and the Dockerfile says why.
- **A hand-written symlink list is short by exactly one tool.** `riscv_embedded` and
  `xtensa_esp` alias their xpack/crosstool-NG prefixes to the ones `dynruntime.mk` and
  `ports/qemu` spell. The list was copied from `natmod.Dockerfile`, where ten names
  sufficed because `dynruntime.mk` never assembles. A port build does: `VIRT_RV32` died on
  a missing `riscv64-unknown-elf-as` at `shared/runtime/gchelper_rv32i.s`. Both files now
  glob the toolchain's own `bin/` — 35 tools for RISC-V, 29 for Xtensa — because a glob
  cannot be short by one.
- **picolibc is not needed, and `arm_embedded` needs three fewer apt packages than the
  composite action installs.** `ports/qemu/Makefile` probes `--print-file-name=picolibc.specs`
  and upstream's comment warns the Debian bare-metal RISC-V toolchain defaults to `nosys`;
  xpack ships newlib, the probe finds nothing, and `VIRT_RV32` links anyway. On the ARM
  side, `build-usermod-rp2040` apt-installs `gcc-arm-none-eabi`, `libnewlib-arm-none-eabi`
  and `libstdc++-arm-none-eabi-newlib`; checked inside the built image, xpack already ships
  `libstdc++.a`, the full C++ header set and newlib's `libc.a`. Installing them would put a
  second, older `arm-none-eabi-gcc` on PATH. A C++ translation unit compiles for Cortex-M0+
  and yields ELF32/ARM — which is [0054]'s own "unverified" C++ question, answered for ARM.

### Why `natmod_host` is not just a manylinux image

The obvious objection, and it was measured rather than argued. natmod's `x86`/`x64` are
native builds; pypa already publishes native images; `manylinux_2_28_x86_64` is already a
cell in this project's own `unix` matrix. Reusing it would delete a Dockerfile and a pin.

It does not work out, for four reasons, three of them found by running the image:

- **Size, and no sharing to offset it.** `manylinux_2_28_x86_64` is 1.69 GB against
  `natmod_host`'s 689 MB. The "it is pulled anyway" argument does not survive contact with
  the consuming repos: natmod and usermod are *separate workflows* in both of them
  (`mp-natmod.yml`/`mp-usermod.yml` in a7p, `natmod.yml`/`usermod.yml` in
  micropython-bclibc), so a natmod job never pulls a `unix` image and there is nothing to
  share with. The reuse is 2.5x more bytes for the same build.
- **pyelftools is too old there.** `dnf` offers `python3-pyelftools 0.27` from EPEL;
  [0012] sets the floor at `>=0.29` deliberately, and argues for it — the pin is shared
  across every tag a user's config builds. Meeting it means `pip` into one of
  `/opt/python/*/bin`, since the image has no system `pip3`.
- **The `cross` prefixes do not exist on RHEL.** `py/dynruntime.mk` at v1.28.0 sets
  `CROSS =` empty for both host arches and adds `-m32` for `x86`, but this table records
  `i686-linux-gnu-`/`x86_64-linux-gnu-` for v1.29.0 and v1.30.0-preview. A Red Hat base has
  no such prefixed binaries, so they would have to be symlinked — and the `i686` one would
  have to genuinely target 32-bit, not just be plain `gcc` under another name.
  `natmod_host` gets both from real Debian packages (`gcc-i686-linux-gnu`,
  `gcc-13-multilib`) instead.
- **It couples natmod's requirements into an image whose job is `unix`.**

What the experiment did establish, and worth keeping: `gcc -m32` works in
`manylinux_2_28_x86_64` and yields ELF32. Nothing about the 32-bit path is fragile or
distribution-specific; `natmod_host` is a size and packaging choice, not a workaround.

### What the old `qemu.Dockerfile` could never do

It installs `gcc-arm-none-eabi` and `libnewlib-arm-none-eabi` and nothing else, while
`build.py`'s `QEMU_BOARD_CROSS` names `VIRT_RV32` and `VIRT_RV64` as supported with
`riscv64-unknown-elf-`. Those two builds would have failed on a missing compiler in that
image. Nothing caught it because the only `qemu` leg CI ever runs is `MPS2_AN385` ([0032]).
So the split closes a latent gap rather than moving one — and `QEMU_BOARD_CROSS` itself,
three boards out of the nine in the table, is what `images.<board>` replaces.

## What is not decided here

- **Where the toolchain pins live.** Each Dockerfile now declares its own as
  `ARG TOOLCHAIN_URL` / `ARG TOOLCHAIN_SHA256` rather than burying them in a `RUN`, so a
  bump is one greppable line and `--build-arg` is a seam a table can feed. They are still
  four values in four files, which is the copy [0010] argues against and [0046] already
  counts as a pinned thing nothing watches. `resources/pinned_toolchains.toml` is the
  answer; it is not written.
- **Deletion order.** `natmod.Dockerfile` and `qemu.Dockerfile` are superseded but must
  outlive the resolver change: `_pins()["port"]` still returns them, so removing the files
  before `image_for()` moves would break `main`. They go once the seven are published and
  pinned, recorded as an addendum here rather than deleted quietly ([0041]).
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

## Addendum, 2026-08-28 — resolver cutover landed; two bugs only running it for real found

Everything the header above still lists as "Not started" is done. `pinned_docker_images.toml`
is one flat `[image_group]` table (the old two-level `[image.<arch>].<floor>` plus separate
`[port]` table are gone); `dockerrun.image_for()` lost its `if port == "unix"` branch and now
resolves every port through `_image_group_for()` reading `build-platforms.toml`'s own
`image`/`images` keys, uniformly; `unix_targets()` reads its fifteen declared cells straight
from `build-platforms.toml` instead of the pin file, so "what targets exist" and "what has a
published image" are the two separate questions the record's own "not decided" section asked
for; `natmod.Dockerfile`/`qemu.Dockerfile` are deleted, superseded by the six toolchain images
plus `esp_idf_base`, all seven built, published and pinned. Of the record's own five "not
decided" items, two are therefore closed by this: **deletion order** (the Dockerfiles are
gone, `_pins()["port"]` no longer exists to break) and **`unix_targets()`'s new source**. The
other three are still genuinely open and are carried forward, not dropped: where the toolchain
pins live (`resources/pinned_toolchains.toml` is still not written — four `ARG` pairs in four
Dockerfiles), whether a natmod sweep should pull per-arch or up front, and whether `windows`'s
single shared image is right.

Two real bugs surfaced only by actually running the cutover, neither found by review:

- **`natmod`/`qemu` briefly resolved to no image at all.** `_image_group_for(port, None)`
  correctly returns `None` for a port whose row is an `images` map when no target is given —
  but the call sites (`natmod/build.py`, `usermod/build.py`'s `build_qemu()`) weren't yet
  passing their own `arch`/`board` through, so `ensure_image("natmod")`/`("qemu")` silently
  resolved to nothing. Caught by CI within one push (`build-examples.yml`'s natmod and qemu
  legs both failed), fixed by threading `arch` through `run_pre_build_command()`/`run_make()`/
  `build_mpy_cross()` into `_natmod_image()`, and `opts.board` through `build_qemu()`'s own
  `ensure_image()`/`timeout_for()`/`platform_for()` calls.
- **`[usermod.webassembly]`'s own `image` key named a group that was never real.** It said
  `image = "emsdk"`; `pinned_docker_images.toml`'s flat table has only ever had a `webassembly`
  key, matching every other row's own convention (`windows`, `esp_idf_base`, `arm_embedded`,
  `xtensa_lx106` all name a real key). `dockerrun.ensure_image("webassembly")` therefore always
  resolved to `None`, and `build_webassembly()`'s own `UsermodBuildError` fired every time —
  just never observed, because `webassembly` hadn't been exercised in `build-examples.yml`
  since before this bug was introduced (`033bce2`, itself titled "0058 — docker image id's",
  predates this session). Found the moment `webassembly`'s image was actually republished (see
  [0059]) and the leg ran for real. Fixed by one-line correction to the row's own `image` key —
  no other row has this mismatch, checked by grepping every `image = "..."` value against
  `pinned_docker_images.toml`'s real keys.

Also folded in from the same wave of pushes, recorded at their own more specific homes: `ar`'s
restoration to `pyproject.toml` and the mount-not-bake mechanism for it and `pyelftools`
([0012]'s own second addendum), and the GHCR "manifest unknown" incident across seven of the
fifteen `ghcr.io/ballistics-lab/...` images — a registry-side content loss underneath pins that
were never touched, not a staleness question ([0046]'s own subject) but a closely related one,
written up as its own record: [0059].

## Addendum, 2026-08-28 (second) — `QEMU_BOARD_CROSS` closes: nine boards, not three

The header's own "still open" line and the "the split closes a latent gap rather than moving
one" section above both name this exactly: `platforms/usermod/build.py`'s `QEMU_BOARD_CROSS`
only had toolchain prefixes for `MPS2_AN385`/`VIRT_RV32`/`VIRT_RV64`, while this table's own
`images.<board>` map (above) already resolved a real image for all nine boards. Every remaining
prefix was already sitting in this table's own per-row `cross` field, verified stable across
v1.24.0..v1.29.0 -- nothing new to derive, just not yet copied into the dict. Closed by copying
it: `MICROBIT`/`MPS2_AN500`/`MPS3_AN547`/`NETDUINO2`/`SABRELITE` (`arm-none-eabi-`, `arm_embedded`)
and `POWERNV9` (`powerpc64le-linux-gnu-`, `ppc64le_linux`) added.

`POWERNV9` needed its own real proof rather than trusting the table: no qemu board had ever built
through `ppc64le_linux` before ([0058]'s own verification table above only ever ran a bare
`gcc`/`#include` smoke test against it). Confirmed live: `cibuildmp examples/template --build
v1.29.0-qemu-POWERNV9` produced a genuine PowerPC64 `firmware.elf` (584640 bytes). All eight
other boards confirmed live the same way, individually, not inferred from the table alone --
`MICROBIT` first, then `MPS2_AN500`/`MPS3_AN547`/`NETDUINO2`/`SABRELITE` in one invocation, all
nine boards across both `v1.28.0`/`v1.29.0` tags green in a real `test-platforms.yml` run the same
session (previously the only qemu identifier that workflow's own broad sweep could build at all
was `MPS2_AN385`, the one board CI already proved via `build-examples.yml`'s own dedicated leg).

**Correction, 2026-09-01 — "nothing about the 32-bit path is fragile" did not hold.** The
`natmod_host` verification table above names `gcc-13-multilib` as one of the two real Debian
packages behind `x86`'s `cross = ""` half (the other being `gcc-i686-linux-gnu`, for the
`i686-linux-gnu-` half this same section's `x86 {'': 22, 'i686-linux-gnu-': 2}` count already
put at only two tags). `gcc-13-multilib` is pinned by gcc *version*, not by what
`build-essential` resolves to — fragile exactly the way a hand-picked version pin usually is,
and it broke the first time `docker/natmod_host.Dockerfile`'s base moved (`ubuntu:24.04` to
`ubuntu:26.04`, whose own `build-essential` resolves to gcc 15, not 13): every `-m32` `x86`
build whose module references libgcc failed with "LinkError: incompatible arch", for every one
of the twenty-two tags this record's own count puts on that path. See docs/records/0068's own
third correction for the full incident and the fix -- the same package name, computed at build
time (`gcc-$(gcc -dumpversion | cut -d. -f1)-multilib`) rather than typed by hand, after the
first attempt (the unversioned `gcc-multilib` metapackage) turned out to conflict with
`gcc-i686-linux-gnu`, the other package this image has always installed alongside it.

**Correction, 2026-09-04 — this record's own headline stops being true for the
`arm_embedded`/`riscv_embedded` group, twice, in two different records.** "The image axis is
the toolchain, not the port" assumed one image held exactly one toolchain, baked in. [0085]/
[0087]/[0089] broke that first: the toolchain *version* moved off the image entirely, into a
per-row `gcc` fact fetched at container run time ([0086]) -- the image still named one toolchain
*family*, just no longer one fixed *version* of it. [0090]'s own item 3 named this as the
revision this record's text owed itself, not a silent drift. [0096] broke it a second, larger
way: `arm_embedded` and `riscv_embedded`, the two Dockerfiles this record's own body cites as
its working example of "one shared group, one Dockerfile" (`ten of the fifteen usermod ports
compile with the same arm-none-eabi GCC ... they name one shared group and there is one
Dockerfile"`), merged into `embedded_base` -- one image now holding *two* toolchain families
(`arm-none-eabi-` and `riscv64-unknown-elf-`), told apart at fetch time by the row's own `cross`
fact, not by the image at all. `docs/reference/vendored-images.md`'s own generated table and
prose, `README.md`'s group counts, and `docs/reference/design.md` are already current as of
[0096]; this correction is this record's own acknowledgment, per [0090]'s item 3, rather than
leaving a later reader to find the gap between this file's title and what the image axis
actually encodes today.

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
[0059]: 0059-ghcr-untagged-cleanup-deletes-referenced-manifests.md
[0068]: 0068-docker-dependabot-grouping-and-mipsel-ubuntu-26-04.md
