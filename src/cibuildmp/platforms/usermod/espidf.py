"""ESP-IDF provisioning for `esp32`-family usermod ports (D19): the same
official recipe `build-usermod-esp32`'s own composite action already uses
(`git clone --recursive` + `install.sh` + `export.sh`), not Docker.

Docker was the original plan D19 flagged as worth revisiting for this port
-- usermod ports have real system dependencies a cross-toolchain tarball
cannot express, unlike every natmod arch. Dropped after live-testing, not
assumed: Docker does not even run in this project's own dev sandbox (no
daemon), and the official clone+install path works there directly with no
isolation layer needed -- the same "a cross-compile that runs fine on the
build host costs nothing extra from a container" reasoning **M2**'s own
"why not docker for x86" note already made, just confirmed here for a
second port rather than re-litigated. The one real gap this fixes is
D19's actual complaint -- "No caching yet... Left as a known follow-up" --
not the toolchain mechanism itself, which already works.

Verified live: a real `v5.5.1` clone, `idf_tools.py install
--targets=esp32` + `install-python-env`, then a full `make -C
ports/esp32 BOARD=ESP32_GENERIC` produced a genuine `micropython.bin`.
One real environment finding along the way: `openocd-esp32`'s own binary
needs `libusb-1.0.so.0` to run its post-install self-check, missing in a
minimal sandbox -- an ordinary Linux runtime dependency any real dev
machine or CI image already has (`apt install libusb-1.0-0` fixed it),
not something a toolchain tarball could supply either way.

Deliberately not `toolchains.py`'s `ToolchainSpec`/`resolve()` shape, the
same reason the since-deleted `usermod/emsdk.py` wasn't: there is no
single `<prefix>gcc` to find on `PATH` here, and `idf_tools.py export`'s own env additions (PATH,
IDF_PYTHON_ENV_PATH, OPENOCD_SCRIPTS, ESP_ROM_ELF_DIR, ...) are resolved
by asking ESP-IDF's own tool for them -- delegated, not reimplemented,
the same D2 "delegate the compile, own the environment" split every other
port here already follows.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ...sources import cache_root, cached_dir

IDF_GIT_URL = "https://github.com/espressif/esp-idf.git"


# The last host-side toolchain resolver in usermod. `emsdk.py` and
# `llvmmingw.py` were both deleted once `webassembly` and `windows` went
# Docker-only (D30/D32) and their pins moved into the port Dockerfiles
# that bake those toolchains in. This one survives only because `esp32`
# has no Docker image yet (D28's own not-started `esp32.Dockerfile`) --
# when it gets one, this module follows them.


class EspIdfError(Exception):
    pass


def _idf_dir(version: str, root: Path | None) -> Path:
    return (root or cache_root()) / "esp-idf" / version / "idf"


def _tools_dir(version: str, idf_target: str, root: Path | None) -> Path:
    return (root or cache_root()) / "esp-idf" / version / "tools" / idf_target


def fetch_esp_idf(
    version: str, *, root: Path | None = None, quiet: bool = False
) -> Path:
    """Clone (or reuse a cached) esp-idf checkout at `version` (e.g.
    "v5.5.1"). `--recursive`, unlike a natmod build of the same chip: a
    usermod compiles into a firmware built against IDF's own components,
    while a natmod only ever borrows the xtensa compiler `install.sh`
    downloads (**M2**'s own `xtensawin` finding).
    """
    dest = _idf_dir(version, root)

    def populate(staging: Path) -> Path:
        target = staging / "idf"
        command = [
            "git",
            "clone",
            "--depth",
            "1",
            "--recursive",
            "--branch",
            version,
            IDF_GIT_URL,
            str(target),
        ]
        if quiet:
            command.insert(2, "--quiet")
        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as exc:
            raise EspIdfError(f"cloning esp-idf {version} failed: {exc}") from exc
        return target

    result, was_cached = cached_dir(dest, populate, force=False)
    if was_cached and not quiet:
        print(f"  esp-idf {version}: cached at {result}")
    return result


def _resolve_esp_idf_tools(
    idf_dir: Path, version: str, idf_target: str, *, root: Path | None, quiet: bool
) -> Path:
    """Install (or reuse a cached) toolchain + Python env for
    `idf_target`, cached by `(version, idf_target)` -- the real gap D19
    flagged: the composite action's own recipe re-downloads both on every
    run.
    """
    dest = _tools_dir(version, idf_target, root)

    def populate(staging: Path) -> Path:
        tools_dir = staging / "tools"
        tools_dir.mkdir()
        env = {**os.environ, "IDF_TOOLS_PATH": str(tools_dir)}
        tools_py = idf_dir / "tools" / "idf_tools.py"
        for command in (
            [sys.executable, str(tools_py), "install", f"--targets={idf_target}"],
            [sys.executable, str(tools_py), "install-python-env"],
        ):
            try:
                subprocess.run(command, env=env, check=True)
            except subprocess.CalledProcessError as exc:
                raise EspIdfError(
                    f"esp-idf tool install failed: `{' '.join(command)}`: {exc}"
                ) from exc
        return tools_dir

    result, was_cached = cached_dir(dest, populate, force=False)
    if was_cached and not quiet:
        print(f"  esp-idf tools ({version}, {idf_target}): cached at {result}")
    return result


@dataclass(frozen=True)
class ResolvedEspIdf:
    idf_dir: Path
    tools_dir: Path

    def env(self, base: dict[str, str] | None = None) -> dict[str, str]:
        """The environment `make -C ports/esp32` needs to run under --
        asks `idf_tools.py export` for it (PATH, `IDF_PYTHON_ENV_PATH`,
        `OPENOCD_SCRIPTS`, `ESP_ROM_ELF_DIR`, ...) rather than
        reconstructing that resolution by hand, plus `IDF_PATH` itself,
        which `export.sh` sets as a separate step before ever calling
        that tool.
        """
        base_env = dict(os.environ if base is None else base)
        export_env = {**base_env, "IDF_TOOLS_PATH": str(self.tools_dir)}
        tools_py = self.idf_dir / "tools" / "idf_tools.py"
        try:
            result = subprocess.run(
                [sys.executable, str(tools_py), "export", "--format", "key-value"],
                env=export_env,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise EspIdfError(f"esp-idf export failed: {exc}") from exc

        merged = dict(base_env)
        merged["IDF_PATH"] = str(self.idf_dir)
        for line in result.stdout.splitlines():
            key, sep, value = line.partition("=")
            if not sep:
                continue
            if key == "IDF_DEACTIVATE_FILE_PATH":
                # Only meaningful for later `export --deactivate` in an
                # interactive shell -- nothing here reactivates a shell.
                continue
            merged[key] = value.replace("$PATH", base_env.get("PATH", ""))
        return merged


def resolve_esp_idf(
    version: str, idf_target: str, *, root: Path | None = None, quiet: bool = False
) -> ResolvedEspIdf:
    idf_dir = fetch_esp_idf(version, root=root, quiet=quiet)
    tools_dir = _resolve_esp_idf_tools(
        idf_dir, version, idf_target, root=root, quiet=quiet
    )
    return ResolvedEspIdf(idf_dir=idf_dir, tools_dir=tools_dir)
