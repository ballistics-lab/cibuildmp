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

from ...resources import build_platforms_data, natmod_data

# ── Architectures ─────────────────────────────────────────────────────────
# Transcribed from MicroPython's own source, and living in resources/
# natmod.toml rather than here -- see resources.py for why pinned data is
# kept out of the source.
#
#   [arch]     py/dynruntime.mk's ifeq chain: the ten ARCH values it accepts
#              and the CROSS prefix each selects. Ten arches, five toolchains.
#
# This table alone -- never gated by tag. Whether a given (tag, arch) pair
# is one dynruntime.mk source tree actually ever supported is a different
# question, answered below from resources/build-platforms.toml instead
# (record 0052's own Track C): [mpy-abi]'s old tag -> abi table and every
# arch's "available since" boundary used to live nowhere at all -- every
# arch was silently treated as buildable against every tag.
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

# ── .mpy ABI and per-tag arch availability (record 0052, Track C) ──────────
#
# Both read from resources/build-platforms.toml's own `[natmod].identifiers`
# rows -- one row per independently-verified `(tag, arch)` pair, not an
# axis product. This replaces resources/natmod.toml's own `[mpy-abi]` table
# (confirmed, not assumed: zero mismatches across every tag both tables
# know about) and its `LATEST_KNOWN_ABI` fallback, which is deleted rather
# than kept as a second, disagreeing source of "what to do for an unknown
# tag" -- an unrecognised tag is now a loud `UnknownTagError`, naming
# `bin/refresh_natmod_archs.py` as the fix, not a silent guess a real build
# might or might not catch later.
_NATMOD_ROWS: list[dict[str, Any]] = build_platforms_data()["natmod"]["identifiers"]

MPY_ABI: dict[str, str] = {row["tag"]: row["mpy"] for row in _NATMOD_ROWS}

# Which arches a given tag's own dynruntime.mk source tree actually has --
# the exact gap that let a config ask for `rv32imc` against a tag that
# predates it (not available before v1.24.0) and only find out deep inside
# a real build. Built once, from the same rows MPY_ABI above reads.
_tag_arch_sets: dict[str, set[str]] = {}
for _row in _NATMOD_ROWS:
    _tag_arch_sets.setdefault(_row["tag"], set()).add(_row["arch"])
_TAG_ARCHS: dict[str, frozenset[str]] = {
    tag: frozenset(archs) for tag, archs in _tag_arch_sets.items()
}


def archs_available_for(tag: str) -> frozenset[str]:
    """Every arch `tag`'s own dynruntime.mk source tree actually has, or
    an empty set for a tag this table has never walked. Public so
    `Options.targets()`/`all_targets()` (record 0052, A2) can filter a
    requested archs list down to what a given ABI's own tag can build
    *before* calling `natmod_targets()`, rather than letting its hard
    error fire while sweeping every known ABI by default -- most ABIs
    predate at least one arch (`rv32imc`/`rv64imc`/`xtensawin` were all
    added over time), so that sweep silently producing fewer targets for
    an older ABI is the intended, ordinary case, not a config mistake the
    way an explicit, single-tag request for an unavailable arch still is.
    """
    return _TAG_ARCHS.get(tag, frozenset())


class UnknownArchError(ValueError):
    pass


class UnknownTagError(ValueError):
    pass


def abi_for_tag(tag: str, override: str | None = None) -> str:
    """Return the .mpy ABI ("6.3") a MicroPython tag produces.

    Raises `UnknownTagError` for a tag `build-platforms.toml` has never
    walked -- no silent fallback. `bin/refresh_natmod_archs.py <tag>` is
    the fix, not a guess a real build might catch later or might not.
    """
    if override is not None:
        return override
    try:
        return MPY_ABI[tag]
    except KeyError:
        raise UnknownTagError(
            f"MicroPython tag {tag!r} is not in resources/build-platforms.toml "
            f"-- run bin/refresh_natmod_archs.py {tag} and merge the result, "
            f"or pass mpy-abi explicitly to override the lookup."
        ) from None


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


def resolve_arch_flags(arch: str, values: Sequence[str]) -> list[int]:
    """Parse every `arch-flags` list entry and dedupe by the *resolved*
    integer, not the raw string.

    `parse_arch_flags()` accepts several textual spellings for the same
    bitmask (a bare numeric string, or a comma-separated flag list) --
    two different spellings that resolve to the same integer would
    otherwise silently produce two `Target`s sharing one identifier, the
    same collision class `all_tag_groups()` avoids for ABIs below by
    working from a dict keyed on the resolved value, not the raw one.
    `dict.fromkeys` preserves first-seen order, the same "whichever came
    first" rule that function follows too.

    Empty input means "no flags requested" -- one target, `arch_flags=0`,
    not zero targets.
    """
    if not values:
        return [0]
    return list(dict.fromkeys(parse_arch_flags(arch, value) for value in values))


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


def _abi_sort_key(abi: str) -> tuple[int, ...]:
    """Order `.mpy` ABI strings ("5", "6", "6.1", ..., "6.3") oldest-first,
    the same numeric-tuple approach `_tag_sort_key()` uses for tags --
    plain string comparison gets "6" < "6.1" right by luck (a shorter
    string is a prefix of a longer one here) but would get "6.10" wrong
    against "6.2", so it is not trusted even though today's real values
    happen to work either way.
    """
    return tuple(int(p) for p in abi.split("."))


