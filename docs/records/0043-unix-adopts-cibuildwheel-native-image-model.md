# 0043 — `unix` adopts cibuildwheel's model in full: native per-target images, PEP 600/656

Status: Accepted (plan — nothing implemented yet)

The user's own call, stated directly: **"я хочу повну відповідність cibuildwheel в цьому
питанні."** Not "borrow the useful parts" — full parity for the `unix` port, both in how
build containers are chosen and in how compatibility is *claimed* (PEP 600 / PEP 656).

This is the decision [0031] explicitly deferred rather than answered. Its own text parks
the glibc-floor problem "alongside the QEMU/native-image question above", and that
question is exactly what this record settles. **[0031] is not superseded — it is
unblocked**: its musl half becomes a small amount of work inside the model decided here,
instead of a second cross-toolchain hunt.

## What triggered it

A plain question — what happens if `runs-on` is `ubuntu-24.04-arm`? — that today has a
bad answer, verified rather than assumed:

- Every published image is `linux/amd64` and a **single manifest**, not a manifest list:
  checked directly against the registry (`mediaType:
  application/vnd.docker.distribution.manifest.v2+json`, and `docker image inspect` says
  `linux/amd64`). `publish-docker-images.yml` runs on `ubuntu-latest` and passes no
  `platforms:` key at all.
- `usermod/targets.py`'s `default_runner` hardcodes `"ubuntu-latest"` with no override —
  unlike natmod, which does have a `runs-on` config knob. So cibuildmp cannot *emit* an
  ARM runner; the case arises when a consumer writes their own workflow and calls the
  action directly, which is entirely legitimate.
- On an arm64 host, an amd64 image without registered binfmt fails with `exec format
  error` from inside `make` — a failure that names nothing about architecture.

The obvious fix looked like "publish manifest lists". **That fix is a trap**, and finding
out why is what produced this record.

## Why multi-arch images are the wrong answer

`unix-manylinux-x64.Dockerfile` installs `build-essential` and nothing else, and
`UNIX_ARCH_SETTINGS["x64"].cross_compile` is `""` — that target is a **native** build.
Add `platforms: linux/arm64` to it and the arm64 variant builds an **aarch64 binary
carrying the identifier `unix-x64`**. Not an error — a silently wrong artifact, the worst
failure mode available. `unix-manylinux-aarch64.Dockerfile` has the mirror problem: its
`dpkg --add-architecture arm64` + `Architectures: amd64` + `ports.ubuntu.com` setup is
only coherent on an amd64 host.

The root cause is structural, not a Dockerfile bug: **which arch is "native" is a
property of the host, and cibuildmp currently encodes it as a constant in Python.**
Multi-arch publishing does not fix that; it multiplies it.

## What cibuildwheel actually does (checked live, not recalled)

Read directly from `main`: `bin/update_docker.py`, `cibuildwheel/architecture.py`,
`cibuildwheel/platforms/linux.py`, `cibuildwheel/oci_container.py`.

1. **It publishes no multi-arch images at all.** `pinned_docker_images.cfg` is keyed by
   *target platform only* — `x86_64`, `i686`, `aarch64`, `ppc64le`, `s390x`, `armv7l`,
   `riscv64` — and each entry is `quay.io/pypa/manylinux_2_28_<platform>@sha256:…`, an
   image **native to that target**, holding a native toolchain. There are no cross
   compilers in this design.
2. **Target arch *is* the container platform.** `ARCHITECTURE_OCI_PLATFORM_MAP`
   (`platforms/linux.py`) maps each `Architecture` to an `OCIPlatform`, and
   `OCIContainer` passes it straight through as `--platform=<value>` alongside
   `--pull=…`. Building for aarch64 on an amd64 host means running the arm64 image under
   binfmt/QEMU.
3. **Host architecture never appears anywhere** — not in the key, not in the image name,
   not in the identifier. It cannot go stale because it is never recorded.
4. **Default is native-only.** `Architecture.auto_archs()` returns `{native_arch}` on
   Linux (only Windows adds a second). `all` is the seven-arch set above. Non-native
   architectures are an explicit opt-in, and the user is expected to have set up
   emulation themselves — cibuildwheel does not install QEMU or probe for it.
5. **32-bit targets get a personality wrapper, not a different image.** For `i386` and
   `ARMV7`, `OCIContainer` runs `uname -m` inside the container first; if the kernel
   reports a 64-bit machine it sets `simulate_32_bit` and wraps commands in `linux32`.
   For `i386` it additionally falls back to `--platform=amd64` when the i386 platform
   fails outright, since such images are often built as amd64.

The consequence worth stating plainly: in this model **the arm64-host question answers
itself**. On an arm64 machine the aarch64 image runs natively and fast; amd64 runs
emulated. Nothing in the pin table changes.

## What this decides for cibuildmp

**The `unix` port stops cross-compiling and starts running native images per target.**

- Each `unix-<libc>-<arch>` image is built `--platform` for *its own* target arch and
  contains a native toolchain. `docker run --platform=<target>` selects it, mirroring
  `OCIContainer`'s own behaviour.
- `UNIX_ARCH_SETTINGS[*].cross_compile` all become `""`. Every unix build is native
  inside its own container. Much of what [0024]/[0025] built — and the six real apt/gcc
  bugs [0025] paid for — is cross-compile machinery this deletes rather than fixes.
- `unix-manylinux-aarch64.Dockerfile`'s apt-multiarch/`ports.ubuntu.com` block disappears
  entirely; it becomes the same trivial Dockerfile as x64.
- `PORT_IMAGES` keys are unchanged: `(port, arch, libc)` already matches cibuildwheel's
  own `(platform, manylinux|musllinux)` shape. **No host-arch axis is added, ever** —
  that is the point.
