from cibuildmp.platforms.usermod.build_common import cmake_extra_args_env


def test_cmake_extra_args_env_joins_into_one_var():
    assert cmake_extra_args_env(
        ("-DMICROPY_C_HEAP_SIZE=131072", "-DFOO=1"), var="CMAKE_ARGS"
    ) == {"CMAKE_ARGS": "-DMICROPY_C_HEAP_SIZE=131072 -DFOO=1"}


def test_cmake_extra_args_env_empty_is_no_entry_at_all():
    # Not {"CMAKE_ARGS": ""} -- dockerrun.run() treats both the same way
    # (`env or {}`), but an absent key keeps a caller's own env= dict free
    # of a no-op entry when nobody configured anything.
    assert cmake_extra_args_env((), var="CMAKE_ARGS") == {}


def test_cmake_extra_args_env_uses_the_given_var_name():
    # rp2 and esp32 name this differently (CMAKE_ARGS vs IDFPY_FLAGS,
    # ESP-IDF's own name for the same idea) -- the helper does not
    # hardcode either.
    assert cmake_extra_args_env(("-DX=1",), var="IDFPY_FLAGS") == {
        "IDFPY_FLAGS": "-DX=1"
    }
