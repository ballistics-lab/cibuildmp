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

from . import resources

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
    """Where downloaded sources and toolchains live -- **fetched input
    only** ([0095]). Compiled build state has no host location at all any
    more: every usermod port builds through `Container`/overlay now
    (record 0095's own addenda 8-12), so a `BUILD=` value
    (`orchestrate._resolved_build_dir()`) is only ever a path *string* a
    container's own `make` writes inside its own ephemeral filesystem,
    never bind-mounted, never read back from the host. `scratch_root()`
    and `CIBMP_SCRATCH_PATH` named that non-existent host location until
    this record's own addendum removed them -- there was nothing left for
    either to redirect."""
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
    ports: list[str] | None = None,
    force: bool = False,
    quiet: bool = False,
) -> Path:
    """Return a MicroPython checkout at `tag`, fetching it if needed.

    `submodules`/`ports` only ever matter on the clone path: the release
    tarball already vendors every port's own `lib/` submodules, which is
    the whole reason it is preferred. See _clone() -- two different
    inputs for two different callers, not one generalised into the other:
    `submodules` is natmod's own public `micropython_submodules` config
    knob (raw `lib/` paths a *user's* own native module needs, which no
    port Makefile has any reason to know about), initialised with a plain
    `git submodule update --init`; `ports` is usermod's -- port names
    whose own `make submodules` (the command each one's own README
    documents) `_clone()` runs, so this project never has to keep its own
    copy of what a port's `GIT_SUBMODULES` currently lists.

    `quiet=False` (the default) prints progress -- download percentage,
    "extracting", "cached at <dest>" -- to stdout, not stderr. A caller that
    captures this function's own return value through a shell `$(...)`
    command substitution (a CI step resolving the checkout path ahead of
    the real build, e.g.) captures every one of those lines too, not just
    the final `print(path)` -- live-caught in
    .github/workflows/test-upstream-usermodule.yml (docs/records/0069): the
    resulting multi-line value corrupted `$GITHUB_OUTPUT`, which GitHub's
    own file-command parser then rejected outright, before either build
    step in that workflow ever ran. Pass `quiet=True` whenever the return
    value is being captured this way.
    """
    dest, was_cached = cached_dir(
        micropython_dir(tag, root),
        lambda staging: _fetch_into(
            tag, staging, submodules=submodules or [], ports=ports or [], quiet=quiet
        ),
        force=force,
    )
    if was_cached and not quiet:
        print(f"  MicroPython {tag}: cached at {dest}")
    return dest


def _fetch_into(
    tag: str, staging: Path, *, submodules: list[str], ports: list[str], quiet: bool
) -> Path:
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
        return _clone(tag, staging, submodules=submodules, ports=ports, quiet=quiet)

    if not quiet:
        print(f"  MicroPython {tag}: extracting")
    extract_archive(archive, staging)
    archive.unlink()
    return sole_directory(staging, f"the {tag} tarball")


