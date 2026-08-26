from pathlib import Path

import pytest

from cibuildmp.platforms.natmod.options import DEFAULT_MICROPYTHON
from cibuildmp.platforms.usermod.options import UsermodConfigError, UsermodOptions
from cibuildmp.platforms.usermod.targets import KNOWN_PORTS, default_axis_values


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


def test_user_c_modules_overridable_per_port(tmp_path):
    # The direct test for Phase F's own cascade wiring: a value only
    # [unix] sets does not leak into [webassembly], which falls back to
    # the global default -- previously impossible, since this key was
    # one shared scalar across every selected port unconditionally.
    write_config(
        tmp_path,
        """
        user-c-modules = "shared"
        [unix]
        user-c-modules = "unix-only"
        [webassembly]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    by_port = {
        t.port: options.build_options(t).user_c_modules for t in options.targets()
    }

    assert by_port["unix"] == "unix-only"
    assert by_port["webassembly"] == "shared"


def test_usermod_family_table_beats_global_but_platform_beats_family(tmp_path):
    # The direct test for the ninth addendum's own new cascade tier:
    # [usermod] sits strictly between the bare top level and each
    # port's own table. [webassembly] has no override of its own, so it
    # falls through to [usermod]'s value, not the (less specific) global
    # one; [unix] overrides both.
    write_config(
        tmp_path,
        """
        user-c-modules = "global-default"
        [usermod]
        user-c-modules = "family-default"
        [unix]
        user-c-modules = "unix-only"
        [webassembly]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    by_port = {
        t.port: options.build_options(t).user_c_modules for t in options.targets()
    }

    assert by_port["unix"] == "unix-only"
    assert by_port["webassembly"] == "family-default"


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
        [unix]
        user-c-modules = "mymod"
        manifest = "extra.py"
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
        [unix]
        extra-make-args = ["DEBUG=1"]
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
    # `skip` (and every other GENERIC_KEYS member) applies to the whole
    # invocation, not to one platform -- the same "read from the top
    # level" diagnostic natmod's own [natmod] table gives, now shared.
    write_config(tmp_path, '[unix]\nskip = "*-manylinux_2_28_i686"\n')

    with pytest.raises(UsermodConfigError, match="read from the top level"):
        UsermodOptions.load(tmp_path)


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


# ── record 0051 point 7: [[overrides]] ───────────────────────────


def test_usermod_overrides_beat_the_file(tmp_path):
    write_config(
        tmp_path,
        """
        [unix]
        extra-make-args = ["COMMON=1"]

        [[overrides]]
        select = "*-manylinux_2_28_x86_64"
        extra-make-args = ["FROM=override"]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    resolved = {
        t.arch: options.build_options(t).extra_make_args for t in options.targets()
    }
    assert resolved["manylinux_2_28_x86_64"] == ["FROM=override"]
    assert resolved["manylinux_2_28_i686"] == ["COMMON=1"]


def test_usermod_override_without_select_is_an_error(tmp_path):
    write_config(
        tmp_path,
        '[unix]\n\n[[overrides]]\nmanifest = "x.py"\n',
    )
    options = UsermodOptions.load(tmp_path)
    with pytest.raises(UsermodConfigError, match="select"):
        options.build_options(options.targets()[0])


def test_usermod_environment_beats_override(tmp_path):
    write_config(
        tmp_path,
        """
        [unix]

        [[overrides]]
        select = "*"
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
        [unix]
        manifest = "default.py"

        [[overrides]]
        select = "*"
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

        [[overrides]]
        select = "*"
        arch-flags = "zba"
        """,
    )
    with pytest.raises(UsermodConfigError, match=r"\[\[overrides\]\]: unknown key"):
        UsermodOptions.load(tmp_path)


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
