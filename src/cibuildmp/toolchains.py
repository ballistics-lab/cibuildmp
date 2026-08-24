"""Resolving the cross toolchain each natmod arch needs.

Two strategies, tried in order:

  host      -- the toolchain is already on PATH. Always tried first: it is
               what CI does today (the build-natmod action apt-installs
               these), it costs nothing, and it keeps a contributor's own
               compiler in play rather than silently substituting another.
  download  -- fetch a pinned tarball into the cache. This is what makes
               `cibuildmp` work on a laptop without mutating the host, which
               is most of the point of the tool existing (D3).

Docker is deliberately absent for natmod: every arch here is a cross-compile
that runs on the build host, so a container buys isolation but no capability.
It is planned for usermod, where port builds have real system dependencies.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .resources import natmod_data
from .sources import (
    SourceError,
    cache_root,
    cached_dir,
    download_file,
    extract_archive,
    sole_directory,
    verify_sha256,
)
from .targets import NATMOD_CROSS


class ToolchainError(Exception):
    pass


@dataclass(frozen=True)
class Download:
    url: str
    sha256: str
    # Version string, only used to key the cache directory.
    version: str


@dataclass(frozen=True)
class ToolchainSpec:
    """One cross toolchain, however many arches share it."""

    name: str
    # The CROSS prefix py/dynruntime.mk hardcodes for the arches using this
    # toolchain. See NATMOD_CROSS.
    expected_prefix: str
    # The prefix the downloadable tarball actually ships. Where this differs
    # from expected_prefix, the difference is reconciled with a CROSS= make
    # override -- see ResolvedToolchain.make_overrides.
    provided_prefix: str
    download: Download | None
    # Named in the error message when neither strategy can supply it.
    apt_packages: str
    # Extra flags for the "can this compiler actually build for the target"
    # probe. Empty means existence on PATH is proof enough.
    probe_args: tuple[str, ...] = ()


def _load_toolchains() -> dict[str, ToolchainSpec]:
    """Build the spec table from resources/natmod.toml's [[toolchain]] list."""
    specs: dict[str, ToolchainSpec] = {}
    for row in natmod_data()["toolchain"]:
        url = row.get("url", "")
        specs[row["name"]] = ToolchainSpec(
            name=row["name"],
            expected_prefix=row["expected-prefix"],
            provided_prefix=row["provided-prefix"],
            apt_packages=row.get("apt-packages", ""),
            probe_args=tuple(row.get("probe-args", [])),
            download=Download(
                url=url,
                sha256=row.get("sha256", ""),
                version=row["version"],
            )
            if url
            else None,
        )
    return specs


TOOLCHAINS: dict[str, ToolchainSpec] = _load_toolchains()

# arch -> toolchain name, from the same file's [arch] table, so this and
# NATMOD_CROSS cannot drift apart. An empty name means the arch needs no
# toolchain resolved at all (x64 builds with the host gcc).
ARCH_TOOLCHAIN: dict[str, str | None] = {
    arch: (row["toolchain"] or None) for arch, row in natmod_data()["arch"].items()
}


