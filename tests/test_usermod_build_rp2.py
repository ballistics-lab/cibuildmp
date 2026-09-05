import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from cibuildmp.platforms.usermod.build_common import UsermodBuildError
from cibuildmp.platforms.usermod.build_rp2 import (
    Rp2BuildOptions,
    _rp2_project_mounts,
    rp2_make_command,
)
from cibuildmp.platforms.usermod.build_rp2 import build_rp2 as _build_rp2


def build_rp2_fn(*args, staging=None, **kwargs):
    """`build_rp2()` with a staging directory supplied.

    Record 0095 made `staging` part of the contract -- the build tree lives
    inside the container's own overlay now, so there is no host path to
    read a result from, and the artifact is copied into this directory
    instead. `orchestrate.build_one()` supplies it in production; a test
    that does not care where it lands gets a throwaway one, and a test that
    does passes its own -- same shape as `test_usermod_build_unix.py`'s own
    `build_unix_fn()`.
    """
    if staging is None:
        staging = Path(tempfile.mkdtemp(prefix="cibmp-test-staging-"))
    return _build_rp2(*args, staging=staging, **kwargs)


def rp2_opts(**overrides) -> Rp2BuildOptions:
    defaults = {
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        # A real tag with a real, pinned toolchain_version -- since
        # [0087], build_rp2() needs one to resolve which cross compiler
        # to fetch (targets.rp2_toolchain()).
        "tag": "v1.29.0",
    }
    defaults.update(overrides)
    return Rp2BuildOptions(**defaults)


def test_rp2_project_mounts_omits_user_c_modules_when_empty():
    assert _rp2_project_mounts(rp2_opts(user_c_modules=""), None) == []


def test_rp2_project_mounts_includes_user_c_modules_parent_when_set():
    assert _rp2_project_mounts(
        rp2_opts(user_c_modules="/gh/ws/mymod/micropython.cmake"), None
    ) == [Path("/gh/ws/mymod")]


def _fake_docker_run(cmd, **kwargs):
    """A `dockerrun.subprocess.run` stand-in, the same one
    `test_usermod_build_unix.py` uses. Since record 0095 the build runs
    inside one long-lived container, so this also stands in for the one
    step that used to happen implicitly on a bind mount: the `cp` of the
    finished `firmware.uf2` into `staging`. Without it the artifact would
    exist nowhere a host-side check could read, which is exactly the real
    behaviour -- the container is the only place it lives until that copy.
    """
    if cmd[:2] == ["docker", "exec"] and "cp" in cmd:
        source, dest = (Path(p) for p in cmd[cmd.index("cp") + 1 :][:2])
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            shutil.copy(source, dest)
    if kwargs.get("capture_output"):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return None


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
    # `rp2`'s own OCI platform is the fixed `linux/amd64` ([0043] does not
    # apply -- there is no per-target axis here), but the *test* host's own
    # architecture is not fixed the same way, and a mismatch would make
    # `Container.__enter__` run a real `_probe_platform()` -- a real
    # `docker run --pull missing`. Stubbed the same way
    # `test_usermod_build_unix.py` stubs it for its own non-native cells.
    monkeypatch.setattr("cibuildmp.dockerrun._probe_platform", lambda *a, **k: "")


def test_rp2_no_docker_image_raises_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv("CIBMP_RP2_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr("cibuildmp.dockerrun._pins", lambda: {"image_group": {}})

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_rp2_fn(rp2_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")

    assert calls == []


def test_rp2_no_tag_raises_a_clear_error_before_touching_docker(monkeypatch, tmp_path):
    # [0087]: with the image no longer baking a cross compiler, a real
    # tag is required to resolve which one to fetch -- this must fail
    # before ever calling `dockerrun.ensure_image()`/`docker`, the same
    # "fail fast, by name" discipline `dockerrun.run()`'s own timeout
    # handling already follows.
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="real MicroPython tag"):
        build_rp2_fn(
            rp2_opts(tag=""), tmp_path / "mpy", toolchain_root=tmp_path / "cache"
        )

    assert calls == []


def test_rp2_no_staging_is_a_clear_error(monkeypatch, tmp_path):
    """Unlike the other four checks above, this one needs a real image
    resolved first (`build_rp2()` only reaches the staging check after
    `ensure_image()` succeeds) but must still fail before any container is
    created -- `_build_rp2()` directly, bypassing `build_rp2_fn()`'s own
    default staging directory."""
    _mock_rp2_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="staging directory"):
        _build_rp2(rp2_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")

    assert calls == []


def test_rp2_missing_firmware_after_success_is_an_error(monkeypatch, tmp_path):
    _mock_rp2_image(monkeypatch)
    (tmp_path / "mpy" / "ports" / "rp2").mkdir(parents=True)

    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: _fake_docker_run(cmd, **k),
    )

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_rp2_fn(rp2_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")


def test_rp2_builds_and_returns_firmware_path(monkeypatch, tmp_path):
    _mock_rp2_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "rp2" / "build-PICO"
    build_dir.mkdir(parents=True)
    (build_dir / "firmware.uf2").write_bytes(b"uf2")

    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: _fake_docker_run(cmd, **k),
    )

    staging = tmp_path / "staging"
    result = build_rp2_fn(
        rp2_opts(),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "cache",
        staging=staging,
    )

    assert result == staging / "firmware.uf2"
    assert result.read_bytes() == b"uf2"


