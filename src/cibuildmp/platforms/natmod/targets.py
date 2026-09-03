"""Build targets: architectures, .mpy ABI versions, and build identifiers.

Nothing here touches the filesystem or the network -- deriving the set of
identifiers a config selects has to stay fast enough to run as its own CI
job whose only output is a matrix (see cli.print_build_identifiers), so it
must not need a MicroPython checkout.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ...resources import build_platforms_data, natmod_data
from ...toolchain_fetch import IMAGE_CROSS_PREFIX

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

# (tag, arch) -> that row's own base identifier, straight from
# `resources/build-platforms.toml`'s own rows -- matched against a real
# fact, not reconstructed by a Python f-string. `identifier_format =
# "mpy{mpy}-{tag}-{arch}"` (the file's own header) is the single place
# that format is spelled out; every row was regenerated from it. Keyed by
# (tag, arch), not (abi, arch): tag *is* part of the identifier (a live,
# user-caught correction of this record's own earlier A2 decision to drop
# it -- keeping it is what makes every row a genuinely distinct, matchable
# fact with no collisions, instead of several tags sharing one ABI
# collapsing onto one identifier and needing an invented "which tag wins"
# rule). `Target.identifier` below looks this up rather than rebuilding
# it -- the same shape cibuildwheel's own `PythonConfiguration.identifier`
# has (a literal field read from `resources/build-platforms.toml`,
# confirmed by reading `cibuildwheel/platforms/linux.py` directly, not
# recalled).
_IDENTIFIER_BY_TAG_ARCH: dict[tuple[str, str], str] = {
    (row["tag"], row["arch"]): row["identifier"] for row in _NATMOD_ROWS
}

MPY_ABI: dict[str, str] = {row["tag"]: row["mpy"] for row in _NATMOD_ROWS}

# Toolchain-fetch wiring ([0086]/[0089]): `(tag, arch) -> version`, for
# every arch whose own image is one of the two `toolchain_fetch.
# IMAGE_CROSS_PREFIX` names -- `build-platforms.toml`'s own `gcc` field,
# already real ([0084]'s own live compiler check), even though nothing
# read it for natmod before this.
_NATMOD_TOOLCHAIN_VERSION_BY_TAG_ARCH: dict[tuple[str, str], str] = {
    (row["tag"], row["arch"]): row["gcc"]
    for row in _NATMOD_ROWS
    if row.get("gcc")
    and build_platforms_data()["natmod"]["images"].get(row["arch"])
    in IMAGE_CROSS_PREFIX
}


def natmod_toolchain(tag: str, arch: str) -> tuple[str, str] | None:
    """`(cross, version)` for `arch`'s own cross-toolchain fetch at
    `tag`, or `None` when `arch` needs no fetch at all -- `x86`/`x64`
    (native, apt-provisioned `natmod_host`, record 0058's own "why
    `natmod_host` is not just a manylinux image") and `xtensawin`/
    `xtensa` (`xtensa_esp`/`xtensa_lx106` still bake their own single
    toolchain -- verified live this session that `xtensawin`'s own
    version needs no per-tag resolution at all, see [0086]'s own
    addendum). `KeyError` for a `(tag, arch)` this table has never
    walked, on one of the two arches that do need a fetch -- the same
    class of caller error `rp2_toolchain()`'s own docstring already
    covers.
    """
    image = build_platforms_data()["natmod"]["images"].get(arch)
    cross = IMAGE_CROSS_PREFIX.get(image or "")
    if cross is None:
        return None
    return cross, _NATMOD_TOOLCHAIN_VERSION_BY_TAG_ARCH[(tag, arch)]


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
            f"-- run bin/refresh_natmod_archs.py (it walks every tag and takes "
            f"no arguments) and merge the rows for {tag} into that file."
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
    """The numerically newest entry in known_abis() -- what a `build`
    glob names when it wants "the current release" without pinning a
    literal tag (`mpy{newest_known_abi()}-*`), a derived value that
    follows `resources/build-platforms.toml`'s own refreshes rather than
    a literal tag string needing a manual bump on every release. There is
    no implicit default `build` narrows to on its own any more (record
    0052's own live-caught correction): an unconfigured `build` selects
    nothing at all, not "the newest known ABI."
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
    # The MicroPython tag actually fetched and built to produce this
    # target, and part of the identifier -- see `identifier` below, whose
    # own comment records the live correction that put it there. This
    # comment said "not part of the identifier" for as long as that
    # correction went unapplied here,
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
        # Matched against `_IDENTIFIER_BY_TAG_ARCH` (a real row's own
        # `identifier` field), not rebuilt -- record 0052's own live
        # finding, cross-checked against cibuildwheel's real
        # `PythonConfiguration.identifier` (a literal field, never
        # computed). Keyed by `(tag, arch)`: tag is part of the identifier
        # (a live correction of this record's own earlier A2 decision to
        # drop it -- every row is then a genuinely distinct fact, no two
        # tags ever collapsing onto one identifier). `KeyError` here means
        # a `Target` was constructed for a `(tag, arch)` pair
        # `build-platforms.toml` has never walked -- every real caller
        # only ever builds one from `natmod_all_targets()`, itself reading
        # straight off real rows, so this can only fire for a hand-built
        # `Target` in a test, and should.
        #
        # arch_flags stays a suffix appended here, not a stored fact: it
        # is config-driven (`arch-flags = [...]`), not something a real
        # MicroPython tag's own history could record -- every row's own
        # `arch_flags` column is `0` unconditionally, confirmed by
        # inspection, because it never varied per (tag, arch) pair to
        # begin with.
        base = _IDENTIFIER_BY_TAG_ARCH[(self.tag, self.arch)]
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


def natmod_all_targets(rv32imc_arch_flags: Sequence[int] = (0,)) -> list[Target]:
    """One `Target` per real `(tag, arch)` row in `build-platforms.toml`
    -- the raw fact list `Options.targets()`/`all_targets()` glob-match
    `build`/`skip`/`[override]` against directly, the same shape
    cibuildwheel's own `get_python_configurations()` has: filter a
    literal list read straight from data (`PythonConfiguration(**item)
    for item in config_dicts`, confirmed by reading
    `cibuildwheel/platforms/linux.py` directly, not recalled). No
    separate "is this arch available for this tag" table is consulted
    here -- a row existing at all already answers that, so nothing here
    can admit a combination the file has never verified.

    rv32imc rows are expanded by `rv32imc_arch_flags`, a real,
    config-driven variant axis no row can pre-declare: every row's own
    `arch_flags` column is `0` unconditionally (it never varied per
    `(tag, arch)` pair to begin with). Every other arch's row produces
    exactly one `Target`.
    """
    result: list[Target] = []
    for row in _NATMOD_ROWS:
        if row["arch"] == "rv32imc":
            result.extend(
                Target(abi=row["mpy"], arch="rv32imc", tag=row["tag"], arch_flags=f)
                for f in rv32imc_arch_flags
            )
        else:
            result.append(Target(abi=row["mpy"], arch=row["arch"], tag=row["tag"]))
    return result


# A tag looks like "v1.30.0-preview" or "v1.24.0" -- MicroPython's own
# release-tag shape, matched against a `build`/`skip` pattern string
# itself (not against any one target) to tell "the user named a specific
# tag" apart from "the user wrote a broad pattern and expects the newest
# one". A plain regex, not a lookup against known tags: a config naming a
# tag this project has not walked yet is still a tag-shaped pattern (and
# will simply match nothing, `check_reachable()`'s own job to catch), not
# grounds to treat it as "no tag named at all".
_TAG_SHAPE = re.compile(r"v\d+\.\d+(?:\.\d+)?(?:-preview)?")


def selector_names_a_tag(patterns: Sequence[str]) -> bool:
    """Whether any of `build`'s own glob patterns literally names a
    MicroPython tag. If none do, `narrow_to_newest_tag()` below treats a
    pattern matching more than one tag for the same `(abi, arch, arch_flags)`
    as intentionally broad ("give me whichever tag is newest"), not
    ambiguous; if at least one does, every match is trusted as-is, tag
    and all, including a wildcard's own multiple real matches within that
    named tag.
    """
    return any(_TAG_SHAPE.search(p) for p in patterns)


def _is_stable_release(tag: str) -> bool:
    """A real release tag, not a preview (e.g. `v1.30.0-preview`) -- the
    same suffix `_tag_sort_key()` already parses out, named here for its
    own meaning rather than its own sort-order role."""
    return "-" not in tag.removeprefix("v")


def newest_stable_tag_for_abi(abi: str) -> str | None:
    """Like `newest_tag_for_abi()`, but skipping preview tags whenever a
    real release is also known for this ABI -- what `narrow_to_newest_tag()`
    resolves an unpinned `build` glob to. Only ever returns a preview tag
    when every tag this project has verified for `abi` is one (an ABI
    walked so far only against an in-progress preview)."""
    candidates = [tag for tag, a in MPY_ABI.items() if a == abi]
    if not candidates:
        return None
    stable = [t for t in candidates if _is_stable_release(t)]
    return max(stable or candidates, key=_tag_sort_key)


def narrow_to_newest_tag(targets: Sequence[Target]) -> list[Target]:
    """One `Target` per distinct `(abi, arch, arch_flags)`, keeping
    whichever candidate carries the newest `tag` -- what a `build`
    pattern that never names a tag (`selector_names_a_tag()` false) means
    by "give me this arch", now that tag is part of the identifier and
    several real tags can otherwise match one arch at once.

    A stable release always beats a preview sharing the same group, even
    a numerically older one -- a config that never pins a tag lands on
    whichever release this project has most recently *verified as
    stable* for that arch, not on whatever preview happens to be newest
    (live-caught: `v1.30.0-preview` outranking `v1.29.0` by version
    number alone put an unstable, still-open tag in the driver's seat of
    every unpinned `build` glob). Only falls back to a preview when it is
    the only candidate a given `(abi, arch, arch_flags)` group has at
    all -- an ABI verified so far only against an in-progress preview
    still has to resolve to *something*.
    """
    best: dict[tuple[str, str, int], Target] = {}
    order: list[tuple[str, str, int]] = []
    for t in targets:
        key = (t.abi, t.arch, t.arch_flags)
        if key not in best:
            order.append(key)
            best[key] = t
            continue
        current = best[key]
        t_stable = _is_stable_release(t.tag)
        current_stable = _is_stable_release(current.tag)
        if t_stable != current_stable:
            if t_stable:
                best[key] = t
        elif _tag_sort_key(t.tag) > _tag_sort_key(current.tag):
            best[key] = t
    return [best[k] for k in order]


# Selector mechanism (parse_selector/matches/select) moved to
# cibuildmp.selector in 0051 -- it was hand-duplicated in
# usermod/targets.py, which is exactly the shape record 0048's drift
# came from. Import from there instead of from here.
