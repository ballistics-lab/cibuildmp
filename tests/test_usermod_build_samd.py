import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from cibuildmp.platforms.usermod.build_common import UsermodBuildError
from cibuildmp.platforms.usermod.build_samd import (
    SamdBuildOptions,
    _samd_project_mounts,
    samd_make_command,
)
from cibuildmp.platforms.usermod.build_samd import build_samd as _build_samd


def build_samd_fn(*args, staging=None, **kwargs):
    """`build_samd()` with a staging directory supplied -- same shape as
    `test_usermod_build_rp2.py`'s own `build_rp2_fn()` (record 0095:
    the build tree lives in the container's own overlay, so the artifact
    is handed back through a `staging` copy, not a host path read)."""
    if staging is None:
        staging = Path(tempfile.mkdtemp(prefix="cibmp-test-staging-"))
    return _build_samd(*args, staging=staging, **kwargs)


def samd_opts(**overrides) -> SamdBuildOptions:
    defaults = {
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        # A real tag with a real, pinned toolchain_version -- build_samd()
        # needs one to resolve which cross compiler to fetch
        # (targets.samd_toolchain()).
        "tag": "v1.29.0",
    }
    defaults.update(overrides)
    return SamdBuildOptions(**defaults)


def test_samd_project_mounts_omits_user_c_modules_when_empty():
    assert _samd_project_mounts(samd_opts(user_c_modules=""), None) == []


def test_samd_project_mounts_includes_user_c_modules_itself_when_set():
    # Unlike rp2/esp32 (cmake ports, mount the *parent* since
    # USER_C_MODULES gets a `/micropython.cmake` suffix appended), samd is
    # a plain Make port -- the mount is the module directory itself.
    assert _samd_project_mounts(samd_opts(user_c_modules="/gh/ws/mymod"), None) == [
        Path("/gh/ws/mymod")
    ]


def _fake_docker_run(cmd, **kwargs):
    """A `dockerrun.subprocess.run` stand-in, same one
    `test_usermod_build_rp2.py`/`test_usermod_build_unix.py` use -- stands
    in for the `cp` of the finished `firmware.uf2` into `staging`."""
    if cmd[:2] == ["docker", "exec"] and "cp" in cmd:
        source, dest = (Path(p) for p in cmd[cmd.index("cp") + 1 :][:2])
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            shutil.copy(source, dest)
    if kwargs.get("capture_output"):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return None


def test_samd_command_shape():
    command = samd_make_command(
        samd_opts(), Path("/gh/ws/mpy"), Path("/gh/ws/mpy/ports/samd/build-SEEED")
    )

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/samd",
        f"-j{os.cpu_count() or 1}",
        "BOARD=SEEED_XIAO_SAMD21",
        "BUILD=/gh/ws/mpy/ports/samd/build-SEEED",
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


def test_samd_command_carries_mpy_cross_when_given():
    command = samd_make_command(
        samd_opts(),
        Path("/gh/ws/mpy"),
        Path("/gh/ws/mpy/ports/samd/build-SEEED"),
        mpy_cross=Path("/gh/ws/mpy-cross"),
    )

    assert "MICROPY_MPYCROSS=/gh/ws/mpy-cross" in command


def test_samd_command_carries_extra_make_args():
    command = samd_make_command(
        samd_opts(extra_make_args=("V=1",)),
        Path("/gh/ws/mpy"),
        Path("/gh/ws/mpy/ports/samd/build-SEEED"),
    )

    assert command[-1] == "V=1"


def test_samd_command_uses_probed_cflags_not_raw_candidates():
    # samd_make_command()'s own extra_cflags override -- the fix for the
    # live-caught bug record 0100 documents: an empty probed tuple must
    # win over tag_cflags()'s own raw (and, for this tag, gcc-15-only)
    # candidate list, not get ignored.
    command = samd_make_command(
        samd_opts(tag="v1.20.0"),
        Path("/gh/ws/mpy"),
        Path("/gh/ws/mpy/ports/samd/build-SEEED"),
        extra_cflags=(),
    )

    assert not any(arg.startswith("CFLAGS_EXTRA=") for arg in command)


