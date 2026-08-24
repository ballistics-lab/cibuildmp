# MPY_DIR and ARCH are supplied on the command line by cibuildmp (see
# build.make_command) -- not hardcoded here, unlike MicroPython's own
# examples/natmod/*/Makefile, which default ARCH to one value for a
# standalone `make`.
MOD = template
SRC = template.c

# Must be set before the include below -- dynruntime.mk only defaults it
# with `?=`. Scopes intermediate objects (*.o/.native.mpy) per arch: found
# for real running the whole matrix in one natmod/ tree -- without this, a
# second `make ARCH=<other>` sees the first arch's own build objects as up
# to date (same path, nothing in the source changed) and skips rebuilding,
# so $(MOD).mpy silently stays the *first* arch's binary.
#
# Deliberately NOT under build/$(ARCH) -- cibuildmp's collect_output()
# globs build/<arch>*/*.mpy for the *finished* dist artifact, and dropping
# dynruntime.mk's own intermediate $(ARCH).native.mpy in that same
# directory makes the glob ambiguous (two .mpy files where it expects
# one). .obj/ keeps make's own per-arch object cache out of the tree
# cibuildmp looks in.
BUILD = .obj/$(ARCH)

include $(MPY_DIR)/py/dynruntime.mk

# The convention every cibuildmp-built natmod Makefile follows (see
# README.md's "Conventions this repo assumes"): `dist` drops the built .mpy
# under build/<arch>*/, which is what build.collect_output() globs for.
dist: all
	mkdir -p build/$(ARCH)
	cp $(MOD).mpy build/$(ARCH)/
