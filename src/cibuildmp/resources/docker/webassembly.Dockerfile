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
# emsdk itself -- the actual `emcc`/`em++` toolchain -- is deliberately
# NOT baked into this image at all, unlike unix's apt-installed
# cross-compilers. `usermod/emsdk.py`'s own `resolve_emsdk()` downloads
# a pinned prebuilt tarball (resources/usermod.toml's own `[emsdk]`
# table) into `sources.cache_root()`, on the bare host, the same way it
# does for every non-Docker caller today -- and per D28 step 4 (not yet
# implemented: `build_webassembly()` has no docker-image branch yet,
# the same as `build_windows()`/`build_qemu()`), that resolved
# directory is meant to be bind-mounted into this image at container
# *run* time, not baked in at image *build* time -- otherwise every
# `docker run` against this image would need its own fresh emsdk
# download (an ordinary `docker run --rm` container's filesystem is
# thrown away after each run), defeating the whole point of caching it
# at all. This image is therefore intentionally incomplete on its own
# until step 4 lands: it has the base OS packages `make -C
# ports/webassembly`'s own non-toolchain steps need, and nothing that
# resolves or invokes `emcc` itself.
#
# TERSER (`npx terser`)/NODE are real dependencies of this port's own
# Makefile -- but only for the `min`/`repl`/`test`/`test_min` targets,
# never the default `all` target (confirmed directly against a real
# v1.28.0 `ports/webassembly/Makefile`: `all: $(BUILD)/micropython.mjs`
# depends on nothing but `emcc` and the shared `$(SRC_JS)` files).
# `webassembly_make_command()` (usermod/build.py) never names a target
# at all, so it always runs `all` -- Node.js/npm/terser are
# deliberately NOT installed here, they would only ever be exercised by
# a target cibuildmp itself never asks for.
#
# Build: docker build -t cibuildmp-webassembly -f src/cibuildmp/resources/docker/webassembly.Dockerfile .
# Use:   CIBMP_WEBASSEMBLY_DOCKER_IMAGE=cibuildmp-webassembly cibuildmp ...
#        (not actually usable yet -- see the emsdk-mounting note above;
#        this only builds the base image today, D28 step 4 wires the
#        mount and the env-var name may still change once that lands)
FROM ubuntu:24.04

# python3: ports/webassembly/Makefile includes py/mkenv.mk, whose own
# `PYTHON = python3` default every port's build shells out to directly
# (makeversionhdr.py, mpy-tool.py, qstr generation) -- confirmed
# directly against a real v1.28.0 checkout, not assumed just because
# every other port here needs it too. build-essential: emcc itself
# shells out to a real host `ar`/`ranlib` for static-archive steps in
# some configurations; kept for the same reason every other image here
# keeps it, not verified as strictly required for this port's own
# default VARIANT.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3 \
    && rm -rf /var/lib/apt/lists/*
