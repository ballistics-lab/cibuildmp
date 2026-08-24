import io
import tarfile
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


def test_read_mpy_abi_incomplete_header(tmp_path):
    with pytest.raises(SourceError, match="MPY_VERSION"):
        read_mpy_abi(fake_checkout(tmp_path, "#define MPY_VERSION 6\n"))


def test_cache_root_honours_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CIBMP_CACHE", str(tmp_path / "c"))
    assert cache_root() == tmp_path / "c"
    monkeypatch.delenv("CIBMP_CACHE")
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

    monkeypatch.setattr(sources, "_download", fake_download)
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
        sources, "_download", lambda url, dest, *, quiet: _tarball(dest)
    )
    mpy_dir = sources.fetch_micropython("v1.28.0", tmp_path, quiet=True)

    assert not (mpy_dir / "junk").exists()
    assert (mpy_dir / STAMP).exists()


def test_failed_fetch_leaves_no_cache_entry(tmp_path, monkeypatch):
    def boom(url, dest, *, quiet):
        raise OSError("network down")

    monkeypatch.setattr(sources, "_download", boom)
    with pytest.raises(OSError, match="network down"):
        sources.fetch_micropython("v1.28.0", tmp_path, quiet=True)

    # Nothing half-built left behind for the next run to trust.
    assert not micropython_dir("v1.28.0", tmp_path).exists()
    assert list((tmp_path / "micropython").iterdir()) == []
