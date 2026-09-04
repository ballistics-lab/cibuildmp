import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from cibuildmp.platforms.usermod.build_common import UsermodBuildError
from cibuildmp.platforms.usermod.build_windows import (
    WINDOWS_ARCH_SETTINGS,
    WindowsBuildOptions,
    verify_windows_output,
    windows_make_command,
)
from cibuildmp.platforms.usermod.build_windows import build_windows as _build_windows


def build_windows_fn(*args, staging=None, **kwargs):
    """`build_windows()` with a staging directory supplied.

    Record 0095 made `staging` part of the contract -- the build tree lives
    inside the container's own overlay now, so there is no host path to
    read a result from, and the artifact is copied into this directory
    instead. Same shape as `test_usermod_build_unix.py`'s own
    `build_unix_fn()`.
    """
    if staging is None:
        staging = Path(tempfile.mkdtemp(prefix="cibmp-test-staging-"))
    return _build_windows(*args, staging=staging, **kwargs)


def _fake_docker_run(cmd, **kwargs):
    """A `dockerrun.subprocess.run` stand-in, the same shape
    `test_usermod_build_unix.py`/`test_usermod_build_rp2.py` use. Since
    record 0095 the build runs inside one long-lived container, so this
    also stands in for the one step that used to happen implicitly on a
    bind mount: the `cp` of the finished `.exe` into `staging`."""
    if cmd[:2] == ["docker", "exec"] and "cp" in cmd:
        source, dest = (Path(p) for p in cmd[cmd.index("cp") + 1 :][:2])
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            shutil.copy(source, dest)
    if kwargs.get("capture_output"):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return None


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
        build_windows_fn(windows_opts(arch="riscv64"), tmp_path / "mpy")


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
    """Docker-only (D30/D32), same helper shape `_mock_unix_image`/
    `_mock_rp2_image` have and for the same reason: build_windows() has no
    bare-host path left at all, so every real build path needs
    ensure_image() to resolve something first.

    Also stubs the in-container mpy-cross build (record 0044): this
    port's image is amd64, so on an arm64 host a host-built mpy-cross
    could not run inside it, and `py/mkrules.mk` runs mpy-cross in the
    container to compile FROZEN_MANIFEST. It is a second real container
    call and has its own live coverage; these cases are about the make
    command's own shape.

    `_probe_platform` is stubbed too, the same way
    `test_usermod_build_rp2.py`'s own `_mock_rp2_image()` stubs it: the
    image's platform is fixed (`linux/amd64`) but the *test* host's own
    architecture is not, and a mismatch would otherwise run a real
    `docker run --pull missing` inside `Container.__enter__`.
    """
    monkeypatch.setattr("cibuildmp.dockerrun.ensure_image", lambda *a, **k: image)
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    monkeypatch.setattr("cibuildmp.dockerrun._probe_platform", lambda *a, **k: "")


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
        build_windows_fn(
            windows_opts(arch=arch, build_dir=tmp_path / f"build-{arch}"),
            tmp_path / "mpy",
        )

    assert calls == []


def test_windows_no_staging_is_a_clear_error(monkeypatch, tmp_path):
    """Needs a real image resolved first (the staging check comes after
    `ensure_image()` succeeds) but must still fail before any container is
    created -- `_build_windows()` directly, bypassing
    `build_windows_fn()`'s own default staging directory."""
    _mock_windows_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or None,
    )

    with pytest.raises(UsermodBuildError, match="staging directory"):
        _build_windows(windows_opts(), tmp_path / "mpy")

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
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    build_dir = tmp_path / f"build-{arch}"
    build_dir.mkdir()
    # This arch's own machine value, not a fixed one: build_windows()
    # verifies the COFF header now, so a stub that is right for x64 and
    # wrong for the other two would fail two thirds of this parametrize.
    (build_dir / "micropython.exe").write_bytes(
        _pe(WINDOWS_ARCH_SETTINGS[arch].machine)
    )

    staging = tmp_path / "staging"
    result = build_windows_fn(
        windows_opts(arch=arch, build_dir=build_dir), tmp_path / "mpy", staging=staging
    )

    assert result == staging / "micropython.exe"
    # Two real `exec`s now, not one: `build_windows()` also probes its
    # own `CFLAGS_EXTRA` candidates against the real cross compiler before
    # the actual build ([0091], the same reason
    # `test_usermod_build_unix.py` sees two calls per build too). The
    # make invocation is the one that actually runs `make`.
    make_calls = [c for c in calls if "make" in c]
    assert len(make_calls) == 1
    exec_command = make_calls[0]
    assert exec_command[:2] == ["docker", "exec"]
    # The make command is passed through unchanged, at the same absolute
    # paths -- `overlay()` mounts the checkout at its own host path.
    assert "make" in exec_command
    assert f"CROSS_COMPILE={WINDOWS_ARCH_SETTINGS[arch].cross_compile}" in (
        exec_command
    )


def test_windows_container_binds_the_checkout_read_only_and_the_project_rw(
    monkeypatch, tmp_path
):
    """Record 0095: the checkout is an overlay lower layer, so it is bound
    **read-only and out of the way** while the writable view goes over its
    own host path; the user's own module tree stays an ordinary read-write
    bind at its own path."""
    _mock_windows_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    build_dir = tmp_path / "build-x86_64"
    build_dir.mkdir()
    (build_dir / "micropython.exe").write_bytes(_pe(0x8664))

    mpy_dir = tmp_path / "mpy"
    staging = tmp_path / "staging"
    opts_ = windows_opts(arch="win_amd64", build_dir=build_dir)
    build_windows_fn(opts_, mpy_dir, staging=staging)

    create = next(c for c in calls if c[:2] == ["docker", "create"])
    assert f"{mpy_dir}:/cibuildmp-lower-1:ro" in create
    assert f"{mpy_dir}:{mpy_dir}" not in create
    assert f"{staging}:{staging}" in create
    assert f"{opts_.user_c_modules}:{opts_.user_c_modules}" in create


def test_windows_missing_exe_after_success_is_an_error(monkeypatch, tmp_path):
    _mock_windows_image(monkeypatch)
    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", _fake_docker_run)
    build_dir = tmp_path / "build-arm64"
    build_dir.mkdir()

    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_windows_fn(
            windows_opts(arch="win_arm64", build_dir=build_dir), tmp_path / "mpy"
        )


def test_windows_build_failure_names_the_command(monkeypatch, tmp_path):
    import subprocess as sp

    _mock_windows_image(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)

    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_windows_fn(
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