- `x86` and `armhf` inherit cibuildwheel's `linux32` handling; they are the same 32-bit
  case, and reinventing it would be strictly worse than copying a solution that has
  already met real images in the wild.

### Architecture coverage

Also the user's own point, and correct: the current five are not all of them. Against
cibuildwheel's seven, cibuildmp is missing **`ppc64le`, `s390x`, `riscv64`**; it has
`mipsel`, which cibuildwheel does not; and `armhf` is its own spelling of `armv7l`
(the naming should be reconciled, not silently kept divergent).

Under the cross model each new arch is a toolchain hunt priced by [0025]. Under the
native model it is one more base image, which is precisely why this record and the
coverage gap belong together rather than as separate efforts.

**The end state is the full arch x libc matrix, not the model change alone.** Parity
means both axes filled in, the same way cibuildwheel fills them — its
`pinned_docker_images.cfg` carries every cell below, and a half-filled table is not
parity. Written out so the scope cannot be read as smaller than it is:

| arch | manylinux | musllinux | today |
| --- | --- | --- | --- |
| `x86_64` (now `x64`) | yes | yes | glibc only, cross-free (native) |
| `i686` (now `x86`) | yes | yes | glibc only, `linux32` case |
| `aarch64` | yes | yes | glibc only, cross |
| `armv7l` (now `armhf`) | yes | yes | glibc only, cross, `linux32` case |
| `ppc64le` | yes | yes | **missing entirely** |
| `s390x` | yes | yes | **missing entirely** |
| `riscv64` | yes | yes | **missing entirely** |
| `mipsel` | ? | ? | glibc only, cross; **no upstream counterpart** |

That is 7 arches x 2 libc = **14 images** to reach parity, against 5 glibc-only images
today — plus whatever is decided for `mipsel`, which is cibuildmp's own addition and the
one row upstream cannot answer for.

Two further things the matrix makes visible, both real work rather than bookkeeping:
the manylinux *version* is not uniform across arches upstream (`manylinux_2_28` for most,
`manylinux_2_31`/`_2_35` for `armv7l`, `manylinux_2_39` for `riscv64` — straight from
`bin/update_docker.py`'s own `IMAGES` list), so the per-arch table that picks a base
image has to carry a version per cell, not one global choice; and the identifier axis
[0031] designed has to be threaded through `UsermodOptions`/`orchestrate.py` before any
of these cells can be *named*, which that record already flags as multi-file work.

### PEP 600 / PEP 656

Full parity means the label stops being decorative. [0031] already recorded that
`"manylinux"` here means only "whatever glibc `ubuntu:24.04` happens to ship", changing
silently underneath every image, with no floor recorded anywhere. Parity means adopting
what cibuildwheel actually does, which [0031] already checked against a real `v4.2.0`
checkout and which this record does not re-derive:

- a static, maintainer-curated table decides *which base image* per arch
  (`manylinux-x86_64-image = "manylinux_2_28"`), trusted rather than computed;
- the *real* floor of a just-built binary comes from shelling out to `auditwheel`
  (glibc) / its musl counterpart, which inspects actual symbol versions;
- a single artifact may carry several stacked floors (PEP 600), and musllinux is the
  same shape under PEP 656.

Whoever implements this reads both PEPs directly first — [0031] is explicit that a
summary is not a sufficient basis, and this record inherits that instruction.

## Scope — what this does *not* touch

`windows`, `webassembly`, `qemu` and `esp32` are genuinely cross-compiling to non-Linux
or bare-metal targets. cibuildwheel has no equivalent and no opinion; their amd64-only
images ([0042] for `windows`) stay as they are. In particular **wiring `qemu` to
`ensure_image()` — [0032]'s last open half — is independent of this record and can
proceed in parallel.**

## Migration sketch

Deliberately a sketch, not a schedule. [0025]'s six bugs are the standing argument for
proving each step against a real container before taking the next.

1. Land the model on **one** arch pair (x64 native + aarch64 emulated) and verify a real
   build of each, including that the produced ELF's machine type matches its identifier
   — the check that would have caught the silent-wrong-binary trap above.
2. Convert the remaining three current arches; delete the cross-toolchain apt sets and
   the `ports.ubuntu.com` block as each is replaced, not before.
3. Adopt `linux32` handling for `x86`/`armhf`, copying cibuildwheel's probe-then-wrap
   rather than assuming when it is needed.
4. Add `ppc64le`/`s390x`/`riscv64`; reconcile `armhf`/`armv7l` and `x64`/`x86_64`,
   `x86`/`i686` naming — parity in the matrix is worth little if the axis labels still
   need translating.
5. [0031]'s musl half — now an Alpine base per arch in the same mechanism, plus the
   identifier axis it already designed. This is what turns the table above from one
   filled column into two.
6. PEP 600/656 floors and the `auditwheel`-equivalent checker.

## Open questions

- **Emulation is a hard dependency for non-native targets.** cibuildwheel pushes this
  onto the user (`docker/setup-qemu-action` on CI, a working binfmt locally) and does not
  probe for it. Parity says do the same — but cibuildmp should still fail with a message
  that names the missing emulation, since today's `exec format error` from inside `make`
  names nothing.
- **Emulated builds are slow**, and unlike wheels a MicroPython port build is not
  obviously cheap. Whether the honest default is "native only unless asked" (parity) or
  something narrower is worth measuring on a real build before committing.
- **`mipsel` has no cibuildwheel counterpart**, so it has no upstream image to inherit.
  It either keeps a bespoke native image or is reconsidered.
- Nothing here is verified live yet. Every claim about cibuildwheel above was read from
  its own current source; every claim about cibuildmp's present state was checked against
  the registry and the running code — but the *proposed* model has not been built once.