def _mock_samd_image(monkeypatch, image="cibuildmp-samd:local"):
    monkeypatch.setenv("CIBMP_SAMD_DOCKER_IMAGE", image)
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    # Same reasoning as _mock_rp2_image(): samd's own OCI platform is the
    # fixed `linux/amd64` embedded_base image, but the *test* host's own
    # architecture is not, and a mismatch would make `Container.__enter__`
    # run a real `_probe_platform()` (a real `docker run --pull missing`).
    monkeypatch.setattr("cibuildmp.dockerrun._probe_platform", lambda *a, **k: "")


def test_samd_no_docker_image_raises_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv("CIBMP_SAMD_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr("cibuildmp.dockerrun._pins", lambda: {"image_group": {}})

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_samd_fn(samd_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")

    assert calls == []


def test_samd_no_tag_raises_a_clear_error_before_touching_docker(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="real MicroPython tag"):
        build_samd_fn(
            samd_opts(tag=""), tmp_path / "mpy", toolchain_root=tmp_path / "cache"
        )

    assert calls == []


def test_samd_no_staging_is_a_clear_error(monkeypatch, tmp_path):
    """Needs a real image resolved first (`build_samd()` only reaches the
    staging check after `ensure_image()` succeeds) but must still fail
    before any container is created -- `_build_samd()` directly, bypassing
    `build_samd_fn()`'s own default staging directory."""
    _mock_samd_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="staging directory"):
        _build_samd(samd_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")

    assert calls == []


def test_samd_missing_firmware_after_success_is_an_error(monkeypatch, tmp_path):
    _mock_samd_image(monkeypatch)
    (tmp_path / "mpy" / "ports" / "samd").mkdir(parents=True)

    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: _fake_docker_run(cmd, **k),
    )

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_samd_fn(samd_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")


def test_samd_builds_and_returns_firmware_path(monkeypatch, tmp_path):
    _mock_samd_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "samd" / "build-SEEED_XIAO_SAMD21"
    build_dir.mkdir(parents=True)
    (build_dir / "firmware.uf2").write_bytes(b"uf2")

    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: _fake_docker_run(cmd, **k),
    )

    staging = tmp_path / "staging"
    result = build_samd_fn(
        samd_opts(),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "cache",
        staging=staging,
    )

    assert result == staging / "firmware.uf2"
    assert result.read_bytes() == b"uf2"


def test_samd_fetches_its_own_toolchain_and_puts_it_on_path(monkeypatch, tmp_path):
    # Same mechanism as build_rp2()'s own equivalent test: the cross
    # compiler is not baked into embedded_base -- build_samd() fetches it
    # at container time and prepends it onto PATH, mounting the cache
    # directory it lands in as a real, persistent read-write host mount.
    _mock_samd_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "samd" / "build-SEEED_XIAO_SAMD21"
    build_dir.mkdir(parents=True)
    (build_dir / "firmware.uf2").write_bytes(b"uf2")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    toolchain_root = tmp_path / "cache"
    mpy_dir = tmp_path / "mpy"
    build_samd_fn(samd_opts(), mpy_dir, toolchain_root=toolchain_root)

    create = next(c for c in calls if c[:2] == ["docker", "create"])
    expected_dir = (
        toolchain_root / "toolchains" / "arm-none-eabi-" / "cross" / "15.2.1-1.1"
    )
    assert expected_dir.parent.is_dir()  # created host-side before the container ran
    mount = f"{expected_dir.parent.as_posix()}:{expected_dir.parent.as_posix()}"
    assert mount in create
    assert f"{mpy_dir}:/cibuildmp-lower-1:ro" in create
    assert f"{mpy_dir}:{mpy_dir}" not in create

    script_call = next(
        c
        for c in calls
        if "BOARD=SEEED_XIAO_SAMD21" in " ".join(str(part) for part in c)
    )
    script = script_call[-1]
    assert f'export PATH="{(expected_dir / "bin").as_posix()}:$PATH"' in script
    # The fetch runs as its own container.call() ahead of the make script
    # -- see build_samd()'s own comment: probe_supported_cflags() needs
    # the real cross compiler already fetched to disk, by full path,
    # before it can probe against it.
    assert any(
        "xpack-arm-none-eabi-gcc-15.2.1-1.1-linux-x64.tar.gz"
        in " ".join(str(part) for part in c)
        for c in calls
    )
