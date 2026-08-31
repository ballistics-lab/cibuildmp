import json

import pytest

from cibuildmp.cli import main
from cibuildmp.platforms.natmod.targets import (
    newest_known_abi,
    newest_stable_tag_for_abi,
)

# Natmod identifiers carry their tag (record 0052's own live-caught
# correction) -- the newest *stable* tag mapping to ABI 6.3
# (narrow_to_newest_tag() prefers a real release over a preview sharing
# the same ABI), not a literal string pinned here that would go stale on
# its own schedule.
NATMOD_X64 = f"mpy6.3-{newest_stable_tag_for_abi('6.3')}-x64"
NATMOD_BUILD_X64 = f"mpy{newest_known_abi()}-*-x64"

UNIX_V129_X86_64 = "v1.29.0-manylinux_2_28_x86_64"


def write(tmp_path, text):
    (tmp_path / "cibuildmp.toml").write_text(text)
    return str(tmp_path)


def make_module_dir(package_dir, name="usermod"):
    mod = package_dir / name / "mymod"
    mod.mkdir(parents=True)
    (mod / "mymod.c").write_text("// stub\n")
    (mod / "micropython.mk").write_text("SRC_USERMOD += mymod.c\n")


def test_no_config_builds_nothing(tmp_path, capsys):
    # There is no more zero-config default (record 0052's own live-caught
    # correction) -- an unconfigured build/skip selects nothing at all,
    # from either family, not "natmod, narrowed to the newest ABI".
    assert main([str(tmp_path)]) == 2
    assert "no targets selected" in capsys.readouterr().err

    assert main([str(tmp_path), "--allow-empty"]) == 0


def test_natmod_build_glob_selects_and_builds(tmp_path, capsys):
    write(tmp_path, f'build = "{NATMOD_BUILD_X64}"\n')
    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == [NATMOD_X64]


def test_usermod_build_glob_dispatches_to_usermod(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, f'build = "{UNIX_V129_X86_64}"\n')

    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == [UNIX_V129_X86_64]


