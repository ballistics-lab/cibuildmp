# 0044 — landing [0043]: pypa-based native images, the full arch × libc matrix, and the two things it broke

Status: Implemented (code, tests and tooling landed; the matrix is published and all
six default cells are green on CI as of 2026-08-26 -- see the addendum; the ten opt-in
cells remain unbuilt)

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
[0043]: 0043-unix-adopts-cibuildwheel-native-image-model.md

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

[32958683512]: https://github.com/ballistics-lab/cibuildmp/actions/runs/32958683512
[32959019090]: https://github.com/ballistics-lab/cibuildmp/actions/runs/32959019090
