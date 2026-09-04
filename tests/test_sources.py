import io
import subprocess
import tarfile
import urllib.error
from pathlib import Path

import pytest

from cibuildmp import sources
from cibuildmp.sources import (
    STAMP,
    SourceError,
    cache_root,
    micropython_dir,
    read_mpy_abi,
)

HEADER = """\
// comment
#define MPY_VERSION 6
#define MPY_SUB_VERSION 3
#define MPY_FEATURE_ARCH_FLAGS (0x40)
"""


def fake_checkout(root: Path, abi_header: str = HEADER) -> Path:
    (root / "py").mkdir(parents=True, exist_ok=True)
    (root / "py" / "persistentcode.h").write_text(abi_header)
    return root


def test_read_mpy_abi(tmp_path):
    assert read_mpy_abi(fake_checkout(tmp_path)) == "6.3"


def test_read_mpy_abi_missing_header(tmp_path):
    with pytest.raises(SourceError, match="cannot read"):
        read_mpy_abi(tmp_path)


def test_read_mpy_abi_without_sub_version(tmp_path):
    """`MPY_SUB_VERSION` is a `v1.20.0`-and-later define: `py/persistentcode.h`
    carries `MPY_VERSION` alone on every tag before it, and the bare `"5"`/`"6"`
    that yields is a real ABI, not a malformed header (record 0093 -- this test
    asserted the opposite until a `v1.18` build actually reached this code)."""
    assert read_mpy_abi(fake_checkout(tmp_path, "#define MPY_VERSION 6\n")) == "6"
    assert read_mpy_abi(fake_checkout(tmp_path, "#define MPY_VERSION 5\n")) == "5"


def test_read_mpy_abi_incomplete_header(tmp_path):
    with pytest.raises(SourceError, match="MPY_VERSION"):
        read_mpy_abi(fake_checkout(tmp_path, "#define MPY_FEATURE_ARCH_FLAGS (0x40)\n"))


def test_cache_root_honours_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CIBMP_CACHE_PATH", str(tmp_path / "c"))
    assert cache_root() == tmp_path / "c"
    monkeypatch.delenv("CIBMP_CACHE_PATH")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "x"))
    assert cache_root() == tmp_path / "x" / "cibuildmp"


def _tarball(dest: Path, top: str = "micropython-1.28.0") -> None:
    """A minimal stand-in for the 104 MiB release asset."""
    buf = io.BytesIO(HEADER.encode())
    with tarfile.open(dest, "w:xz") as tar:
        info = tarfile.TarInfo(f"{top}/py/persistentcode.h")
        info.size = len(buf.getvalue())
        tar.addfile(info, buf)


def test_fetch_extracts_and_stamps(tmp_path, monkeypatch):
    calls = []

    def fake_download(url, dest, *, quiet):
        calls.append(url)
        _tarball(dest)

    monkeypatch.setattr(sources, "download_file", fake_download)
    mpy_dir = sources.fetch_micropython("v1.28.0", tmp_path, quiet=True)

    assert mpy_dir == micropython_dir("v1.28.0", tmp_path)
    assert (mpy_dir / STAMP).exists()
    assert read_mpy_abi(mpy_dir) == "6.3"
    # The release asset, not the auto-generated archive: only the former
    # vendors lib/ submodules.
    expected = (
        "https://github.com/micropython/micropython/releases/download/"
        "v1.28.0/micropython-1.28.0.tar.xz"
    )
    assert calls == [expected]

    # Second call is a cache hit -- no further download.
    sources.fetch_micropython("v1.28.0", tmp_path, quiet=True)
    assert len(calls) == 1


def test_incomplete_checkout_is_not_reused(tmp_path, monkeypatch):
    # Simulate a run killed mid-extract: the tree exists, the stamp does not.
    stale = micropython_dir("v1.28.0", tmp_path)
    stale.mkdir(parents=True)
    (stale / "junk").write_text("half a tarball")

    monkeypatch.setattr(
        sources, "download_file", lambda url, dest, *, quiet: _tarball(dest)
    )
    mpy_dir = sources.fetch_micropython("v1.28.0", tmp_path, quiet=True)

    assert not (mpy_dir / "junk").exists()
    assert (mpy_dir / STAMP).exists()


