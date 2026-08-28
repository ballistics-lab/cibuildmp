import pytest

from cibuildmp.options import (
    ConfigError,
    InheritRule,
    Options,
    check_known_keys,
    known_option_names,
    resolve_cascade,
    suggest,
)

# ── resolve_cascade() ──────────────────────────────────────────────────


def test_resolve_cascade_last_none_layer_wins():
    assert (
        resolve_cascade(
            ("default", InheritRule.NONE),
            ("global", InheritRule.NONE),
            ("platform", InheritRule.NONE),
        )
        == "platform"
    )


def test_resolve_cascade_skips_none_values():
    assert (
        resolve_cascade(
            ("default", InheritRule.NONE),
            (None, InheritRule.NONE),
            (None, InheritRule.NONE),
        )
        == "default"
    )


def test_resolve_cascade_all_none_values_returns_none():
    assert resolve_cascade((None, InheritRule.NONE), (None, InheritRule.NONE)) is None


def test_resolve_cascade_explicit_empty_replaces():
    # An explicit "" or [] is a real value, not "unset" -- distinct from
    # None, which means the layer said nothing at all.
    assert resolve_cascade(("default", InheritRule.NONE), ("", InheritRule.NONE)) == ""
    assert resolve_cascade((["a"], InheritRule.NONE), ([], InheritRule.NONE)) == []


def test_resolve_cascade_append_extends_list():
    assert resolve_cascade(
        (["a", "b"], InheritRule.NONE),
        (["c"], InheritRule.APPEND),
    ) == ["a", "b", "c"]


def test_resolve_cascade_prepend_extends_list():
    assert resolve_cascade(
        (["a", "b"], InheritRule.NONE),
        (["c"], InheritRule.PREPEND),
    ) == ["c", "a", "b"]


def test_resolve_cascade_append_then_prepend_compose_in_order():
    assert resolve_cascade(
        (["b"], InheritRule.NONE),
        (["c"], InheritRule.APPEND),
        (["a"], InheritRule.PREPEND),
    ) == ["a", "b", "c"]


def test_resolve_cascade_first_layer_ignores_its_own_rule():
    # There is nothing to append/prepend to yet -- the first real value
    # always just becomes the running result, whatever rule it carries.
    assert resolve_cascade((["a"], InheritRule.APPEND)) == ["a"]


def test_resolve_cascade_append_on_scalar_is_an_error():
    with pytest.raises(ConfigError, match="only applies to list-valued"):
        resolve_cascade(("a", InheritRule.NONE), ("b", InheritRule.APPEND))


def test_resolve_cascade_unknown_rule_is_an_error():
    with pytest.raises(ConfigError, match="unknown inherit rule"):
        resolve_cascade(("a", InheritRule.NONE), ("b", "sideways"))


# ── known_option_names() / check_known_keys() / suggest() ────────────────


def test_known_option_names_unions_every_schema_plus_generic():
    schemas = {
        "natmod": frozenset({"archs", "arch-flags"}),
        "unix": frozenset({"archs", "variant"}),
    }
    names = known_option_names(schemas, generic=frozenset({"micropython"}))
    assert names == frozenset({"micropython", "archs", "arch-flags", "variant"})


def test_check_known_keys_accepts_known():
    check_known_keys({"archs": ["x64"]}, frozenset({"archs"}), where="[natmod]")


def test_check_known_keys_rejects_unknown_with_no_hint():
    with pytest.raises(ConfigError, match=r"\[natmod\]: unknown key `bogus`"):
        check_known_keys({"bogus": 1}, frozenset({"archs"}), where="[natmod]")


def test_check_known_keys_suggests_a_close_match():
    with pytest.raises(ConfigError, match="Perhaps you meant `module-dir`"):
        check_known_keys(
            {"module-dr": "."}, frozenset({"module-dir", "manifest"}), where="[unix]"
        )


def test_suggest_returns_none_when_nothing_is_close():
    assert suggest("zzz", frozenset({"archs", "boards"})) is None


def test_suggest_returns_the_close_match():
    assert suggest("modle-dir", frozenset({"module-dir", "manifest"})) == "module-dir"


# ── Options.get() ──────────────────────────────────────────────────────


def test_options_get_default_only():
    options = Options(global_table={})
    assert options.get("archs", default="fallback") == "fallback"


def test_options_get_global_beats_default():
    options = Options(global_table={"micropython": "v1.28.0"})
    assert options.get("micropython", default="v1.29.0") == "v1.28.0"


def test_options_get_platform_no_longer_selects_a_table_at_all():
    # record 0052's own live-caught correction, retracting the earlier
    # "per-platform build/skip" addendum this test used to cover:
    # Options has no platform_tables field left at all -- `platform=` is
    # kept purely to build the per-platform env var's own name (below),
    # not to select a TOML sub-table. A `platform_tables=` keyword is a
    # plain TypeError now, not a real construction option.
    with pytest.raises(TypeError):
        Options(global_table={}, platform_tables={"unix": {"archs": ["aarch64"]}})  # type: ignore[call-arg]


def test_options_get_platform_env_beats_plain_env():
    options = Options(
        global_table={},
        env={"CIBMP_ARCHS": "x64", "CIBMP_ARCHS_UNIX": "aarch64"},
    )
    assert options.get("archs", platform="unix") == "aarch64"
    # A different platform's own env-var name doesn't apply.
    assert options.get("archs", platform="windows") == "x64"


def test_options_get_env_plat_false_ignores_the_platform_env_var():
    options = Options(
        global_table={},
        env={"CIBMP_ARCHS": "x64", "CIBMP_ARCHS_UNIX": "aarch64"},
    )
    assert options.get("archs", platform="unix", env_plat=False) == "x64"


def test_options_get_extra_layers_come_last_and_can_append():
    options = Options(global_table={"extra-make-args": ["COMMON=1"]})
    result = options.get(
        "extra-make-args", extra_layers=[(["FROM=override"], InheritRule.APPEND)]
    )
    assert result == ["COMMON=1", "FROM=override"]


# ── family_table (record 0051's ninth addendum) ──────────────────────────


def test_options_get_family_beats_global():
    options = Options(
        global_table={"user-c-modules": "global"},
        family_table={"user-c-modules": "family"},
    )
    assert options.get("user-c-modules") == "family"


def test_options_get_family_wins_regardless_of_platform_argument():
    # The counterpart to test_options_get_platform_no_longer_selects_a_
    # table_at_all above: passing `platform=` no longer narrows anything
    # below the family layer -- every platform sees the exact same
    # family-resolved value, since there is no more per-platform table to
    # distinguish them.
    options = Options(global_table={}, family_table={"user-c-modules": "family"})
    assert options.get("user-c-modules", platform="unix") == "family"
    assert options.get("user-c-modules", platform="webassembly") == "family"


def test_options_get_no_family_table_is_fine():
    # The default -- an Options instance with no family_table at all
    # (natmod's own; a direct construction like every test above this
    # point) behaves exactly as it did before this layer existed. An
    # empty Mapping.get() always contributes None, which resolve_cascade()
    # skips outright.
    options = Options(global_table={"archs": ["x64"]})
    assert options.get("archs", platform="natmod") == ["x64"]


def test_options_get_env_beats_family():
    options = Options(
        global_table={},
        family_table={"user-c-modules": "family"},
        env={"CIBMP_USER_C_MODULES": "from-env"},
    )
    assert options.get("user-c-modules") == "from-env"
