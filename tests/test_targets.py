import pytest

from cibuildmp.platforms.natmod.targets import (
    NATMOD_ARCH_NATIVE_CODE,
    NATMOD_ARCHS,
    Target,
    UnknownArchError,
    UnknownTagError,
    abi_for_tag,
    all_tag_groups,
    known_abis,
    natmod_all_targets,
    newest_known_abi,
    newest_tag_for_abi,
    parse_arch_flags,
    resolve_arch_flags,
)
from cibuildmp.selector import parse_selector, select


def test_identifier_shape():
    # Tag is part of the identifier (a live, user-caught correction of
    # this record's own earlier A2 decision to drop it): a real
    # (tag, arch) row is a genuinely distinct fact, matched against
    # `resources/build-platforms.toml`'s own `identifier` field, not
    # rebuilt. No literal "natmod" segment, though (A2's other half,
    # unchanged) -- natmod is one platform among six sharing this exact
    # identifier shape now, not a mode this string needs to spell out.
    t = Target(abi="6.3", arch="armv7emsp", tag="v1.30.0-preview")
    assert t.identifier == "mpy6.3-v1.30.0-preview-armv7emsp"
    assert t.port == "natmod"


def test_identifier_carries_arch_flags_only_when_set():
    plain = Target(abi="6.3", arch="rv32imc", tag="v1.30.0-preview")
    assert plain.identifier == "mpy6.3-v1.30.0-preview-rv32imc"
    flagged = Target(abi="6.3", arch="rv32imc", tag="v1.30.0-preview", arch_flags=3)
    assert flagged.identifier == "mpy6.3-v1.30.0-preview-rv32imc+0x3"


def test_parse_arch_flags_numeric_forms():
    assert parse_arch_flags("rv32imc", "") == 0
    assert parse_arch_flags("rv32imc", "3") == 3
    assert parse_arch_flags("rv32imc", "0x3") == 3
    assert parse_arch_flags("rv32imc", "0b11") == 3


def test_parse_arch_flags_named_forms():
    assert parse_arch_flags("rv32imc", "zba") == 1
    assert parse_arch_flags("rv32imc", "zcmp") == 2
    assert parse_arch_flags("rv32imc", "zba,zcmp") == 3
    assert parse_arch_flags("rv32imc", "ZBA,ZCMP") == 3  # case-insensitive


def test_parse_arch_flags_rejects_unknown_flag():
    with pytest.raises(UnknownArchError, match="unknown rv32imc arch-flag"):
        parse_arch_flags("rv32imc", "not-a-flag")


def test_parse_arch_flags_rejects_every_other_arch():
    # mpy_ld.py's own validate_arch_flags() raises the same way.
    with pytest.raises(UnknownArchError, match="only valid for rv32imc"):
        parse_arch_flags("rv64imc", "zba")


def test_resolve_arch_flags_empty_means_one_zero_target():
    assert resolve_arch_flags("rv32imc", []) == [0]


def test_resolve_arch_flags_dedupes_by_resolved_value_not_raw_string():
    # "0x3" and "zba,zcmp" are two different spellings of the same
    # bitmask (zba=1, zcmp=2) -- without dedup this silently produced two
    # targets sharing one identifier (+0x3 twice), the second overwriting
    # the first's output.
    assert resolve_arch_flags("rv32imc", ["0x3", "zba,zcmp"]) == [3]


def test_resolve_arch_flags_preserves_first_seen_order():
    assert resolve_arch_flags("rv32imc", ["zcmp", "zba", "zba,zcmp"]) == [2, 1, 3]


def test_natmod_all_targets_arch_flags_land_only_on_rv32imc():
    targets = [t for t in natmod_all_targets([3]) if t.tag == "v1.30.0-preview"]
    by_arch = {t.arch: t.arch_flags for t in targets}
    assert by_arch["rv32imc"] == 3
    assert all(flags == 0 for arch, flags in by_arch.items() if arch != "rv32imc")


def test_natmod_all_targets_one_rv32imc_identifier_per_arch_flags_entry():
    # "build every arch-flags variant" is distinct from "build every arch":
    # each entry produces its own rv32imc identifier, side by side.
    targets = natmod_all_targets([0, 1, 3])
    rv32imc_ids = sorted(
        t.identifier
        for t in targets
        if t.arch == "rv32imc" and t.tag == "v1.30.0-preview"
    )
    assert rv32imc_ids == [
        "mpy6.3-v1.30.0-preview-rv32imc",
        "mpy6.3-v1.30.0-preview-rv32imc+0x1",
        "mpy6.3-v1.30.0-preview-rv32imc+0x3",
    ]


def test_ten_arches_five_toolchains():
    # Straight from py/dynruntime.mk's own ifeq chain.
    assert len(NATMOD_ARCHS) == 10
    assert len(NATMOD_ARCH_NATIVE_CODE) == 10
    assert "aarch64" not in NATMOD_ARCH_NATIVE_CODE  # dynruntime.mk has no such ARCH


