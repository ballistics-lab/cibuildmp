"""Build targets: architectures, .mpy ABI versions, and build identifiers.

Nothing here touches the filesystem or the network -- deriving the set of
identifiers a config selects has to stay fast enough to run as its own CI
job whose only output is a matrix (see cli.print_build_identifiers), so it
must not need a MicroPython checkout.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..resources import natmod_data

# ── Architectures ─────────────────────────────────────────────────────────
# Both tables below are transcriptions of MicroPython's own source, and both
# live in resources/natmod.toml rather than here -- see resources.py for
# why pinned data is kept out of the source.
#
#   [arch]     py/dynruntime.mk's ifeq chain: the ten ARCH values it accepts
#              and the CROSS prefix each selects. Ten arches, five toolchains.
#   [mpy-abi]  py/persistentcode.h's MPY_VERSION/MPY_SUB_VERSION per tag.
_ARCH_TABLE: dict[str, dict[str, Any]] = natmod_data()["arch"]

# The ten `ARCH` values `py/dynruntime.mk` accepts. Only the keys, since
# record 0050: the table used to carry each arch's `CROSS` prefix too,
# read by nothing but a display column, and MicroPython v1.29.0 made
# those values wrong (`x86` moved from an empty prefix to
# `i686-linux-gnu-`, `x64` to `x86_64-linux-gnu-`). Wrong data that only
# reaches a log line is still wrong data, and the image supplies every
# prefix under the name dynruntime.mk expects anyway.
NATMOD_ARCH_NATIVE_CODE: dict[str, int] = {
    arch: row["native-code"] for arch, row in _ARCH_TABLE.items()
}

NATMOD_ARCHS: tuple[str, ...] = tuple(NATMOD_ARCH_NATIVE_CODE)

# The MP_NATIVE_ARCH_* code tools/mpy_ld.py bakes into a native .mpy's own
# header. Used to verify a produced file against the identifier it was built
# for -- see build.verify_output().
NATIVE_ARCH_CODE: dict[str, int] = {
    arch: row["native-code"] for arch, row in _ARCH_TABLE.items()
}

# rv32imc's named ARCH_FLAGS= values (mpy_ld.py's own RV32_EXTENSIONS).
# Nothing else accepts arch-flags at all -- see parse_arch_flags().
RV32_ARCH_FLAGS: dict[str, int] = dict(natmod_data()["arch-flags"]["rv32imc"])

# ── .mpy ABI ──────────────────────────────────────────────────────────────
_ABI_TABLE: dict[str, str] = dict(natmod_data()["mpy-abi"])

# Used when a tag is not listed. Every release since v1.23.0 has been 6.3,
# so assuming the latest for an unknown (i.e. newer, or a branch name) tag
# is right far more often than it is wrong -- and when it is wrong the build
# catches it: the ABI actually encoded in each produced .mpy header is
# verified against its identifier before the file is collected.
LATEST_KNOWN_ABI: str = _ABI_TABLE.pop("latest")

MPY_ABI: dict[str, str] = _ABI_TABLE


# ── Runners ───────────────────────────────────────────────────────────────
# Which GitHub Actions runner a target needs.
#
# For natmod this is genuinely one value: every one of the ten arches is a
class UnknownArchError(ValueError):
    pass


class UnknownAbiError(ValueError):
    pass


def abi_for_tag(tag: str, override: str | None = None) -> str:
    """Return the .mpy ABI ("6.3") a MicroPython tag produces."""
    if override is not None:
        return override
    return MPY_ABI.get(tag, LATEST_KNOWN_ABI)


def is_abi_known(tag: str) -> bool:
    """False when abi_for_tag() had to fall back to LATEST_KNOWN_ABI."""
    return tag in MPY_ABI


def parse_arch_flags(arch: str, value: str) -> int:
    """Parse an `arch-flags` config value the way mpy_ld.py's own
    validate_arch_flags() does: a bare numeric string (0b/0x/decimal), or a
    comma-separated list of named RV32 extensions (`RV32_ARCH_FLAGS`).

    Only `rv32imc` accepts this -- mpy_ld.py raises for every other arch,
    and py/persistentcode.h's mp_raw_code_load() only validates arch_flags
    for MP_NATIVE_ARCH_RV32IMC (any other arch with the bit set is an
    unconditional "incompatible .mpy file" on load).
    """
    if not value:
        return 0
    if arch != "rv32imc":
        raise UnknownArchError(
            f"arch-flags is only valid for rv32imc, not {arch!r} -- "
            f"mpy_ld.py itself rejects it for every other arch"
        )
    stripped = value.strip()
    prefix = stripped[:2].lower()
    if prefix in ("0b", "0x") or stripped.isdigit():
        base = {"0b": 2, "0x": 16}.get(prefix, 10)
        return int(stripped, base)
    flags = 0
    for flag in stripped.lower().split(","):
        if flag not in RV32_ARCH_FLAGS:
            raise UnknownArchError(
                f"unknown rv32imc arch-flag {flag!r}. Known: "
                f"{', '.join(sorted(RV32_ARCH_FLAGS))}"
            )
        flags |= RV32_ARCH_FLAGS[flag]
    return flags


def resolve_micropython_tags(
    tags: list[str], override: str | None = None
) -> list[tuple[str, str]]:
    """One (tag, abi) pair per distinct ABI `tags` resolves to.

    Building against several tags is a real use case only when they span an
    ABI boundary (py/persistentcode.h's MPY_VERSION/MPY_SUB_VERSION) --
    otherwise every one of them produces a byte-for-byte identical native
    .mpy, since the identifier (and so the output) is keyed on ABI, not tag.
    A later tag whose ABI an earlier one already covers is silently
    dropped rather than built again for no different output; order follows
    `tags`, so the kept tag is whichever came first in the config.
    """
    seen: dict[str, str] = {}
    for tag in tags:
        abi = abi_for_tag(tag, override)
        if abi not in seen:
            seen[abi] = tag
    return [(tag, abi) for abi, tag in seen.items()]


def _tag_sort_key(tag: str) -> tuple[tuple[int, ...], int, str]:
    """Order MicroPython tags newest-last, without a `packaging` dependency
    (this project has exactly two runtime deps -- pyelftools, ar -- and
    vendors rather than depends elsewhere, e.g. usermod/boards.py). Tags
    look like "v1.22.0", "v1.22.0-preview", "v1.29.0": strip the leading
    "v", split the dotted release from an optional "-suffix", and sort a
    prerelease below its own release (0 before 1) rather than lexically
    ("-preview" would otherwise sort *above* the bare release, since "-"
    is ASCII-lower than nothing at all, which happens to be right here
    but is the wrong reason).
    """
    body = tag.removeprefix("v")
    release, _, suffix = body.partition("-")
    parts = tuple(int(p) for p in release.split("."))
    return (parts, 0 if suffix else 1, suffix)


def newest_tag_for_abi(abi: str) -> str | None:
    """The newest MicroPython tag known to produce `.mpy` ABI `abi`,
    reading MPY_ABI (tag -> abi) backwards. None if no known tag maps to
    it -- MPY_ABI only records tags this project has actually checked, not
    every tag that will ever exist for a given ABI."""
    candidates = [tag for tag, a in MPY_ABI.items() if a == abi]
    if not candidates:
        return None
    return max(candidates, key=_tag_sort_key)


def resolve_abi_selector(abis: list[str]) -> list[tuple[str, str]]:
    """One (tag, abi) pair per entry in `abis` -- the axis stated directly,
    the direction resolve_micropython_tags() cannot run since MPY_ABI only
    maps tag -> abi (0051). Order follows `abis`, matching
    resolve_micropython_tags()'s own "order follows the input" contract.
    """
    result = []
    for abi in abis:
        tag = newest_tag_for_abi(abi)
        if tag is None:
            known = sorted(set(MPY_ABI.values()) | {LATEST_KNOWN_ABI})
            raise UnknownAbiError(
                f"unknown .mpy ABI {abi!r} -- no known MicroPython tag "
                f"produces it. Known ABIs: {', '.join(known)}"
            )
        result.append((tag, abi))
    return result


@dataclass(frozen=True)
class Target:
    """One build: an identifier plus the axes it decodes back into."""

    abi: str  # "6.3"
    mode: str  # "natmod"
    arch: str  # "armv7emsp"
    # The MicroPython tag actually fetched and built to produce this target
    # -- not part of the identifier (that's ABI, the compatibility axis),
    # but the build itself needs to know which checkout to run against.
    tag: str = ""
    # rv32imc's ARCH_FLAGS=, packed the way the .mpy header itself packs it
    # (RV32_ARCH_FLAGS bits OR'd together). Zero for every other arch: it is
    # part of the identifier because it is a real compatibility axis
    # dynruntime.mk supports (micropython/micropython#19479) -- two rv32imc
    # builds that differ only here are not interchangeable, so they must not
    # share an identifier.
    arch_flags: int = 0

    @property
    def identifier(self) -> str:
        # Shaped after cibuildwheel's cp311-manylinux_x86_64, i.e.
        # {ABI}-{platform}_{arch}, with '-' throughout so that both
        # "mpy6.3-*" and "*-armv7em*" are useful globs. arch_flags, when
        # present, is an opaque `+0x..` suffix rather than named flags: it
        # would otherwise have to stay in lockstep with RV32_ARCH_FLAGS to
        # remain accurate, and the identifier must still mean the same thing
        # if that table grows a flag this build predates.
        base = f"mpy{self.abi}-{self.mode}-{self.arch}"
        if self.arch_flags:
            base += f"+0x{self.arch_flags:x}"
        return base

    def __str__(self) -> str:
        return self.identifier


def natmod_targets(
    archs: list[str], abi: str, tag: str, arch_flags: Sequence[int] = (0,)
) -> list[Target]:
    """Build a Target per arch, preserving NATMOD_ARCHS order.

    `arch_flags` only ever lands on the rv32imc target(s), if `rv32imc` is
    selected -- every other arch's Target gets 0 regardless, since
    dynruntime.mk itself only accepts ARCH_FLAGS= for rv32imc. rv32imc
    itself gets one Target *per* `arch_flags` entry, not one overall --
    "build every arch-flags variant" is a real, distinct request from
    "build every arch" (both select on the same `archs`/`arch-flags` list
    shape everywhere else in this config), so a `[0x1, 0x3]` list produces
    two rv32imc identifiers, `+0x1` and `+0x3`, side by side.
    """
    unknown = [a for a in archs if a not in NATMOD_ARCH_NATIVE_CODE]
    if unknown:
        raise UnknownArchError(
            f"unknown natmod arch(es): {', '.join(sorted(unknown))}. "
            f"py/dynruntime.mk supports: {', '.join(NATMOD_ARCHS)}"
        )
    selected = set(archs)
    targets = []
    for a in NATMOD_ARCHS:
        if a not in selected:
            continue
        if a == "rv32imc":
            targets += [
                Target(abi=abi, mode="natmod", arch=a, tag=tag, arch_flags=flags)
                for flags in arch_flags
            ]
        else:
            targets.append(Target(abi=abi, mode="natmod", arch=a, tag=tag))
    return targets


# Selector mechanism (parse_selector/matches/select) moved to
# cibuildmp.selector in 0051 -- it was hand-duplicated in
# usermod/targets.py, which is exactly the shape record 0048's drift
# came from. Import from there instead of from here.
