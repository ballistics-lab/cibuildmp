# The Make-side twin of ../micropython.cmake's own MICROPY_DIR trick: py.mk's
# `$(USER_C_MODULES)/*/micropython.mk` glob finds *this* file (user-c-modules stays the
# built-in "." default -- this fixture's own directory), so py.mk sets USERMOD_DIR to
# this file's own directory before including it, not to upstream's real cexample/ inside
# the pinned checkout. Upstream's own micropython.mk reads $(USERMOD_DIR) to build
# CEXAMPLE_MOD_DIR (examples/template/usermod/micropython.mk's own header comment
# documents the identical mechanism for a sibling-source case) -- forwarding the
# `include` unchanged would point every one of its SRC_USERMOD/CFLAGS_USERMOD entries at
# this fixture's own (contentless) directory instead. Overriding USERMOD_DIR here, to
# $(TOP) (py/mkenv.mk's own checkout-root variable, already set by the time py.mk's own
# USER_C_MODULES loop runs this), before the real include, fixes that -- no vendoring
# (0054), the real file is still what builds.
USERMOD_DIR := $(TOP)/examples/usercmodule/cexample
include $(USERMOD_DIR)/micropython.mk
