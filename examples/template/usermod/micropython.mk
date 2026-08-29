# Included by MicroPython's py.mk when USER_C_MODULES=<usermod-dir>.
# USERMOD_DIR is set by py.mk to the directory containing this file
# (= usermod/). "usermod" itself is the one-level module-name directory
# py.mk's own $(USER_C_MODULES)/*/micropython.mk glob needs -- this
# example's own [usermod] module-dir = "." (cibuildmp.toml) points
# USER_C_MODULES at the project root, one level above this file, the
# same shape micropython-bclibc's own usermod/micropython.mk already
# uses (not cibuildmp's own usermod/<name>/micropython.mk default) --
# required here, not just stylistic: src/template_core.c is a sibling of
# usermod/, not a descendant of it, and dockerrun.py only bind-mounts
# USER_C_MODULES itself into the build container, so src/ has to live
# inside whatever directory USER_C_MODULES resolves to or the container
# genuinely cannot see it -- found for real, "No rule to make target
# .../src/template_core.c" from inside the container, the file present
# and correct on the host the whole time.

TEMPLATE_MOD_DIR := $(USERMOD_DIR)

SRC_USERMOD += $(TEMPLATE_MOD_DIR)/template_usermod.c
# Shared with natmod/Makefile's own SRC -- see that file's own comment,
# and template_core.h's. $(abspath ...), not a bare $(TEMPLATE_MOD_DIR)/
# ../src/... string: py.mk's own PATHFIX strips $(USER_C_MODULES)/ as a
# literal text prefix, not a canonicalized one, and this path's raw text
# starts with exactly that prefix before ../ ever gets resolved --
# stripping it left the broken relative fragment
# "../src/template_core.c" relative to nothing sane, which make then
# failed to find. $(abspath) collapses the ../ lexically first, so the
# result no longer starts with $(USER_C_MODULES)/ at all and PATHFIX
# leaves it untouched.
SRC_USERMOD += $(abspath $(TEMPLATE_MOD_DIR)/../src/template_core.c)
