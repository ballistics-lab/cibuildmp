"""`toolchain_fetch.py` -- record 0086's generic in-container tarball fetch.

`fetch_script()`'s own output is real shell text meant to run inside a
container, so these tests run it for real with `bash -c` against `file://`
tarballs rather than asserting on the string -- no Docker daemon needed
(nothing here is image-specific), but a real `curl`/`sha256sum`/`tar`
pipeline exercises the actual failure and idempotency behaviour rather than
a string that merely looks right.
"""

import subprocess
import tarfile
from pathlib import Path

import pytest

from cibuildmp import resources
from cibuildmp.sources import STAMP
from cibuildmp.toolchain_fetch import (
    ToolchainFetchError,
    fetch_script,
    rename_prefix_script,
    resolve_pin,
    resolve_toolchain,
    toolchain_dir,
)


def _make_tarball(dest: Path, top: str = "arm-none-eabi-1.2.3") -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = dest.parent / "_payload"
    (payload / top / "bin").mkdir(parents=True)
    (payload / top / "bin" / "gcc").write_text("#!/bin/sh\necho fake gcc\n")
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(payload / top, arcname=top)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False
    )


def test_toolchain_dir_is_keyed_by_cross_kind_and_version(tmp_path):
    assert toolchain_dir("arm-none-eabi-", "cross", "13.3.1", tmp_path) == (
        tmp_path / "toolchains" / "arm-none-eabi-" / "cross" / "13.3.1"
    )


def test_resolve_pin_returns_the_pinned_url_and_sha256(monkeypatch):
    monkeypatch.setattr(
        resources,
        "pinned_toolchains_data",
        lambda: {
            "arm-none-eabi-": {
                "15.2.1-1.1": {"url": "https://example/tc.tar.gz", "sha256": "a" * 64}
            }
        },
    )
    assert resolve_pin("arm-none-eabi-", "15.2.1-1.1") == (
        "https://example/tc.tar.gz",
        "a" * 64,
    )


def test_resolve_pin_raises_for_an_unpinned_version(monkeypatch):
    monkeypatch.setattr(
        resources, "pinned_toolchains_data", lambda: {"arm-none-eabi-": {}}
    )
    with pytest.raises(ToolchainFetchError, match="arm-none-eabi-.*13.3.1"):
        resolve_pin("arm-none-eabi-", "13.3.1")


def test_resolve_pin_raises_for_an_unknown_cross_prefix(monkeypatch):
    monkeypatch.setattr(resources, "pinned_toolchains_data", dict)
    with pytest.raises(ToolchainFetchError):
        resolve_pin("riscv64-unknown-elf-", "15.2.0-1")


def test_resolve_toolchain_combines_the_lookup_and_the_script(tmp_path, monkeypatch):
    monkeypatch.setattr(
        resources,
        "pinned_toolchains_data",
        lambda: {
            "arm-none-eabi-": {
                "15.2.1-1.1": {"url": "https://example/tc.tar.gz", "sha256": "a" * 64}
            }
        },
    )

    dest, script = resolve_toolchain("arm-none-eabi-", "15.2.1-1.1", root=tmp_path)

    assert dest == toolchain_dir("arm-none-eabi-", "cross", "15.2.1-1.1", tmp_path)
    assert dest.parent.is_dir()  # created host-side, ahead of any container start
    assert script == fetch_script(dest, "https://example/tc.tar.gz", "a" * 64)


def test_resolve_toolchain_honours_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(
        resources,
        "pinned_toolchains_data",
        lambda: {
            "arm-none-eabi-": {"1": {"url": "https://x/y.tar.gz", "sha256": "b" * 64}}
        },
    )

    dest, _ = resolve_toolchain("arm-none-eabi-", "1", kind="native", root=tmp_path)

    assert dest == toolchain_dir("arm-none-eabi-", "native", "1", tmp_path)


def test_resolve_toolchain_raises_for_an_unpinned_version(tmp_path, monkeypatch):
    monkeypatch.setattr(
        resources, "pinned_toolchains_data", lambda: {"arm-none-eabi-": {}}
    )
    with pytest.raises(ToolchainFetchError):
        resolve_toolchain("arm-none-eabi-", "13.3.1", root=tmp_path)


def test_fetch_verifies_and_extracts_a_real_tarball(tmp_path):
    tarball = tmp_path / "src" / "tc.tar.gz"
    _make_tarball(tarball)
    sha = _sha256(tarball)
    dest = tmp_path / "cache" / "arm_embedded" / "cross" / "13.3.1"

    result = _run(fetch_script(dest, f"file://{tarball}", sha))

    assert result.returncode == 0, result.stderr
    assert (dest / STAMP).exists()
    assert (dest / "bin" / "gcc").read_text() == "#!/bin/sh\necho fake gcc\n"


