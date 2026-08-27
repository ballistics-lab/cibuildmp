from pathlib import Path

import pytest

from cibuildmp.platforms.natmod.options import DEFAULT_MICROPYTHON
from cibuildmp.platforms.usermod.options import UsermodConfigError, UsermodOptions
from cibuildmp.platforms.usermod.targets import (
    KNOWN_PORTS,
    UnknownAxisError,
    default_axis_values,
)


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "cibuildmp.toml"
    path.write_text(text)
    return path


def _default_build_unix_cells() -> list[str]:
    # What a bare `build = "*"` actually selects for unix: the full axis
    # minus the emulated-everywhere group (0051 point 8) -- neither
    # default_axis_values("unix") (now the full fifteen) nor GROUPS on
    # their own answer this, only both together do.
    return [
        v
        for v in default_axis_values("unix")
        if not v.endswith(("_ppc64le", "_s390x", "_riscv64"))
    ]


def test_every_present_port_table_is_active(tmp_path):
    # Phase F (record 0051 points 4/6): there is no more `ports = [...]`
    # list, or a curated "default ports" set -- table presence alone
    # selects a port, exactly the rule [natmod]'s own presence has always
    # followed. `esp32` stays out unless its own table is written, same
    # as before, but now for the same reason every other port does.
    write_config(tmp_path, "[unix]\n[windows]\n[qemu]\n[webassembly]\n")
    options = UsermodOptions.load(tmp_path)

    assert options.ports == ["unix", "windows", "qemu", "webassembly"]
    assert "esp32" not in options.ports
    assert "esp32" in KNOWN_PORTS


def test_a_subset_of_port_tables_selects_only_those(tmp_path):
    write_config(tmp_path, "[unix]\n[esp32]\n")
    options = UsermodOptions.load(tmp_path)

    # Derived rather than spelled out: what this test is about is that
    # table presence selects a subset of *ports*, in KNOWN_PORTS order.
    # Restating the unix default axis here would make it a second owner
    # of that list. `test_usermod_targets.py` owns the list.
    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == [
        f"{DEFAULT_MICROPYTHON}-unix-{value}" for value in _default_build_unix_cells()
    ] + [f"{DEFAULT_MICROPYTHON}-esp32-ESP32_GENERIC"]


def test_per_port_axis_override(tmp_path):
    write_config(
        tmp_path,
        """
        [unix]
        archs = ["manylinux_2_28_aarch64"]
        """,
    )
    options = UsermodOptions.load(tmp_path)

    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == [f"{DEFAULT_MICROPYTHON}-unix-manylinux_2_28_aarch64"]


def test_multiple_boards_same_port(tmp_path):
    # Answers the user's own question directly: yes, a list of boards for
    # one port produces one target each, built independently.
    write_config(
        tmp_path,
        """
        [esp32]
        boards = ["ESP32_GENERIC", "ESP32_GENERIC_S3"]
        """,
    )
    options = UsermodOptions.load(tmp_path)

    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == [
        f"{DEFAULT_MICROPYTHON}-esp32-ESP32_GENERIC",
        f"{DEFAULT_MICROPYTHON}-esp32-ESP32_GENERIC_S3",
    ]


def test_unknown_esp32_board_is_rejected(tmp_path):
    # boards = [...] values were never validated against anything before
    # this -- any string became a real UsermodTarget, board typos
    # included. Checked against resources/build-platforms.toml's own
    # independently-verified board list. Propagates as UnknownAxisError,
    # the same class usermod_targets() already raises for an axis put on
    # a port that has none -- not wrapped into UsermodConfigError.
    write_config(tmp_path, '[esp32]\nboards = ["NOT_A_REAL_BOARD"]\n')
    with pytest.raises(UnknownAxisError, match="unrecognised board 'NOT_A_REAL_BOARD'"):
        UsermodOptions.load(tmp_path).targets()


def test_an_unknown_key_on_axisless_port_is_rejected(tmp_path):
    # `variant` is real (three of five ports' *BuildOptions have a fixed
    # one) but has no config surface at all yet -- so it is simply
    # unknown to webassembly's own schema, the same as any other typo.
    # (Before Phase F, any non-empty table on an axisless port was
    # rejected outright, since a per-port table could only ever mean an
    # axis override; now it can also carry user-c-modules/manifest/
    # extra-make-args, so only a key genuinely unknown to the schema is
    # an error.)
    write_config(
        tmp_path,
        """
        [webassembly]
        variant = ["pyscript"]
        """,
    )
    with pytest.raises(
        UsermodConfigError, match=r"\[webassembly\]: unknown key `variant`"
    ):
        UsermodOptions.load(tmp_path)


