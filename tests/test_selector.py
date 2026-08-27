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

    natmod_targets = [Target(abi="6.3", arch="x64", tag="v1.30.0-preview")]
    assert select(natmod_targets, "*", "")[0].identifier == "mpy6.3-v1.30.0-preview-x64"

    usermod_targets = [UsermodTarget(port="qemu", arch="MICROBIT", tag="v1.29.0")]
    assert select(usermod_targets, "*", "")[0].identifier == "v1.29.0-qemu-MICROBIT"


@pytest.mark.parametrize("value", ["", None])
def test_matches_empty_pattern_list_matches_nothing(value):
    assert not matches("anything", parse_selector(value))
