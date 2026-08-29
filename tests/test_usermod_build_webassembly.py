from pathlib import Path

import pytest

from cibuildmp.platforms.usermod.build_common import UsermodBuildError
from cibuildmp.platforms.usermod.build_webassembly import (
    WebassemblyBuildOptions,
    build_webassembly,
    webassembly_make_command,
)


def wasm_opts(**overrides) -> WebassemblyBuildOptions:
    defaults = {
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        "build_dir": Path("/gh/ws/usermod/build/wasm"),
    }
    defaults.update(overrides)
    return WebassemblyBuildOptions(**defaults)


def test_webassembly_command_matches_build_usermod_webassembly_shape():
    # build-usermod-webassembly's own "Build usermod (webassembly, pyscript
    # variant)" step -- no CROSS_COMPILE, emsdk activation is PATH/env, not
    # a make variable.
    command = webassembly_make_command(wasm_opts(), Path("/gh/ws/mpy"))

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/webassembly",
        "VARIANT=pyscript",
        "BUILD=/gh/ws/usermod/build/wasm",
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


def test_webassembly_no_image_registered_is_a_clear_error(monkeypatch, tmp_path):
    # Docker-only (D30), and cibuildmp never builds an image itself any
    # more (checked against cibuildwheel's real source before deciding --
    # its own container runtime only ever pulls an already-published,
    # digest-pinned image) -- with no override and nothing pinned in
    # resources/pinned_docker_images.toml, build_webassembly() must fail
    # loudly, not fall back to building docker/webassembly.Dockerfile.
    monkeypatch.delenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr("cibuildmp.dockerrun._pins", lambda: {"image_group": {}})
    build_dir = tmp_path / "build-wasm"

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_webassembly(wasm_opts(build_dir=build_dir), tmp_path / "mpy")

    assert calls == []


def test_webassembly_docker_image_override_skips_own_dockerfile_build(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")
    # See `_mock_windows_image` for why the in-container mpy-cross build
    # is stubbed out here too (record 0044).
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()
    (build_dir / "micropython.mjs").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    build_webassembly(wasm_opts(build_dir=build_dir), tmp_path / "mpy")

    assert len(calls) == 1
    docker_command = calls[0]
    assert docker_command[:3] == ["docker", "run", "--rm"]
    assert "cibuildmp-webassembly:local" in docker_command
    assert "make" in docker_command


def test_webassembly_docker_image_mounts_mpy_dir_and_user_c_modules(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")
    # See `_mock_windows_image` for why the in-container mpy-cross build
    # is stubbed out here too (record 0044).
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()
    (build_dir / "micropython.mjs").write_bytes(b"")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    mpy_dir = tmp_path / "mpy"
    build_webassembly(wasm_opts(build_dir=build_dir), mpy_dir)

    docker_command = calls[0]
    assert f"{mpy_dir}:{mpy_dir}" in docker_command
    assert "/gh/ws/micropython/usermod:/gh/ws/micropython/usermod" in docker_command


def test_webassembly_missing_mjs_after_success_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")
    # See `_mock_windows_image` for why the in-container mpy-cross build
    # is stubbed out here too (record 0044).
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    build_dir = tmp_path / "build-wasm"
    build_dir.mkdir()

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", lambda *a, **k: None)

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_webassembly(wasm_opts(build_dir=build_dir), tmp_path / "mpy")


def test_webassembly_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")
    # See `_mock_windows_image` for why the in-container mpy-cross build
    # is stubbed out here too (record 0044).
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_webassembly(
            wasm_opts(build_dir=tmp_path / "build-wasm"), tmp_path / "mpy"
        )


def test_webassembly_no_docker_daemon_raises_clear_error(monkeypatch, tmp_path):
    # Docker-only means "docker unavailable" is a hard, clearly-worded
    # error, not a silent bare-host fallback -- the user's own call.
    monkeypatch.setenv("CIBMP_WEBASSEMBLY_DOCKER_IMAGE", "cibuildmp-webassembly:local")
    # See `_mock_windows_image` for why the in-container mpy-cross build
    # is stubbed out here too (record 0044).
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)

    with pytest.raises(UsermodBuildError, match="docker CLI itself is not on PATH"):
        build_webassembly(
            wasm_opts(build_dir=tmp_path / "build-wasm"), tmp_path / "mpy"
        )
