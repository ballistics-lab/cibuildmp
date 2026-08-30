# CMake-port entry point for the [0054]/[0069] upstream-usercmodule fixture.
# `user-c-modules = "."` (this project's own default) makes
# `portinfo.resolve_user_c_modules()` point USER_C_MODULES at
# "<this dir>/micropython.cmake" for a CMake port -- this file, not
# upstream's own `examples/usercmodule/micropython.cmake` in the pinned
# checkout (docs/records/0069 explains why a fixture-owned file is needed
# at all rather than pointing straight at upstream's: its own aggregator
# omits `subpackage`).
#
# MICROPY_DIR needs no injection from outside: every CMake port sets it at
# the top of its own CMakeLists.txt before `include(${MICROPY_DIR}/py/
# usermod.cmake)` ever runs (rp2/CMakeLists.txt's own `get_filename_component`
# call, esp32/main/CMakeLists.txt's own `if(NOT MICROPY_DIR)` guard), and
# `include()` does not open a new variable scope -- it is still set when
# usermod.cmake includes *this* file. Confirmed against both checkouts
# directly, not assumed; this replaces the CIBMP_UPSTREAM_USERCMODULE_DIR
# cache variable an earlier version of this file needed
# (test-upstream-usermodule.yml no longer resolves the checkout itself or
# passes extra-cmake-args at all -- see docs/records/0069's own addendum).
if(NOT DEFINED MICROPY_DIR)
    message(FATAL_ERROR
        "MICROPY_DIR is not set. This fixture expects to be include()d from "
        "py/usermod.cmake, the same way every other CMake-port user module "
        "is -- see docs/records/0069.")
endif()

# Upstream's own aggregator (cexample, cppexample) -- read straight out of
# the pinned checkout, never copied here (docs/records/0054: no vendoring).
include(${MICROPY_DIR}/examples/usercmodule/micropython.cmake)

# subpackage is not in upstream's own aggregator above (confirmed against a
# real checkout, micropython@e0e9fbb17) even though py/py.mk's own
# directory glob already builds it on the Make side with no extra line at
# all -- this is the one line this project adds to build the same three
# modules on both build systems, per docs/records/0069's own reasoning.
include(${MICROPY_DIR}/examples/usercmodule/subpackage/micropython.cmake)
