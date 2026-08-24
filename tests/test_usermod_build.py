from pathlib import Path

import pytest

from cibuildmp.usermod import build
from cibuildmp.usermod.build import (
    UNIX_ARCH_SETTINGS,
    UnixBuildOptions,
    UsermodBuildError,
    build_unix,
    run_unix_deplibs,
    unix_make_command,
)


def opts(arch: str = "x64", **overrides) -> UnixBuildOptions:
    defaults = {
        "arch": arch,
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        "build_dir": Path("/gh/ws/usermod/build/x64"),
    }
    defaults.update(overrides)
    return UnixBuildOptions(**defaults)


def test_x64_command_matches_a7p_workflow_shape():
    # build-usermod-unix's own "Build usermod (x64)" step, x64 has no
    # CROSS_COMPILE and no link_opts.
    command = unix_make_command(opts("x64"), Path("/gh/ws/mpy"))

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/unix",
        "VARIANT=standard",
        "BUILD=/gh/ws/usermod/build/x64",
        "CROSS_COMPILE=",
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


def test_x86_command_adds_force_32bit():
    command = unix_make_command(opts("x86"), Path("/gh/ws/mpy"))

    assert "MICROPY_FORCE_32BIT=1" in command


def test_armhf_command_adds_standalone_and_static_link():
    command = unix_make_command(opts("armhf"), Path("/gh/ws/mpy"))

    assert "CROSS_COMPILE=arm-linux-gnueabihf-" in command
    assert "MICROPY_STANDALONE=1" in command
    assert "LDFLAGS_EXTRA=-static" in command


def test_deplibs_command_shape(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

    monkeypatch.setattr(build.subprocess, "run", fake_run)
    run_unix_deplibs(opts("armhf"), Path("/gh/ws/mpy"))

    assert calls[0][-1] == "deplibs"
    assert "MICROPY_STANDALONE=1" in calls[0]


def test_all_five_archs_have_settings():
    assert set(UNIX_ARCH_SETTINGS) == {"x64", "x86", "aarch64", "armhf", "mipsel"}


def test_unknown_arch_rejected():
    with pytest.raises(UsermodBuildError, match="unknown unix arch"):
        build_unix(opts("riscv64"), Path("/gh/ws/mpy"))


@pytest.mark.parametrize("arch", ["armhf", "mipsel"])
def test_armhf_mipsel_not_runnable_yet(arch):
    with pytest.raises(UsermodBuildError, match="not buildable yet"):
        build_unix(opts(arch), Path("/gh/ws/mpy"))


def test_x64_builds_and_returns_binary_path(tmp_path, monkeypatch):
    build_dir = tmp_path / "build-x64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(b"\x7fELF")

    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)
    result = build_unix(opts("x64", build_dir=build_dir), tmp_path / "mpy")

    assert result == build_dir / "micropython"


def test_missing_binary_after_success_is_an_error(tmp_path, monkeypatch):
    build_dir = tmp_path / "build-x64"
    build_dir.mkdir()

    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)
    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_unix(opts("x64", build_dir=build_dir), tmp_path / "mpy")


def test_build_failure_names_the_command(tmp_path, monkeypatch):
    import subprocess as sp

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr(build.subprocess, "run", fake_run)
    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_unix(opts("x64", build_dir=tmp_path / "build-x64"), tmp_path / "mpy")


def test_x86_probes_toolchain_before_building(tmp_path, monkeypatch):
    """x86 must reuse toolchains.resolve("x86"), natmod's own -m32 probe --
    not re-implement multilib detection here."""
    calls = []
    monkeypatch.setattr(
        build.toolchains, "resolve", lambda arch, **k: calls.append(arch)
    )
    build_dir = tmp_path / "build-x86"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(b"\x7fELF")
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: None)

    build_unix(opts("x86", build_dir=build_dir), tmp_path / "mpy")

    assert calls == ["x86"]


def test_x86_toolchain_error_propagates_unwrapped(tmp_path, monkeypatch):
    from cibuildmp.toolchains import ToolchainError

    def boom(arch, **k):
        raise ToolchainError("x86 needs gcc-multilib")

    monkeypatch.setattr(build.toolchains, "resolve", boom)
    with pytest.raises(ToolchainError, match="gcc-multilib"):
        build_unix(opts("x86", build_dir=tmp_path / "build-x86"), tmp_path / "mpy")
