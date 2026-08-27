from dataclasses import dataclass

import pytest

from cibuildmp.selector import matches, parse_selector, select


@dataclass(frozen=True)
class _Fake:
    """A minimal stand-in for Target/UsermodTarget -- select() only ever
    needs a string `.identifier`, proven by using neither real type here."""

    identifier: str


def test_parse_selector_accepts_both_forms():
    assert parse_selector("a b") == ["a", "b"]
    assert parse_selector(["a", "b"]) == ["a", "b"]
    assert parse_selector(None) == []


def test_matches_plain_fnmatch():
    assert matches("mpy6.3-x64", ["mpy6.3-*"])
    assert not matches("mpy6.3-x64", ["mpy6.2-*"])


def test_matches_expands_braces():
    # The gap 0051 flagged against upstream's own bracex-based
    # selector_matches(): cp{36,37}-* matching either cp36-* or cp37-*.
    assert matches("mpy6.3-x64", ["*-{x64,x86}"])
    assert matches("mpy6.3-x86", ["*-{x64,x86}"])
    assert not matches("mpy6.3-armv6m", ["*-{x64,x86}"])


def test_matches_expands_braces_with_more_than_two_options():
    assert matches("v1.29.0-webassembly", ["v1.{28,29,30}.0-*"])
    assert not matches("v1.27.0-webassembly", ["v1.{28,29,30}.0-*"])


def test_matches_handles_two_brace_groups_in_one_pattern():
    assert matches("mpy6.3-x64", ["mpy{6.2,6.3}-{x64,x86}"])
    assert matches("mpy6.2-x86", ["mpy{6.2,6.3}-{x64,x86}"])
    assert not matches("mpy6.1-x86", ["mpy{6.2,6.3}-{x64,x86}"])


def test_matches_pattern_with_no_braces_is_unaffected():
    assert matches("qemu", ["qemu"])
    assert not matches("qemu", ["esp32"])


def test_matches_unterminated_brace_is_left_alone():
    # No closing "}" -- treated as a literal pattern rather than raising,
    # the same "fail where it did" rule targets.py's own axis-value
    # handling already follows for an unrecognised value.
    assert not matches("mpy6.3-x64", ["mpy{6.3-natmod-x64"])


def test_select_globs():
    targets = [_Fake(i) for i in ("a-1", "a-2", "b-1")]
    assert [t.identifier for t in select(targets, "a-*", "")] == ["a-1", "a-2"]
    # skip is applied after build, and wins
    assert select(targets, "a-*", "a-*") == []


def test_select_with_brace_expansion():
    targets = [_Fake(i) for i in ("v1.28.0-qemu", "v1.29.0-qemu", "v1.30.0-qemu")]
    assert [t.identifier for t in select(targets, "v1.{28,29}.0-*", "")] == [
        "v1.28.0-qemu",
        "v1.29.0-qemu",
    ]


def test_select_generic_over_any_identifier_bearing_type():
    # The whole point of moving this out of natmod/targets.py: one
    # implementation, used with both real target types, not just the
    # stand-in above.
    from cibuildmp.platforms.natmod.targets import Target
    from cibuildmp.platforms.usermod.targets import UsermodTarget

    natmod_targets = [Target(abi="6.3", arch="x64")]
    assert select(natmod_targets, "*", "")[0].identifier == "mpy6.3-x64"

    usermod_targets = [UsermodTarget(port="qemu", tag="v1.29.0")]
    assert select(usermod_targets, "*", "")[0].identifier == "v1.29.0-qemu"


@pytest.mark.parametrize("value", ["", None])
def test_matches_empty_pattern_list_matches_nothing(value):
    assert not matches("anything", parse_selector(value))


# ── groups / enable (0051 point 8) ───────────────────────────────────────

_GROUPS = {"exotic": ["*-riscv64", "*-s390x"]}


def test_select_excludes_an_unenabled_group_even_though_build_matches():
    targets = [_Fake(i) for i in ("v1-unix-x86_64", "v1-unix-riscv64")]
    assert [t.identifier for t in select(targets, "*", "", groups=_GROUPS)] == [
        "v1-unix-x86_64"
    ]


def test_select_reaches_the_group_once_enabled():
    targets = [_Fake(i) for i in ("v1-unix-x86_64", "v1-unix-riscv64")]
    result = select(targets, "*", "", enable=frozenset({"exotic"}), groups=_GROUPS)
    assert [t.identifier for t in result] == ["v1-unix-x86_64", "v1-unix-riscv64"]


def test_select_group_filter_outranks_build_and_skip():
    # A group exclusion cannot be worked around by naming the target in
    # build -- it is checked first, same as upstream's own EnableGroup.
    targets = [_Fake("v1-unix-riscv64")]
    assert select(targets, "*-riscv64", "", groups=_GROUPS) == []


def test_select_with_no_groups_argument_is_unaffected_by_group_shaped_identifiers():
    # Callers that pass nothing (every one before 0051 point 8) see no
    # behaviour change at all, even for an identifier that would match a
    # group pattern if groups were supplied.
    targets = [_Fake("v1-unix-riscv64")]
    assert [t.identifier for t in select(targets, "*", "")] == ["v1-unix-riscv64"]


def test_select_enabling_an_unrelated_group_does_not_reach_a_different_one():
    targets = [_Fake(i) for i in ("v1-unix-riscv64", "v1-esp32-generic")]
    groups = {"exotic": ["*-riscv64"], "other": ["*-esp32-*"]}
    result = select(targets, "*", "", enable=frozenset({"exotic"}), groups=groups)
    assert [t.identifier for t in result] == ["v1-unix-riscv64"]
