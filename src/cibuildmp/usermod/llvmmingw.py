"""llvm-mingw provisioning for the `windows`/`arm64` usermod target only
(**D18**) -- pinned in resources/usermod.toml's own `[llvm-mingw]` table,
same shape and same reasoning as `emsdk.py`'s own `[emsdk]` table (a
literal version pin, not floating on "latest").

`x64`/`x86` do not use this: both cross-compile with a plain
apt-installed mingw-w64 GCC (`build.py`'s `WINDOWS_ARCH_SETTINGS`) --
zero extra flags needed, and it is the exact toolchain upstream
MicroPython's own CI uses for the same port. `arm64` cannot follow: no
Linux distro packages a GCC targeting `aarch64-w64-mingw32` at all. This
module resolves the one real alternative (mingw-w64's own docs point at
it by name): `llvm-mingw`, a Clang/LLD-based mingw-w64 toolchain whose
Linux-hosted release tarball can cross-compile to all four Windows
architectures, ARM64 included -- verified live against a real v1.28.0
checkout (`docs/BACKLOG.md`'s D18 has the full proof).

Deliberately not `toolchains.py`'s `ToolchainSpec`/`resolve()` shape,
same reasoning as `emsdk.py`: that machinery expects one apt-installable
package as the fallback when no tarball is pinned (`x86`'s own "cannot
provision itself" case), which does not apply here -- there is no apt
package for this target at all, only the tarball.
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
    sole_directory,
    verify_sha256,
)


class LlvmMingwError(Exception):
    pass


def _host_platform_key() -> str:
    os_name = {"linux": "linux"}.get(platform.system().lower())
    arch = {"x86_64": "x64", "amd64": "x64"}.get(platform.machine().lower())
    if os_name is None or arch is None:
        raise LlvmMingwError(
            f"unsupported host for llvm-mingw: {platform.system()}/"
            f"{platform.machine()} (only Linux x86_64 is pinned today -- "
            f"mstorsjo/llvm-mingw also publishes a linux-aarch64-hosted "
            f"build, not pinned here since nothing exercises it yet)"
        )
    return f"{os_name}-{arch}"


@dataclass(frozen=True)
class ResolvedLlvmMingw:
    install_dir: Path

    def env(self, base: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(os.environ if base is None else base)
        bin_dir = self.install_dir / "bin"
        env["PATH"] = os.pathsep.join([str(bin_dir), env.get("PATH", "")])
        return env


def resolve_llvm_mingw(
    *, root: Path | None = None, quiet: bool = False
) -> ResolvedLlvmMingw:
    """Download (or reuse a cached) pinned llvm-mingw release for this host."""
    data = usermod_data()["llvm-mingw"]
    key = _host_platform_key()
    try:
        platform_data = data["platform"][key]
    except KeyError:
        raise LlvmMingwError(
            f"no pinned llvm-mingw build for host {key!r}. Known: "
            f"{', '.join(sorted(data['platform']))}"
        ) from None

    version = data["version"]
    dest = (root or cache_root()) / "llvm-mingw" / version / key

    def populate(staging: Path) -> Path:
        archive = staging / Path(platform_data["url"]).name
        download_file(platform_data["url"], archive, quiet=quiet)
        verify_sha256(archive, platform_data["sha256"])
        extract_archive(archive, staging)
        archive.unlink()
        return sole_directory(staging, f"the llvm-mingw {version} tarball")

    result, was_cached = cached_dir(dest, populate, force=False)
    if was_cached and not quiet:
        print(f"  llvm-mingw {version} ({key}): cached at {result}")
    return ResolvedLlvmMingw(install_dir=result)