def test_fetch_is_a_no_op_once_the_marker_exists(tmp_path):
    tarball = tmp_path / "src" / "tc.tar.gz"
    _make_tarball(tarball)
    sha = _sha256(tarball)
    dest = tmp_path / "cache" / "arm_embedded" / "cross" / "13.3.1"
    script = fetch_script(dest, f"file://{tarball}", sha)

    assert _run(script).returncode == 0
    # Prove the second run never re-fetches: remove the source tarball a
    # warm cache would have no reason to touch again, then run once more.
    tarball.unlink()
    result = _run(script)

    assert result.returncode == 0, result.stderr
    assert (dest / "bin" / "gcc").exists()


def test_checksum_mismatch_fails_and_leaves_no_cache_entry(tmp_path):
    tarball = tmp_path / "src" / "tc.tar.gz"
    _make_tarball(tarball)
    dest = tmp_path / "cache" / "arm_embedded" / "cross" / "13.3.1"

    result = _run(fetch_script(dest, f"file://{tarball}", "0" * 64))

    assert result.returncode != 0
    assert not dest.exists()
    assert not (dest.parent / f".staging-{dest.name}").exists()


def test_download_failure_leaves_no_debris(tmp_path):
    dest = tmp_path / "cache" / "arm_embedded" / "cross" / "13.3.1"
    missing = tmp_path / "src" / "does-not-exist.tar.gz"

    result = _run(fetch_script(dest, f"file://{missing}", "0" * 64))

    assert result.returncode != 0
    assert not dest.exists()
    assert not (dest.parent / f".staging-{dest.name}").exists()
    assert list((tmp_path / "cache" / "arm_embedded" / "cross").iterdir()) == []


def test_a_stale_partial_tree_is_not_trusted(tmp_path):
    """Simulate a container killed mid-fetch: `dest` exists (leftover
    partial extraction) but its own marker never got written. A second run
    must not treat that as cached -- it should discard it and fetch for
    real, the same guarantee `sources.cached_dir()` gives on the host."""
    tarball = tmp_path / "src" / "tc.tar.gz"
    _make_tarball(tarball)
    sha = _sha256(tarball)
    dest = tmp_path / "cache" / "arm_embedded" / "cross" / "13.3.1"
    dest.mkdir(parents=True)
    (dest / "junk").write_text("half a tarball")

    result = _run(fetch_script(dest, f"file://{tarball}", sha))

    assert result.returncode == 0, result.stderr
    assert not (dest / "junk").exists()
    assert (dest / STAMP).exists()
    assert (dest / "bin" / "gcc").exists()


def test_rename_prefix_script_symlinks_every_matching_tool(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "riscv-none-elf-gcc").write_text("#!/bin/sh\necho gcc\n")
    (bin_dir / "riscv-none-elf-as").write_text("#!/bin/sh\necho as\n")
    (bin_dir / "unrelated-tool").write_text("#!/bin/sh\necho nope\n")

    script = rename_prefix_script(bin_dir, "riscv-none-elf-", "riscv64-unknown-elf-")
    result = _run(script)

    assert result.returncode == 0, result.stderr
    gcc = bin_dir / "riscv64-unknown-elf-gcc"
    assert gcc.is_symlink()
    assert gcc.resolve() == (bin_dir / "riscv-none-elf-gcc").resolve()
    assert (bin_dir / "riscv64-unknown-elf-as").is_symlink()
    assert not (bin_dir / "riscv64-unknown-elf-unrelated-tool").exists()


def test_rename_prefix_script_is_idempotent(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "riscv-none-elf-gcc").write_text("#!/bin/sh\necho gcc\n")
    script = rename_prefix_script(bin_dir, "riscv-none-elf-", "riscv64-unknown-elf-")

    assert _run(script).returncode == 0
    result = _run(script)  # re-running must not fail on an existing symlink

    assert result.returncode == 0, result.stderr
    assert (bin_dir / "riscv64-unknown-elf-gcc").is_symlink()


def test_strip_components_is_honoured(tmp_path):
    tarball = tmp_path / "src" / "tc.tar.gz"
    _make_tarball(tarball, top="one/two")
    sha = _sha256(tarball)
    dest = tmp_path / "cache" / "arm_embedded" / "cross" / "13.3.1"

    result = _run(fetch_script(dest, f"file://{tarball}", sha, strip_components=2))

    assert result.returncode == 0, result.stderr
    assert (dest / "bin" / "gcc").exists()