def _fake_404(url, dest, *, quiet):
    raise urllib.error.HTTPError(url, 404, "not found", None, None)


def test_clone_path_runs_git_submodule_update_for_raw_paths(tmp_path, monkeypatch):
    """`submodules=` (natmod's own `micropython_submodules` knob, arbitrary
    user-supplied paths) still goes through a plain `git submodule update
    --init`, not any port's own `make submodules` -- natmod is not a port
    and has no such target to delegate to."""
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["git", "clone"]:
            fake_checkout(Path(command[-1]))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(sources, "download_file", _fake_404)
    monkeypatch.setattr(sources.subprocess, "run", fake_run)

    sources.fetch_micropython(
        "v1.30.0-preview", tmp_path, submodules=["lib/berkeley-db-1.xx"], quiet=True
    )

    assert calls[0][:2] == ["git", "clone"]
    assert calls[1] == [
        "git",
        "submodule",
        "update",
        "--init",
        "--depth",
        "1",
        "lib/berkeley-db-1.xx",
    ]


def test_clone_path_runs_each_ports_own_make_submodules(tmp_path, monkeypatch):
    """`ports=` (usermod's) delegates to each named port's own `make
    submodules` target -- the command that port's own README documents --
    rather than this project keeping its own list of submodule paths."""
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["git", "clone"]:
            fake_checkout(Path(command[-1]))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(sources, "download_file", _fake_404)
    monkeypatch.setattr(sources.subprocess, "run", fake_run)

    sources.fetch_micropython(
        "v1.30.0-preview", tmp_path, ports=["unix", "rp2"], quiet=True
    )

    make_calls = [c for c in calls if c[0] == "make"]
    assert len(make_calls) == 2
    assert make_calls[0][:2] == ["make", "-C"]
    assert make_calls[0][-1] == "submodules"
    assert Path(make_calls[0][2]).name == "unix"
    assert Path(make_calls[1][2]).name == "rp2"


def test_clone_path_with_no_submodules_or_ports_runs_only_clone(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["git", "clone"]:
            fake_checkout(Path(command[-1]))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(sources, "download_file", _fake_404)
    monkeypatch.setattr(sources.subprocess, "run", fake_run)

    sources.fetch_micropython("v1.30.0-preview", tmp_path, quiet=True)

    assert len(calls) == 1
    assert calls[0][:2] == ["git", "clone"]


def test_failed_fetch_leaves_no_cache_entry(tmp_path, monkeypatch):
    def boom(url, dest, *, quiet):
        raise OSError("network down")

    monkeypatch.setattr(sources, "download_file", boom)
    with pytest.raises(OSError, match="network down"):
        sources.fetch_micropython("v1.28.0", tmp_path, quiet=True)

    # Nothing half-built left behind for the next run to trust.
    assert not micropython_dir("v1.28.0", tmp_path).exists()
    assert list((tmp_path / "micropython").iterdir()) == []


def test_find_mpy_cross_handles_both_upstream_layouts(tmp_path):
    """`py/mkrules.mk` links `all: $(PROG)` through `v1.19.1` and
    `all: $(BUILD)/$(PROG)` from `v1.20.0` on, with `py/dynruntime.mk`'s own
    hardcoded `MPY_CROSS =` moving in lockstep -- so the built binary is at
    `mpy-cross/mpy-cross` on the nine ABI 5/6 tags and `mpy-cross/build/mpy-cross`
    on everything newer (record 0093)."""
    assert sources.find_mpy_cross(tmp_path) is None

    old = tmp_path / "mpy-cross" / "mpy-cross"
    old.parent.mkdir(parents=True)
    old.touch()
    assert sources.find_mpy_cross(tmp_path) == old

    new = tmp_path / "mpy-cross" / "build" / "mpy-cross"
    new.parent.mkdir(parents=True)
    new.touch()
    # Never both in one checkout; the newer layout wins if a tree ever has both.
    assert sources.find_mpy_cross(tmp_path) == new