def test_usermod_print_build_identifiers_json(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, 'build = "v1.29.0-esp32-ESP32_GENERIC"\n')

    assert main([str(tmp_path), "--print-build-identifiers", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == ["v1.29.0-esp32-ESP32_GENERIC"]


def test_usermod_dry_run_lists_the_target(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, 'build = "v1.29.0-wasm32"\n')

    assert main([str(tmp_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "v1.29.0-wasm32" in out
    # No runner in the plan line any more -- cibuildmp does not choose a
    # host for anything (record 0049).
    assert "runs-on" not in out


# ── the headline capability: both families in one invocation, always ────


def test_both_families_build_together_by_default(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, f'build = "{NATMOD_BUILD_X64} {UNIX_V129_X86_64}"\n')

    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    identifiers = capsys.readouterr().out.split()
    assert NATMOD_X64 in identifiers
    assert UNIX_V129_X86_64 in identifiers


def test_both_families_print_build_identifiers_json_is_one_array(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, f'build = "{NATMOD_BUILD_X64} {UNIX_V129_X86_64}"\n')

    assert main([str(tmp_path), "--print-build-identifiers", "--json"]) == 0
    identifiers = json.loads(capsys.readouterr().out)
    assert NATMOD_X64 in identifiers
    assert UNIX_V129_X86_64 in identifiers


def test_both_families_dry_run_lists_both(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, f'build = "{NATMOD_BUILD_X64} {UNIX_V129_X86_64}"\n')

    assert main([str(tmp_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert NATMOD_X64 in out
    assert UNIX_V129_X86_64 in out


def test_one_family_selecting_nothing_is_not_an_error_when_the_other_does(
    tmp_path, capsys
):
    # The ordinary case: a config only ever configures one family's own
    # build/skip, and the other's naturally selects nothing -- that must
    # not need --allow-empty, unlike the case where *nothing at all* was
    # selected (test_no_config_builds_nothing above).
    write(tmp_path, f'build = "{NATMOD_BUILD_X64}"\n')

    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == [NATMOD_X64]


def test_three_platforms_at_once(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(
        tmp_path,
        f'build = "{NATMOD_BUILD_X64} {UNIX_V129_X86_64} v1.29.0-esp32-ESP32_GENERIC"\n',
    )

    assert main([str(tmp_path), "--print-build-identifiers", "--json"]) == 0
    identifiers = json.loads(capsys.readouterr().out)
    assert NATMOD_X64 in identifiers
    assert UNIX_V129_X86_64 in identifiers
    assert "v1.29.0-esp32-ESP32_GENERIC" in identifiers


# ── --build/--skip CLI overrides (record 0052: replaces --only/--platform) ──


def test_cli_build_overrides_the_config(tmp_path, capsys):
    write(tmp_path, 'build = "*bogus*"\n')

    assert (
        main([str(tmp_path), "--build", NATMOD_BUILD_X64, "--print-build-identifiers"])
        == 0
    )
    assert capsys.readouterr().out.split() == [NATMOD_X64]


def test_cli_skip_overrides_the_config(tmp_path, capsys):
    write(tmp_path, f'build = "{NATMOD_BUILD_X64}"\n')

    assert (
        main(
            [
                str(tmp_path),
                "--skip",
                "*",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == []


def test_cli_build_can_name_exactly_one_identifier(tmp_path, capsys):
    # Replaces the old --only: name a build glob specific enough to match
    # exactly one real identifier.
    assert (
        main([str(tmp_path), "--build", NATMOD_X64, "--print-build-identifiers"]) == 0
    )
    assert capsys.readouterr().out.split() == [NATMOD_X64]


# ── the flattened config tree: retired tables ────────────────────────────


def test_usermod_table_is_just_an_unknown_table_now(tmp_path, capsys):
    # [usermod] (record 0051's ninth addendum) is gone (record 0074), with
    # no dedicated migration message: no real config in this project's own
    # examples ever actually used it, unlike the six real tables below --
    # a stray [usermod] falls through to the same plain "unknown table"
    # error as any other unrecognised name.
    write(tmp_path, '[usermod]\nports = ["unix"]\n')

    assert main([str(tmp_path)]) == 2
    assert "unknown table(s) at the top level: [usermod]" in capsys.readouterr().err


def test_retired_natmod_table_is_just_an_unknown_table_now(tmp_path, capsys):
    write(tmp_path, "[natmod]\n")

    assert main([str(tmp_path)]) == 2
    assert "unknown table(s) at the top level: [natmod]" in capsys.readouterr().err


def test_retired_unix_table_is_just_an_unknown_table_now(tmp_path, capsys):
    write(tmp_path, "[unix]\n")

    assert main([str(tmp_path)]) == 2
    assert "unknown table(s) at the top level: [unix]" in capsys.readouterr().err


def test_unknown_top_level_table_is_an_error(tmp_path, capsys):
    write(tmp_path, "[stm32]\n")

    assert main([str(tmp_path)]) == 2
    assert "unknown table(s) at the top level: [stm32]" in capsys.readouterr().err


# ── the same treatment for scalar keys (record 0075) ─────────────────────


def test_unknown_top_level_scalar_key_is_an_error(tmp_path, capsys):
    # The gap record 0074 found while checking a claim in design.md:
    # neither family's own load() validated the top-level scalar keyset at
    # all, so a key no family reads was silently absent -- the config
    # looked accepted and the option simply never applied. `micropython =`
    # is the real shape this bites (record 0052 retired that key; a config
    # written against the old schema keeps it and gets no complaint).
    write(tmp_path, 'micropython = "v1.29.0"\n')

    assert main([str(tmp_path)]) == 2
    assert "unknown key `micropython`" in capsys.readouterr().err


def test_unknown_top_level_scalar_key_suggests_a_close_match(tmp_path, capsys):
    write(tmp_path, 'buidl = "mpy*-x64"\n')

    assert main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "unknown key `buidl`" in err
    assert "Perhaps you meant `build`?" in err


def test_every_family_own_top_level_keys_are_accepted(tmp_path, capsys):
    # The union across FAMILIES, not one family's own set: natmod-only
    # (`module-dir`, `make-target`, `arch-flags`, `pre-build-command`,
    # `micropython-submodules`) and usermod-only (`user-c-modules`,
    # `manifest`, `extra-cmake-args`) keys are both valid at the bare top
    # level, since the global layer is every platform's own default.
    write(
        tmp_path,
        """
        name = "mod"
        version = "1.0"
        output-dir = "mpyhouse"
        build = ""
        skip = ""
        extra-make-args = []
        micropython-submodules = []
        module-dir = "natmod"
        make-target = "all"
        pre-build-command = ""
        arch-flags = []
        user-c-modules = "."
        manifest = ""
        extra-cmake-args = []
        """,
    )

    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    assert capsys.readouterr().err == ""


def test_unknown_array_of_tables_is_reported_as_a_table(tmp_path, capsys):
    # `[[name]]` parses to a list of dicts, not a dict -- a `dict`-only
    # test would hand it to the scalar keyset check and report "unknown
    # key `stm32`" for something that is plainly a table.
    write(tmp_path, '[[stm32]]\nboard = "PYBV11"\n')

    assert main([str(tmp_path)]) == 2
    assert "unknown table(s) at the top level: [stm32]" in capsys.readouterr().err


def test_publish_and_override_tables_are_not_scalar_keys(tmp_path, capsys):
    # The scalar check skips table-valued keys outright -- neither is in
    # any family's own OPTION_KEYS, and _validate_top_level_tables() is
    # what judges those.
    write(
        tmp_path,
        '[publish]\nextra-files = []\n\n[override."*"]\nmodule-dir = "natmod"\n',
    )

    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    assert capsys.readouterr().err == ""


def test_platform_and_only_flags_no_longer_exist(tmp_path, capsys):
    # Both retired in the same round (record 0052): everything either one
    # reached, an ordinary build/skip glob against the real identifier
    # already reaches directly. argparse itself rejects the unknown flag
    # (SystemExit(2)), not main()'s own return value.
    with pytest.raises(SystemExit) as exc_info:
        main([str(tmp_path), "--platform", "natmod"])
    assert exc_info.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc_info:
        main([str(tmp_path), "--only", NATMOD_X64])
    assert exc_info.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