def test_abi_spans_many_releases():
    # The whole reason the identifier carries the ABI and not the tag.
    for tag in ("v1.23.0", "v1.25.0", "v1.28.0"):
        assert abi_for_tag(tag) == "6.3"
    assert abi_for_tag("v1.22.0") == "6.2"
    assert abi_for_tag("v1.21.0") == "6.1"


def test_unknown_tag_is_a_hard_error_not_a_fallback():
    # record 0052, Track C: an unrecognised tag used to silently resolve
    # to a guessed ABI; it is now a loud UnknownTagError instead, since
    # resources/build-platforms.toml names every tag this project has
    # actually verified.
    with pytest.raises(UnknownTagError, match="v1.99.0"):
        abi_for_tag("v1.99.0")
    # An explicit override still bypasses the lookup entirely.
    assert abi_for_tag("v1.99.0", override="7.0") == "7.0"


def test_newest_tag_for_abi_reads_the_table_backwards():
    # ABI 6.3 spans v1.23.0..v1.30.0-preview in resources/build-platforms.toml
    # (record 0052, Track C) -- the newest tag is the one this resolves
    # to, not the first one listed. Every superseded preview except the
    # single newest one is pruned from that table (A6's own "only the
    # most recent preview tag is pinned" rule), so 6.3's newest tag is
    # now the still-open v1.30.0-preview, not v1.29.0's own real release.
    assert newest_tag_for_abi("6.3") == "v1.30.0-preview"
    # 6.2 and 6.1 are each fully covered by a real, non-preview release
    # tag (v1.22.2, v1.21.0) already present in build-platforms.toml.
    assert newest_tag_for_abi("6.2") == "v1.22.2"
    assert newest_tag_for_abi("6.1") == "v1.21.0"


def test_newest_tag_for_abi_unknown_abi_is_none():
    assert newest_tag_for_abi("9.9") is None


def test_known_abis_is_every_distinct_abi_oldest_first():
    # record 0052, A2: there is no micropython/mpy-abi config key to state
    # this any more -- known_abis() is the whole natmod version axis'
    # static domain, and build-platforms.toml records five distinct ABIs
    # across MicroPython's own history (5, 6, 6.1, 6.2, 6.3), not the
    # three resources/natmod.toml's own smaller [mpy-abi] table used to
    # know about.
    abis = known_abis()
    assert abis == ["5", "6", "6.1", "6.2", "6.3"]
    # Numeric order, not lexical -- "6" must sort before "6.1", which a
    # plain string comparison also happens to get right here, but for the
    # right reason (verified via a real multi-digit case elsewhere is not
    # needed: this project's own known ABI values never reach two digits
    # in either component).
    assert abis == sorted(abis, key=lambda a: tuple(int(p) for p in a.split(".")))


def test_newest_known_abi_is_the_numeric_maximum():
    assert newest_known_abi() == "6.3"


def test_all_tag_groups_covers_every_known_abi():
    groups = all_tag_groups()
    assert dict(groups) == {
        "v1.18": "5",
        "v1.19.1": "6",
        "v1.21.0": "6.1",
        "v1.22.2": "6.2",
        "v1.30.0-preview": "6.3",
    }


def test_natmod_all_targets_is_the_raw_row_list_not_gated_up_front():
    # record 0052's own live-caught correction: no separate "is this arch
    # available for this ABI's tag" table is consulted here any more --
    # rv32imc/rv64imc genuinely predate some tags (v1.23.0 has neither),
    # and that shows up simply as those rows not existing, not as an
    # error raised while building the candidate list.
    targets = natmod_all_targets()
    v1_23 = {t.arch for t in targets if t.tag == "v1.23.0"}
    assert "rv32imc" not in v1_23
    assert "rv64imc" not in v1_23
    assert {"x64", "x86", "armv6m"} <= v1_23


def test_every_row_is_its_own_distinct_identifier_no_collapsing_needed():
    # record 0052's own live, user-caught correction: with tag part of
    # the identifier, several tags mapping to one ABI (6.3 spans
    # v1.23.0..v1.30.0-preview) no longer collide on one identifier --
    # each row stays its own separately matchable fact.
    targets = natmod_all_targets()
    ids = [t.identifier for t in targets]
    assert len(ids) == len(set(ids))
    assert "mpy6.3-v1.23.0-x64" in ids
    assert "mpy6.3-v1.30.0-preview-x64" in ids


def test_parse_selector_accepts_both_forms():
    assert parse_selector("a b") == ["a", "b"]
    assert parse_selector(["a", "b"]) == ["a", "b"]
    assert parse_selector(None) == []


def test_select_globs_against_one_tags_own_row_set():
    targets = [
        t for t in natmod_all_targets() if t.tag == "v1.30.0-preview" and t.abi == "6.3"
    ]
    assert sorted(t.arch for t in select(targets, "*-armv7em*", "")) == [
        "armv7emdp",
        "armv7emsp",
    ]
    assert sorted(
        t.arch for t in select(targets, "mpy6.3-v1.30.0-preview-*", "*-xtensa*")
    ) == sorted(a for a in NATMOD_ARCHS if not a.startswith("xtensa"))
    # skip is applied after build, and wins
    assert select(targets, "*-x64", "*-x64") == []
