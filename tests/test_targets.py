import pytest

from cibuildmp.natmod.targets import (
    LATEST_KNOWN_ABI,
    NATMOD_ARCHS,
    NATMOD_CROSS,
    Target,
    UnknownArchError,
    abi_for_tag,
    is_abi_known,
    natmod_targets,
    parse_arch_flags,
    parse_selector,
    resolve_micropython_tags,
    select,
)


def test_identifier_shape():
    t = Target(abi="6.3", mode="natmod", arch="armv7emsp")
    assert t.identifier == "mpy6.3-natmod-armv7emsp"
    assert t.cross == "arm-none-eabi-"


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
    assert len(set(NATMOD_CROSS.values())) == 5
    assert "aarch64" not in NATMOD_CROSS  # dynruntime.mk has no such ARCH


def test_abi_spans_many_releases():
    # The whole reason the identifier carries the ABI and not the tag.
    for tag in ("v1.23.0", "v1.25.0", "v1.28.0"):
        assert abi_for_tag(tag) == "6.3"
    assert abi_for_tag("v1.22.0") == "6.2"
    assert abi_for_tag("v1.21.0") == "6.1"


def test_unknown_tag_falls_back_and_is_reported():
    assert abi_for_tag("v1.99.0") == LATEST_KNOWN_ABI
    assert not is_abi_known("v1.99.0")
    assert is_abi_known("v1.28.0")
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


def test_natmod_targets_preserve_canonical_order():
    targets = natmod_targets(["rv64imc", "x64", "armv6m"], "6.3", "v1.28.0")
    assert [t.arch for t in targets] == ["x64", "armv6m", "rv64imc"]
    assert all(t.tag == "v1.28.0" for t in targets)


def test_unknown_arch_rejected():
    with pytest.raises(UnknownArchError, match="aarch64"):
        natmod_targets(["x64", "aarch64"], "6.3", "v1.28.0")


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


def test_every_natmod_arch_shares_one_runner():
    # The premise behind D9: no natmod target needs a runner another cannot
    # use, so nothing forces a job per identifier.
    runners = {
        Target(abi="6.3", mode="natmod", arch=a).default_runner for a in NATMOD_ARCHS
    }
    assert runners == {"ubuntu-latest"}
