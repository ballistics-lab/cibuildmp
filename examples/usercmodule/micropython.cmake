# CMake-port entry point for the [0054]/[0069] upstream-usercmodule fixture.
# `user-c-modules = "."` (this project's own default) makes
# `portinfo.resolve_user_c_modules()` point USER_C_MODULES at
# "<this dir>/micropython.cmake" for a CMake port -- this file, not
# upstream's own `examples/usercmodule/micropython.cmake` in the pinned
# checkout (docs/records/0069 explains why a fixture-owned file is needed
# at all rather than pointing straight at upstream's: its own aggregator
# omits `subpackage`).
#
# CIBMP_UPSTREAM_USERCMODULE_DIR is not this project's own config key -- it
# is a plain CMake cache variable, supplied by
# .github/workflows/test-upstream-usermodule.yml via `extra-cmake-args`
# (CIBMP_EXTRA_CMAKE_ARGS -> CMAKE_ARGS/IDFPY_FLAGS,
# build_common.cmake_extra_args_env(), record 0066 -- unextended here), set
# to <the checkout sources.fetch_micropython() resolved>/examples/usercmodule.
# Never hardcoded here: the checkout's own path depends on the cache root
# and the pinned tag, neither of which this file can know.
if(NOT DEFINED CIBMP_UPSTREAM_USERCMODULE_DIR)
    message(FATAL_ERROR
        "CIBMP_UPSTREAM_USERCMODULE_DIR is not set. This fixture expects "
        "-DCIBMP_UPSTREAM_USERCMODULE_DIR=<pinned MicroPython checkout>/"
        "examples/usercmodule, passed via extra-cmake-args -- see "
        ".github/workflows/test-upstream-usermodule.yml and "
        "docs/records/0069.")
endif()

# Upstream's own aggregator (cexample, cppexample) -- read straight out of
# the pinned checkout, never copied here (docs/records/0054: no vendoring).
include(${CIBMP_UPSTREAM_USERCMODULE_DIR}/micropython.cmake)

# subpackage is not in upstream's own aggregator above (confirmed against a
# real checkout, micropython@e0e9fbb17) even though py/py.mk's own
# directory glob already builds it on the Make side with no extra line at
# all -- this is the one line this project adds to build the same three
# modules on both build systems, per docs/records/0069's own reasoning.
include(${CIBMP_UPSTREAM_USERCMODULE_DIR}/subpackage/micropython.cmake)
