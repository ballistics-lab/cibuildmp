import hashlib
import io
import os
import platform
import tarfile
from pathlib import Path

import pytest

from cibuildmp.usermod import emsdk
from cibuildmp.usermod.emsdk import EmsdkError, ResolvedEmsdk, resolve_emsdk


def _fake_emsdk_tarball(dest: Path) -> None:
    """A minimal stand-in for the ~300 MiB real wasm-binaries.tar.xz:
    just enough structure (install/emscripten/, install/bin/) for
    resolve_emsdk()'s own extraction and PATH assembly to exercise for
    real."""
    with tarfile.open(dest, "w:xz") as tar:
        for name in ("install/emscripten/emcc", "install/bin/clang"):
            buf = io.BytesIO(b"#!/bin/sh\n")
            info = tarfile.TarInfo(name)
            info.size = len(buf.getvalue())
            tar.addfile(info, buf)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(
    platform.system() != "Linux"
    or platform.machine().lower() not in ("x86_64", "amd64"),
    reason="sanity check for this project's own linux-x64 dev/CI host, not a portability claim",
)
def test_host_platform_key_matches_pinned_table():
    assert emsdk._host_platform_key() == "linux-x64"


def test_host_platform_key_rejects_unmapped_os(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(platform, "machine", lambda: "AMD64")
    with pytest.raises(EmsdkError, match="unsupported host for emsdk: Windows/AMD64"):
        emsdk._host_platform_key()


def test_resolve_emsdk_downloads_extracts_and_verifies(tmp_path, monkeypatch):
    calls = []

    def fake_download(url, dest, *, quiet):
        calls.append(url)
        _fake_emsdk_tarball(dest)

    # Compute the fake tarball's real sha256 once, so verify_sha256() --
    # exercised for real, not mocked -- actually passes.
    probe = tmp_path / "probe.tar.xz"
    _fake_emsdk_tarball(probe)
    data = {
        "version": "6.0.8",
        "platform": {
            "fake-host": {
                "hash": "deadbeef",
                "url": "https://example.invalid/wasm-binaries.tar.xz",
                "sha256": _sha256(probe),
            }
        },
    }

    # _host_platform_key() mocked too -- this test must be hermetic to
    # whatever OS/arch actually runs it, not coupled to being linux-x64
    # the way an earlier version of this test was (it failed for real on
    # a windows-latest CI run for exactly this reason).
    monkeypatch.setattr(emsdk, "_host_platform_key", lambda: "fake-host")
    monkeypatch.setattr(emsdk, "usermod_data", lambda: {"emsdk": data})
    monkeypatch.setattr(emsdk, "download_file", fake_download)

    result = resolve_emsdk(root=tmp_path, quiet=True)

    assert calls == ["https://example.invalid/wasm-binaries.tar.xz"]
    assert (result.install_dir / "emscripten" / "emcc").exists()
    assert (result.install_dir / "bin" / "clang").exists()
    # cached_dir() moves populate()'s returned subdir (staging/"install")
    # to become dest itself -- dest is not dest/"install".
    assert result.install_dir == tmp_path / "emsdk" / "6.0.8" / "fake-host"

    # Second call is a cache hit -- no further download.
    resolve_emsdk(root=tmp_path, quiet=True)
    assert len(calls) == 1


def test_resolve_emsdk_rejects_checksum_mismatch(tmp_path, monkeypatch):
    def fake_download(url, dest, *, quiet):
        _fake_emsdk_tarball(dest)

    data = {
        "version": "6.0.8",
        "platform": {
            "fake-host": {
                "hash": "deadbeef",
                "url": "https://example.invalid/wasm-binaries.tar.xz",
                "sha256": "0" * 64,
            }
        },
    }
    monkeypatch.setattr(emsdk, "_host_platform_key", lambda: "fake-host")
    monkeypatch.setattr(emsdk, "usermod_data", lambda: {"emsdk": data})
    monkeypatch.setattr(emsdk, "download_file", fake_download)

    from cibuildmp.sources import SourceError

    with pytest.raises(SourceError, match="checksum mismatch"):
        resolve_emsdk(root=tmp_path, quiet=True)


def test_resolve_emsdk_unknown_host_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(emsdk, "_host_platform_key", lambda: "windows-x64")
    monkeypatch.setattr(
        emsdk, "usermod_data", lambda: {"emsdk": {"version": "6.0.8", "platform": {}}}
    )
    with pytest.raises(
        EmsdkError, match="no pinned emsdk build for host 'windows-x64'"
    ):
        resolve_emsdk(root=tmp_path, quiet=True)


def test_env_prepends_both_bin_dirs(tmp_path):
    install_dir = tmp_path / "install"
    sdk = ResolvedEmsdk(install_dir=install_dir)
    env = sdk.env({"PATH": "/usr/bin"})

    # os.pathsep, not a hardcoded ":" -- this must hold on Windows (";")
    # too, not just Linux/macOS.
    sep = os.pathsep
    assert env["PATH"] == (
        f"{install_dir / 'emscripten'}{sep}{install_dir / 'bin'}{sep}/usr/bin"
    )
