# 0044 — landing [0043]: pypa-based native images, the full arch × libc matrix, and the two things it broke

Status: Implemented (code, tests and tooling landed; the matrix is published and all
six default cells are green on CI as of 2026-08-26 -- see the addendum. The six
emulated-everywhere cells are **descoped from CI, kept in the matrix** by the
2026-08-28 addendum, which closes this record's last open question)

Supersedes nothing. This is the implementation record for [0043], which was
accepted as a plan with "nothing here is verified live yet" written into its own
closing line. Everything below either confirms that plan against real containers
or corrects it — and two of the corrections are things the plan could not have
known, because they only appear once a build actually runs.

## What the user decided, and it widened the plan

[0043] sketched a migration in six steps, starting from one arch pair. Asked
directly, the user chose otherwise on three axes, and the scope here follows
their call rather than the sketch:

- **Base images: a thin layer over pypa's own**, not `ubuntu:24.04`. This is
  what makes the manylinux claim real rather than decorative — the floor is
  pypa's, curated per arch, not "whatever the base happens to ship" ([0031]'s
  own complaint).
- **The whole matrix at once**, not one cell proven before the next. Fifteen
  cells: cibuildwheel's seven architectures × manylinux/musllinux, plus
  cibuildmp's own `mipsel`.
- **Rename the axes now**, accepting that every existing `unix` identifier
  changes. `x64` → `x86_64`, `x86` → `i686`, `armhf` → `armv7l`.

Two further calls came mid-implementation and are equally load-bearing:
**image names are pypa's own, with no `cibuildmp-` prefix**
(`ghcr.io/ballistics-lab/manylinux_2_28_x86_64`), and **the pin table moves out
of Python into `resources/`** — which closes a gap [0010] had already ruled on
and `PORT_IMAGES` had simply been exempt from.

## What landed

### The identifier is now a platform tag

`unix-manylinux_2_28_x86_64`, `unix-musllinux_1_2_aarch64`,
`unix-manylinux_2_39_mipsel`. `UnixBuildOptions.arch` became
`UnixBuildOptions.target`, and the value is the whole tag, not a bare
architecture.

The libc *version* is deliberately inside the identifier, which is where this
departs from cibuildwheel: upstream's build identifiers drop it
(`cp313-manylinux_x86_64`) because the version is a user-facing knob
(`manylinux-x86_64-image`). cibuildmp curates exactly one floor per architecture
and offers no such knob, so including the version costs nothing and buys the
thing [0031] and [0043] both asked for — a name that *is* a PEP 600 / PEP 656
claim rather than a label that gestures at one.

### Two pin files, both data

- `resources/pinned_pypa_images.toml` — a faithful mirror of cibuildwheel's own
  `pinned_docker_images.cfg`, every section and variant included (`manylinux2014`,
  `_2_34`, `_2_35`, the `pypy_*` sections) so re-syncing is a diff against one
  upstream file rather than a judgement call per line. Base images only.
- `resources/pinned_docker_images.toml` — cibuildmp's own published layer, plus
  the three cross-compiling ports. **Its `[image.<arch>]` keys are the matrix**:
  which floor each architecture is curated onto, and therefore which cells
  exist at all.

`cibuildmp/resources.py` -- the loader both tables go through -- moved back up
from `cibuildmp/natmod/` in the same change, since it is no longer a natmod
thing in any sense: `usermod/portinfo.py` and `usermod/dockerrun.py` now read
three of the four tables it serves.

A declared cell with an empty value is a real, nameable target that has nothing
published for it yet — `--print-build-identifiers` lists it, and building it
fails with "no image registered" rather than "unknown architecture". Those are
different errors, and conflating them is how a half-published matrix quietly
starts looking like a smaller one.

`bin/update_docker.py` refreshes both against quay.io and GHCR
(`--pypa` / `--images` / `--check`), line-oriented rather than a TOML round-trip
because both files carry far more explanation than data and `tomli_w` would
delete all of it. Its first real run immediately earned its keep: **the pypa
pins transcribed from upstream were already nine days stale**
(`2026.08.15-1` → `2026.08.24-1`). Not bumped here — a base bump is its own
reviewed decision, and for `armv7l` it can even be a different floor.

### Every port now states its container platform

`dockerrun.run()` passes `--platform`, resolved per target. For `unix` that
platform *is* the build target (the image is native to it). For `windows`,
`qemu` and `webassembly` it is `linux/amd64` — a statement about the image, a
Linux cross-compile host, not about any build target.

**This is what makes the non-`unix` ports work on an arm64 runner at all, and it
is a requirement in its own right rather than a side effect.** Those images are
amd64 and will stay amd64: they target Windows, bare metal and wasm, which no
Linux container is native to, so there is nothing for them to be native *to* and
[0043] correctly left them out of its model. What they were missing was the
platform being *stated*. Without it, resolution fell out of whatever host the
job happened to run on — correct by luck on `ubuntu-latest`, and on
`ubuntu-24.04-arm` a bare `exec format error` from inside `make`. With it, they
run emulated on an arm64 host and natively on an amd64 one, from the same pins
and the same config. Host architecture is recorded nowhere: not in a key, not in
an image name, not in an identifier. `platform.machine()` is consulted in
exactly one function, `host_oci_platform()`, and only ever to decide whether to
warn about missing emulation.

### Where this goes beyond parity, on purpose