def test_axis_table_qemu_boards_selects_riscv(tmp_path):
    write_config(
        tmp_path,
        """
        [qemu]
        boards = ["VIRT_RV32", "VIRT_RV64"]
        """,
    )
    options = UsermodOptions.load(tmp_path)

    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == [
        f"{DEFAULT_MICROPYTHON}-qemu-VIRT_RV32",
        f"{DEFAULT_MICROPYTHON}-qemu-VIRT_RV64",
    ]


def test_user_c_modules_and_manifest_default(tmp_path):
    # "." (the project root), not "usermod" -- record 0051's ninth
    # addendum: the old default was a leftover of the [usermod] table
    # name that used to exist pre-Phase-F, not an argued choice, and "."
    # is the broader glob (py.mk's own USER_C_MODULES/*/micropython.mk
    # still finds a real usermod/ subdirectory just as well).
    write_config(tmp_path, "[unix]\n")
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.user_c_modules == "."
    assert build_options.manifest == ""


def test_user_c_modules_and_manifest_overridable_globally(tmp_path):
    # A global (bare top-level) value is every active port's own default
    # -- the cascade's whole point (Phase F): natmod has no `manifest`
    # key at all, so this is unambiguous even in a config that also has
    # [natmod]. Still true after the ninth addendum's own [usermod]
    # family tier -- global stays the least-specific layer, not replaced.
    write_config(
        tmp_path,
        """
        user-c-modules = "mymod"
        manifest = "extra_manifest.py"
        [unix]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.user_c_modules == "mymod"
    assert build_options.manifest == "extra_manifest.py"


def test_user_c_modules_inside_a_port_table_is_an_error(tmp_path):
    # record 0052's own live-caught correction, retracting Phase F's own
    # per-platform-table cascade wiring this test used to cover:
    # [unix] user-c-modules = "..." was always exactly a sufficiently-
    # scoped global (or [usermod]-family) value restated, since unix's
    # own real identifiers already carry a marker ([override] could
    # already address directly). It is a loud, specific "move it to the
    # top level" error now, the same as any other generic key.
    write_config(
        tmp_path,
        """
        user-c-modules = "shared"
        [unix]
        user-c-modules = "unix-only"
        """,
    )
    with pytest.raises(UsermodConfigError, match="read from the top level"):
        UsermodOptions.load(tmp_path)


def test_usermod_family_table_beats_global(tmp_path):
    # [usermod] still sits strictly between the bare top level and every
    # port -- that tier was never in question, only the per-port table
    # one level below it (see test_user_c_modules_inside_a_port_table_is_
    # an_error above). [webassembly] has no override of its own, so it
    # falls through to [usermod]'s value, not the (less specific) global
    # one.
    write_config(
        tmp_path,
        """
        user-c-modules = "global-default"
        [usermod]
        user-c-modules = "family-default"
        [webassembly]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.user_c_modules == "family-default"


def test_empty_usermod_family_table_is_not_an_error(tmp_path):
    # [usermod] with nothing in it (or nothing at all) is legal -- it is
    # not a selector any more (Phase F), so its own presence or absence
    # never changes which ports are active, only their shared defaults.
    write_config(tmp_path, "[usermod]\n[unix]\n")
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.user_c_modules == "."


def test_a_key_valid_for_a_different_platform_is_rejected(tmp_path):
    # `make-target` is natmod-only. Written inside [webassembly] it must
    # still be a loud, specific error -- this is the regression test for
    # the two-tier validation split the cascade needs: per-platform-table
    # validation checks only that platform's own schema, never the union
    # of every platform's, or a misplaced key would silently readmit
    # record 0048's own bug under the cascade.
    write_config(
        tmp_path,
        """
        [unix]
        archs = ["manylinux_2_28_x86_64"]
        [webassembly]
        make-target = "x"
        """,
    )
    with pytest.raises(
        UsermodConfigError, match=r"\[webassembly\]: unknown key `make-target`"
    ):
        UsermodOptions.load(tmp_path)


def test_ports_key_inside_a_port_table_is_rejected(tmp_path):
    # There is no more `ports = [...]` concept at all -- a config that
    # still writes one (a plausible post-migration typo) gets the same
    # loud "unknown key" error any other typo does.
    write_config(tmp_path, '[unix]\nports = ["windows"]\n')

    with pytest.raises(UsermodConfigError, match=r"\[unix\]: unknown key `ports`"):
        UsermodOptions.load(tmp_path)


def test_build_skip_selectors(tmp_path):
    write_config(
        tmp_path,
        """
        build = "*-manylinux_2_28_x86_64 *-manylinux_2_28_i686"
        skip = "*-manylinux_2_28_i686"
        [unix]
        """,
    )
    options = UsermodOptions.load(tmp_path)

    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == [f"{DEFAULT_MICROPYTHON}-unix-manylinux_2_28_x86_64"]


def test_micropython_shared_top_level_key(tmp_path):
    write_config(tmp_path, 'micropython = "v1.24.0"\n')
    options = UsermodOptions.load(tmp_path)

    assert options.micropython == ["v1.24.0"]


def test_micropython_list_keeps_every_entry(tmp_path):
    # Before 0051 this was silently truncated to the first entry, the
    # only thing standing between a two-tag config and a collision (the
    # identifier carried no version, so two releases' output landed in
    # the same directory under the same filename). Now the identifier
    # carries the tag, so nothing needs truncating.
    write_config(tmp_path, 'micropython = ["v1.24.0", "v1.21.0"]\n')
    options = UsermodOptions.load(tmp_path)

    assert options.micropython == ["v1.24.0", "v1.21.0"]


def test_build_options_carries_user_c_modules_and_manifest(tmp_path):
    write_config(
        tmp_path,
        """
        user-c-modules = "mymod"
        manifest = "extra.py"
        [unix]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    target = options.targets()[0]
    build_options = options.build_options(target)

    assert (
        build_options.identifier == f"{DEFAULT_MICROPYTHON}-unix-manylinux_2_28_x86_64"
    )
    assert build_options.port == "unix"
    assert build_options.user_c_modules == "mymod"
    assert build_options.manifest == "extra.py"


def test_extra_make_args_shared_across_targets(tmp_path):
    write_config(
        tmp_path,
        """
        extra-make-args = ["DEBUG=1"]
        [unix]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.extra_make_args == ["DEBUG=1"]


# ── record 0048: where build/skip live, and typos in platform tables ────


def test_skip_is_read_from_the_top_level(tmp_path):
    # The canonical, and now the only, placement -- there is no more
    # `[usermod]` for a deprecated nested spelling to live in.
    write_config(
        tmp_path,
        """
        skip = "*-manylinux_2_28_i686"
        [unix]
        """,
    )
    identifiers = [t.identifier for t in UsermodOptions.load(tmp_path).targets()]

    assert not any(i.endswith("manylinux_2_28_i686") for i in identifiers)
    assert any(i.endswith("manylinux_2_28_x86_64") for i in identifiers)


def test_a_generic_key_inside_a_port_table_names_where_it_goes(tmp_path):
    # `version` is truly top-level-only, same as every other generic key
    # -- "unknown key" would be a lie here, the tool knows precisely what
    # `version` means, just not in this table.
    write_config(tmp_path, '[unix]\nversion = "0.1.0"\n')

    with pytest.raises(UsermodConfigError, match="read from the top level"):
        UsermodOptions.load(tmp_path)


def test_skip_inside_a_port_table_is_an_error(tmp_path):
    # record 0052's own live-caught correction, retracting the earlier
    # "per-platform build/skip" addendum this test used to cover:
    # [unix]'s own skip was always exactly a sufficiently-scoped
    # top-level pattern restated, so it is a loud, specific "move it to
    # the top level" error now -- `archs` (the port's own real axis key)
    # stays legal right beside it, unaffected.
    write_config(
        tmp_path,
        """
        [unix]
        archs = ["manylinux_2_28_i686", "manylinux_2_28_x86_64"]
        skip = ""
        """,
    )
    with pytest.raises(UsermodConfigError, match="read from the top level"):
        UsermodOptions.load(tmp_path)


def test_family_skip_narrows_every_active_port_but_not_natmod(tmp_path):
    # [usermod]'s own skip/build sit strictly between global and
    # per-port, the same tier every other family-scoped key already has
    # -- a port with no skip of its own still falls through to
    # [usermod]'s, not straight past it to the top level.
    write_config(
        tmp_path,
        """
        [usermod]
        skip = "*-webassembly"

        [unix]
        [webassembly]
        """,
    )
    identifiers = [t.identifier for t in UsermodOptions.load(tmp_path).targets()]

    assert not any(i.endswith("webassembly") for i in identifiers)
    assert any("-unix-" in i for i in identifiers)


def test_per_port_build_skip_env_override(tmp_path, monkeypatch):
    # CIBMP_SKIP_UNIX -- the per-platform env var every other dual-read
    # key already gets for free from the cascade.
    write_config(tmp_path, "[unix]\n[webassembly]\n")
    monkeypatch.setenv("CIBMP_SKIP_UNIX", "*")

    identifiers = [t.identifier for t in UsermodOptions.load(tmp_path).targets()]

    assert not any("-unix-" in i for i in identifiers)
    assert any(i.endswith("webassembly") for i in identifiers)


def test_reachability_audit_rejects_an_unreachable_build(tmp_path):
    # No [unix]-table build tier any more (record 0052's own live-caught
    # correction) -- build is global-only, checked against the full
    # identifier space this config can reach.
    write_config(tmp_path, 'build = "*-not-a-real-unix-cell"\n[unix]\n')

    with pytest.raises(UsermodConfigError, match=r"build: '\*-not-a-real"):
        UsermodOptions.load(tmp_path).targets()


def test_an_unknown_key_in_a_port_table_is_an_error(tmp_path):
    # `arch` for `archs` builds the whole default axis instead of the one
    # cell asked for -- a wrong build, not a missing one.
    write_config(
        tmp_path,
        """
        [unix]
        arch = ["manylinux_2_28_x86_64"]
        """,
    )

    with pytest.raises(UsermodConfigError, match=r"\[unix\]: unknown key"):
        UsermodOptions.load(tmp_path)


def test_a_port_table_with_a_valid_axis_key_is_accepted(tmp_path):
    write_config(
        tmp_path,
        """
        [unix]
        archs = ["manylinux_2_28_x86_64"]
        """,
    )
    options = UsermodOptions.load(tmp_path)

    assert [t.identifier for t in options.targets()] == [
        f"{DEFAULT_MICROPYTHON}-unix-manylinux_2_28_x86_64"
    ]


def test_shared_top_level_keys_honour_the_environment_in_usermod_mode(
    tmp_path, monkeypatch
):
    # This module's docstring claimed micropython/output-dir were read
    # "the same env-aware way natmod/options.py's own opt() does" while
    # the code consulted no environment at all, so CIBMP_MICROPYTHON
    # silently did nothing in usermod mode and worked in natmod mode.
    # Same defect as the one 0048 is named for, one layer up.
    write_config(tmp_path, 'micropython = "v1.21.0"\n[unix]\n')
    monkeypatch.setenv("CIBMP_MICROPYTHON", "v1.28.0")
    monkeypatch.setenv("CIBMP_OUTPUT_DIR", "elsewhere")
    options = UsermodOptions.load(tmp_path)

    assert options.micropython == ["v1.28.0"]
    assert options.output_dir == Path("elsewhere")


def test_name_and_version_default_empty_and_are_settable(tmp_path):
    # record 0052, A3: usermod reads `name`/`version` too now -- both feed
    # orchestrate.py's own _dest_name() filename prefix.
    write_config(tmp_path, "[unix]\n")
    unset = UsermodOptions.load(tmp_path)
    assert unset.name == ""
    assert unset.version == ""

    write_config(tmp_path, 'name = "mylib"\nversion = "1.2.0"\n[unix]\n')
    options = UsermodOptions.load(tmp_path)
    assert options.name == "mylib"
    assert options.version == "1.2.0"


# ── record 0051 point 7: [override] ──────────────────────────────


def test_usermod_overrides_beat_the_file(tmp_path):
    write_config(
        tmp_path,
        """
        extra-make-args = ["COMMON=1"]
        [unix]

        [override."*-manylinux_2_28_x86_64"]
        extra-make-args = ["FROM=override"]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    resolved = {
        t.arch: options.build_options(t).extra_make_args for t in options.targets()
    }
    assert resolved["manylinux_2_28_x86_64"] == ["FROM=override"]
    assert resolved["manylinux_2_28_i686"] == ["COMMON=1"]


def test_usermod_a_select_key_inside_an_override_body_is_an_error(tmp_path):
    write_config(
        tmp_path,
        '[unix]\n\n[override."*"]\nselect = "*"\nmanifest = "x.py"\n',
    )
    with pytest.raises(UsermodConfigError, match="select"):
        UsermodOptions.load(tmp_path)


def test_usermod_environment_beats_override(tmp_path):
    write_config(
        tmp_path,
        """
        [unix]

        [override."*"]
        extra-make-args = ["FROM=override"]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    target = options.targets()[0]
    env = {"CIBMP_EXTRA_MAKE_ARGS": "FROM=env A=1"}
    assert options.build_options(target, env=env).extra_make_args == [
        "FROM=env",
        "A=1",
    ]


def test_usermod_override_beats_the_file_for_manifest(tmp_path):
    write_config(
        tmp_path,
        """
        manifest = "default.py"
        [unix]

        [override."*"]
        manifest = "special.py"
        """,
    )
    options = UsermodOptions.load(tmp_path)
    assert options.build_options(options.targets()[0]).manifest == "special.py"


def test_an_unknown_key_in_usermod_overrides_is_an_error(tmp_path):
    write_config(
        tmp_path,
        """
        [unix]

        [override."*"]
        arch-flags = "zba"
        """,
    )
    with pytest.raises(UsermodConfigError, match=r'\[override\."\*"\]: unknown key'):
        UsermodOptions.load(tmp_path)


def test_reachability_audit_rejects_an_override_select_that_can_never_match(tmp_path):
    # record 0052, A5: "notaport" names no real port at all, in any tag --
    # all_targets() spans every known port regardless of which ones are
    # active here, so this is genuinely unreachable, not merely unselected.
    write_config(
        tmp_path,
        """
        [unix]

        [override."*-notaport"]
        extra-make-args = ["X=1"]
        """,
    )
    with pytest.raises(
        UsermodConfigError, match=r'\[override\."\*-notaport"\]: \'\*-notaport\''
    ):
        UsermodOptions.load(tmp_path).targets()


def test_reachability_audit_allows_an_override_meant_only_for_natmod(tmp_path):
    # task #66, reported live against the root cibuildmp.toml:
    # `cibuildmp --dry-run --platform unix` rejected a natmod-only
    # override ("*-armv7emsp" names no usermod identifier at all) as
    # unreachable, even though it is entirely valid natmod config this
    # invocation simply never loads (no [natmod] table here at all --
    # natmod's own all_targets() does not require one). extra-make-args
    # is deliberately used since it is one of the few keys shared by both
    # families' own override schemas -- the bug was never about the key,
    # only about which family's identifiers check_reachable() checked
    # select against.
    write_config(
        tmp_path,
        """
        [unix]

        [override."*-armv7emsp"]
        extra-make-args = ["MP_BCLIBC_PRECISION=single"]
        """,
    )
    UsermodOptions.load(tmp_path).targets()  # must not raise


def test_reachability_audit_allows_a_deliberate_skip_everything(tmp_path):
    # Same distinction as natmod's own case: skip = "*" narrows a real,
    # reachable domain to zero *selected* targets, which stays legitimate.
    write_config(tmp_path, 'skip = "*"\n[unix]\n')
    assert UsermodOptions.load(tmp_path).targets() == []


# ── record 0051 point 8: enable / GROUPS ──────────────────────────────────


def test_enable_reaches_the_emulated_everywhere_cells(tmp_path):
    write_config(tmp_path, 'enable = "unix-emulated-everywhere"\n[unix]\n')
    options = UsermodOptions.load(tmp_path)
    identifiers = [t.identifier for t in options.targets()]
    for arch in ("ppc64le", "s390x", "riscv64"):
        assert any(i.endswith(f"_{arch}") for i in identifiers), arch


def test_without_enable_the_emulated_everywhere_cells_stay_out(tmp_path):
    write_config(tmp_path, "[unix]\n")
    options = UsermodOptions.load(tmp_path)
    identifiers = [t.identifier for t in options.targets()]
    for arch in ("ppc64le", "s390x", "riscv64"):
        assert not any(i.endswith(f"_{arch}") for i in identifiers), arch


def test_unknown_enable_group_is_an_error(tmp_path):
    write_config(tmp_path, 'enable = "bogus"\n[unix]\n')
    options = UsermodOptions.load(tmp_path)
    with pytest.raises(UsermodConfigError, match="unknown group.*bogus"):
        options.targets()
