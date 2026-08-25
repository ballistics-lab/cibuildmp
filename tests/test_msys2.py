from pathlib import Path

import pytest

from cibuildmp.usermod import msys2
from cibuildmp.usermod.msys2 import (
    Msys2Error,
    ResolvedMsys2,
    find_msys2,
    install_msys2,
    resolve_msys2,
)


def test_find_msys2_present(tmp_path):
    root = tmp_path / "msys64"
    (root / "usr" / "bin").mkdir(parents=True)
    (root / "usr" / "bin" / "bash.exe").write_bytes(b"")

    assert find_msys2(root) == root


def test_find_msys2_absent(tmp_path):
    assert find_msys2(tmp_path / "msys64") is None


def test_install_msys2_downloads_verifies_and_extracts(tmp_path, monkeypatch):
    calls = []

    def fake_download(url, dest, *, quiet=False):
        calls.append(("download", url, dest))
        dest.write_bytes(b"fake-installer")

    def fake_verify(path, checksum):
        calls.append(("verify", path, checksum))

    def fake_run(command, **kwargs):
        calls.append(("run", command))
        # The real installer self-extracts a msys64/ dir next to itself.
        (Path(kwargs["cwd"]) / "msys64").mkdir()

    monkeypatch.setattr(msys2, "download_file", fake_download)
    monkeypatch.setattr(msys2, "verify_sha256", fake_verify)
    monkeypatch.setattr(msys2.subprocess, "run", fake_run)

    result = install_msys2(root=tmp_path, quiet=True)

    assert result == tmp_path / "msys2" / msys2.INSTALLER_VERSION
    assert result.exists()
    kinds = [c[0] for c in calls]
    assert kinds == ["download", "verify", "run"]
    assert calls[0][1] == msys2.INSTALLER_URL
    assert calls[1][2] == msys2.INSTALLER_CHECKSUM
    assert calls[2][1][-1] == "-y"

    # Second call is a cache hit -- no further download/install.
    install_msys2(root=tmp_path, quiet=True)
    assert len(calls) == 3


def test_install_msys2_failure_raises(tmp_path, monkeypatch):
    import subprocess as sp

    monkeypatch.setattr(
        msys2, "download_file", lambda url, dest, **k: dest.write_bytes(b"")
    )
    monkeypatch.setattr(msys2, "verify_sha256", lambda path, checksum: None)

    def fake_run(command, **kwargs):
        raise sp.CalledProcessError(1, command)

    monkeypatch.setattr(msys2.subprocess, "run", fake_run)

    with pytest.raises(Msys2Error, match="MSYS2 installer failed"):
        install_msys2(root=tmp_path, quiet=True)


def test_resolve_msys2_prefers_pre_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(msys2, "find_msys2", lambda: tmp_path / "preinstalled")

    def boom(**kwargs):
        raise AssertionError("install_msys2 must not run when find_msys2() hits")

    monkeypatch.setattr(msys2, "install_msys2", boom)

    assert resolve_msys2(quiet=True) == tmp_path / "preinstalled"


def test_resolve_msys2_falls_back_to_install(tmp_path, monkeypatch):
    monkeypatch.setattr(msys2, "find_msys2", lambda: None)
    monkeypatch.setattr(msys2, "install_msys2", lambda **k: tmp_path / "fresh")

    assert resolve_msys2(root=tmp_path, quiet=True) == tmp_path / "fresh"


# ── ResolvedMsys2 ────────────────────────────────────────────────────────


def test_run_invokes_bash_login_shell_with_msystem(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(msys2.subprocess, "run", fake_run)
    session = ResolvedMsys2(root=tmp_path, msystem="MINGW64")
    session.run("make -C /d/a/mpy/ports/windows")

    (command, kwargs) = calls[0]
    assert command == [
        str(tmp_path / "usr" / "bin" / "bash.exe"),
        "-leo",
        "pipefail",
        "-c",
        "make -C /d/a/mpy/ports/windows",
    ]
    assert kwargs["env"]["MSYSTEM"] == "MINGW64"
    assert kwargs["env"]["CHERE_INVOKING"] == "1"


def test_run_failure_wraps_in_msys2_error(tmp_path, monkeypatch):
    import subprocess as sp

    def fake_run(command, **kwargs):
        raise sp.CalledProcessError(1, command)

    monkeypatch.setattr(msys2.subprocess, "run", fake_run)
    session = ResolvedMsys2(root=tmp_path, msystem="MINGW64")

    with pytest.raises(Msys2Error, match="msys2 command failed"):
        session.run("false")


def test_install_packages_runs_pacman_needed_noconfirm(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        ResolvedMsys2, "run", lambda self, command, **k: calls.append(command)
    )
    session = ResolvedMsys2(root=tmp_path, msystem="MINGW64")

    session.install_packages(["make", "git", "mingw-w64-x86_64-gcc"])

    assert calls == ["pacman -S --needed --noconfirm make git mingw-w64-x86_64-gcc"]


def test_to_posix_path_runs_cygpath_u(tmp_path, monkeypatch):
    class FakeCompleted:
        stdout = "/d/a/mpy\n"

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return FakeCompleted()

    monkeypatch.setattr(msys2.subprocess, "run", fake_run)
    session = ResolvedMsys2(root=tmp_path, msystem="MINGW64")

    result = session.to_posix_path("D:\\a\\mpy")

    assert result == "/d/a/mpy"
    (command, kwargs) = calls[0]
    assert command == [
        str(tmp_path / "usr" / "bin" / "bash.exe"),
        "-lc",
        'cygpath -u "D:\\a\\mpy"',
    ]
    assert kwargs["env"]["MSYSTEM"] == "MINGW64"


def test_to_posix_path_failure_raises(tmp_path, monkeypatch):
    import subprocess as sp

    def fake_run(command, **kwargs):
        raise sp.CalledProcessError(1, command)

    monkeypatch.setattr(msys2.subprocess, "run", fake_run)
    session = ResolvedMsys2(root=tmp_path, msystem="MINGW64")

    with pytest.raises(Msys2Error, match="cygpath -u"):
        session.to_posix_path("D:\\a\\mpy")