cibuildwheel pushes emulation setup onto the caller and does not probe for it,
so a missing binfmt surfaces as `exec format error` from inside the build.
`_probe_platform()` runs one throwaway `uname -m` for non-native targets and
turns that into a sentence naming the missing binfmt and how to install it —
and, separately, distinguishes "this image is not published for that platform",
which is a pin problem rather than a host problem. One container per (image,
platform) per process, cached; native runs pay nothing.

`needs_linux32()` + `run(linux32=...)` copy cibuildwheel's own 32-bit handling
for `i686`/`armv7l` exactly: probe `uname -m` inside the container, wrap in
`linux32` only if the kernel reports 64-bit. Not verified live.

### Verification that the identifier is not a lie

Two checks run after every `unix` build, and both exist because under this model
a *wrong* result no longer looks like a failure:

- `verify_unix_output()` reads `e_machine`, `EI_CLASS` and `EI_DATA` from the
  produced ELF and compares them against the target's architecture. [0043] named
  this as required, and it is: point a build at an image for another platform
  and `make` succeeds, `gcc` succeeds, and the output is a working binary of the
  wrong architecture filed under the right identifier. `EI_DATA` is checked, not
  just `e_machine`, because `s390x` is big-endian and because `mipsel` shares
  `EM_MIPS` with big-endian MIPS. Values were read from this machine's
  `/usr/include/elf.h`, not recalled.
