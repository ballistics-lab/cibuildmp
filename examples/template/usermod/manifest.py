# ruff: noqa -- include()/freeze() are makemanifest.py's own DSL,
# injected at manifest-parse time by MicroPython's own tooling, not real
# Python builtins ruff can see; same suppression micropython-bclibc's own
# usermod/manifest.py already carries for the identical reason.
#
# Freeze facade.py (the same Python-level facade natmod's own [publish]
# extra-files copies alongside template.mpy, D14) into the firmware image
# instead -- usermod builds a full port binary with no package.json/
# mip-install step of its own (D23), so "frozen in" is the equivalent
# delivery mechanism here, not "copied alongside".
#
# For port-specific builds (qemu today; esp32/rp2 etc. later) include the
# board's default manifest so _boot.py and other standard frozen scripts
# are preserved. unix's own FROZEN_MANIFEST has no such default to
# include ($(PORT_DIR)/boards/manifest.py does not exist there), hence
# the try/except -- same shape micropython-bclibc's own usermod/manifest.py
# already uses for the identical reason.
try:
    include("$(PORT_DIR)/boards/manifest.py")  # type: ignore
except Exception:
    pass

freeze("../src", "facade.py")  # type: ignore
