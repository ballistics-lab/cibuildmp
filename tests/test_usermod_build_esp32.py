from pathlib import Path

import pytest

from cibuildmp.platforms.usermod import espidf
from cibuildmp.platforms.usermod.build_common import UsermodBuildError
from cibuildmp.platforms.usermod.build_esp32 import (
    Esp32BuildOptions,
    build_esp32,
    esp32_make_command,
)


def esp32_opts(**overrides) -> Esp32BuildOptions:
    defaults = {
        "user_c_modules": "/gh/ws/micropython/usermod/micropython.cmake",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
    }
    defaults.update(overrides)
    return Esp32BuildOptions(**defaults)


def test_esp32_command_matches_build_usermod_esp32_shape():
    # build-usermod-esp32's own "Build usermod" step -- no BUILD=
    # override, matching its own documented reason not to pass one at all.
    command = esp32_make_command(esp32_opts(), Path("/gh/ws/mpy"))

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/esp32",
        "BOARD=ESP32_GENERIC",
        "USER_C_MODULES=/gh/ws/micropython/usermod/micropython.cmake",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]
    assert not any(arg.startswith("BUILD=") for arg in command)


def test_esp32_command_carries_mpy_cross_when_given():
    command = esp32_make_command(
        esp32_opts(), Path("/gh/ws/mpy"), mpy_cross=Path("/gh/ws/mpy-cross")
    )

    assert "MICROPY_MPYCROSS=/gh/ws/mpy-cross" in command


def _mock_esp32_image(monkeypatch, image="cibuildmp-esp32:local"):
    """Docker, since 2026-08-28 -- every real build_esp32() path needs
    ensure_image() to resolve something before it will run anything at
    all, the same shape `_mock_unix_image()`/webassembly's own tests
    already use. `container_mpy_cross()` is stubbed out for the same
    reason those do (record 0044's own live finding, now true for esp32
    too): it is a second real container, and these cases are about
    build_esp32()'s own command/script shape."""
    monkeypatch.setenv("CIBMP_ESP32_DOCKER_IMAGE", image)
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    monkeypatch.setattr(
        espidf, "fetch_esp_idf", lambda version, **k: Path("/gh/ws/idf")
    )


def test_esp32_docker_image_override_skips_own_dockerfile_build(monkeypatch, tmp_path):
    _mock_esp32_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    build_esp32(esp32_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")

    assert len(calls) == 1
    docker_command = calls[0]
    assert docker_command[:3] == ["docker", "run", "--rm"]
    assert "cibuildmp-esp32:local" in docker_command
    assert "bash" in docker_command


def test_esp32_no_docker_image_raises_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv("CIBMP_ESP32_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr("cibuildmp.dockerrun._pins", lambda: {"image_group": {}})

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_esp32(esp32_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")

    assert calls == []


def test_esp32_script_installs_once_then_makes(monkeypatch, tmp_path):
    """The container script installs ESP-IDF's own tools only when the
    `.installed` marker is missing, then runs the real `make` -- both in
    the one shell invocation `_esp32_container_script()` builds."""
    _mock_esp32_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    build_esp32(esp32_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")

    script = calls[0][-1]
    assert "idf_tools.py install --targets=esp32" in script
    assert "idf_tools.py install-python-env" in script
    assert "idf_tools.py export --format key-value" in script
    # Real CI (unmapped --user UID, unlike a local UID matching the
    # image's own /etc/passwd) resolves an unset HOME to "/" -- ESP-IDF's
    # own CMake ComponentManager then fails to create its cache dir
    # there, live-caught 2026-08-28. HOME must be exported before
    # anything that could touch it runs.
    assert script.index("export HOME=") < script.index("idf_tools.py install")
    assert ".installed" in script
    assert "make -C" in script
    assert "ports/esp32" in script


def test_esp32_mounts_idf_and_tools_dirs(monkeypatch, tmp_path):
    _mock_esp32_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    mpy_dir = tmp_path / "mpy"
    build_esp32(esp32_opts(), mpy_dir, toolchain_root=tmp_path / "cache")

    docker_command = calls[0]
    assert f"{mpy_dir}:{mpy_dir}" in docker_command
    assert "/gh/ws/idf:/gh/ws/idf" in docker_command
    tools_dir = tmp_path / "cache" / "esp-idf" / "v5.5.1" / "tools" / "esp32"
    assert f"{tools_dir}:{tools_dir}" in docker_command


def test_esp32_missing_bin_after_success_is_an_error(monkeypatch, tmp_path):
    _mock_esp32_image(monkeypatch)
    (tmp_path / "mpy" / "ports" / "esp32").mkdir(parents=True)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", lambda *a, **k: None)

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_esp32(esp32_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")


def test_esp32_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    _mock_esp32_image(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_esp32(esp32_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")


def test_esp32_custom_board_and_target():
    command = esp32_make_command(
        esp32_opts(board="ESP32S3_GENERIC"), Path("/gh/ws/mpy")
    )

    assert "BOARD=ESP32S3_GENERIC" in command


def test_esp32_extra_cmake_args_reach_the_container_as_idfpy_flags(
    monkeypatch, tmp_path
):
    # Not a make command-line token (unlike extra_make_args): ported
    # through the container's own environment instead, since
    # ports/esp32/Makefile builds IDFPY_FLAGS with a plain `+=` that a
    # command-line assignment would replace rather than add to -- see
    # build_common.cmake_extra_args_env()'s own docstring.
    _mock_esp32_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    build_esp32(
        esp32_opts(extra_cmake_args=("-DMICROPY_C_HEAP_SIZE=131072",)),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "cache",
    )

    docker_command = calls[0]
    assert "IDFPY_FLAGS=-DMICROPY_C_HEAP_SIZE=131072" in docker_command


def test_esp32_no_extra_cmake_args_means_no_idfpy_flags_env(monkeypatch, tmp_path):
    _mock_esp32_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True)
    (build_dir / "micropython.bin").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    build_esp32(esp32_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")

    assert not any(arg.startswith("IDFPY_FLAGS=") for arg in calls[0])
