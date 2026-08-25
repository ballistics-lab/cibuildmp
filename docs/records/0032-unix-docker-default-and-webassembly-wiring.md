# 0032. Closing D28's own gap: unix usermod now defaults to Docker via ensure_image()

- Status: Implemented for `unix`/`webassembly`; `windows`/`qemu` never wired to `ensure_image()` — superseded in part by [0033]
- Related: [0026], [0028], [0030], [0033]

<!-- migrated verbatim from docs/BACKLOG.md lines 2655-2903 -->

**D32 — closing D28's own "one real gap": `unix` usermod now defaults to
Docker whenever cibuildmp ships that arch's own Dockerfile, instead of
requiring an explicit override or a maintainer-registered `PORT_IMAGES`
entry first.** The user's own framing, directly: cibuildmp should call
`docker` itself and build (or reuse a local cache of) its own packaged
Dockerfile when nothing more specific is named, the same way
cibuildwheel defaults every manylinux/musllinux identifier through its
own pinned container rather than treating a container as an opt-in
fallback for a host missing packages.

`usermod/dockerrun.py`'s `image_for()` stays the pure, side-effect-free
lookup (env override, then `PORT_IMAGES`) it always was -- `arch` is now
optional there too, so a no-axis port (`qemu`/`webassembly`) can resolve
a key with no dangling `-` segment. A new `ensure_image()` wraps it with
a third fallback: if neither an override nor a registered default is
set, but cibuildmp ships this `(port, arch[, libc])`'s own Dockerfile
(`_DOCKERFILES`, mirroring the five `unix-manylinux-*` plus
`windows`/`qemu`/`webassembly` files already on disk from D28's own
migration), it builds that image and returns the tag -- relying on a
cache for "reuse if already there" rather than reinventing one, in
whichever of two shapes actually applies:

- **On a laptop**, a plain `docker build -f <packaged Dockerfile> -t
  cibuildmp-<key>:local <dockerfile's own dir>`. Docker's own local
  image/layer cache already gives "build once, instant no-op rebuild
  until the Dockerfile changes" for free -- nothing to add.
- **Inside any GitHub Actions job** (`GITHUB_ACTIONS=true`, set by the
  runner itself, not an opt-in) -- a fresh VM on every run, with no
  local layer cache persisting between them at all -- `docker buildx
  build --cache-from type=gha,scope=<dockerfile stem> --cache-to
  type=gha,mode=max,scope=<dockerfile stem> --load`, first switching to
  (creating if needed) a `docker-container`-driver builder named
  `cibuildmp`: the classic default `docker` driver does not support the
  `type=gha` cache exporter/importer at all. The scope string is
  deliberately the packaged Dockerfile's own stem (`unix-manylinux-x64`,
  not `ensure_image()`'s own `key`, which additionally folds in the
  libc segment `unix` alone carries) -- the same string
  `build-examples.yml`'s own `verify-docker-images` job already uses for
  its matrix leg, so this fallback can land in (and, on a cache hit,
  read from) the exact cache lineage that job populates, not a disjoint
  one that happens to also say `type=gha`. This is the direct answer to
  "will this work for other repos, not just this one": a consumer who
  writes nothing but a `cibuildmp.toml` and `uses: cibuildmp@vX` in
  their own workflow gets real cross-run image caching in their own CI
  too, from nothing they had to set up themselves -- matching D2's own
  framing (cibuildmp owns provisioning) rather than leaving every
  consumer to reinvent build-examples.yml's own cache wiring by hand.

