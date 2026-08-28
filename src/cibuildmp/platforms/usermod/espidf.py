"""ESP-IDF provisioning for `esp32`-family usermod ports (D19).

**Went Docker 2026-08-28** ([0028]/[0053]'s own still-open gap, closed for
this port): `build_esp32()` (`usermod/build.py`) now runs entirely inside
`esp_idf_base` ([0058]), not on the bare host. The bare-host path this
module used to own -- `git clone --recursive` + `idf_tools.py install` +
`install-python-env`, the same recipe `build-usermod-esp32`'s own
composite action already used -- broke the moment `esp32` was exercised
broadly rather than by hand: `idf_tools.py install-python-env` refuses to
create a venv from inside one that is already active, and cibuildmp's own
`uv tool install` puts every invocation inside exactly that (live-caught
2026-08-28, `test-platforms.yml`'s own broad sweep -- 83 of 94 real
failures in one run were this single cause). Docker sidesteps it by
construction: the container's own `python3` is never inside cibuildmp's
venv to begin with.

This is also the same class of bug `usermod/build.py`'s own
`container_mpy_cross()` already exists to prevent, the other direction:
`idf_tools.py install` downloads real compiled binaries (an xtensa or
riscv32 gcc, `openocd`, ...), not source -- installing them on the host
and mounting the result into a *different* base image risks the exact
"built against one glibc, run against another" mismatch
`container_mpy_cross()`'s own docstring documents hitting for real.
`esp_idf_base.Dockerfile`'s own comment already says so: "the cache must
be populated from inside this image, not on the host."

What stays host-side: `fetch_esp_idf()` below, since a `git clone` is
source, not a binary -- the same reasoning that lets `mpy_dir` itself, and
`pyelftools`/`ar` ([0012]), mount straight from the host into any image
with no rebuild. Only the *tools* (`idf_tools.py install`, and by
extension `make` itself, which needs them on `PATH`) need to run where
they were installed.

Deliberately not `toolchains.py`'s `ToolchainSpec`/`resolve()` shape, the
same reason the since-deleted `usermod/emsdk.py` wasn't: there is no
single `<prefix>gcc` to find on `PATH` here, and `idf_tools.py export`'s
own env additions (PATH, IDF_PYTHON_ENV_PATH, OPENOCD_SCRIPTS,
ESP_ROM_ELF_DIR, ...) are resolved by asking ESP-IDF's own tool for them
-- delegated, not reimplemented, the same D2 "delegate the compile, own
the environment" split every other port here already follows. `build_esp32()`
now does that delegation *inside* the container too (a `bash -c` script,
not a second Python-side parse of `idf_tools.py export`'s output) --
[0052]'s own "`pre_checkout`/`post_checkout` stay documentation, not
something executed as a shell string at build time" is about *stored
config* driving execution, not about this module's own code constructing
one; the script below is built from real paths this module resolves, the
same way every other port's `*_make_command()` builds a typed
`list[str]`, just wrapped in `bash -c` because installing (once, cached)
and building both need to happen in the one container invocation that has
this cell's own tools on `PATH`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ...sources import cache_root, cached_dir

IDF_GIT_URL = "https://github.com/espressif/esp-idf.git"


class EspIdfError(Exception):
    pass


def idf_dir(version: str, root: Path | None = None) -> Path:
    return (root or cache_root()) / "esp-idf" / version / "idf"


def tools_dir(version: str, idf_target: str, root: Path | None = None) -> Path:
    return (root or cache_root()) / "esp-idf" / version / "tools" / idf_target


def fetch_esp_idf(
    version: str, *, root: Path | None = None, quiet: bool = False
) -> Path:
    """Clone (or reuse a cached) esp-idf checkout at `version` (e.g.
    "v5.5.1"). `--recursive`, unlike a natmod build of the same chip: a
    usermod compiles into a firmware built against IDF's own components,
    while a natmod only ever borrows the xtensa compiler `install.sh`
    downloads (**M2**'s own `xtensawin` finding).

    Two `git` calls, not `clone --recursive` in one -- MicroPython's own
    `tools/ci.sh` (`ci_esp32_idf_setup`), read directly rather than
    guessed: a plain `--depth 1` clone of the superproject, then `git -C
    esp-idf submodule update --init --recursive --filter=tree:0` for the
    submodules. That script's own comment explains the `--filter=tree:0`
    choice over the more obvious `--shallow-submodules`: "isn't quite as
    good as --shallow-submodules, but is smaller than full clones and
    works when the submodule commit isn't a head" -- a submodule pinned to
    a non-tip commit is exactly the case `--recursive` alone hits hardest,
    since every one of its dozens of submodules then clones full history.
    """
    dest = idf_dir(version, root)

    def populate(staging: Path) -> Path:
        target = staging / "idf"
        clone_command = [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            version,
            IDF_GIT_URL,
            str(target),
        ]
        submodule_command = [
            "git",
            "-C",
            str(target),
            "submodule",
            "update",
            "--init",
            "--recursive",
            "--filter=tree:0",
        ]
        if quiet:
            clone_command.insert(2, "--quiet")
            submodule_command.insert(4, "--quiet")
        try:
            subprocess.run(clone_command, check=True)
            subprocess.run(submodule_command, check=True)
        except subprocess.CalledProcessError as exc:
            raise EspIdfError(f"cloning esp-idf {version} failed: {exc}") from exc
        return target

    result, was_cached = cached_dir(dest, populate, force=False)
    if was_cached and not quiet:
        print(f"  esp-idf {version}: cached at {result}")
    return result
