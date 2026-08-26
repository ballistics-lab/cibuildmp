# MPY_DIR and ARCH are supplied on the command line by cibuildmp (see
# build.make_command) -- not hardcoded here, unlike MicroPython's own
# examples/natmod/*/Makefile, which default ARCH to one value for a
# standalone `make`.
MOD = template
# ../src/template_core.c is the shared core usermod/template/template.c
# also compiles unchanged -- see that file's own header comment.
SRC = template.c ../src/template_core.c

# Must be set before the include below -- dynruntime.mk only defaults it
# with `?=`. Scopes intermediate objects (*.o/.native.mpy) per arch *and*
# per arch-flags variant: found for real running the whole matrix in one
# natmod/ tree -- without the $(ARCH) half, a second `make ARCH=<other>`
# sees the first arch's own build objects as up to date (same path,
# nothing in the source changed) and skips rebuilding, so $(MOD).mpy
# silently stays the *first* arch's binary. The $(ARCH_FLAGS) half is the
# same bug on a second axis, found the same way: rv32imc's own object file
# doesn't depend on ARCH_FLAGS at all, so building several arch-flags
# variants back to back (D15) reuses the first variant's cached .o/.mpy for
# every later one just as silently, even though $(ARCH) never changed.
#
# Deliberately NOT under build/$(ARCH) -- cibuildmp's collect_output()
# globs build/<arch>*/*.mpy for the *finished* dist artifact, and dropping
# dynruntime.mk's own intermediate $(ARCH).native.mpy in that same
# directory makes the glob ambiguous (two .mpy files where it expects
# one). .obj/ keeps make's own per-arch object cache out of the tree
# cibuildmp looks in.
# The trailing /o is load-bearing and is the *third* instance of the bug
# the paragraph above describes, found the same way as the other two --
# running the whole matrix in one tree, which record 0049 made the normal
# thing to do by putting natmod builds in a container.
#
# dynruntime.mk forms each object as $(BUILD)/$(src:.c=.o). For a source
# inside this directory that is arch-scoped as intended. For one *outside*
# it, the `..` eats the arch component instead:
#
#   template.c            -> .obj/x64/template.o          scoped
#   ../src/template_core.c -> .obj/x64/../src/….o
#                          =  .obj/src/template_core.o    NOT scoped
#
# So the shared core object was built once, by whichever arch ran first,
# and silently linked into every later one -- `make ARCH=x86` then
# `ARCH=x64` produced `LinkError: incompatible arch`, and a 32-bit EM_386
# object sitting in .obj/src/ was the reason. Adding one directory level
# gives the `..` somewhere to go that is still under $(ARCH):
#
#   ../src/template_core.c -> .obj/x64/o/../src/….o
#                          =  .obj/x64/src/template_core.o  scoped
#
# One level covers one `..`, which is the layout this repo documents
# (natmod/, usermod/ and src/ as siblings). A source two levels up would
# need two, and would deserve its own comment saying so.
BUILD = .obj/$(ARCH)$(if $(ARCH_FLAGS),+$(ARCH_FLAGS))/o

include $(MPY_DIR)/py/dynruntime.mk

# $(MOD).mpy itself (dynruntime.mk's own merge target) is NOT scoped by
# $(ARCH) the way $(BUILD) above is -- it's one fixed filename in
# module-dir, reused across every arch and every separate `cibuildmp`
# invocation in this same tree. Its own rule only depends on
# $(BUILD)/$(MOD).native.mpy, so if a *previous* run already left
# $(BUILD)/$(MOD).native.mpy for the *current* $(ARCH) sitting there older
# than the last arch's $(MOD).mpy, make sees it as up to date and `dist`
# copies stale output from a different arch -- found for real running
# `cibuildmp` twice in the same tree, not just after manual meddling.
# (Tried making $(MOD).mpy phony-dependent first: dynruntime.mk's own
# recipe merges every prerequisite via `$^`, so an extra dependency here
# lands in that list as if it were a real input file -- mpy-tool.py then
# fails trying to open a file literally named after the fake prerequisite.
# Deleting the stale file before a recursive `$(MAKE) all` sidesteps that:
# it never touches dynruntime.mk's own prerequisite list.) ARCH/MPY_DIR/
# PYTHON are plain `=` command-line overrides (see build.make_command),
# which `$(MAKE)` always re-passes to a sub-make without needing `export`.
dist:
	rm -f $(MOD).mpy
	$(MAKE) all
	mkdir -p build/$(ARCH)
	cp $(MOD).mpy build/$(ARCH)/
