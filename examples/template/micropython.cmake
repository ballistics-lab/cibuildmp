# The CMake-port twin of usermod/micropython.mk -- proof the same shared
# core (src/template_core.c) builds through a CMake port (esp32, rp2, ...)
# as well as a Make one, not just the natmod/usermod pair. Lives at the
# package root, not inside usermod/: py/usermod.cmake resolves
# USER_C_MODULES directly (`resolve_user_c_modules()`'s cmake branch
# appends "/micropython.cmake" to whatever USER_C_MODULES already is),
# unlike py.mk's own `$(USER_C_MODULES)/*/micropython.mk` glob -- this
# example's own `user_c_modules = "."` (cibuildmp.toml's default) points
# both at the project root, but a CMake port needs the file to actually
# be there, not one level down.
#
# Upstream's own examples/usercmodule/usercmodule.cmake is the reference
# this mirrors (an INTERFACE library, sources, include dirs, then linked
# into the `usermod` target).
add_library(usermod_template INTERFACE)

target_sources(usermod_template INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/usermod/template_usermod.c
    ${CMAKE_CURRENT_LIST_DIR}/src/template_core.c
)

target_include_directories(usermod_template INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/src
)

target_link_libraries(usermod INTERFACE usermod_template)
