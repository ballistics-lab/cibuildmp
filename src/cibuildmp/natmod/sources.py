"""Provisioning MicroPython itself, and mpy-cross.

Both are shared by every target in an invocation -- the reason the default
build layout is one job looping rather than a matrix leg per identifier
(D9). Everything lands in a cache directory so a second run, locally or on a
runner with a warm cache, does neither again.

Standard library only, deliberately: `wget` is not available on every host
(the composite `fetch-micropython` action is unusable on a Windows runner
outside MSYS2 for exactly that reason), and a build tool that needs its own
dependency tree resolved before it can fetch anything is harder to trust.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

# The release *asset*, not GitHub's auto-generated archive: only the former
# vendors every port's lib/ submodules, which is what makes a submodule init
# unnecessary. Same URL the fetch-micropython action has always used.
RELEASE_TARBALL = "https://github.com/micropython/micropython/releases/download/{tag}/micropython-{ver}.tar.xz"
GIT_URL = "https://github.com/micropython/micropython.git"

# Written into a finished checkout. Its absence means the directory is a
# leftover from an interrupted run and must not be reused.
STAMP = ".cibuildmp-complete"


class SourceError(Exception):
    pass


def cache_root() -> Path:
    """Where downloaded sources and toolchains live."""
    env = os.environ.get("CIBMP_CACHE_PATH")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "cibuildmp"


# -- Shared primitives ----------------------------------------------------


def verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise SourceError(
            f"checksum mismatch for {path.name}: expected {expected}, got {actual}"
        )


def extract_archive(archive: Path, into: Path) -> None:
    """Extract a .tar.gz/.tar.xz, refusing paths that escape `into`."""
    with tarfile.open(archive) as tar:
        # filter="data" refuses absolute paths and traversal out of the
        # destination. Guarded because it landed mid-3.11.
        kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(into, **kwargs)  # type: ignore[arg-type]


def sole_directory(parent: Path, what: str) -> Path:
    roots = [p for p in parent.iterdir() if p.is_dir()]
    if len(roots) != 1:
        raise SourceError(
            f"expected one top-level directory in {what}, found {len(roots)}"
        )
    return roots[0]


def cached_dir(
    dest: Path, populate: Callable[[Path], Path], *, force: bool
) -> tuple[Path, bool]:
    """Ensure `dest` holds a complete tree, building it via `populate`.

    `populate` receives a staging directory and returns the subdirectory of
    it that should become `dest`. The move is atomic and gated on a stamp
    file, so a run killed midway leaves nothing the next run will trust.
    Returns (dest, was_cached).
    """
    if dest.joinpath(STAMP).exists() and not force:
        return dest, True
    if dest.exists():
        shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=dest.parent))
    try:
        built = populate(staging)
        built.joinpath(STAMP).touch()
        os.replace(built, dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return dest, False


# -- MicroPython ----------------------------------------------------------


def micropython_dir(tag: str, root: Path | None = None) -> Path:
    return (root or cache_root()) / "micropython" / tag


def fetch_micropython(
    tag: str,
    root: Path | None = None,
    *,
    submodules: list[str] | None = None,
    force: bool = False,
    quiet: bool = False,
) -> Path:
    """Return a MicroPython checkout at `tag`, fetching it if needed.

    `submodules` only ever matters on the clone path: the release tarball
    already vendors every one of them, which is the whole reason it is
    preferred. See _clone().
    """
    dest, was_cached = cached_dir(
        micropython_dir(tag, root),
        lambda staging: _fetch_into(
            tag, staging, submodules=submodules or [], quiet=quiet
        ),
        force=force,
    )
    if was_cached and not quiet:
        print(f"  MicroPython {tag}: cached at {dest}")
    return dest


def _fetch_into(tag: str, staging: Path, *, submodules: list[str], quiet: bool) -> Path:
    """Populate `staging` and return the directory holding the source tree."""
    url = RELEASE_TARBALL.format(tag=tag, ver=tag.removeprefix("v"))
    archive = staging / "micropython.tar.xz"

    try:
        download_file(url, archive, quiet=quiet)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise SourceError(f"downloading {url} failed: {exc}") from exc
        # Preview tags and branches publish no release asset -- verified:
        # v1.28.0 and v1.25.0 have one, v1.29.0-preview does not.
        if not quiet:
            print(f"  MicroPython {tag}: no release tarball, cloning instead")
        return _clone(tag, staging, submodules=submodules, quiet=quiet)

    if not quiet:
        print(f"  MicroPython {tag}: extracting")
    extract_archive(archive, staging)
    archive.unlink()
    return sole_directory(staging, f"the {tag} tarball")


def _clone(tag: str, staging: Path, *, submodules: list[str], quiet: bool) -> Path:
    """Shallow-clone the tag, initialising only the requested submodules.

    This is where the tarball and the clone genuinely differ: a release
    tarball vendors every lib/ submodule, a --depth 1 clone vendors none.
    Most natmods need none either -- py/ and tools/mpy_ld.py are in-tree,
    and so are the parts of lib/ that are not submodules -- but "most" is
    not "all": upstream's own examples/natmod/btree builds against
    $(MPY_DIR)/lib/berkeley-db-1.xx, which is one. Hence the option, and
    hence the same input existing on the clone-micropython action.
    """
    dest = staging / "micropython"
    command = ["git", "clone", "--depth", "1", "--branch", tag, GIT_URL, str(dest)]
    if quiet:
        command.insert(2, "--quiet")
    try:
        subprocess.run(command, check=True)
        if submodules:
            if not quiet:
                print(f"  MicroPython {tag}: init submodules {' '.join(submodules)}")
            subprocess.run(
                ["git", "submodule", "update", "--init", "--depth", "1", *submodules],
                cwd=dest,
                check=True,
                capture_output=quiet,
            )
    except FileNotFoundError as exc:
        raise SourceError(
            f"MicroPython {tag} publishes no release tarball and git is not installed, "
            f"so it cannot be cloned either"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise SourceError(f"cloning MicroPython {tag} failed: {exc}") from exc
    return dest


def download_file(url: str, dest: Path, *, quiet: bool) -> None:
    with urllib.request.urlopen(url) as response:
        total = int(response.headers.get("Content-Length") or 0)
        show = not quiet and sys.stderr.isatty() and total > 0
        done = 0
        with dest.open("wb") as handle:
            while chunk := response.read(1 << 20):
                handle.write(chunk)
                done += len(chunk)
                if show:
                    print(
                        f"\r  downloading {dest.name}: {done / total:.0%} "
                        f"({done >> 20}/{total >> 20} MiB)",
                        end="",
                        file=sys.stderr,
                    )
        if show:
            print(file=sys.stderr)
        elif not quiet:
            print(f"  downloaded {dest.name} ({done >> 20} MiB)")


# -- .mpy ABI -------------------------------------------------------------

_ABI_DEFINES = ("MPY_VERSION", "MPY_SUB_VERSION")


def read_mpy_abi(mpy_dir: Path) -> str:
    """Read "<MPY_VERSION>.<MPY_SUB_VERSION>" out of py/persistentcode.h.

    The authoritative answer, as opposed to targets.MPY_ABI's table, which
    exists only so identifiers can be produced with no checkout at all.
    """
    header = mpy_dir / "py" / "persistentcode.h"
    try:
        text = header.read_text()
    except OSError as exc:
        raise SourceError(f"cannot read {header}: {exc}") from exc

    found: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "#define" and parts[1] in _ABI_DEFINES:
            found[parts[1]] = parts[2]

    if len(found) != len(_ABI_DEFINES):
        raise SourceError(f"could not find MPY_VERSION/MPY_SUB_VERSION in {header}")
    return f"{found['MPY_VERSION']}.{found['MPY_SUB_VERSION']}"


# -- mpy-cross ------------------------------------------------------------


def build_mpy_cross(mpy_dir: Path, *, force: bool = False, quiet: bool = False) -> Path:
    """Build mpy-cross in the checkout, once, and return the binary."""
    binary = mpy_dir / "mpy-cross" / "build" / "mpy-cross"
    if binary.exists() and not force:
        if not quiet:
            print(f"  mpy-cross: cached at {binary}")
        return binary

    if not quiet:
        print("  mpy-cross: building")
    command = ["make", "-C", str(mpy_dir / "mpy-cross"), f"-j{os.cpu_count() or 1}"]
    try:
        subprocess.run(command, check=True, capture_output=quiet)
    except subprocess.CalledProcessError as exc:
        raise SourceError(f"building mpy-cross failed: {exc}") from exc

    if not binary.exists():
        raise SourceError(f"mpy-cross build reported success but {binary} is missing")
    return binary