@dataclass(frozen=True)
class ResolvedToolchain:
    strategy: str  # "none" | "host" | "download"
    prefix: str  # the prefix that actually works
    expected_prefix: str  # what dynruntime.mk would use unaided
    bin_dir: Path | None  # prepended to PATH, None when already there

    @property
    def make_overrides(self) -> list[str]:
        """`CROSS=` when the toolchain's prefix is not the one hardcoded.

        py/dynruntime.mk assigns CROSS with `=` inside a per-ARCH ifeq chain
        and never marks it `override`, so a variable given on the make
        command line wins over it -- including for the `$(shell $(CROSS)gcc
        ...)` probes evaluated during parsing.
        """
        if self.prefix != self.expected_prefix:
            return [f"CROSS={self.prefix}"]
        return []

    def env(self, base: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(os.environ if base is None else base)
        if self.bin_dir is not None:
            env["PATH"] = f"{self.bin_dir}{os.pathsep}{env.get('PATH', '')}"
        return env

    def describe(self) -> str:
        if self.strategy == "none":
            return "host gcc"
        where = f" ({self.bin_dir})" if self.bin_dir else ""
        return f"{self.prefix}gcc via {self.strategy}{where}"


def resolve(
    arch: str,
    *,
    strategy: str = "auto",
    root: Path | None = None,
    quiet: bool = False,
) -> ResolvedToolchain:
    """Find, or fetch, the toolchain `arch` needs."""
    name = ARCH_TOOLCHAIN.get(arch)
    if arch not in ARCH_TOOLCHAIN:
        raise ToolchainError(f"no toolchain mapping for arch {arch!r}")
    if name is None:
        return ResolvedToolchain("none", "", "", None)

    spec = TOOLCHAINS[name]

    if strategy in {"auto", "host"}:
        found = _find_on_path(spec)
        if found is not None:
            return found
        if strategy == "host":
            raise ToolchainError(
                f"{arch}: {spec.expected_prefix}gcc is not on PATH and "
                f"--toolchain=host forbids downloading one. Install it with: "
                f"apt install {spec.apt_packages}"
            )

    if spec.download is None:
        # x86 is the one arch that cannot provision itself: what it needs is
        # the host compiler's 32-bit runtime, not a separate cross toolchain.
        raise ToolchainError(
            f"{arch}: needs `{spec.apt_packages}` installed on this machine; "
            f"there is no toolchain tarball that can supply it"
        )

    return _download_toolchain(spec, root=root, quiet=quiet)


def _find_on_path(spec: ToolchainSpec) -> ResolvedToolchain | None:
    """Look for either prefix already on PATH, expected one first."""
    for prefix in (spec.expected_prefix, spec.provided_prefix):
        gcc = shutil.which(f"{prefix}gcc")
        if gcc and _probe(gcc, spec.probe_args):
            return ResolvedToolchain("host", prefix, spec.expected_prefix, None)
    return None


def _probe(gcc: str, args: tuple[str, ...]) -> bool:
    """Compile an empty translation unit, to check the target really works.

    Only meaningful where a compiler's presence does not imply it can build
    for the target -- x86, where the host gcc is always there but its 32-bit
    runtime may not be. Skipped entirely when no probe args are configured,
    so a cross toolchain still costs nothing to detect.
    """
    if not args:
        return True
    try:
        result = subprocess.run(
            [gcc, *args, "-xc", "-c", "-", "-o", os.devnull],
            input=b"",
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _download_toolchain(
    spec: ToolchainSpec, *, root: Path | None, quiet: bool
) -> ResolvedToolchain:
    assert spec.download is not None
    dest = (root or cache_root()) / "toolchains" / spec.name / spec.download.version

    def populate(staging: Path) -> Path:
        archive = staging / Path(spec.download.url).name  # type: ignore[union-attr]
        if not quiet:
            print(f"  {spec.name}: downloading {spec.download.version}")  # type: ignore[union-attr]
        download_file(spec.download.url, archive, quiet=quiet)  # type: ignore[union-attr]
        verify_sha256(archive, _expected_sha256(spec))
        extract_archive(archive, staging)
        archive.unlink()
        return sole_directory(staging, f"the {spec.name} tarball")

    try:
        resolved_dir, was_cached = cached_dir(dest, populate, force=False)
    except SourceError as exc:
        raise ToolchainError(f"{spec.name}: {exc}") from exc

    if was_cached and not quiet:
        print(f"  {spec.name}: cached at {resolved_dir}")

    bin_dir = _find_bin_dir(resolved_dir, spec.provided_prefix)
    return ResolvedToolchain(
        "download", spec.provided_prefix, spec.expected_prefix, bin_dir
    )


def _expected_sha256(spec: ToolchainSpec) -> str:
    """The pinned digest, or the one from the release's own .sha sidecar.

    xpack publishes `<asset>.sha` in sha256sum format next to every asset;
    micropython.org and espressif publish none, so those digests are pinned
    literally above.
    """
    assert spec.download is not None
    if spec.download.sha256:
        return spec.download.sha256

    import tempfile
    import urllib.error

    with tempfile.TemporaryDirectory() as tmp:
        sidecar = Path(tmp) / "sha"
        try:
            download_file(spec.download.url + ".sha", sidecar, quiet=True)
        except urllib.error.HTTPError as exc:
            raise ToolchainError(
                f"{spec.name}: no pinned sha256 and its .sha sidecar is unavailable ({exc})"
            ) from exc
        return sidecar.read_text().split()[0]


def _find_bin_dir(root: Path, prefix: str) -> Path:
    """Locate the bin/ holding <prefix>gcc inside an extracted toolchain.

    Searched rather than hardcoded: xpack, micropython.org and Espressif all
    lay their tarballs out differently, and a layout change would otherwise
    surface as a confusing "command not found" during make.
    """
    direct = root / "bin"
    if (direct / f"{prefix}gcc").exists():
        return direct
    for candidate in sorted(root.glob("*/bin")):
        if (candidate / f"{prefix}gcc").exists():
            return candidate
    raise ToolchainError(f"extracted {root} but found no bin/ containing {prefix}gcc")


def toolchain_for(arch: str) -> ToolchainSpec | None:
    name = ARCH_TOOLCHAIN.get(arch)
    return TOOLCHAINS[name] if name else None


def _check_tables() -> None:
    """The two tables must agree with dynruntime.mk's own CROSS values."""
    for arch, cross in NATMOD_CROSS.items():
        spec = toolchain_for(arch)
        expected = spec.expected_prefix if spec else ""
        if expected != cross:
            raise AssertionError(
                f"{arch}: NATMOD_CROSS says {cross!r} but its toolchain expects {expected!r}"
            )


_check_tables()