Returns `None` only where cibuildmp genuinely
ships no Dockerfile at all yet (`windows/arm64`, `esp32`), which still
falls all the way through to a bare host build exactly as before.
**Stale as of the Docker-only call above (this document's own D30):**
that bare-host fallback is scheduled for removal in favour of a hard
error, not left as the permanent answer for a missing Dockerfile.
`build_unix()` now calls `ensure_image()`, not `image_for()` directly --
the only call site changed this round; `windows`/`qemu`/`webassembly`
own Dockerfiles exist and are in `_DOCKERFILES` too, but their
`build_windows()`/`build_qemu()`/`build_webassembly()` are not wired to
call `ensure_image()` yet, since none of them has a real example project
this repo's own CI exercises the way `examples/usermod-unix` does for
`unix` (**D26**'s own "one port, proven live, before the next"
precedent) -- wiring them blind, with no real build ever run through
them, is the wrong order.

**`webassembly` landed next, following exactly that precedent.**
`examples/usermod-webassembly` (a trivial `USER_C_MODULES` module,
mirroring `examples/usermod-unix`'s own `mymod`) plus a
`build-usermod-webassembly` job in `build-examples.yml`, `needs:
verify-docker-images`, same shape as `build-usermod-unix`'s own job
(env-var override pointed at the pushed `ghcr.io/.../cibuildmp-webassembly:
sha-<gitsha>` tag on a push, empty on a `pull_request` so
`ensure_image()`'s own local-build fallback runs instead). No per-arch
matrix needed -- `webassembly` has no axis at all, one combined image.
`build_webassembly()` now calls `ensure_image("webassembly")` and
`dockerrun.run()` directly, with no bare-host branch at all (unlike
`build_unix()`'s still-conditional shape): `webassembly` ships a
Dockerfile with emsdk already baked in, so `ensure_image()` never
returns `None` for it, and this decision's own Docker-only call (D30)
means there is nothing for a bare-host branch to fall back to any more.
A `docker_image is None` guard still exists, but only as the hard,
clearly-worded error this document's own "concrete follow-up" note
(under D30's usermod bullet) called for -- not a fallback path.
`emsdk.resolve_emsdk()`'s bare-host call is gone from this function
entirely: the image's own baked-in `ENV PATH` covers what `sdk.env()`
used to inject, so `usermod/emsdk.py` now only pins what the packaged
Dockerfile's own `RUN` step downloads at image-build time, verified by
running the real CLI against `examples/usermod-webassembly` in this
session's own sandbox: `--dry-run` needed no Docker at all (confirming
the earlier "scoped to an actual build only" note holds), and a real
(non-dry-run) build reached `ensure_image()` and failed with a clean,
expected `docker build ... failed with exit code 1` /
`failed to connect to the docker API` message -- this sandbox has no
reachable Docker daemon (same limitation `unix-manylinux-x64.Dockerfile`'s
own header already records), so the actual image build and `make`
invocation are proven live in this repo's own CI
(`build-usermod-webassembly`), not locally. All 253 tests pass, `ruff
check`/`ruff format --check` clean, `pyright` 0 errors.

**A real caching conflict, caught before it shipped, not after.** Naively
wiring `ensure_image()` into `build_unix()` and leaving
`build-examples.yml` untouched would have meant `build-examples.yml`'s
own `build` job -- a separate job, on a separate runner, from
`verify-docker-images` -- redoing all five `unix-manylinux-*`
`docker build`s from a cold layer cache on every single push, duplicating
work `verify-docker-images` already does *with* a real cache
(`cache-from`/`cache-to: type=gha`) and already pushes to GHCR moments
earlier in the same workflow run. Two jobs, two runners, no shared Docker
daemon: nothing about `ensure_image()`'s own plain `docker build` call
could have reached that cache by accident. Fixed by splitting
`usermod-unix` out of `build` into its own `build-usermod-unix` job
(`template`/`wasm2mpy` have nothing to do with any of this and stay
independent), `needs: verify-docker-images`, with the five
`CIBMP_UNIX_<ARCH>_MANYLINUX_DOCKER_IMAGE` env vars pointed at the exact
`ghcr.io/.../cibuildmp-unix-manylinux-<arch>:sha-<gitsha>` tags
`verify-docker-images` just built and pushed -- so `image_for()`'s own
override wins immediately and `ensure_image()`'s local-build fallback
never triggers in this repo's own CI at all, on a push. This is also,
finally, the real end-to-end proof D28's own handoff called the "one
real gap": a real `usermod-unix-x64` (and the other four arches) build
running *through* `dockerrun.run()` against one of these pushed images,
not just `docker build`/`docker push` succeeding. On a `pull_request`
run those five env vars stay unset (empty string, not absent --
`image_for()`'s own `if override:` check is truthiness-based, so this
does not repeat D28's own ninth bug where `ACTION_OUTPUT_DIR=""` read as
an explicit override), so `ensure_image()`'s local-build fallback runs
instead there -- slower, no GHA cache reachable from that job, but
correct, and exactly the path a consumer with no published image of
their own takes too.

**Two real bugs, both caught from actual CI logs, not guessed** (there is
no reachable Docker daemon in the sandbox this was written in -- `docker
info` fails to reach `/var/run/docker.sock` -- so every claim here is
checked against a real run, not local reasoning):

- The first push through this design broke 11 tests on real CI that
  passed locally. Root cause: `usermod dev`'s own "test" job runs
  `pytest` *inside a real GitHub Actions job*, where `GITHUB_ACTIONS=true`
  is genuinely set -- so any test reaching `ensure_image()`'s default path
  (no override, nothing registered) hit the real buildx+gha-cache branch,
  where `_ensure_buildx_container_builder()`'s own
  `subprocess.run(...).returncode` read broke against several
  pre-existing tests' bare `lambda *a, **k: None` stub for
  `subprocess.run` (fine before this branch existed, since nothing used
  to read a return value). Fixed with an autouse fixture
  (`tests/conftest.py`) clearing `GITHUB_ACTIONS` for every test by
  default, verified this time by running the suite locally both with and
  without `GITHUB_ACTIONS=true` set -- not just whichever one happened to
  match the sandbox's own ambient environment, which is exactly the gap
  that let this reach real CI at all.
- With that fixed, `build-usermod-unix`'s own override path (the
  `CIBMP_UNIX_*_MANYLINUX_DOCKER_IMAGE` env vars pointed at
  `verify-docker-images`'s freshly-pushed images) failed for real:
  `docker: Error response from daemon: ... unauthorized` pulling
  `ghcr.io/ballistics-lab/cibuildmp-unix-manylinux-x64:sha-<gitsha>`.
  `verify-docker-images` logs into `ghcr.io` before its own push;
  `build-usermod-unix` never did, so `dockerrun.run()`'s `docker run
  --pull missing` hit an unauthenticated pull against what GHCR treats as
  a private package by default, even for a package this same repository
  owns. Fixed by adding the same `docker/login-action@v3` step (`if:
  github.event_name == 'push'`, matching the env vars it unblocks) plus
  `permissions: packages: read` to `build-usermod-unix`.
- **A third real bug, this time a genuine link failure inside the
  actual usermod build**, not CI plumbing: `unix-aarch64` compiled
  clean but failed to link, `undefined reference to ffi_type_sint8` /
  `ffi_call` / `ffi_prep_cif` / etc. across every `modffi.c` symbol.
  Root cause: `resources/docker/unix-manylinux-aarch64.Dockerfile`
  installed only `libffi-dev:arm64`, not the plain (host/amd64)
  `libffi-dev` -- a real regression from **D26**'s own per-arch split,
  since the original combined `action.Dockerfile` always installed
  both together and nobody re-derived why. Plain `pkg-config` (no
  cross-wrapper) only searches its own build target's multiarch
  pkgconfig directory by default (`x86_64-linux-gnu` on this base
  image), never `aarch64-linux-gnu`'s -- with only the arm64 package
  present, `pkg-config --libs libffi`
  (`ports/unix/Makefile`'s own non-standalone `LIBFFI_LDFLAGS`
  resolution) silently resolved to nothing, so `-lffi` was never
  passed to the linker at all.
  - **A real self-inflicted repeat of this exact failure, caught
    immediately, not shipped twice.** The first attempt at this fix
    added a long, correct-sounding explanatory comment to the
    Dockerfile but never actually added the `libffi-dev` line the
    comment described -- pushed, and the identical CI failure
    reproduced, on the identical tag, because nothing had actually
    changed. Caught by reading the real CI logs again rather than
    assuming the fix landed because the diff looked right.
  - **Fixed for real this time, and verified live end to end in the
    sandbox before pushing again**, not just reasoned about: with
    `PKG_CONFIG_LIBDIR` pointed at nowhere (simulating "only
    `libffi-dev:arm64` installed, no host `.pc` reachable"), a real
    `aarch64-linux-gnu-gcc` compile+link reproduced the exact same
    `undefined reference to ffi_type_sint32`/`ffi_prep_cif` failure;
    with plain `pkg-config --libs libffi` resolving normally (the
    fixed state), the identical command linked clean, producing a real
    `ELF 64-bit ... ARM aarch64 ... dynamically linked` binary, and
    `readelf -d` confirmed its `NEEDED` entry is `libffi.so.8` -- the
    real, correct, arch-specific runtime dependency, not a baked-in
    host path. Fixed by actually re-adding the unqualified `libffi-dev`
    package this time: the aarch64 cross-linker's own default sysroot
    search path still finds and links the *correct* arm64 `libffi.so`
    once `-lffi` is present, regardless of which architecture's `.pc`
    file supplied the flag.
  - **A real, considered alternative, raised directly and checked
    against real source, not memory**: does `cibuildwheel` avoid this
    entire class of cross-toolchain bug? Confirmed live against a real
    `pypa/cibuildwheel` checkout (`oci_container.py`): yes -- it never
    cross-compiles from an x86_64 host at all. `docker run
    --platform=linux/arm64 <native manylinux2014_aarch64 image>`, via
    QEMU user-mode emulation (`binfmt_misc`, registered by a
    `docker/setup-qemu-action`-equivalent step, not present on a
    GitHub-hosted runner by default) runs a genuinely *native* aarch64
    container -- native `gcc`, native `libffi`, no multiarch apt
    sources, no foreign-arch packages, no `pkg-config` cross-arch
    mismatch possible at all, because nothing is cross-compiled.
    Switching `unix`'s own aarch64/armhf/mipsel images to this shape
    would very plausibly make their own Dockerfiles nearly identical to
    `unix-manylinux-x64`'s (just a different base image tag plus
    `--platform`), eliminating this entire bug category rather than
    patching each instance -- but it is a real, separate architecture
    change (QEMU setup in every workflow that runs these containers,
    including third-party consumers; `--platform` threaded through
    `dockerrun.py`'s own `run()`/`ensure_image()`; slower builds under
    emulation), not a drop-in fix for the specific failure above.
    **Deliberately not adopted now** -- raised mid-incident, while
    under real time pressure to get a concrete result rather than a
    bigger diff, and correctly deferred: swapping the architecture out
    from under five already-Dockerfiles that were otherwise working
    (four of five never even hit this bug) is a bigger, riskier change
    than the one-line fix above, and deserves its own deliberate
    decision later, not one made reactively mid-debugging. Flagged here
    precisely so a future session evaluates it as a real option rather
    than re-discovering cibuildwheel's own approach from scratch.

**D32's own end-to-end proof is now fully green, confirmed live, not
assumed**: `build-usermod-unix` succeeded for real (all 5 `unix`
arches, through `dockerrun.run()` against the exact
`ghcr.io/.../cibuildmp-unix-manylinux-<arch>:sha-<gitsha>` images
`verify-docker-images` just pushed moments earlier in the same run) --
alongside `build`, all 8 `verify-docker-images` legs, and
`usermod-dev.yml`, on the same commit. This is the actual close of
D28's own "one real gap": a real usermod build has now run *through*
the Docker path end to end, not just `docker build`/`docker push`
succeeding.

`windows`/`qemu`/`webassembly` wiring, and `PORT_IMAGES` actually being
registered (still empty -- `ensure_image()`'s local build is the thing
proving the path works at all now, registering a maintained default on
top of that is a separate, later step) remain open, same as D28 left
them.
