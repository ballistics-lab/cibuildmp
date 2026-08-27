import pytest

from cibuildmp.platforms.natmod.targets import (
    NATMOD_ARCH_NATIVE_CODE,
    NATMOD_ARCHS,
    Target,
    UnknownAbiError,
    UnknownArchError,
    UnknownTagError,
    abi_for_tag,
    natmod_targets,
    newest_tag_for_abi,
    parse_arch_flags,
    resolve_abi_selector,
    resolve_arch_flags,
    resolve_micropython_tags,
)
from cibuildmp.selector import parse_selector, select


def test_identifier_shape():
    t = Target(abi="6.3", mode="natmod", arch="armv7emsp")
    assert t.identifier == "mpy6.3-natmod-armv7emsp"


def test_identifier_carries_arch_flags_only_when_set():
    plain = Target(abi="6.3", mode="natmod", arch="rv32imc")
    assert plain.identifier == "mpy6.3-natmod-rv32imc"
    flagged = Target(abi="6.3", mode="natmod", arch="rv32imc", arch_flags=3)
    assert flagged.identifier == "mpy6.3-natmod-rv32imc+0x3"


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


def test_natmod_targets_arch_flags_land_only_on_rv32imc():
    targets = natmod_targets(["rv32imc", "rv64imc", "x64"], "6.3", "v1.28.0", [3])
    by_arch = {t.arch: t.arch_flags for t in targets}
    assert by_arch == {"rv32imc": 3, "rv64imc": 0, "x64": 0}


def test_natmod_targets_one_rv32imc_target_per_arch_flags_entry():
    # "build every arch-flags variant" is distinct from "build every arch":
    # each entry produces its own rv32imc identifier, side by side.
    targets = natmod_targets(["rv32imc"], "6.3", "v1.28.0", [0, 1, 3])
    assert [t.identifier for t in targets] == [
        "mpy6.3-natmod-rv32imc",
        "mpy6.3-natmod-rv32imc+0x1",
        "mpy6.3-natmod-rv32imc+0x3",
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
    # to LATEST_KNOWN_ABI; it is now a loud UnknownTagError instead, since
    # resources/build-platforms.toml names every tag this project has
    # actually verified.
    with pytest.raises(UnknownTagError, match="v1.99.0"):
        abi_for_tag("v1.99.0")
    # An explicit override still bypasses the lookup entirely.
    assert abi_for_tag("v1.99.0", override="7.0") == "7.0"


def test_resolve_micropython_tags_dedups_by_abi():
    # v1.23.0 and v1.28.0 both produce ABI 6.3 -- the second is redundant,
    # not a second build.
    assert resolve_micropython_tags(["v1.23.0", "v1.28.0"]) == [("v1.23.0", "6.3")]


def test_resolve_micropython_tags_keeps_distinct_abis():
    # v1.22.0 (6.2) and v1.28.0 (6.3) are a real ABI boundary.
    assert resolve_micropython_tags(["v1.22.0", "v1.28.0"]) == [
        ("v1.22.0", "6.2"),
        ("v1.28.0", "6.3"),
    ]


def test_resolve_micropython_tags_honours_override():
    # An explicit mpy-abi override makes every listed tag resolve to the
    # same ABI, so only the first is kept.
    assert resolve_micropython_tags(["v1.22.0", "v1.28.0"], override="7.0") == [
        ("v1.22.0", "7.0")
    ]


def test_newest_tag_for_abi_reads_the_table_backwards():
    # ABI 6.3 spans v1.23.0..v1.30.0-preview in resources/build-platforms.toml
    # (record 0052, Track C) -- the newest tag is the one this resolves
    # to, not the first one listed. Every superseded preview except the
    # single newest one is pruned from that table (A6's own "only the
    # most recent preview tag is pinned" rule), so 6.3's newest tag is
    # now the still-open v1.30.0-preview, not v1.29.0's own real release.
    assert newest_tag_for_abi("6.3") == "v1.30.0-preview"
    # 6.2 and 6.1 are each fully covered by a real, non-preview release
    # tag (v1.22.2, v1.21.0) already present in build-platforms.toml, so
    # pruning the old previews that used to answer this in natmod.toml
    # (v1.23.0-preview, v1.22.0-preview) does not lose anything real --
    # it resolves to the actual shipped release instead.
    assert newest_tag_for_abi("6.2") == "v1.22.2"
    assert newest_tag_for_abi("6.1") == "v1.21.0"


def test_newest_tag_for_abi_unknown_abi_is_none():
    assert newest_tag_for_abi("9.9") is None


def test_resolve_abi_selector_states_the_axis_directly():
    # The direction resolve_micropython_tags() cannot run: ABIs in, tags
    # out, each resolved to its own newest known tag.
    assert resolve_abi_selector(["6.3", "6.2"]) == [
        ("v1.30.0-preview", "6.3"),
        ("v1.22.2", "6.2"),
    ]


def test_resolve_abi_selector_rejects_unknown_abi():
    with pytest.raises(UnknownAbiError, match="unknown .mpy ABI '9.9'"):
        resolve_abi_selector(["9.9"])


def test_natmod_targets_preserve_canonical_order():
    targets = natmod_targets(["rv64imc", "x64", "armv6m"], "6.3", "v1.28.0")
    assert [t.arch for t in targets] == ["x64", "armv6m", "rv64imc"]
    assert all(t.tag == "v1.28.0" for t in targets)


def test_unknown_arch_rejected():
    with pytest.raises(UnknownArchError, match="aarch64"):
        natmod_targets(["x64", "aarch64"], "6.3", "v1.28.0")


def test_arch_not_available_for_this_specific_tag_is_rejected():
    # record 0052, Track C: rv32imc/rv64imc are real dynruntime.mk arches
    # (accepted by test_unknown_arch_rejected's own check above), but
    # v1.23.0's own source tree predates both -- rv32imc arrives at
    # v1.24.0, rv64imc at v1.27.0, verified live against
    # resources/build-platforms.toml. This is the exact bug the table
    # exists to catch before a real build fails deep inside dynruntime.mk.
    with pytest.raises(UnknownArchError, match="not available for.*v1.23.0"):
        natmod_targets(["rv32imc"], "6.3", "v1.23.0")
    # x64/x86/armv6m are all real for v1.23.0 -- no false positive from
    # the same check.
    targets = natmod_targets(["x64", "armv6m"], "6.3", "v1.23.0")
    assert {t.arch for t in targets} == {"x64", "armv6m"}


def test_parse_selector_accepts_both_forms():
    assert parse_selector("a b") == ["a", "b"]
    assert parse_selector(["a", "b"]) == ["a", "b"]
    assert parse_selector(None) == []


def test_select_globs():
    targets = natmod_targets(list(NATMOD_ARCHS), "6.3", "v1.28.0")
    assert [t.arch for t in select(targets, "*-armv7em*", "")] == [
        "armv7emsp",
        "armv7emdp",
    ]
    assert [t.arch for t in select(targets, "mpy6.3-*", "*-xtensa*")] == [
        a for a in NATMOD_ARCHS if not a.startswith("xtensa")
    ]
    # skip is applied after build, and wins
    assert select(targets, "*-x64", "*-x64") == []
