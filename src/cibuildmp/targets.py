"""Build targets: architectures, .mpy ABI versions, and build identifiers.

Nothing here touches the filesystem or the network -- deriving the set of
identifiers a config selects has to stay fast enough to run as its own CI
job whose only output is a matrix (see cli.print_build_identifiers), so it
must not need a MicroPython checkout.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

# ── Architectures ─────────────────────────────────────────────────────────
# The ten ARCH values py/dynruntime.mk actually accepts, with the CROSS
# prefix each one selects there. Read straight off dynruntime.mk's own
# ifeq chain -- ten arches, but only five distinct toolchains.
#
# No aarch64: dynruntime.mk has no ARCH=aarch64 branch at all as of
# MicroPython v1.28, so natmod cannot target it under any configuration.
NATMOD_CROSS: dict[str, str] = {
    "x86": "",  # host gcc, -m32
    "x64": "",  # host gcc
    "armv6m": "arm-none-eabi-",
    "armv7m": "arm-none-eabi-",
    "armv7emsp": "arm-none-eabi-",
    "armv7emdp": "arm-none-eabi-",
    "xtensa": "xtensa-lx106-elf-",
    "xtensawin": "xtensa-esp32-elf-",
    "rv32imc": "riscv64-unknown-elf-",
    "rv64imc": "riscv64-unknown-elf-",
}

NATMOD_ARCHS: tuple[str, ...] = tuple(NATMOD_CROSS)

# ── .mpy ABI ──────────────────────────────────────────────────────────────
# MicroPython release tag -> "<MPY_VERSION>.<MPY_SUB_VERSION>", read out of
# py/persistentcode.h at that tag.
#
# This is the compatibility axis, and it is deliberately not the release
# tag: a native .mpy loads into any runtime whose MPY_VERSION *and*
# MPY_SUB_VERSION both match (py/persistentcode.h's own rule -- a
# bytecode-only .mpy needs only the former). ABI 6.3 alone spans v1.23.0
# through v1.29.0-preview, so pinning a matrix to a release tag would claim
# far narrower compatibility than the artifact actually has.
#
# A table rather than a lookup in the checkout because identifier
# generation must work with no checkout at all. Tags missing here are not
# an error: see abi_for_tag().
MPY_ABI: dict[str, str] = {
    "v1.20.0": "6.1",
    "v1.21.0": "6.1",
    "v1.22.0-preview": "6.1",
    "v1.22.0": "6.2",
    "v1.22.1": "6.2",
    "v1.22.2": "6.2",
    "v1.23.0-preview": "6.2",
    "v1.23.0": "6.3",
    "v1.24.0-preview": "6.3",
    "v1.24.0": "6.3",
    "v1.24.1": "6.3",
    "v1.25.0-preview": "6.3",
    "v1.25.0": "6.3",
    "v1.26.0-preview": "6.3",
    "v1.26.0": "6.3",
    "v1.26.1": "6.3",
    "v1.27.0-preview": "6.3",
    "v1.27.0": "6.3",
    "v1.28.0-preview": "6.3",
    "v1.28.0": "6.3",
    "v1.29.0-preview": "6.3",
}

# Used when a tag is not in MPY_ABI. Every release since v1.23.0 has been
# 6.3, so assuming it for an unknown (i.e. newer, or a branch name) tag is
# right far more often than it is wrong -- and when it is wrong the build
# catches it: the arch/ABI actually encoded in each produced .mpy header is
# verified against its identifier before the file is collected.
LATEST_KNOWN_ABI = "6.3"


# ── Runners ───────────────────────────────────────────────────────────────
# Which GitHub Actions runner a target needs.
#
# For natmod this is genuinely one value: every one of the ten arches is a
# cross-compile that runs on x86-64 Linux, so nothing here forces a job per
# target the way building a macOS wheel forces a macOS runner in
# cibuildwheel. That absence is why the default is a single job looping over
# targets (D9) rather than a matrix leg per identifier -- fetching
# MicroPython and building mpy-cross are identical for all ten and get paid
# once instead of ten times.
#
# usermod is where this table starts earning its keep (aarch64/armhf on
# ubuntu-24.04-arm, windows-latest, ...), which is also when the matrix
# generator becomes load-bearing rather than optional.
NATMOD_RUNNER = "ubuntu-latest"


def default_runner(mode: str, arch: str) -> str:
    del arch  # every natmod arch cross-compiles on the same runner
    if mode == "natmod":
        return NATMOD_RUNNER
    raise ValueError(f"no runner mapping for build mode {mode!r}")


class UnknownArchError(ValueError):
    pass


def abi_for_tag(tag: str, override: str | None = None) -> str:
    """Return the .mpy ABI ("6.3") a MicroPython tag produces."""
    if override is not None:
        return override
    return MPY_ABI.get(tag, LATEST_KNOWN_ABI)


def is_abi_known(tag: str) -> bool:
    """False when abi_for_tag() had to fall back to LATEST_KNOWN_ABI."""
    return tag in MPY_ABI


@dataclass(frozen=True)
class Target:
    """One build: an identifier plus the axes it decodes back into."""

    abi: str  # "6.3"
    mode: str  # "natmod"
    arch: str  # "armv7emsp"

    @property
    def identifier(self) -> str:
        # Shaped after cibuildwheel's cp311-manylinux_x86_64, i.e.
        # {ABI}-{platform}_{arch}, with '-' throughout so that both
        # "mpy6.3-*" and "*-armv7em*" are useful globs.
        return f"mpy{self.abi}-{self.mode}-{self.arch}"

    @property
    def cross(self) -> str:
        """The CROSS prefix dynruntime.mk will use for this arch."""
        return NATMOD_CROSS[self.arch]

    @property
    def default_runner(self) -> str:
        """The runner this target builds on, absent a `runs-on` override."""
        return default_runner(self.mode, self.arch)

    def __str__(self) -> str:
        return self.identifier


def natmod_targets(archs: list[str], abi: str) -> list[Target]:
    """Build a Target per arch, preserving NATMOD_ARCHS order."""
    unknown = [a for a in archs if a not in NATMOD_CROSS]
    if unknown:
        raise UnknownArchError(
            f"unknown natmod arch(es): {', '.join(sorted(unknown))}. "
            f"py/dynruntime.mk supports: {', '.join(NATMOD_ARCHS)}"
        )
    selected = set(archs)
    return [
        Target(abi=abi, mode="natmod", arch=a) for a in NATMOD_ARCHS if a in selected
    ]


# ── Selectors ─────────────────────────────────────────────────────────────


def parse_selector(value: str | list[str] | None) -> list[str]:
    """Accept either a space-separated string or a list of globs."""
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    return [str(v) for v in value]


def matches(identifier: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(identifier, p) for p in patterns)


def select(
    targets: list[Target], build: str | list[str], skip: str | list[str]
) -> list[Target]:
    """Apply build/skip globs, skip last -- same order as cibuildwheel."""
    build_patterns = parse_selector(build) or ["*"]
    skip_patterns = parse_selector(skip)
    return [
        t
        for t in targets
        if matches(t.identifier, build_patterns)
        and not matches(t.identifier, skip_patterns)
    ]
