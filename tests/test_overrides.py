"""The genuinely new, cross-cutting mechanism Phase G adds (record 0051's
third/fifth addenda): one shared top-level `[override]` table, `inherit`,
and per-matched-platform ("tier-2") key validation now that every `Target`
(natmod included) has a `.port`. Natmod's and usermod's own existing
`[override]` tests (`tests/test_options.py`, `tests/test_usermod_options.py`)
stay where they are -- they're about each class's own single-platform
`build_options()` behaviour, unchanged in substance by this phase. This file
is for behaviour that spans both.
"""

from pathlib import Path

import pytest

from cibuildmp.cli import main
from cibuildmp.platforms.natmod.options import OVERRIDE_UNION_KEYS, ConfigError, Options
from cibuildmp.platforms.natmod.targets import Target, newest_tag_for_abi
from cibuildmp.platforms.usermod.options import (
    USERMOD_PORT_BASE,
    UsermodConfigError,
    UsermodOptions,
)
from cibuildmp.platforms.usermod.targets import UsermodTarget


def write(tmp_path: Path, text: str) -> Path:
    (tmp_path / "cibuildmp.toml").write_text(text)
    return tmp_path


def test_override_union_keys_covers_usermod_port_base():
    # The drift guard for natmod/options.py's own mirrored constant (it
    # must not import usermod/options.py, so it restates
    # USERMOD_PORT_BASE by hand) -- if the two ever diverge, this fails
    # loudly instead of the union silently going stale.
    assert OVERRIDE_UNION_KEYS >= USERMOD_PORT_BASE


def test_one_shared_override_reaches_both_natmod_and_a_usermod_port(tmp_path):
    # The headline claim: one [override] table, one config, both
    # platforms honour it -- with inherit=append actually composing onto
    # each platform's own base, not replacing it. Record 0052's own
    # live-caught correction retracted per-platform tables entirely
    # (`[natmod] extra-make-args = "..."` is gone), so each platform's own
    # "base" is itself expressed as a scoped [override] entry now --
    # natmod's own identifiers all start with the literal "mpy" prefix,
    # unix's own always carry "manylinux"/"musllinux" -- written *before*
    # the universal "*" entry so file order still layers append on top.
    #
    # Targets are constructed directly rather than resolved through
    # .targets() -- natmod's own reachability audit has no way to widen
    # its domain with usermod's own identifiers without importing it back
    # (a one-way dependency this project keeps deliberately), so a
    # unix-only override selector genuinely is unreachable *from natmod's
    # own side*, a real, separately-tracked, still-open gap (record
    # 0052's own addendum on task #66) -- not what this test is about.
    write(
        tmp_path,
        """
        [override."mpy*"]
        extra-make-args = ["N=1"]

        [override."v*-{manylinux,musllinux}*"]
        extra-make-args = ["U=1"]

        [override."*"]
        extra-make-args = ["EXTRA=1"]
        inherit = {extra-make-args = "append"}
        """,
    )

    natmod_options = Options.load(tmp_path, env={})
    natmod_target = Target(abi="6.3", arch="x64", tag=newest_tag_for_abi("6.3"))
    assert natmod_options.build_options(natmod_target, env={}).extra_make_args == [
        "N=1",
        "EXTRA=1",
    ]

    usermod_options = UsermodOptions.load(tmp_path, ports=["unix"])
    usermod_target = UsermodTarget(
        port="unix", arch="manylinux_2_28_x86_64", tag="v1.29.0"
    )
    assert usermod_options.build_options(usermod_target).extra_make_args == [
        "U=1",
        "EXTRA=1",
    ]


def test_natmod_only_override_key_rejected_for_a_usermod_target(tmp_path):
    # make-target is valid *somewhere* (natmod's own schema), so it passes
    # tier-1 (load()); it must still be rejected at tier-2 (build_options())
    # once the matched identifier's own platform (unix) is known -- the
    # direct regression test for "runtime per-matched-platform validation"
    # not silently readmitting record 0048's own bug class under the
    # cascade.
    write(tmp_path, '[unix]\n\n[override."*"]\nmake-target = "dist"\n')
    options = UsermodOptions.load(tmp_path, ports=["unix"])

    with pytest.raises(UsermodConfigError, match="unknown key `make-target`"):
        options.build_options(options.targets()[0])


