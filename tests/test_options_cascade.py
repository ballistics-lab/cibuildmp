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


def test_options_get_platform_beats_global():
    options = Options(
        global_table={"archs": ["x64"]},
        tree={"unix": {"archs": ["aarch64"]}},
    )
    assert options.get("archs", platform="unix") == ["aarch64"]
    # A different platform never sees unix's own table.
    assert options.get("archs", platform="windows") == ["x64"]


def test_options_get_env_beats_platform():
    options = Options(
        global_table={},
        tree={"unix": {"archs": ["aarch64"]}},
        env={"CIBMP_ARCHS": "x64,x86"},
    )
    assert options.get("archs", platform="unix") == "x64,x86"


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


def test_options_get_no_platform_table_for_this_platform_is_fine():
    options = Options(global_table={"archs": ["x64"]}, tree={})
    assert options.get("archs", platform="unix") == ["x64"]


# ── multi-segment paths (record 0052, Track B, B0/B4.1) ──────────────────
#
# `tree["usermod"]` plays the role the separate `family_table` field used
# to (record 0051's ninth addendum): a dict holding both the family
# node's own scalar keys and, as sibling keys, each port's own nested
# table -- the same shape a real `[usermod.<port>]` TOML table would
# parse to, walked one path segment at a time rather than addressed by a
# second dataclass field.


def test_options_get_family_beats_global():
    options = Options(
        global_table={"user-c-modules": "global"},
        tree={"usermod": {"user-c-modules": "family"}},
    )
    assert options.get("user-c-modules", platform="usermod") == "family"


def test_options_get_platform_beats_family():
    options = Options(
        global_table={},
        tree={
            "usermod": {
                "user-c-modules": "family",
                "unix": {"user-c-modules": "unix-only"},
            }
        },
    )
    assert options.get("user-c-modules", platform=("usermod", "unix")) == "unix-only"
    # A platform with no override of its own still falls through to the
    # family layer, not straight past it to global.
    assert (
        options.get("user-c-modules", platform=("usermod", "webassembly")) == "family"
    )


def test_options_get_no_family_table_is_fine():
    # The default -- an Options instance with no tree at all (natmod's
    # own; a direct construction like every test above this point)
    # behaves exactly as it did before this layer existed. An empty
    # Mapping.get() always contributes None, which resolve_cascade() skips
    # outright.
    options = Options(global_table={"archs": ["x64"]})
    assert options.get("archs", platform="natmod") == ["x64"]


def test_options_get_env_beats_family():
    options = Options(
        global_table={},
        tree={"usermod": {"user-c-modules": "family"}},
        env={"CIBMP_USER_C_MODULES": "from-env"},
    )
    assert options.get("user-c-modules", platform="usermod") == "from-env"


def test_options_get_three_segment_path_walks_every_node():
    # The esp32-board-shaped case (record 0052, Track B, B4.2, not wired
    # into any real caller yet) -- proof the walk generalises past the
    # two-segment depth every real caller uses today, not just asserted
    # by the record's own prose.
    options = Options(
        global_table={"extra-make-args": ["GLOBAL=1"]},
        tree={
            "usermod": {
                "esp32": {
                    "extra-make-args": ["PORT=1"],
                    "ESP32_GENERIC_S3": {"extra-make-args": ["BOARD=1"]},
                }
            }
        },
    )
    assert options.get("extra-make-args", platform=("usermod", "esp32")) == ["PORT=1"]
    assert options.get(
        "extra-make-args", platform=("usermod", "esp32", "ESP32_GENERIC_S3")
    ) == ["BOARD=1"]
    # A board with no override of its own falls through to the port
    # layer, not straight past it to global.
    assert options.get(
        "extra-make-args", platform=("usermod", "esp32", "ESP32_GENERIC_C3")
    ) == ["PORT=1"]


def test_options_get_missing_middle_segment_contributes_nothing_further():
    # A path that walks off the tree partway through (e.g. a port with no
    # table of its own) contributes None for every remaining segment,
    # the same silent-miss behaviour a single missing platform always had
    # -- not an error, and not a reason to stop resolving earlier layers.
    options = Options(
        global_table={"archs": ["x64"]},
        tree={"usermod": {}},
    )
    assert options.get(
        "archs", platform=("usermod", "unix", "manylinux_2_28_x86_64")
    ) == ["x64"]


def test_options_get_platform_env_var_keys_off_the_last_segment_only():
    # CIBMP_EXTRA_MAKE_ARGS_UNIX, not CIBMP_EXTRA_MAKE_ARGS_USERMOD_UNIX --
    # the env var name a two-segment usermod path produces must stay
    # exactly what a bare "unix" platform string already produced before
    # usermod's own path grew a leading "usermod" segment.
    options = Options(
        global_table={},
        env={"CIBMP_EXTRA_MAKE_ARGS_UNIX": "from-env"},
    )
    assert options.get("extra-make-args", platform=("usermod", "unix")) == "from-env"