- `verify_unix_floor()` is the PEP 600 half [0031] specified and [0043] carried
  forward: read the binary's own highest required `GLIBC_x.y` symbol version
  (via `pyelftools`, already a dependency for [0012]'s reasons) and fail if it
  exceeds the floor the identifier claims. This is `auditwheel`'s
  `elf_find_versioned_symbols` job, reimplemented rather than shelled out to
  because `auditwheel`'s CLI only accepts a `.whl`, and `unix` produces a bare
  executable. musllinux is skipped: musl has no symbol versioning, which is
  precisely why PEP 656 is a separate spec, and its guarantee comes from the
  pinned base instead.

## The two things a live build broke, that the plan did not anticipate

### 1. mpy-cross cannot be built on the host any more

The first real build under a pypa base failed like this:

    mpy-cross: /lib64/libc.so.6: version `GLIBC_2.34' not found
    make: *** [py/mkrules.mk:231: .../frozen_content.c] Error 1

`sources.build_mpy_cross()` builds mpy-cross on the **host**, and
`py/mkrules.mk` then runs it *inside the container* to compile the frozen
manifest. That worked only for as long as every image was `ubuntu:24.04` — the
same glibc as a typical host, by coincidence rather than by design. It breaks
two independent ways now, and neither is incidental:

- **A real libc floor is a floor.** `manylinux_2_28` is AlmaLinux 8, glibc 2.28;
  a host binary needing 2.34 cannot run there. The failure gets *worse* as the
  manylinux claim gets *better*. For musllinux there is no version to argue
  about — a glibc binary does not run under musl at all.
- **Native images have a native architecture.** An x86_64 host's mpy-cross
  cannot execute inside a `linux/arm64` container under any libc. This alone
  makes the in-container build mandatory rather than merely safer, for most of
  the matrix.

`container_mpy_cross()` builds it inside the target image, into
`mpy-cross/build-<slug>/`, and the port build gets
`MICROPY_MPYCROSS=` (`py/mkenv.mk`'s own override). natmod is untouched — it
only ever runs mpy-cross on the host.

The same reasoning reaches the cross-compiling ports from the other direction,
and this is the second half of "every port works on either runner": their images
are amd64, so on an **arm64 host** the host-built mpy-cross is an arm64 binary
that cannot run inside them either. They use it too.

### 2. Only one base family was actually missing anything

Checked by running the probes inside the real images rather than assuming:

| base | distro | `pkg-config --libs libffi` | needs |
| --- | --- | --- | --- |
| `manylinux_2_28_*` | AlmaLinux 8 | **fails** | `dnf install libffi-devel` |
| `manylinux_2_31_armv7l` | Ubuntu 20.04 | `-lffi` | nothing |
| `manylinux_2_39_riscv64` | Rocky Linux 10 | `-lffi` | nothing |
| `musllinux_1_2_*` | Alpine 3.22 | `-lffi` | nothing |

All four ship gcc 14, make, python3, pkg-config, libtool and autoreconf already.
So nine of the fifteen Dockerfiles are a bare `FROM` with no `RUN` at all. They
are still published as cibuildmp images rather than pinning pypa's directly, so
that every cell shares one name scheme, one publish pipeline and one pin table —
and so the day `ports/unix` needs a package there, the file already exists. The
layers are the base's own, so a registry stores nothing new for them.

This also deletes machinery rather than fixing it, which is worth stating
plainly because it was expensive: `MICROPY_FORCE_32BIT=1` (the old `x86` row),
`MICROPY_STANDALONE=1 LDFLAGS_EXTRA=-static` plus the whole `deplibs` pre-step
(the old `armhf` row), the `dpkg --add-architecture` / `ports.ubuntu.com` mirror
rewrite, and every apt cross-toolchain are all gone. [0025] paid for six real
apt/gcc bugs in that code and [0024] verified it live. It was correct, and it is
still gone — every line of it encoded *"the host is x86_64"* as a constant.

## The third thing a live build broke: `-Werror` meets new toolchains

Neither [0043] nor this record's first draft priced this in, and it is the
clearest evidence that the plan needed running rather than reviewing. Leaving
`ubuntu:24.04` for AlmaLinux 8, Rocky 10 and Alpine means MicroPython's own
vendored third-party code — `lib/mbedtls`, `lib/berkeley-db-1.xx` — meets
compilers and libcs it has not met before, and `ports/unix` builds all of it
with `-Werror`.

Two cells failed on first run, both in vendored headers, neither in MicroPython's
own code:

- **The whole musllinux column.** `extmod/modbtree.c` includes berkeley-db's
  `db.h`, which includes `<sys/cdefs.h>` — and musl's entire copy of that header
  is `#warning usage of non-standard #include <sys/cdefs.h> is deprecated`.
  glibc has no such warning, so this is a property of the libc, not the
  architecture. Fixed with `-Wno-error=cpp` for every `musllinux_*` cell.

  **Alpine solves this differently, and it is worth reading before agreeing
  with the choice made here.** `community/micropython` in `alpinelinux/aports`
  — the distro that actually ships MicroPython built against musl — carries
  `no_legacy_berkeley_db.patch`, which is one line: `MICROPY_PY_BTREE = 0`. It
  also carries `no-werror.patch` (dropping `-Werror` wholesale rather than one
  warning) and `no_ssl.patch` (dropping mbedtls entirely). So the alternative
  this record first dismissed in a sentence is in fact the upstream-distro
  answer, and the dismissal was a guess where evidence existed.

  The guess was then checked, which is the only reason it stands. Running the
  built musl binary: `btree.open()` on a `BytesIO`, `db[b"k1"] = b"v1"`,
  read-back, `flush()`, `items()` and `close()` all work; `ssl.SSLContext(
  ssl.PROTOCOL_TLS_CLIENT)` constructs; and the usermod C module itself
  answers `template.add(2, 3) == 5`. Nothing here is broken under musl — the
  `sys/cdefs.h` warning really is cosmetic, and mbedtls builds and runs. Alpine
  is packaging a distro binary, where dropping a legacy vendored DB and an
  embedded TLS stack is a sound packaging decision; cibuildmp is producing the
  *same* MicroPython for two libcs, where a silently smaller musl feature set
  would be a worse outcome than one suppressed warning. Different goals, and
  the narrower suppression is what keeps the two columns comparable.

  If btree under musl ever does misbehave at runtime, Alpine's patch is the
  fallback and it is one line.

  One more thing that aport says, and it bears directly on this matrix:
  `arch="all !ppc64le !s390x !loongarch64"`. **Alpine does not build MicroPython
  on ppc64le or s390x at all** — two of the fourteen cells declared here, and
  two that have never been built. That is not proof they cannot work, but it is
  the strongest available signal about which unbuilt cells to expect trouble
  from first.
- **`manylinux_2_28_aarch64` only.** `lib/mbedtls/library/ctr_drbg.c` trips
  `-Werror=array-bounds=` inside `common.h`'s `mbedtls_xor` ("array subscript 48
  is outside array bounds of `unsigned char[48]`"), a gcc 14 false positive on a
  loop bounded by exactly that size. Worth stating precisely because it is *not*
  a floor problem: `manylinux_2_28_x86_64` is the same AlmaLinux 8 base and the
  same `gcc 14.2.1`, and builds clean. gcc's bounds analysis differs by target,
  so this cannot be a column-wide rule and stays a per-cell entry.

`unix_extra_cflags()` combines a libc-wide rule with a per-tag one-off table and
passes the result as `CFLAGS_EXTRA`. This is the same shape [0018] already
established for `windows`, whose `arm64` alone needs three Clang-specific
suppressions.

**Expect that table to grow.** A cell absent from it has not been proven clean;
in almost every case it has not been built at all yet. Ten of the fifteen cells
have never had a compiler pointed at them, and on this evidence — two failures in
the first two cells beyond the reference one — some of them will need entries
too.

## `mipsel` is `manylinux_2_39_mipsel`

[0043] left this open ("keeps a bespoke native image or is reconsidered") and
this record answers it: it keeps the old cross model, and says so, but it does
**not** get a private name. PEP 600's tag is
`manylinux_${GLIBCMAJOR}_${GLIBCMINOR}_${ARCH}` with the architecture being
whatever the platform reports — a *form*, not a closed list of architectures —
so `manylinux_2_39_mipsel` is well-formed and simply has no pypa image behind
it. The `2_39` is checked, not assumed: `libc6-dev-mipsel-cross` on
`ubuntu:24.04` is glibc `2.39-0ubuntu8cross2`.

Because the name is a claim, that package is **version-pinned in the Dockerfile**
(`"libc6-dev-mipsel-cross=2.39-*"`), the one apt pin in the tree. Every other
cell gets that guarantee from a digest-pinned pypa base; this one has no pypa
base, so it pins the package. The glob rather than the exact revision: apt
accepts it (verified by a real install), a security update within 2.39 neither
changes the floor nor should break the build, and the exact revision is removed
from the archive when superseded.

## Verified live, and not

**Verified, on real containers, this session:**

- `manylinux_2_28_x86_64` builds, and a full `examples/template` usermod build
  runs end to end through it (45.7s) — including mpy-cross built inside the
  container and a real custom C module linked in.
- The produced binary is `ELF 64-bit LSB executable, x86-64`, and its highest
  required symbol version is exactly `GLIBC_2.28` — the claim and the binary
  agree. `verify_unix_floor()` accepts that target and rejects a
  `manylinux_2_17_x86_64` claim on the same file.
- **`musllinux_1_2_x86_64` builds too**, once `-Wno-error=cpp` is passed —
  ~50s, and the result is a genuine musl binary rather than a glibc one under a
  musl name: `readelf -d` shows `libc.musl-x86_64.so.1` in `NEEDED`, and the
  binary carries **zero** `GLIBC_` symbol references. Run, not just linked: the
  usermod C module answers `template.add(2, 3) == 5` and the frozen
  `facade.add_three(1, 2, 3) == 6`, so both halves of what a usermod build is
  for work on the musl column. That is what [0031]'s musl half had been missing
  since it was written.
- The libffi probe table above, per base image.
- `libc6-dev-mipsel-cross` is glibc 2.39, and apt accepts the `2.39-*` pin.
- `bin/update_docker.py --check` against both registries.
- 275 unit tests.

**Not verified live, and each is a real risk rather than a formality:**

- Every cell except `manylinux_2_28_x86_64`. In particular no emulated build has
  completed here, so the aarch64 half of [0043]'s own step 1 is not closed by
  this record.
- `linux32` handling — no `i686` or `armv7l` build has run.
- musllinux entirely. [0031] found that a "static" glibc build still reaches
  glibc's `dlopen`-based NSS, so the musl column is the part of this whose
  behaviour is least predictable from the glibc column.
- The workflows. `publish-docker-images.yml` and `build-examples.yml` both grew
  an 18-cell `(image, platform)` matrix and a `setup-qemu-action` step; neither
  has run.
- **Nothing is published.** Every `[image.*]` cell is empty, so on this branch a
  `unix` build resolves nothing and says so. Local work goes through
  `CIBMP_UNIX_<TARGET>_DOCKER_IMAGE`, which is what that knob has always been
  for. Filling the table needs a real `publish-docker-images.yml` run.

## Still open

- Publish the matrix, then fill `[image.*]` (`bin/update_docker.py --images`
  does it in one pass).
- Every consuming repo's `unix` identifiers change. [0038]'s three repos pin
  cibuildmp and name identifiers in their own workflows.
- ~~`usermod/targets.py`'s `default_runner` is still a hardcoded
  `"ubuntu-latest"`~~ — **half closed.** It is arch-aware now: `aarch64` and
  `armv7l` targets name `ubuntu-24.04-arm`, everything else keeps
  `ubuntu-latest`, so `--print-build-matrix` emits a per-leg runner and an
  `aarch64` build becomes native instead of ~20x emulated. Two things remain:
  there is still no per-target config override the way natmod has `runs-on`,
  and **`armv7l`'s inclusion is a bet rather than a certainty** — a 32-bit ARM
  binary is native on an arm64 host only if the CPU implements AArch32 at EL0,
  which server-class parts generally do not. cibuildwheel treats this as a real
  hazard, carrying an explicit AArch32 EL0 check in
  `Architecture.bitness_archs()` for exactly ARM64 Linux. If the bet does not
  pay off the cost is nil (emulated either way) and that entry moves back.
- **`--only` cannot reach an opt-in cell**, found while verifying musllinux
  here: `--only unix-musllinux_1_2_x86_64` answers "matches no usermod target
  this config can produce", because it filters the axis the config selected
  rather than overriding it. cibuildwheel's own `--only` does override
  architecture selection outright, so this is a real parity gap rather than a
  preference — and it makes every one of the ten opt-in cells unreachable
  without editing `cibuildmp.toml`. Not fixed here; it belongs to the selector
  machinery, not to the image model, and now has its own record: [0045],
  which also found that the in-code comment claiming cibuildwheel parity for
  this flag is wrong on both counts.

[0045]: 0045-only-is-a-filter-not-a-forced-identifier.md
- The `unix` default axis is the old five translated one-for-one, not the new
  fifteen: defaulting to the whole matrix would turn one `ports = ["unix"]` line
  into fifteen mostly-emulated builds. Whether native-only-by-default
  (cibuildwheel's own `auto_archs()`) is the better rule is [0043]'s own open
  measurement question, still unmeasured.

[0010]: 0010-pinned-data-in-resources.md
[0012]: 0012-pyelftools-ar-own-deps.md
[0024]: 0024-unix-armhf-mipsel-cross-compiles.md
[0025]: 0025-dockerfiles-bake-unix-cross-toolchains.md
[0031]: 0031-unix-musllinux-libc-axis.md
[0038]: 0038-m5-adopt-in-three-repos.md
[0042]: 0042-windows-docker-wiring-and-resolver-removal.md
[0043]: 0043-unix-adopts-cibuildwheel-native-image-model.md
[0046]: 0046-pin-staleness-checker.md
[0047]: 0047-run-output-parity-with-cibuildwheel.md
[0049]: 0049-no-matrix-generation-archs-vocabulary.md
[0052]: 0052-config-is-a-tree-not-a-selector-matrix.md

---

## Addendum, 2026-08-26 — the six default cells are green on CI, and the `armv7l` bet paid off

Two consecutive `Build examples` runs on `feat/usermod` — [32958683512] (435ae82)
and [32959019090] (c1ba45b) — completed with **all six default `unix` targets
passing**, not the four the tracker had recorded. What changed between them and
the failures before is one commit: 435ae82, which fixed the composite action's
apt step assuming an amd64 host (`dpkg --add-architecture i386` and the i386
sources-list rewrite exist for **natmod's `x86` arch alone** and cannot apply on
arm64). That was the last amd64-host constant left anywhere in the tree, and it
was outside `dockerrun.py` entirely — the same correction this record made
everywhere else, applied to the one place still assuming it.

| target | runner | `cibuildmp` step | mechanism |
| --- | --- | --- | --- |
| `manylinux_2_28_x86_64` | `ubuntu-latest` | — | native container |
| `manylinux_2_28_i686` | `ubuntu-latest` | — | native container |
| `manylinux_2_39_mipsel` | `ubuntu-latest` | — | cross, amd64 host |
| `webassembly` | `ubuntu-latest` | — | cross, amd64 host |
| `manylinux_2_28_aarch64` | `ubuntu-24.04-arm` | **88.8s** | native container |
| `manylinux_2_31_armv7l` | `ubuntu-24.04-arm` | **59.5s** | see below |

**`aarch64` is native, and the figure is the argument.** 88.8s inside
`ghcr.io/ballistics-lab/manylinux_2_28_aarch64@sha256:498ac07…`, against the
1041s an emulated build of the same cell took locally — ~12x, which is the ratio
emulation costs and not something a faster runner explains. [0043]'s own step 1
is closed by this, and the "no emulated build has completed here" caveat above
is answered from the other direction: the point was never to make emulation
work, it was to stop needing it.

**`armv7l` was called "a bet rather than a certainty" in *Still open* above, and
the bet won.** 59.5s — *faster than the native `aarch64` build on the same
runner class*. Under `qemu-arm` it would be some multiple of 88.8s, not two
thirds of it, so GitHub's `ubuntu-24.04-arm` parts do implement AArch32 at EL0
and `default_runner`'s `armv7l` → `ubuntu-24.04-arm` entry stays where it is
rather than moving back. Recorded as timing evidence rather than as a direct
observation, because the one thing that would settle it outright is not visible
— see the next paragraph. cibuildwheel's own explicit AArch32-EL0 check in
`Architecture.bitness_archs()` remains the more careful thing to do for a tool
that must be right on *any* arm64 host; this is a statement about GitHub's
runners specifically.

**A diagnosability wart, found while reading these logs.** The `armv7l` job's
log contains no image pull at all — no `Unable to find image`, no digest, no
`ghcr.io` anywhere — yet it built in the right container. `linux/arm/v7` is not
the host's native platform, so `_probe_platform()` ran first and its
`docker run --pull missing` is `capture_output=True`; it silently fetched the
image, and `run()`'s own `--pull missing` then found it cached and printed
nothing. The only trace the container was ever pulled is a **19-second gap with
no output** between `LINK build/mpy-cross` and the target build starting. So for
every non-native target the first pull is invisible, and its cost looks like a
hang. This belongs to [0047] rather than here, but it is worth naming: the probe
that exists to turn a silent failure into a sentence also turned a visible pull
into silence.

**Still not verified, and now for a sharper reason.** `linux32` handling was
listed above as "no `i686` or `armv7l` build has run" — both have now run and
both passed, but that does *not* close it. `_kernel_is_64bit()` reads
`_probe_platform()`'s `uname -m`, and that value is captured, never printed. An
`arm/v7` container on an arm64 kernel reports either `armv8l` (not in
`_64BIT_MACHINES`, wrap does not fire) or `aarch64` (in it, wrap fires), and the
logs cannot distinguish the two. The `i686` case is already known from a live
probe to report `i686` on an amd64 host — so the wrap does not fire there
either. Either way the branch that has never executed is the one that *does*
wrap, on both 32-bit cells. Printing the probed machine would close this and
[0047]'s gap in the same line.

**And then the probe reported it, which settled `i686` on the spot.**
`_probe_platform()` now prints what it measured (and announces itself before
the silent pull), which required fixing a larger thing first: *every* `print()`
in cibuildmp was block-buffered and arrived at interpreter exit — in the run
above, "downloaded micropython.tar.xz (104 MiB)" carries the same timestamp as
the final summary, ninety seconds late and after `make`'s own output.
`cli.main()` sets line buffering now.

With that in place, one local probe against the real pinned image answers the
`i686` half: `ghcr.io/ballistics-lab/manylinux_2_28_i686` at `linux/386` on an
amd64 host reports `uname -m = i686`, not `x86_64` — so `_kernel_is_64bit()` is
False and **the `linux32` wrap does not fire on this cell and never will**.
That is a property of the *image*, not of the platform: plain `alpine:3.22` at
the same `linux/386` on the same host reports `x86_64`, because pypa's 32-bit
images already apply the `PER_LINUX32` personality themselves. cibuildwheel's
wrap is still correct to carry — it is what makes an arbitrary 32-bit image
behave — it simply has nothing left to do here. `armv7l` was not probed;
the printed line settles it on its next CI run without anyone having to reason
about it.

## Addendum, 2026-08-26 (second) — the musllinux column, and one rule that was on the wrong axis

Four of the seven musl cells have a runner they are native to, and all four now
have a CI leg (run [32960761641]): `x86_64`/`i686` on amd64, `aarch64`/`armv7l`
on the arm64 runner. `ppc64le`, `s390x` and `riscv64` are emulated on every
runner GitHub offers and stay a separate decision about cost. Three of the four
went green on the first attempt, which is a better rate than the "expect that
table to grow" above predicted — and the one failure was worth more than the
three passes.

**`musllinux_1_2_aarch64` failed with a diagnostic this record already
contains.** Byte for byte the `manylinux_2_28_aarch64` one: `mbedtls_xor` at
`lib/mbedtls/library/common.h:235`, inlined from `ctr_drbg_update_internal`,
"array subscript 48 is outside array bounds of `unsigned char[48]`". Different
base image (Alpine 3.22, not AlmaLinux 8), different libc, same failure.

That kills the reasoning attached to the original entry. It read:

> gcc's own bounds analysis differs by target, so this cannot be a column-wide
> rule and has to stay per cell.

The first half is true and the conclusion does not follow from it. *Target* was
being used to mean *cell* when what varies is the **backend** — and the backend
is the architecture, not the (arch, libc) pair. The evidence is now two aarch64
cells failing and seven non-aarch64 cells clean across both columns, so
`-Wno-error=array-bounds` moved from `UNIX_TARGET_CFLAGS["manylinux_2_28_aarch64"]`
to a new `_ARCH_CFLAGS["aarch64"]`. `musllinux_1_2_aarch64` then needs no entry
of its own, and neither will any future aarch64 floor.

`unix_extra_cflags()` is three layers now — libc, architecture, per-tag — and
`UNIX_TARGET_CFLAGS` is empty, which is the honest state rather than a gap:
every suppression found so far has generalised to one of the two general axes.
It stays because `windows`/`arm64` has three Clang-specific flags no other
target needs ([0018]), so a genuine one-off is known to be reachable.

Worth naming as a pattern rather than a one-off correction, since this record
made the same mistake twice in different clothes: a rule derived from a single
cell will pick whichever axis that cell happens to sit on. The musl
`-Wno-error=cpp` rule got its axis right first time only because the *reason*
was known (musl's `sys/cdefs.h` is a bare `#warning`); the array-bounds rule got
it wrong because the reason was "gcc did something odd here". Where the
mechanism is understood, the axis follows from it; where it is not, the axis is
a guess until a second cell disagrees.

### Both fixes landed visibly, and `armv7l` is now settled directly

Run [32961216804] is the first with line buffering and probe reporting in it,
and the same `armv7l` leg that produced the nineteen seconds of silence above
now reads:

    11:02:36  cibuildmp: 1 usermod target(s) against MicroPython v1.28.0
    11:02:36    downloaded micropython.tar.xz (104 MiB)
    11:02:46    mpy-cross: building
    11:02:50    linux/arm/v7: probing (pulls ghcr.io/...manylinux_2_31_armv7l@sha256:ce049c…)
    11:03:10    linux/arm/v7: uname -m = armv8l (32-bit kernel)
    11:03:47  LINK .../build-unix-manylinux_2_31_armv7l/micropython
    11:03:48  cibuildmp: 1 usermod target(s) built in 57.3s

Each line at the time the thing it describes happened, interleaved with `make`'s
own output, instead of all of them stamped with the final summary's timestamp.
The nineteen-second gap is still nineteen seconds — it is a real pull — but it
now says so.

**`armv8l` settles `armv7l` better than the timing argument did.** A 64-bit
ARMv8 kernel reports `armv8l` to a 32-bit process; `qemu-arm` reports `armv7l`.
So the first addendum's inference from build times ("59.5s is too fast to be
emulated") is now a direct observation: the CPU is executing AArch32 at EL0 and
the container is native. `default_runner`'s entry is confirmed rather than
merely un-refuted.

**And `linux32` is closed, in the sense that it is unreachable.** `armv8l` is
not in `_64BIT_MACHINES`, so `_kernel_is_64bit()` is False and the wrap does
not fire on `armv7l`; the real `manylinux_2_28_i686` image reports `i686` at
`linux/386` for the same outcome. Both 32-bit cells take the non-wrapping
branch, for two different reasons — pypa's i686 images apply the `PER_LINUX32`
personality themselves, and an arm64 kernel names its own 32-bit personality
`armv8l`. The wrapping branch stays unexercised, but it is no longer *unknown*:
no cell cibuildmp declares can reach it. cibuildwheel's code is still right to
carry it (an arbitrary 32-bit image on a 64-bit kernel does need it); it simply
has nothing to do in this matrix.

### The musllinux cells joined the default axis, and `windows` got its first leg

Two consequences of the above, both taken the same day.

**`_UNIX_DEFAULT_TARGETS` is nine cells now, not five.** The rule written next
to that tuple is "default = everything actually proven at the time it became the
default", and once the four native musl cells were green and required, they
qualified — leaving them out would have meant the rule said one thing and the
list another. The argument for holding them back was cost, and it did not
survive being stated: the cost only exists in D9's one-job-loop layout, where
nothing is native to anything and `aarch64`/`armv7l` are emulated regardless of
libc, and the default axis already carried two such cells. Adding two more of
the same shape is a bigger known cost, not a new kind of one. 0045's
`auto`/`native` vocabulary is the actual fix and will make this list a question
about the host rather than a hardcode; until it exists, the rule as written
wins. `ppc64le`, `s390x` and `riscv64` stay out for the original reason, which
is unchanged: emulated on every runner GitHub offers, and never built.

That also collapsed the CI job those cells had. They arrive in the default
matrix now, so the `--only` opt-in leg is gone — the lifecycle it exists for
(`only` legs allowed to fail → required → into the default axis) ran to
completion in one day.

**`windows` entered that same lifecycle at step one.** It had never been built
by `build-examples.yml` at all: [0042] verified all three arches live, by hand,
in a session, against an image pushed by hand, and nothing since re-ran it —
"it worked once on a laptop" is exactly the state every other port left behind
when it got a leg here. Three `only` legs, `continue-on-error`, promoted when
green. Checked locally first against the pinned image: `windows-x64` from
`examples/template` builds in 206.9s and produces `PE32+ executable ... x86-64`,
so the legs are expected to pass rather than hoped to.

**And the one claim this record made that nothing had ever executed now has a
job.** It says `--platform=linux/amd64` "is what now lets [the cross-compiling
ports] run on an arm64 host at all — emulated, instead of failing with `exec
format error`", and calls it a requirement in its own right. Every
cross-compiling port resolves to `ubuntu-latest`, which is amd64, so the
emulated path the claim is about was the one path the workflow structurally
could not reach. `build-usermod-amd64-image-on-arm64-host` runs `webassembly`
— green on amd64 in every run, so a failure is unambiguously about the host —
on `ubuntu-24.04-arm`. Its runner is hardcoded, deliberately: everywhere else
the runner is a property of the target and comes from `default_runner`, while
this job is an experiment about the *host*, which cibuildmp records nowhere and
should not choose. The honest alternative is usermod's missing per-target
`runs-on` override, still open above, and that is a config-schema feature rather
than the evidence this job is after.

[32961216804]: https://github.com/ballistics-lab/cibuildmp/actions/runs/32961216804

[32960761641]: https://github.com/ballistics-lab/cibuildmp/actions/runs/32960761641
[0018]: 0018-windows-provisioning-fourth-story.md

[32958683512]: https://github.com/ballistics-lab/cibuildmp/actions/runs/32958683512
[32959019090]: https://github.com/ballistics-lab/cibuildmp/actions/runs/32959019090

## Addendum, 2026-08-27 — reversing "still published... so the file already exists": nine
of the fifteen `unix` cells no longer have an image of their own

This record's own body above (the `pkg-config --libs libffi` table) already knew nine of
the fifteen Dockerfiles were a bare `FROM` with no `RUN` at all, and made a deliberate,
argued call to keep publishing them as cibuildmp's own images anyway: "so that every cell
shares one name scheme, one publish pipeline and one pin table — and so the day
`ports/unix` needs a package there, the file already exists." That reasoning held for over
a day; this addendum reverses it, on the user's own call, not a rediscovery of the fact.

The tradeoff looks different once it is actually nine idle GHCR packages plus nine idle
CI build-check legs, indefinitely, against a hypothetical future package that may never
be needed for these particular libc/arch combinations specifically (`musllinux` and the
two non-`_2_28` manylinux floors already have no known `ports/unix` requirement the
`_2_28` cells don't). "The file already exists" bought convenience for a need that has
not materialized in the time since this record landed, against a real, ongoing cost:
publishing, pulling and caching a second, identical copy of an image cibuildmp adds
nothing to. A Dockerfile that only ever says `FROM <x>` is not a build step, it is a
second name for `<x>` — and if the need does materialize for one specific cell later, one
Dockerfile is one Dockerfile, not a reason to carry nine speculative ones now.

Deleted rather than kept idle: the nine Dockerfiles, their nine matrix rows in
`publish-docker-images.yml` and `verify-docker-images.yml`, and their nine GHCR
packages (left to expire, not force-deleted). `resources/pinned_docker_images.toml`'s
matching nine cells now hold `resources/pinned_pypa_images.toml`'s own `quay.io/pypa/...`
reference verbatim instead of a `ghcr.io/ballistics-lab/...` copy of it —
`dockerrun.image_for()` needed no change at all, since it only ever returns whatever
string a cell holds and never inspects which registry it names. `bin/update_docker.py
--images` and `bin/publish_images.py`'s own `cells()` both now skip a cell whose
reference is not `ghcr.io/...`-prefixed: the former mirrors it straight from
`pinned_pypa_images.toml` instead of querying a GHCR package that was never published;
the latter excludes it from what gets built and pushed, since there is no
`docker/<name>.Dockerfile` left for it to build.

The published/build-checked matrix is ten cells now, not fifteen (`unix`) plus four
(the cross-compiling ports): the five `manylinux_2_28` arches, `mipsel`, `natmod`,
`windows`, `qemu`, `webassembly`. `unix_targets()` in `dockerrun.py` is unaffected —
it still lists all fifteen `[image.<arch>]` cells, published or mirrored alike, since
every one of them is still a real, buildable `unix` target from a consumer's own point
of view. Only *how many of them cibuildmp itself publishes* changed.

This does not touch the separate, larger question of whether `dockerrun.py`'s own
per-port resolution logic (`image_for()`'s hardcoded `if port == "unix": ... else:
_pins()["port"].get(port)` branches) should instead be driven by
`resources/build-platforms.toml`'s own per-row `cross` fact — grouping many natmod
arches and usermod ports onto a small number of shared toolchain images (the
`arm_embedded`/`riscv_embedded`/`xtensa_lx106`/`esp_idf` consolidation sketched but not
built this session). That is a resolver-shape redesign, not a data cleanup, and stays
open.

## Addendum, 2026-08-28 — the six emulated-everywhere cells: descoped from CI, kept in the matrix

Closes the row this record carried in the tracker's "In progress / Proposed" since
2026-08-26 ("build them or descope"). The answer is **descope**, and the word needs
qualifying, because it does not mean what it usually means here: nothing is deleted,
nothing becomes unnameable, and no digest goes stale on purpose. What is descoped is
the *promise*, not the target.

### What the six actually are today

`ppc64le`, `s390x` and `riscv64`, both libc columns — the ⚠️ rows in `README.md`'s own
usermod table. They are not uniform, which the tracker row flattened and this addendum
should not:

| Cell | What `[image.<arch>]` names | Layer |
| --- | --- | --- |
| `manylinux_2_28_ppc64le` | `ghcr.io/ballistics-lab/…@sha256:f6dc11a9…` | cibuildmp's own (`libffi-devel`) |
| `manylinux_2_28_s390x` | `ghcr.io/ballistics-lab/…@sha256:575a7d5c…` | cibuildmp's own (`libffi-devel`) |
| `manylinux_2_39_riscv64` | `quay.io/pypa/…@sha256:9fa1bc38…` | pypa's, mirrored verbatim |
| `musllinux_1_2_ppc64le` | `quay.io/pypa/…@sha256:d70f4708…` | pypa's, mirrored verbatim |
| `musllinux_1_2_s390x` | `quay.io/pypa/…@sha256:97af923e…` | pypa's, mirrored verbatim |
| `musllinux_1_2_riscv64` | `quay.io/pypa/…@sha256:c81bcd32…` | pypa's, mirrored verbatim |

Two of the six carry a real cibuildmp-published layer; four point straight at pypa,
by the 2026-08-27 addendum's own rule — their Dockerfiles were a bare `FROM` and
nothing else, so a second copy bought nothing. All six have an immutable digest, all
six are reachable by an ordinary `build`/`skip` glob naming them
(`build = "*_ppc64le *_s390x *_riscv64"`), and since [0052] retracted every opt-in and
keyword layer, nothing implicitly excludes them from a bare `build = "*"` either.

### Why not build them, stated honestly

The tracker row's reason — "native to no runner GitHub offers" — is true but is *not*
on its own a reason they cannot be built. cibuildwheel builds wheels for these exact
architectures on GitHub Actions today, through QEMU binfmt emulation, and simply
accepts what that costs. cibuildmp could do the same thing tomorrow; the machinery
(`dockerrun.run()` on an already-pinned image) needs nothing new.

So the real reasons are these, and they are about cost and demand, not capability:

- **The cost is per-run and recurring.** Each cell is a full emulated MicroPython
  `make`, not a single compile. Six of them on every push is the wrong shape for a
  gate — cibuildwheel's own emulated legs are release-time work, not per-commit work.
- **Nobody is asking.** None of [0038]'s three consuming repos names any of the six in
  its own workflow, and no consumer has asked for one. A target built only to keep a
  matrix square is a maintenance cost with no reader.
- **Upstream's own support signal is weakest exactly here.** Alpine's
  `community/micropython` excludes `ppc64le` and `s390x` outright. That is a fact
  about MicroPython on those arches, not about cibuildmp, and it argues against
  spending emulated CI minutes proving something upstream itself does not ship.

### What "descoped" commits this project to

- The six stay in `resources/pinned_docker_images.toml`, stay listed by
  `--print-build-identifiers`, and stay buildable by anyone who names them.
- Their digests stay maintained by `bin/update_docker.py` alongside every other cell —
  they are not frozen, and they are not exempt from [0046] when it lands.
- `README.md` marks them ⚠️ with a footnote saying, in as many words, that no real
  build has ever run through one. **That footnote is the descope.** It was already
  written before this decision; this addendum makes it the recorded position rather
  than an observation about the present.
- **No CI leg is added, and none is planned.** This is the part that is actually being
  decided. `qemu`'s own gap closed on 2026-08-28 by getting a dedicated leg; these six
  deliberately do not get the same treatment, and the difference is that `qemu` is
  native on the runner it builds on and these are not.

### What would reopen it

Any one of: GitHub offering a runner native to one of the three architectures; a real
consumer naming one of the six; or a release-time (not per-push) workflow existing for
other reasons, at which point adding six emulated cells to something that already runs
rarely is cheap. Until then, local work goes through the documented per-cell override —
`CIBMP_UNIX_MANYLINUX_2_28_PPC64LE_DOCKER_IMAGE=<tag>` and friends — pointed at a
locally-built or emulated image.

### This closes [0031]'s equivalent sentence too

[0031]'s row records that its own three remaining cells "are `ppc64le`/`s390x`/`riscv64`,
which is this record's descope question above and not a musl question at all". Same six cells,
same answer, no separate decision needed: the musllinux column is complete at four of
seven, and the three it is missing are missing for a reason that has nothing to do with
musl.

### The rest of this record's own "Still open", for the record

Closing the tracker row means saying where the other items went, since none of them is
this question:

- Publishing the matrix and filling `[image.*]` — **done**; every cell holds a real
  digest. (The file's own "Everything is empty right now, on purpose" section header is
  now stale prose describing a state that no longer exists.)
- Consuming repos' `unix` identifiers changing — **still open**, and it is [0038]'s row,
  not this one.
- `default_runner` / per-target `runs-on` — **closed by deletion** in [0049]; cibuildmp
  generates no matrix and chooses no host any more, so the `armv7l` AArch32-EL0 bet is
  no longer cibuildmp's bet to make.
- `--only` cannot reach an opt-in cell — **closed** by [0045]/[0049], and then made
  moot by [0052] removing the opt-in concept entirely.
- The `unix` default axis being the old five translated one-for-one — **superseded**:
  there is no default axis any more, only what a `build` glob names.
