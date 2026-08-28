import pytest

from cibuildmp.platforms.usermod.portinfo import (
    UnknownPortError,
    build_system,
    default_manifest,
    known_ports,
    resolve_user_c_modules,
)


def test_known_ports_is_the_six_d16_d21_covers():
    assert known_ports() == ("esp32", "qemu", "rp2", "unix", "webassembly", "windows")


@pytest.mark.parametrize("port", ["unix", "webassembly", "windows", "qemu"])
def test_make_driven_ports(port):
    assert build_system(port) == "make"


@pytest.mark.parametrize("port", ["esp32", "rp2"])
def test_cmake_driven_ports(port):
    assert build_system(port) == "cmake"


def test_default_manifest_paths():
    # unix/webassembly build a specific, non-default variant in a7p's own
    # mp-usermod.yml (standard, pyscript), each with its own
    # mpconfigvariant.mk override -- not the port-level Makefile default
    # (variants/manifest.py) both ports otherwise share.
    assert default_manifest("unix") == "variants/standard/manifest.py"
    assert default_manifest("webassembly") == "variants/pyscript/manifest.py"
    # windows/esp32/rp2 build with no variant/board override in that same
    # workflow, so these are each port's own unmodified default.
    assert default_manifest("windows") == "variants/manifest.py"
    assert default_manifest("esp32") == "boards/manifest.py"
    assert default_manifest("rp2") == "boards/manifest.py"


def test_qemu_has_no_default_manifest():
    assert default_manifest("qemu") is None


def test_unknown_port_raises_with_the_known_list():
    with pytest.raises(UnknownPortError, match="stm32.*Known:.*esp32"):
        build_system("stm32")
    with pytest.raises(UnknownPortError):
        default_manifest("stm32")


def test_resolve_user_c_modules_matches_a7p_workflow_literal():
    # a7p's own `user_c_modules:` inputs, byte for byte:
    #   unix/webassembly/windows: .../micropython/usermod  (a directory)
    #   esp32/rp2:                .../micropython/usermod/micropython.cmake
    module_dir = "/gh/ws/micropython/usermod"

    assert resolve_user_c_modules("unix", module_dir) == module_dir
    assert resolve_user_c_modules("webassembly", module_dir) == module_dir
    assert resolve_user_c_modules("windows", module_dir) == module_dir
    assert resolve_user_c_modules("qemu", module_dir) == module_dir
    assert (
        resolve_user_c_modules("esp32", module_dir)
        == "/gh/ws/micropython/usermod/micropython.cmake"
    )
    assert (
        resolve_user_c_modules("rp2", module_dir)
        == "/gh/ws/micropython/usermod/micropython.cmake"
    )