def test_usermod_only_override_key_rejected_for_a_natmod_target(tmp_path):
    # The mirror case: manifest is valid somewhere (usermod's own schema),
    # passes tier-1, but is not natmod's to read.
    write(
        tmp_path,
        '[natmod]\n\n[override."*"]\nmanifest = "x.py"\n',
    )
    options = Options.load(tmp_path, env={})

    with pytest.raises(ConfigError, match="unknown key `manifest`"):
        options.build_options(options.targets()[0], env={})


def test_tier_2_rejection_is_a_clean_cli_error_not_a_traceback(tmp_path, capsys):
    # Regression, found via live testing: build_options() can raise
    # ConfigError/UsermodConfigError for a tier-2 mismatch on the very
    # first target a --dry-run or real build loop resolves -- a path
    # neither natmod/cli.py's nor usermod/cli.py's own try/except around
    # Options.load()/targets() covers, since load()/targets() cannot see
    # this error (it only surfaces once a specific target is resolved).
    # Both call sites (the --dry-run loop, and the real build wrapper)
    # needed their own ConfigError/UsermodConfigError handling added.
    (tmp_path / "cibuildmp.toml").write_text(
        '[natmod]\n\n[override."*"]\nmanifest = "x.py"\n'
    )

    assert main([str(tmp_path), "--dry-run"]) == 2
    err = capsys.readouterr().err
    assert "unknown key `manifest`" in err
    assert "Traceback" not in err


def test_arch_flags_still_rejected_in_the_merged_overrides_natmod(tmp_path):
    # Regression: the merge must not have widened OVERRIDE_UNION_KEYS to
    # readmit arch-flags, resolved once for the whole config and never
    # per target -- exactly the shape record 0048 is about.
    write(
        tmp_path,
        '[natmod]\n[unix]\n\n[override."*"]\narch-flags = "rv32imc"\n',
    )

    with pytest.raises(ConfigError, match=r'\[override\."\*"\]: unknown key'):
        Options.load(tmp_path, env={})


def test_arch_flags_still_rejected_in_the_merged_overrides_usermod(tmp_path):
    write(
        tmp_path,
        '[natmod]\n[unix]\n\n[override."*"]\narch-flags = "rv32imc"\n',
    )

    with pytest.raises(UsermodConfigError, match=r'\[override\."\*"\]: unknown key'):
        UsermodOptions.load(tmp_path, ports=["unix"])


def test_inherit_on_a_scalar_key_is_a_parse_time_error_natmod(tmp_path):
    # A bad inherit key can never become valid regardless of which target
    # later matches -- caught at load(), not deferred to build_options().
    write(
        tmp_path,
        '[natmod]\n\n[override."*"]\n'
        'module-dir = "x"\ninherit = {module-dir = "append"}\n',
    )

    with pytest.raises(ConfigError, match="inherit only applies to list-valued"):
        Options.load(tmp_path, env={})


def test_inherit_on_a_scalar_key_is_a_parse_time_error_usermod(tmp_path):
    write(
        tmp_path,
        '[unix]\n\n[override."*"]\n'
        'module-dir = "x"\ninherit = {module-dir = "append"}\n',
    )

    with pytest.raises(UsermodConfigError, match="inherit only applies to list-valued"):
        UsermodOptions.load(tmp_path, ports=["unix"])


def test_inherit_unknown_rule_is_a_parse_time_error(tmp_path):
    write(
        tmp_path,
        '[natmod]\n\n[override."*"]\n'
        'extra-make-args = ["X=1"]\ninherit = {extra-make-args = "sideways"}\n',
    )

    with pytest.raises(ConfigError, match="unknown inherit rule 'sideways'"):
        Options.load(tmp_path, env={})


def test_inherit_prepend(tmp_path):
    write(
        tmp_path,
        """
        extra-make-args = ["BASE=1"]

        [override."*"]
        extra-make-args = ["FIRST=1"]
        inherit = {extra-make-args = "prepend"}
        """,
    )
    options = Options.load(tmp_path, env={})
    target = options.targets()[0]

    assert options.build_options(target, env={}).extra_make_args == [
        "FIRST=1",
        "BASE=1",
    ]