def _clone(
    tag: str, staging: Path, *, submodules: list[str], ports: list[str], quiet: bool
) -> Path:
    """Shallow-clone the tag, then fetch whatever `lib/` submodules the
    caller asked for: `submodules` (raw paths, natmod's own
    `micropython_submodules` knob) via a plain `git submodule update
    --init`, and each named port in `ports` (usermod) via that port's own
    `make submodules` target -- the command its own README documents.

    This is where the tarball and the clone genuinely differ: a release
    tarball vendors every lib/ submodule, a --depth 1 clone vendors none.
    `ports` delegates to each port's own target rather than this project
    keeping its own list of submodule paths: that list is upstream's to
    maintain (a port's own `GIT_SUBMODULES` additions, in its own
    Makefile), not something that stays in sync here only because someone
    remembered to update it too, and it is free to vary tag to tag the
    same way everything else upstream does.

    `esp32` is deliberately excluded from `ports` by every usermod caller:
    its own `submodules` target is `idf.py -D UPDATE_SUBMODULES=1
    reconfigure`, which manages ESP-IDF's own components, needs the
    ESP-IDF environment to run at all, and cannot run against a bare host
    clone -- and, unlike every port here, it declares no `GIT_SUBMODULES`
    of its own against MicroPython's own `lib/` in the first place, so it
    never needed this step regardless.
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
        for port in ports:
            if not quiet:
                print(f"  MicroPython {tag}: make -C ports/{port} submodules")
            subprocess.run(
                # `MICROPY_STANDALONE=1`: `unix`'s own `GIT_SUBMODULES +=
                # lib/libffi` (ports/unix/Makefile) sits behind
                # `ifeq ($(MICROPY_STANDALONE),1)` -- without it here,
                # `make submodules` computes a *different*, incomplete
                # `GIT_SUBMODULES` than the real build needs, silently
                # skipping lib/libffi. Found live: a clone-path tag with
                # no release tarball (v1.30.0-preview) failed deplibs with
                # `No rule to make target '../../lib/libffi/autogen.sh'`
                # -- the submodule was simply never checked out.
                # `build_unix()` always passes `MICROPY_STANDALONE=1` now
                # (every unix target, not just the ones that need static
                # linking), so this matches the real build rather than
                # guessing at it. A no-op for every other port -- none
                # references this variable at all.
                [
                    "make",
                    "-C",
                    str(dest / "ports" / port),
                    "MICROPY_STANDALONE=1",
                    "submodules",
                ],
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

    **`MPY_SUB_VERSION` is itself a `v1.20.0`-and-later define** -- upstream
    added it in the same release that introduced ABI 6.1, and
    `py/persistentcode.h` before that carries `MPY_VERSION` alone (record
    0093). So a missing sub-version is a real, valid ABI here, not a
    malformed header: it yields the bare `"5"`/`"6"` that
    `build-platforms.toml`'s own `mpy` column already records for exactly
    those nine tags.
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

    if "MPY_VERSION" not in found:
        raise SourceError(f"could not find MPY_VERSION in {header}")
    if "MPY_SUB_VERSION" not in found:
        return found["MPY_VERSION"]
    return f"{found['MPY_VERSION']}.{found['MPY_SUB_VERSION']}"


# -- per-tag CFLAGS_EXTRA --------------------------------------------------

# `resources/tag_cflags.toml` -- record 0010's own rule (pinned data lives
# in resources/, not in Python) applied to the fact record 0084 first put
# in a `usermod/build_common.py` dict literal. Two reasons it moved here,
# to the module both families already import `fetch_micropython()`/
# `read_mpy_abi()` from, rather than staying `usermod`'s own: [0091] found
# the identical diagnostic hitting `natmod`'s own `mpy-cross` build too,
# and `natmod` never imports `usermod` (the established one-way
# dependency); and once a tag-keyed fact is confirmed to apply "in any
# port", per [0091]'s own live verification, it stops being resolver logic
# and becomes exactly the kind of "goes stale on someone else's schedule"
# data record 0010 already has a rule for -- bumping this file for a newly
# released tag is a reviewable data diff, not a source change. See that
# file's own header for the full reasoning and per-entry citations.
TAG_CFLAGS: dict[str, tuple[str, ...]] = {
    tag: tuple(flags) for tag, flags in resources.tag_cflags_data()["cflags"].items()
}


def tag_cflags(tag: str) -> tuple[str, ...]:
    """Every `CFLAGS_EXTRA` flag this MicroPython release needs, in any
    port or family. Empty for a tag that needs none, and for no tag at
    all."""
    return TAG_CFLAGS.get(tag, ())


# -- mpy-cross ------------------------------------------------------------


# `mpy-cross`'s own output path is a fact about the MicroPython tag, not a
# constant. Upstream's `py/mkrules.mk` links `all: $(PROG)` --
# `mpy-cross/mpy-cross` -- through `v1.19.1`, and `all: $(BUILD)/$(PROG)`
# from `v1.20.0` on; `py/dynruntime.mk`'s own hardcoded `MPY_CROSS =`
# moves with it in the same release. Checked against every tag
# `build-platforms.toml` knows, not inferred from the two ends -- record
# 0093, found while closing 0082's own ABI 5/6 gap. The two candidates are
# disjoint in practice (a tag produces one or the other, never both), so
# taking the first that exists needs no tag comparison of its own.
def mpy_cross_candidates(mpy_dir: Path, build_dir: str = "build") -> tuple[Path, ...]:
    """Every path `make -C mpy-cross` may have written the binary to, newest
    layout first."""
    root = mpy_dir / "mpy-cross"
    return (root / build_dir / "mpy-cross", root / "mpy-cross")


def find_mpy_cross(mpy_dir: Path, build_dir: str = "build") -> Path | None:
    """The built `mpy-cross` binary, or `None` if no layout has one."""
    for path in mpy_cross_candidates(mpy_dir, build_dir):
        if path.exists():
            return path
    return None


def build_mpy_cross(mpy_dir: Path, *, force: bool = False, quiet: bool = False) -> Path:
    """Build mpy-cross on the host, once, and return the binary.

    **In the checkout, at `mpy-cross/build/`, deliberately** -- [0095]
    moved this under `scratch_root()` and CI caught why it cannot go there
    within the day (`build-examples.yml`, `v1.29.0-qemu-MPS2_AN385`). This
    function's one caller is `usermod`'s `qemu` (`_HOST_MPY_CROSS_PORTS`),
    which passes **no** `MICROPY_MPYCROSS=` and so reaches this binary
    through `py/mkrules.mk`'s own default path. Move it and that path is
    simply empty, at which point `mkrules.mk`'s own
    `$(MICROPY_MPYCROSS_DEPENDENCY)` rule builds mpy-cross *itself*, as a
    sub-make of the port build -- which compiles the **port's** own
    `genhdr/qstrdefs.generated.h` against mpy-cross's qstr pool and fails:

        qstrdefs.generated.h:666:21: error: unsigned conversion from 'int'
        to 'unsigned char' changes value from '2791' to '231'
        [-Werror=overflow]
        make: *** [py/mkrules.mk:209: ../../mpy-cross/build/mpy-cross]

    That makes this the same class as `natmod`'s own container-built
    mpy-cross (`py/dynruntime.mk` hardcodes `MPY_CROSS`) and `rp2`/`esp32`'s
    CMake trees: a path upstream fixes and cibuildmp cannot redirect. It
    stops being a write into `cache_root()` when `qemu` moves to the
    container model, not before -- there the checkout is an overlay and
    this path exists only inside the container.
    """
    binary = find_mpy_cross(mpy_dir)
    if binary is not None and not force:
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

    binary = find_mpy_cross(mpy_dir)
    if binary is None:
        raise SourceError(
            "mpy-cross build reported success but no binary at "
            + " or ".join(str(p) for p in mpy_cross_candidates(mpy_dir))
        )
    return binary
