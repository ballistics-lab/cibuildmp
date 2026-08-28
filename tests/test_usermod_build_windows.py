from pathlib import Path

import pytest

from cibuildmp.platforms.usermod.build_common import UsermodBuildError
from cibuildmp.platforms.usermod.build_windows import (
    WINDOWS_ARCH_SETTINGS,
    WindowsBuildOptions,
    build_windows,
    verify_windows_output,
    windows_make_command,
)


def _pe(machine: int, *, pe_offset: int = 0x80) -> bytes:
    """The smallest byte string `verify_windows_output()` will accept.

    A two-byte `b"MZ"` used to be enough for the windows build tests,
    because `build_windows()` checked only that the file existed. It
    checks the COFF `Machine` now, so a stub has to carry a real DOS
    stub, a real `e_lfanew`, a real `PE\0\0` and a real machine value --
    which is the point: the stub that used to pass is exactly the shape
    of output the check exists to reject.
    """
    data = bytearray(pe_offset + 6)
    data[:2] = b"MZ"
    data[0x3C:0x40] = pe_offset.to_bytes(4, "little")
    data[pe_offset : pe_offset + 4] = b"PE\0\0"
    data[pe_offset + 4 : pe_offset + 6] = machine.to_bytes(2, "little")
    return bytes(data)


def windows_opts(**overrides) -> WindowsBuildOptions:
    defaults = {
        "arch": "win_amd64",
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        "build_dir": Path("/gh/ws/usermod/build/windows-win_amd64"),
    }
    defaults.update(overrides)
    return WindowsBuildOptions(**defaults)


def test_windows_win_amd64_command_matches_upstream_cross_build_shape():
    # tools/ci.sh's own ci_windows_build: CROSS_COMPILE=x86_64-w64-mingw32-,
    # no MSYS2-specific overrides (STRIP/SIZE/COMPILER_TARGET) -- a plain
    # GNU mingw-w64 cross-gcc needs none of them.
    command = windows_make_command(windows_opts(arch="win_amd64"), Path("/gh/ws/mpy"))

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/windows",
        "VARIANT=standard",
        "BUILD=/gh/ws/usermod/build/windows-win_amd64",
        "CROSS_COMPILE=x86_64-w64-mingw32-",
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


def test_windows_win32_command_uses_i686_prefix():
    command = windows_make_command(windows_opts(arch="win32"), Path("/gh/ws/mpy"))

    assert "CROSS_COMPILE=i686-w64-mingw32-" in command


def test_windows_unknown_arch_rejected(tmp_path):
    with pytest.raises(UsermodBuildError, match="unknown windows arch"):
        build_windows(windows_opts(arch="riscv64"), tmp_path / "mpy")


# ── windows/win_arm64 (llvm-mingw) ───────────────────────────────────────


def test_windows_win_arm64_command_matches_verified_shape():
    # Verified live: COMPILER_TARGET=/STRIP=/SIZE= and the three
    # CFLAGS_EXTRA suppressions are load-bearing (see
    # WINDOWS_ARCH_SETTINGS' own comments for exactly why), not
    # cosmetic.
    command = windows_make_command(
        windows_opts(
            arch="win_arm64",
            build_dir=Path("/gh/ws/usermod/build/windows-win_arm64"),
        ),
        Path("/gh/ws/mpy"),
    )

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/windows",
        "VARIANT=standard",
        "BUILD=/gh/ws/usermod/build/windows-win_arm64",
        "CROSS_COMPILE=aarch64-w64-mingw32-",
        "COMPILER_TARGET=mingw-forced",
        "STRIP=",
        "SIZE=true",
        (
            "CFLAGS_EXTRA=-Wno-double-promotion -Wno-uninitialized "
            "-Wno-default-const-init-var-unsafe"
        ),
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


_FAKE_WINDOWS_IMAGE = "cibuildmp-windows:local"


def _mock_windows_image(monkeypatch, image=_FAKE_WINDOWS_IMAGE):
    """Docker-only (D30/D32), same helper shape `_mock_unix_image` has
    and for the same reason: build_windows() has no bare-host path left
    at all, so every real build path needs ensure_image() to resolve
    something first. Tests that only care about the make command shape
    fake a resolved image here and mock dockerrun's own subprocess.run
    -- build_windows.subprocess is no longer called by this port under
    any circumstance.

    Also stubs the in-container mpy-cross build (record 0044): this
    port's image is amd64, so on an arm64 host a host-built mpy-cross
    could not run inside it, and `py/mkrules.mk` runs mpy-cross in the
    container to compile FROZEN_MANIFEST. It is a second real container
    and has its own live coverage; these cases are about the make
    command's own shape."""
    monkeypatch.setattr("cibuildmp.dockerrun.ensure_image", lambda *a, **k: image)
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )


