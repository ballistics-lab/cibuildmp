import pytest

from cibuildmp.cli import (
    ALL_PLATFORMS,
    _parse_platform_names,
    active_platforms,
)
from cibuildmp.platforms.natmod.options import ConfigError


def test_all_platforms_is_natmod_then_the_five_usermod_ports():
    assert ALL_PLATFORMS == (
        "natmod",
        "unix",
        "windows",
        "qemu",
        "webassembly",
        "esp32",
    )


# ── active_platforms() ────────────────────────────────────────────────


def test_no_tables_defaults_to_natmod_only():
    assert active_platforms({}, None) == ["natmod"]


def test_natmod_table_only():
    assert active_platforms({"natmod": {}}, None) == ["natmod"]


def test_a_single_usermod_port_table():
    assert active_platforms({"unix": {}}, None) == ["unix"]


def test_both_natmod_and_a_usermod_port_are_both_active():
    # The headline change: no more ambiguity error, no more --platform
    # required just to build more than one platform in one invocation.
    assert active_platforms({"natmod": {}, "unix": {}}, None) == ["natmod", "unix"]


def test_table_order_in_the_config_does_not_matter_result_is_all_platforms_order():
    assert active_platforms({"esp32": {}, "natmod": {}, "unix": {}}, None) == [
        "natmod",
        "unix",
        "esp32",
    ]


def test_explicit_wins_outright_over_table_presence():
    assert active_platforms({"natmod": {}}, ["unix"]) == ["unix"]
    assert active_platforms({}, ["unix", "qemu"]) == ["unix", "qemu"]


def test_legacy_usermod_ports_key_is_rejected():
    # [usermod] itself is legal again (record 0051's ninth addendum --
    # shared defaults, sibling to [natmod], not a selector), but the old
    # `ports = [...]` selector it used to carry is still gone -- this is
    # the one thing inside it that remains a loud, specific error.
    with pytest.raises(
        ConfigError, match=r"\[usermod\] ports = \[\.\.\.\] no longer exists"
    ):
        active_platforms({"usermod": {"ports": ["unix"]}}, None)


def test_legacy_usermod_ports_key_is_rejected_even_with_explicit_platform():
    # The config itself is broken regardless of what --platform says --
    # this is not a "which platform" question, it is "this config still
    # uses the old shape".
    with pytest.raises(
        ConfigError, match=r"\[usermod\] ports = \[\.\.\.\] no longer exists"
    ):
        active_platforms({"usermod": {"ports": ["unix"]}}, ["natmod"])


def test_legacy_nested_usermod_port_table_is_rejected():
    # [usermod.unix] (TOML nesting) parses as usermod={"unix": {...}} --
    # the other pre-Phase-F shape, also still gone.
    with pytest.raises(ConfigError, match=r"\[usermod\.unix\] no longer exists"):
        active_platforms({"usermod": {"unix": {}}}, None)


def test_empty_usermod_table_is_legal_and_not_a_selector():
    # The ninth addendum's own headline change: [usermod] with nothing
    # (or only shared defaults) in it is not an error, and its presence
    # or absence never selects a port -- table presence of [unix]/
    # [esp32]/etc. still does that alone, unchanged from Phase F.
    assert active_platforms({"usermod": {}}, None) == ["natmod"]
    assert active_platforms({"usermod": {"user-c-modules": "."}, "unix": {}}, None) == [
        "unix"
    ]


def test_unknown_top_level_table_is_rejected():
    with pytest.raises(
        ConfigError, match=r"unknown table\(s\) at the top level: \[stm32\]"
    ):
        active_platforms({"stm32": {}}, None)


def test_publish_table_is_not_mistaken_for_an_unknown_platform():
    assert active_platforms({"natmod": {}, "publish": {"extra-files": []}}, None) == [
        "natmod"
    ]


def test_arrays_of_tables_are_not_mistaken_for_unknown_platforms():
    # [[overrides]] (shared by every platform since Phase G) parses as a
    # list, not a dict -- must never trip the unknown-table check.
    assert active_platforms({"natmod": {}, "overrides": [{"select": "*"}]}, None) == [
        "natmod"
    ]


# ── _parse_platform_names() ─────────────────────────────────────────────


def test_parse_platform_names_comma_separated():
    assert _parse_platform_names("unix,windows") == ["unix", "windows"]


def test_parse_platform_names_space_separated():
    assert _parse_platform_names("unix windows") == ["unix", "windows"]


def test_parse_platform_names_natmod_is_valid():
    assert _parse_platform_names("natmod") == ["natmod"]


def test_parse_platform_names_usermod_is_not_a_platform():
    with pytest.raises(ConfigError, match="unknown platform\\(s\\) usermod"):
        _parse_platform_names("usermod")


def test_parse_platform_names_unknown_name_is_an_error():
    with pytest.raises(ConfigError, match=r"unknown platform\(s\) bogus"):
        _parse_platform_names("bogus")
