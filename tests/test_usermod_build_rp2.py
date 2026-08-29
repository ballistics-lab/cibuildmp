from pathlib import Path

import pytest

from cibuildmp.platforms.usermod.build_common import UsermodBuildError
from cibuildmp.platforms.usermod.build_rp2 import (
    Rp2BuildOptions,
    build_rp2,
    rp2_make_command,
)


def rp2_opts(**overrides) -> Rp2BuildOptions:
    defaults = {
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
    }
    defaults.update(overrides)
    return Rp2BuildOptions(**defaults)


def test_rp2_command_shape():
    command = rp2_make_command(rp2_opts(), Path("/gh/ws/mpy"))

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/rp2",
        "BOARD=PICO",
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


def test_rp2_command_carries_mpy_cross_when_given():
    command = rp2_make_command(
        rp2_opts(), Path("/gh/ws/mpy"), mpy_cross=Path("/gh/ws/mpy-cross")
    )

    assert "MICROPY_MPYCROSS=/gh/ws/mpy-cross" in command


def _mock_rp2_image(monkeypatch, image="cibuildmp-rp2:local"):
    monkeypatch.setenv("CIBMP_RP2_DOCKER_IMAGE", image)
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )


def test_rp2_no_docker_image_raises_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv("CIBMP_RP2_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr("cibuildmp.dockerrun._pins", lambda: {"image_group": {}})

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_rp2(rp2_opts(), tmp_path / "mpy")

    assert calls == []


def test_rp2_missing_firmware_after_success_is_an_error(monkeypatch, tmp_path):
    _mock_rp2_image(monkeypatch)
    (tmp_path / "mpy" / "ports" / "rp2").mkdir(parents=True)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", lambda *a, **k: None)

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_rp2(rp2_opts(), tmp_path / "mpy")


def test_rp2_builds_and_returns_firmware_path(monkeypatch, tmp_path):
    _mock_rp2_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "rp2" / "build-PICO"
    build_dir.mkdir(parents=True)
    (build_dir / "firmware.uf2").write_bytes(b"")

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", lambda *a, **k: None)

    result = build_rp2(rp2_opts(), tmp_path / "mpy")

    assert result == build_dir / "firmware.uf2"


def test_rp2_extra_cmake_args_reach_the_container_as_cmake_args(monkeypatch, tmp_path):
    # Not a make command-line token (unlike extra_make_args): ported
    # through the container's own environment instead, since
    # ports/rp2/Makefile builds CMAKE_ARGS with a plain `+=` that a
    # command-line assignment would replace rather than add to -- see
    # build_common.cmake_extra_args_env()'s own docstring.
    _mock_rp2_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "rp2" / "build-PICO"
    build_dir.mkdir(parents=True)
    (build_dir / "firmware.uf2").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    build_rp2(
        rp2_opts(extra_cmake_args=("-DMICROPY_C_HEAP_SIZE=131072",)), tmp_path / "mpy"
    )

    docker_command = calls[0]
    assert "CMAKE_ARGS=-DMICROPY_C_HEAP_SIZE=131072" in docker_command


def test_rp2_no_extra_cmake_args_means_no_cmake_args_env(monkeypatch, tmp_path):
    _mock_rp2_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "rp2" / "build-PICO"
    build_dir.mkdir(parents=True)
    (build_dir / "firmware.uf2").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    build_rp2(rp2_opts(), tmp_path / "mpy")

    assert not any(arg.startswith("CMAKE_ARGS=") for arg in calls[0])
