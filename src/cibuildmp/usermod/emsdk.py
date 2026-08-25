"""emsdk provisioning for the `webassembly` usermod port (D2/D3), pinned
in resources/usermod.toml rather than floating on "latest" the way
build-usermod-webassembly's own composite action does -- see that file's
own `[emsdk]` table for the full reasoning.

Deliberately not toolchains.py's `ToolchainSpec`/`resolve()` shape: those
are built around exactly one `<prefix>gcc`-named cross-compiler on PATH
(`_find_bin_dir` looks for precisely that), and existing reuse (usermod's
own `x86`/`armv7m`) leans on that convention. emsdk has no such binary --
`emcc`/`em++` are Python driver scripts living in their own directory
(`emscripten/`), separate from the LLVM/wasm toolchain binaries (`bin/`)
they invoke -- and needs two PATH entries, not one `bin_dir`. A dedicated,
smaller resolver here is more honest than forcing that shape to fit.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path

from ..resources import usermod_data
from ..sources import (
    cache_root,
    cached_dir,
    download_file,
    extract_archive,
    verify_sha256,
)


class EmsdkError(Exception):
    pass


def _host_platform_key() -> str:
    os_name = {"linux": "linux", "darwin": "mac"}.get(platform.system().lower())
    arch = {
        "x86_64": "x64",
        "amd64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(platform.machine().lower())
    if os_name is None or arch is None:
        raise EmsdkError(
            f"unsupported host for emsdk: {platform.system()}/{platform.machine()}"
        )
    return f"{os_name}-{arch}"


@dataclass(frozen=True)
class ResolvedEmsdk:
    install_dir: Path

    def env(self, base: dict[str, str] | None = None) -> dict[str, str]:
        """PATH prepended with `emscripten/` (the emcc/em++ driver
        scripts) and `bin/` (the LLVM/wasm binaries they invoke) --
        verified live to be sufficient on its own, no `.emscripten`
        config file needed (see resources/usermod.toml's own `[emsdk]`
        table for why).
        """
        env = dict(os.environ if base is None else base)
        bin_dirs = (self.install_dir / "emscripten", self.install_dir / "bin")
        env["PATH"] = os.pathsep.join(
            [*(str(d) for d in bin_dirs), env.get("PATH", "")]
        )
        return env


def resolve_emsdk(*, root: Path | None = None, quiet: bool = False) -> ResolvedEmsdk:
    """Download (or reuse a cached) pinned emsdk release for this host."""
    data = usermod_data()["emsdk"]
    key = _host_platform_key()
    try:
        platform_data = data["platform"][key]
    except KeyError:
        raise EmsdkError(
            f"no pinned emsdk build for host {key!r}. Known: "
            f"{', '.join(sorted(data['platform']))}"
        ) from None

    version = data["version"]
    dest = (root or cache_root()) / "emsdk" / version / key

    def populate(staging: Path) -> Path:
        archive = staging / "wasm-binaries.tar.xz"
        download_file(platform_data["url"], archive, quiet=quiet)
        verify_sha256(archive, platform_data["sha256"])
        extract_archive(archive, staging)
        archive.unlink()
        return staging / "install"

    result, was_cached = cached_dir(dest, populate, force=False)
    if was_cached and not quiet:
        print(f"  emsdk {version} ({key}): cached at {result}")
    return ResolvedEmsdk(install_dir=result)