def test_rp2_fetches_its_own_toolchain_and_puts_it_on_path(monkeypatch, tmp_path):
    # [0086]/[0087]: the cross compiler is no longer baked into the
    # image -- build_rp2() must fetch it at container time and prepend
    # it onto PATH, mounting the cache directory it lands in -- a real,
    # persistent read-write host mount, not part of the checkout's own
    # overlay ([0095]: fetched toolchains are category-A input, meant to
    # survive across runs, unlike the ephemeral build tree).
    _mock_rp2_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "rp2" / "build-PICO"
    build_dir.mkdir(parents=True)
    (build_dir / "firmware.uf2").write_bytes(b"uf2")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    toolchain_root = tmp_path / "cache"
    mpy_dir = tmp_path / "mpy"
    build_rp2_fn(rp2_opts(), mpy_dir, toolchain_root=toolchain_root)

    create = next(c for c in calls if c[:2] == ["docker", "create"])
    expected_dir = (
        toolchain_root / "toolchains" / "arm-none-eabi-" / "cross" / "15.2.1-1.1"
    )
    assert expected_dir.parent.is_dir()  # created host-side before the container ran
    # `.parent`, not `expected_dir` itself -- see build_rp2()'s own
    # comment: mounting the not-yet-existing leaf would leave Docker to
    # synthesize its own path up to it, root-owned, inside the container.
    mount = f"{expected_dir.parent.as_posix()}:{expected_dir.parent.as_posix()}"
    assert mount in create
    # The checkout itself arrives as a read-only overlay lower, out of the
    # way, not at its own host path -- record 0095's own addendum 2.
    assert f"{mpy_dir}:/cibuildmp-lower-1:ro" in create
    assert f"{mpy_dir}:{mpy_dir}" not in create

    script_call = next(
        c for c in calls if "BOARD=PICO" in " ".join(str(part) for part in c)
    )
    script = script_call[-1]
    assert f'export PATH="{(expected_dir / "bin").as_posix()}:$PATH"' in script
    # The fetch now runs as its own container.call() ahead of the make
    # script -- see build_rp2()'s own comment: probe_supported_cflags()
    # needs the real cross compiler already fetched to disk, by full
    # path, before it can probe against it. So the tarball URL lives in a
    # separate call now, not inside the "BOARD=PICO" script itself.
    assert any(
        "xpack-arm-none-eabi-gcc-15.2.1-1.1-linux-x64.tar.gz" in " ".join(
            str(part) for part in c
        )
        for c in calls
    )


def test_rp2_extra_cmake_args_reach_the_container_as_cmake_args(monkeypatch, tmp_path):
    # Not a make command-line token (unlike extra_make_args): ported
    # through the container's own environment instead, since
    # ports/rp2/Makefile builds CMAKE_ARGS with a plain `+=` that a
    # command-line assignment would replace rather than add to -- see
    # build_common.cmake_extra_args_env()'s own docstring.
    _mock_rp2_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "rp2" / "build-PICO"
    build_dir.mkdir(parents=True)
    (build_dir / "firmware.uf2").write_bytes(b"uf2")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    build_rp2_fn(
        rp2_opts(extra_cmake_args=("-DMICROPY_C_HEAP_SIZE=131072",)),
        tmp_path / "mpy",
        toolchain_root=tmp_path / "cache",
    )

    script_call = next(
        c for c in calls if "BOARD=PICO" in " ".join(str(part) for part in c)
    )
    assert "CMAKE_ARGS=-DMICROPY_C_HEAP_SIZE=131072" in script_call


def test_rp2_no_extra_cmake_args_means_no_cmake_args_env(monkeypatch, tmp_path):
    _mock_rp2_image(monkeypatch)
    build_dir = tmp_path / "mpy" / "ports" / "rp2" / "build-PICO"
    build_dir.mkdir(parents=True)
    (build_dir / "firmware.uf2").write_bytes(b"uf2")

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    build_rp2_fn(rp2_opts(), tmp_path / "mpy", toolchain_root=tmp_path / "cache")

    script_call = next(
        c for c in calls if "BOARD=PICO" in " ".join(str(part) for part in c)
    )
    assert not any(arg.startswith("CMAKE_ARGS=") for arg in script_call)
