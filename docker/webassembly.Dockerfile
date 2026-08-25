# D28 step 3's own fourth per-port image -- see
# unix-manylinux-x64.Dockerfile's own header for the general split
# rationale (cibuildmp stays on the bare host, this image holds nothing
# but the toolchain a real `make -C ports/webassembly` invocation
# needs, no `cibuildmp` installed inside it) and for why this lives
# under src/cibuildmp/resources/docker/ rather than a top-level
# docker/ directory (a real package resource, shipped with the
# installed tool).
#
# One combined image, not split per (arch, libc) like `unix` -- this
# port only ever targets one output (`micropython.mjs`, WebAssembly),
# not a native-libc-linked executable, so there is no
# manylinux/musllinux-shaped axis here at all (same reasoning
# qemu.Dockerfile's own header gives).
#
# emsdk IS baked into this image -- an earlier version of this file
# mounted it from the host's own `sources.cache_root()` instead, on a
# reasoning that does not actually hold: a Dockerfile `RUN` step's own
# output is a real image layer, not something `docker run --rm` ever
# discards -- only the ephemeral *container* goes away after each run,
# the *image* it was built from (and everything a `RUN` step wrote
# into it) is reused unchanged by every later `docker run`, exactly
# like every apt package `unix`'s own images already bake in the same
# way. There was never a "redownloads every run" problem to design
# around. The real, live-checked tradeoff is image size: the extracted
# emsdk here is ~1.5GB (`tar tJf`'d and measured directly, not
# guessed), noticeably larger than any other image here -- baking it
# in duplicates it against the same download `usermod/emsdk.py`'s own
# `resolve_emsdk()` already caches for a bare-host build, rather than
# sharing one copy the way a `sources.cache_root()` mount would. Baking
# in won anyway (the user's own call, asked directly): it needs no
# `dockerrun.py` mount/PATH-injection support at all (`ENV PATH` below
# is enough, matching how a normal `docker run` against any of these
# images already works, no design changes needed elsewhere), and ships
# a genuinely self-contained, immediately-usable image the moment
# `docker build` finishes -- consistent with every other image here.
#
# TERSER (`npx terser`) is a real dependency of this port's own
# Makefile, but only for the `min`/`repl`/`test`/`test_min` targets,
# never the default `all` target (confirmed directly against a real
# v1.28.0 `ports/webassembly/Makefile`: `all: $(BUILD)/micropython.mjs`
# depends on nothing but `emcc` and the shared `$(SRC_JS)` files).
# `webassembly_make_command()` (usermod/build.py) never names a target
# at all, so it always runs `all` -- terser/npm are deliberately NOT
# installed here, they would only ever be exercised by
# **`nodejs` itself is a different story -- see the `RUN apt-get`
# step below, corrected live after this exact assumption (originally
# "NODE deliberately NOT installed, only exercised by targets
# cibuildmp never asks for") turned out wrong: `emcc`'s own config
# sanity check wants a real `node` on every invocation, `all` included,
# regardless of which Make target is running.**
# a target cibuildmp itself never asks for.
#
# The emsdk version/URL/sha256 below MUST stay in sync with
# resources/usermod.toml's own `[emsdk]` table -- there is no tooling
# that keeps a Dockerfile RUN step and a TOML file in sync
# automatically, so a future emsdk version bump needs both edited
# together, or this image silently starts shipping a stale toolchain
# while the bare-host path moves on.
#
# Build: docker build -t cibuildmp-webassembly -f src/cibuildmp/resources/docker/webassembly.Dockerfile .
# Use:   CIBMP_WEBASSEMBLY_DOCKER_IMAGE=cibuildmp-webassembly cibuildmp ...
FROM ubuntu:24.04

