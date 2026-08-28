# 0026. usermod moves to one Docker image per port, not one combined image

- Status: Accepted; amended by [0031] (per-arch/libc split for unix)
- Related: [0003], [0025], [0028]

<!-- migrated verbatim from docs/BACKLOG.md lines 1796-1888 -->

**D26 — usermod moves to one Docker image *per port*, not one combined
image; `action.yml` stops being a Docker action itself and becomes a
thin composite action that ensures Docker is present, then runs
`cibuildmp` directly on the bare runner; `cibuildmp` itself launches
sibling per-port containers rather than running inside one.** Direct
follow-up to D25's own cibuildwheel comparison and the six real bugs
found there -- the user's own proposal, refined once from "per
architecture" to "per port" citing `mpbuild`'s own precedent of
separate containers per port.

- **Not a new idea grafted on** -- `toolchains.py`'s own module
  docstring already said this outright, before any of D25's bugs were
  found: "Docker is deliberately absent for natmod... It is planned
  for usermod, where port builds have real system dependencies." This
  decision is that plan, made concrete.
- **Why sibling containers, not Docker-in-Docker:** today's
  `action.yml` already runs entirely *inside* one container
  (`action.Dockerfile`, D18's own conversion). If `cibuildmp` itself
  tried to launch per-port containers from in there, it would need the
  host's Docker socket passed through (`-v /var/run/docker.sock:...`)
  -- a real, fragile pattern (DinD), not free. Flipping it -- the
  action installs/confirms Docker and runs `cibuildmp` bare on the
  runner, which then runs ordinary sibling `docker run` calls -- avoids
  DinD entirely, since GitHub-hosted runners already have a working
  Docker daemon with no container boundary in the way. natmod is
  unaffected either way: every natmod arch is a cross-compile that
  already runs directly on the host (D2/M2), no container at all,
  today or after this change.
- **Honest limit: per-port splitting does not, by itself, avoid the
  six bugs D25 just fixed.** Every one of them was `unix` colliding
  with itself -- its own five architectures (`x64`/`x86`/`aarch64`/
  `armhf`/`mipsel`) sharing one filesystem, not `unix` colliding with
  `windows` or `esp32`. A `unix`-only image still combines all five
  unix cross-compilers in one place and would still need every fix
  D25 documents. The real, distinct benefits are: (1) no DinD, as
  above; (2) a caller building only `unix` never pulls `windows`'s
  `gcc-mingw-w64-*` or `esp32`'s multi-gigabyte ESP-IDF checkout at
  all -- today's single image pays that cost for everyone regardless
  of `ports = [...]`; (3) blast radius -- a broken `esp32` image
  (ESP-IDF's own churn is real and frequent) can't block a `unix`-only
  build the way one shared image's failed `docker build` does today;
  (4) matches `mpbuild`'s own independently-arrived-at shape (cited by
  the user, not yet independently verified against `mpbuild`'s own
  source by this project).
- **Scope, not yet built:** a new `docker` toolchain strategy in
  `cibuildmp` (build/pull a port's own image, run the port's existing
  `make`/`cmake` invocation inside a container via ordinary volume
  mounts -- `mpy_dir` and the caller's `package_dir` cover every path
  the existing commands already reference, no path translation needed
  since mounts land at identical absolute paths); five per-port
  Dockerfiles replacing today's one `action.Dockerfile` (`unix`,
  `windows`, `qemu`, `webassembly`, `esp32`); `action.yml` rewritten
  from `runs: using: docker` to a composite action; `publish.yml`'s
  GHCR push extended from one image to five. Each per-port image needs
  only that port's own toolchain, not `cibuildmp` itself baked in --
  `cibuildmp` stays on the bare runner and only ever `docker run`s the
  port's own build command, keeping every image far smaller than
  today's combined one.
- **First slice, agreed with the user:** a proof-of-concept for `unix`
  only -- a `resources/docker/unix.Dockerfile` (just that port's own toolchain,
  the exact package set D20/D24/D25 already verified live, minus
  `windows`/`esp32`-only packages) and a minimal `docker`
  toolchain-strategy path in `usermod/build.py`, opt-in and not yet
  wired into the public `action.yml` at all. This project's dev
  sandbox has no Docker daemon (**D19**), so unlike every apt-level fix
  above, an actual `docker build`/`docker run` of this slice cannot be
  verified here at all -- only on real CI, the same round-trip
  constraint D25's own six-bug chain already worked under, now one
  level higher (a whole new image, not one more apt package).
- **Amended (D31): "one image per port" was still too coarse for
  `unix` specifically.** The user's own correction, directly: `unix`
  needed cutting further, into one image per *(arch, libc)* --
  cibuildwheel's own `manylinux_x86_64`/`musllinux_aarch64` shape, not
  one combined "unix" image the way this decision first described it
  above. `resources/docker/unix.Dockerfile` (one image, all five
  arches) was replaced by five separate
  `resources/docker/unix-manylinux-<arch>.Dockerfile` files, each only
  that arch's own packages -- real isolation this decision's own bullet
  above already argued for at the *port* level now also holds at the
  *arch* level (an armhf toolchain bump can no longer touch an x64
  image's own build). `natmod` is explicitly NOT part of this
  refinement -- the user's own point: a `.mpy` is loaded by an
  already-running target interpreter, not exec'd as its own process, so
  the build host's own libc linkage never enters the picture the way it
  does for a full `unix` port executable; one combined `natmod`
  Dockerfile (**D30**'s own point 2) stays correct. `windows` also
  stays one combined image (this file's own `resources/docker/windows.Dockerfile`
  header has the reasoning: no manylinux/musllinux-shaped axis exists
  for Windows at all). See **D31** for the full musllinux gap this
  correction sits inside, and `usermod/dockerrun.py`'s own resolver,
  now keyed by `(port, arch)` with an optional trailing `libc` segment
  rather than `port` alone.