@pytest.mark.parametrize("arch", ["win_amd64", "win32", "win_arm64"])
def test_windows_no_image_registered_is_a_clear_error(monkeypatch, tmp_path, arch):
    # D32's own closing gap: `windows` used to have pinned entries
    # nothing ever read. All three arches now resolve through
    # ensure_image(), so with no override and nothing registered they
    # must fail loudly rather than quietly cross-compiling on the host.
    monkeypatch.setattr("cibuildmp.dockerrun.ensure_image", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_windows(
            windows_opts(arch=arch, build_dir=tmp_path / f"build-{arch}"),
            tmp_path / "mpy",
        )

    assert calls == []


@pytest.mark.parametrize("arch", ["win_amd64", "win32", "win_arm64"])
def test_windows_runs_make_inside_the_container(monkeypatch, tmp_path, arch):
    # Every arch, arm64 included: the llvm-mingw toolchain arm64 needs is
    # baked into docker/windows.Dockerfile now, so there is no host-side
    # resolve step and nothing to inject into the environment -- the
    # image's own ENV PATH covers it.
    _mock_windows_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )

    build_dir = tmp_path / f"build-{arch}"
    build_dir.mkdir()
    # This arch's own machine value, not a fixed one: build_windows()
    # verifies the COFF header now, so a stub that is right for x64 and
    # wrong for the other two would fail two thirds of this parametrize.
    (build_dir / "micropython.exe").write_bytes(
        _pe(WINDOWS_ARCH_SETTINGS[arch].machine)
    )

    result = build_windows(
        windows_opts(arch=arch, build_dir=build_dir), tmp_path / "mpy"
    )

    assert result == build_dir / "micropython.exe"
    assert len(calls) == 1
    docker_command = calls[0]
    assert docker_command[0] == "docker"
    assert _FAKE_WINDOWS_IMAGE in docker_command
    # The make command is passed through unchanged, at the same absolute
    # paths -- dockerrun mounts them identically inside (D26).
    assert "make" in docker_command
    assert f"CROSS_COMPILE={WINDOWS_ARCH_SETTINGS[arch].cross_compile}" in (
        docker_command
    )


def test_windows_mounts_mpy_dir_and_user_c_modules(monkeypatch, tmp_path):
    _mock_windows_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )

    build_dir = tmp_path / "build-x86_64"
    build_dir.mkdir()
    (build_dir / "micropython.exe").write_bytes(_pe(0x8664))

    opts_ = windows_opts(arch="win_amd64", build_dir=build_dir)
    build_windows(opts_, tmp_path / "mpy")

    mounts = [calls[0][i + 1] for i, part in enumerate(calls[0]) if part == "-v"]
    mpy = (tmp_path / "mpy").as_posix()
    assert f"{mpy}:{mpy}" in mounts
    assert any(opts_.user_c_modules in m for m in mounts)


def test_windows_missing_exe_after_success_is_an_error(monkeypatch, tmp_path):
    _mock_windows_image(monkeypatch)
    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", lambda *a, **k: None)
    build_dir = tmp_path / "build-arm64"
    build_dir.mkdir()

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_windows(
            windows_opts(arch="win_arm64", build_dir=build_dir), tmp_path / "mpy"
        )


def test_windows_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    _mock_windows_image(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_windows(
            windows_opts(arch="win_arm64", build_dir=tmp_path / "build-arm64"),
            tmp_path / "mpy",
        )


# ── verify_windows_output() -- the check windows did not have ───────────


@pytest.mark.parametrize(
    ("arch", "machine"),
    [("win_amd64", 0x8664), ("win32", 0x014C), ("win_arm64", 0xAA64)],
)
def test_each_windows_arch_accepts_its_own_machine(arch, machine, tmp_path):
    binary = tmp_path / "micropython.exe"
    binary.write_bytes(_pe(machine))

    verify_windows_output(arch, binary)


def test_another_arch_machine_is_rejected(tmp_path):
    # The whole point: `make` and `ld` both succeed when CROSS_COMPILE
    # names another architecture's toolchain, so the failure this catches
    # does not look like a failure anywhere else.
    binary = tmp_path / "micropython.exe"
    binary.write_bytes(_pe(0x8664))

    with pytest.raises(UsermodBuildError, match="0x8664, expected 0xaa64"):
        verify_windows_output("win_arm64", binary)


def test_an_elf_named_exe_is_rejected(tmp_path):
    # A `CROSS_COMPILE=` that resolved to the host's own gcc produces
    # exactly this, and `binary.exists()` -- the only check windows had
    # before -- passes it.
    binary = tmp_path / "micropython.exe"
    binary.write_bytes(b"\x7fELF" + bytes(0x100))

    with pytest.raises(UsermodBuildError, match="not a PE executable at all"):
        verify_windows_output("win_amd64", binary)


def test_a_dos_header_pointing_nowhere_is_rejected(tmp_path):
    binary = tmp_path / "micropython.exe"
    data = bytearray(_pe(0x8664))
    data[0x3C:0x40] = (0x7000).to_bytes(4, "little")
    binary.write_bytes(bytes(data))

    with pytest.raises(UsermodBuildError, match="no PE signature"):
        verify_windows_output("win_amd64", binary)


def test_every_windows_arch_declares_a_machine():
    # A settings entry added without one would default to 0 and reject
    # every real binary, which is a worse failure than no check at all.
    for arch, settings in WINDOWS_ARCH_SETTINGS.items():
        assert settings.machine, arch