def known_abis() -> list[str]:
    """Every distinct `.mpy` ABI this project has verified against a real
    MicroPython tag, oldest first -- the natmod version axis' own static
    domain (record 0052, A2). There is no `micropython`/`mpy-abi` config
    key stating it any more; `build`/`skip` narrow it by matching
    identifiers, exactly the way `archs` already narrows `NATMOD_ARCHS`.
    """
    return sorted(set(MPY_ABI.values()), key=_abi_sort_key)


def newest_known_abi() -> str:
    """The numerically newest entry in known_abis() -- what an
    unconfigured `build` selector narrows a natmod invocation to by
    default (record 0052, A2), so a bare config keeps building only the
    newest ABI instead of every one this project has ever verified.
    Replaces `DEFAULT_MICROPYTHON`'s old role for natmod specifically: a
    derived value that follows `resources/build-platforms.toml`'s own
    refreshes rather than a literal tag string needing a manual bump on
    every release (usermod's own `DEFAULT_MICROPYTHON` is unaffected --
    A2 is natmod-only).
    """
    return max(known_abis(), key=_abi_sort_key)


def all_tag_groups() -> list[tuple[str, str]]:
    """One (tag, abi) pair per known_abis() entry, each resolved to its
    own newest known tag via newest_tag_for_abi() -- the full natmod
    version-axis domain `Options.targets()`/`all_targets()` cross with
    `archs` before `build`/`skip` narrow the result by identifier.
    Replaces `resolve_micropython_tags()`/`resolve_abi_selector()`, both
    of which took a user-declared tag/ABI list that no longer exists as a
    config key -- there is nothing left to validate or dedupe here that
    known_abis() has not already done once, up front.
    """
    result = []
    for abi in known_abis():
        tag = newest_tag_for_abi(abi)
        assert tag is not None, f"{abi!r} came from MPY_ABI itself"
        result.append((tag, abi))
    return result


@dataclass(frozen=True)
class Target:
    """One build: an identifier plus the axes it decodes back into."""

    abi: str  # "6.3"
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
        # {ABI}-{platform}_{arch} -- but with no literal "natmod" segment
        # (record 0052, A2): natmod is now one platform among six sharing
        # this exact identifier shape (`.port` below), not a special mode
        # this string needs to spell out, and dropping it is what lets
        # "mpy6.3-*" and "*-armv7em*" both stay useful, minimal globs.
        # arch_flags, when present, is an opaque `+0x..` suffix rather than
        # named flags: it would otherwise have to stay in lockstep with
        # RV32_ARCH_FLAGS to remain accurate, and the identifier must still
        # mean the same thing if that table grows a flag this build
        # predates.
        base = f"mpy{self.abi}-{self.arch}"
        if self.arch_flags:
            base += f"+0x{self.arch_flags:x}"
        return base

    @property
    def port(self) -> str:
        # Always "natmod" -- natmod is a platform among six now (record
        # 0051 points 4/6), so Target needs the same `.port` UsermodTarget
        # already has, for Phase G's own per-matched-platform override
        # validation (natmod/options.py's build_options()). Since A2
        # dropped the literal word from the identifier itself, this is now
        # the *only* place "natmod" appears on a Target at all.
        return "natmod"

    def __str__(self) -> str:
        return self.identifier


def validate_archs_recognized(archs: list[str]) -> None:
    """Raise `UnknownArchError` for any arch `dynruntime.mk` has never
    heard of at all, at any tag -- a typo, as opposed to a real arch a
    specific tag's own source tree does not have (see `natmod_targets()`'s
    own docstring for that distinction). Shared so `Options.targets()`/
    `all_targets()` (record 0052, A2) can validate `self.archs` once,
    globally, *before* filtering it per tag against `archs_available_for()`
    -- filtering first would silently swallow a genuine typo instead of
    ever reaching `natmod_targets()`'s own check, since a nonexistent arch
    is never "available" for any tag either.
    """
    unrecognized = [a for a in archs if a not in NATMOD_ARCH_NATIVE_CODE]
    if unrecognized:
        raise UnknownArchError(
            f"unknown natmod arch(es): {', '.join(sorted(unrecognized))}. "
            f"py/dynruntime.mk supports: {', '.join(NATMOD_ARCHS)}"
        )


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

    Two different ways to be an unknown arch, checked separately (record
    0052, Track C): `unrecognized` is an arch dynruntime.mk has never
    heard of at all, at any tag -- a typo. `unavailable` is a real arch
    this specific `tag`'s own source tree does not have -- `rv32imc`
    against a tag older than v1.24.0, the exact bug this table exists to
    catch instead of a real build failing deep inside `dynruntime.mk`.
    Both raise the same `UnknownArchError` a caller already has to catch
    (no new exception type), just with a message naming the real reason.
    """
    validate_archs_recognized(archs)
    available = _TAG_ARCHS.get(tag, frozenset())
    unavailable = [a for a in archs if a not in available]
    if unavailable:
        raise UnknownArchError(
            f"arch(es) not available for MicroPython {tag}: "
            f"{', '.join(sorted(unavailable))}. Available for {tag}: "
            f"{', '.join(sorted(available)) or '(none)'}"
        )
    selected = set(archs)
    targets = []
    for a in NATMOD_ARCHS:
        if a not in selected:
            continue
        if a == "rv32imc":
            targets += [
                Target(abi=abi, arch=a, tag=tag, arch_flags=flags)
                for flags in arch_flags
            ]
        else:
            targets.append(Target(abi=abi, arch=a, tag=tag))
    return targets


# Selector mechanism (parse_selector/matches/select) moved to
# cibuildmp.selector in 0051 -- it was hand-duplicated in
# usermod/targets.py, which is exactly the shape record 0048's drift
# came from. Import from there instead of from here.
