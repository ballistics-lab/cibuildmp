import pytest

from cibuildmp.platforms.usermod.portinfo import (
    UnknownPortError,
    build_system,
    default_manifest,
    known_ports,
    resolve_user_c_modules,
)


def test_known_ports_is_the_seven_wired_drivers():
    assert known_ports() == (
        "esp32",
        "qemu",
        "rp2",
        "samd",
        "unix",
        "webassembly",
        "windows",
    )


@pytest.mark.parametrize("port", ["unix", "webassembly", "windows", "qemu", "samd"])
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
    assert default_manifest("samd") == "boards/manifest.py"


def test_qemu_has_no_default_manifest():
    assert default_manifest("qemu") is None


def test_unknown_port_raises_with_the_known_list():
    with pytest.raises(UnknownPortError, match="stm32.*Known:.*esp32"):
        build_system("stm32")
    with pytest.raises(UnknownPortError):
        default_manifest("stm32")


def test_resolve_user_c_modules_matches_a7p_workflow_literal():
    # a7p's own `user_c_modules:` inputs, byte for byte -- a path that does
    # not exist on disk at all, so the make branch's own micropython.mk
    # existence check (below) is guaranteed false here and this exercises
    # only the pre-existing pass-through/append behaviour, unchanged:
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


def test_resolve_user_c_modules_make_port_multi_module_shape_unchanged(tmp_path):
    # a7p's own real shape: module_dir ("usermod") holds a subdirectory
    # ("a7p") with the actual micropython.mk, not a micropython.mk of its
    # own -- py/py.mk's glob already finds this one correctly, so
    # resolve_user_c_modules() must keep returning module_dir as-is.
    module_dir = tmp_path / "usermod"
    (module_dir / "a7p").mkdir(parents=True)
    (module_dir / "a7p" / "micropython.mk").write_text("")

    assert resolve_user_c_modules("unix", str(module_dir)) == str(module_dir)


def test_resolve_user_c_modules_make_port_flat_shape_resolves_to_parent(tmp_path):
    # o-murphy/micropython-wasm3's own real shape, live-caught 2026-08-29:
    # module_dir ("usermod") holds micropython.mk directly -- py/py.mk's
    # glob (<module_dir>/*/micropython.mk) finds nothing there at all, no
    # error anywhere, and the port silently builds and links with zero
    # user modules. resolve_user_c_modules() must rewrite this to
    # module_dir's own parent, so the glob finds it one level down
    # instead, at <parent>/usermod/micropython.mk.
    module_dir = tmp_path / "usermod"
    module_dir.mkdir()
    (module_dir / "micropython.mk").write_text("")

    assert resolve_user_c_modules("unix", str(module_dir)) == str(tmp_path)


def test_resolve_user_c_modules_flat_shape_unaffected_for_cmake_ports(tmp_path):
    # The same flat module_dir a make port needs rewritten for must still
    # resolve straight to <module_dir>/micropython.cmake for a cmake port
    # -- these two branches are independent, and a make-port fix must not
    # change cmake-port behaviour just because the same directory happens
    # to also hold a micropython.mk (a real consumer can and does ship
    # both files side by side in one module_dir, e.g. wasm3's own
    # usermod/micropython.mk + usermod/micropython.cmake).
    module_dir = tmp_path / "usermod"
    module_dir.mkdir()
    (module_dir / "micropython.mk").write_text("")

    assert resolve_user_c_modules("esp32", str(module_dir)) == str(
        module_dir / "micropython.cmake"
    )