# python3: ports/webassembly/Makefile includes py/mkenv.mk, whose own
# `PYTHON = python3` default every port's build shells out to directly
# (makeversionhdr.py, mpy-tool.py, qstr generation) -- confirmed
# directly against a real v1.28.0 checkout, not assumed just because
# every other port here needs it too. curl/ca-certificates: fetching
# the pinned emsdk tarball below, nothing else -- removed from PATH's
# own footprint by nothing here needing them afterwards (unlike
# unix/windows/qemu, this image's own toolchain download happens
# inside the Dockerfile itself, not on the host before `docker run`).
#
# nodejs -- real dependency after all, found live inside this exact
# image, not assumed away the way this file's own header comment above
# used to argue (TERSER/NODE "only for min/repl/test/test_min, never
# `all`"): `emcc`'s own sanity check runs, and fails
# ("NODE_JS not set in config ..., and `node` not found in PATH"), on
# *every* invocation, including a bare `-E` preprocess for qstr
# generation -- not gated behind those other targets at all. The
# `wasm-binaries.tar.xz` release asset this image downloads below does
# not bundle a Node.js binary itself (only JS sources under
# `emscripten/src/`, no runtime); a full `emsdk install`/`activate` run
# would fetch a matching one as part of its own managed toolchain set,
# which is exactly the installer path this image (and
# `usermod/emsdk.py`'s own bare-host resolver, which has the identical
# gap) deliberately bypasses for a smaller, faster, directly-verified
# download. Ubuntu 24.04's own `nodejs` package (18.x) is enough --
# `emcc`'s config sanity check only needs *a* working `node` to run
# against, confirmed live by installing it into a real container and
# re-running the exact failing command.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    curl \
    ca-certificates \
    xz-utils \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

# Pinned exactly as resources/usermod.toml's own [emsdk] table
# (version = "6.0.8", [emsdk.platform.linux-x64]) -- verified live
# before pinning here: downloaded the real tarball, confirmed this
# exact sha256 with `sha256sum -c`, and inspected its own internal
# layout with `tar tJf` (a top-level `install/` directory containing
# `install/emscripten/` and `install/bin/`, exactly what
# `usermod/emsdk.py`'s own `ResolvedEmsdk.env()` already expects on a
# bare-host resolve) rather than assumed from the tarball's name alone.
RUN curl -fsSL -o /tmp/wasm-binaries.tar.xz \
      https://storage.googleapis.com/webassembly/emscripten-releases-builds/linux/9d70dbe8860ccdd3595f6e6065d94bfb543ae955/wasm-binaries.tar.xz && \
    echo "9bea769c189d9f52196e74283fb86937318cc24bf14879f2c6bdd19862131901  /tmp/wasm-binaries.tar.xz" | sha256sum -c - && \
    mkdir -p /opt/emsdk && \
    tar -xJf /tmp/wasm-binaries.tar.xz -C /opt/emsdk && \
    rm /tmp/wasm-binaries.tar.xz && \
    chmod -R a+rwX /opt/emsdk/install/emscripten/cache

# emcc writes into its own cache/ dir (sanity-check state, cached system
# headers) on every invocation, not just the first -- extracted here
# owned by whatever UID `docker build` itself ran as (root, or the
# tarball's own baked-in "ubuntu" UID 1000 depending on layer), which
# `dockerrun.run()`'s own `--user $(id -u):$(id -g)` (real host UID,
# almost never 1000) cannot write to by default. Found for real: passed
# on a real ubuntu-latest GitHub Actions runner (a different UID than
# this sandbox's own, which happened to already be 1000 -- coincidence,
# not a fix) with `emcc: error: cache directory ... is not writable
# while accessing cache for: sanity`. `chmod -R a+rwX` (not a `chown` to
# some specific UID cibuildmp could not know in advance) is what makes
# this work for literally any `--user`, cibuildmp's own or anyone
# else's -- confirmed live against a real `--user 12345:12345` (an
# arbitrary UID with nothing else granting it access).

# Same two PATH entries ResolvedEmsdk.env() prepends on a bare-host
# resolve (emscripten/ for the emcc/em++ driver scripts, bin/ for the
# LLVM/wasm binaries they invoke) -- set once here via ENV rather than
# needing dockerrun.py to inject it per run, since the toolchain is
# baked into this image rather than mounted in.
ENV PATH="/opt/emsdk/install/emscripten:/opt/emsdk/install/bin:${PATH}"
