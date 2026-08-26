import json

from cibuildmp.cli import main
from cibuildmp.platforms.natmod.options import DEFAULT_MICROPYTHON
from cibuildmp.platforms.usermod.targets import default_axis_values


def write(tmp_path, text):
    (tmp_path / "cibuildmp.toml").write_text(text)
    return str(tmp_path)


def _default_build_unix_cells():
    # Same derivation as test_usermod_options.py's own helper: what
    # build = "*" actually selects, the full axis minus the
    # emulated-everywhere group (0051 point 8).
    return [
        v
        for v in default_axis_values("unix")
        if not v.endswith(("_ppc64le", "_s390x", "_riscv64"))
    ]


def make_module_dir(package_dir, name="usermod"):
    mod = package_dir / name / "mymod"
    mod.mkdir(parents=True)
    (mod / "mymod.c").write_text("// stub\n")
    (mod / "micropython.mk").write_text("SRC_USERMOD += mymod.c\n")


def test_no_config_still_defaults_to_natmod(tmp_path, capsys):
    # No cibuildmp.toml at all -- must build exactly as it always has,
    # completely untouched by usermod's own existence.
    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    identifiers = capsys.readouterr().out.split()
    assert "mpy6.3-natmod-x64" in identifiers
    assert not any(i.startswith("unix") for i in identifiers)


def test_a_port_table_dispatches_to_usermod_cli(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, "[unix]\n")

    # This test is about dispatch -- a `[unix]` table reaching the
    # usermod CLI at all -- not about which unix cells the default axis
    # holds, so it derives them. See test_usermod_targets.py for the one
    # place that asserts the list itself.
    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == [
        f"{DEFAULT_MICROPYTHON}-unix-{value}" for value in _default_build_unix_cells()
    ]


def test_usermod_print_build_identifiers_json(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, "[esp32]\n")

    assert main([str(tmp_path), "--print-build-identifiers", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        f"{DEFAULT_MICROPYTHON}-esp32-ESP32_GENERIC"
    ]


def test_usermod_dry_run_lists_every_target(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, "[webassembly]\n")

    assert main([str(tmp_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "webassembly" in out
    # No runner in the plan line any more -- cibuildmp does not choose a
    # host for anything (record 0049).
    assert "runs-on" not in out


def test_usermod_only_selects_one_target(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, "[unix]\n")

    assert (
        main(
            [
                str(tmp_path),
                "--only",
                f"{DEFAULT_MICROPYTHON}-unix-manylinux_2_28_i686",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == [
        f"{DEFAULT_MICROPYTHON}-unix-manylinux_2_28_i686"
    ]


def test_usermod_only_unknown_identifier_is_an_error(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, "[unix]\n")

    # `unix-riscv64` is the bare-arch spelling records 0043/0044 retired;
    # the real identifier is `unix-manylinux_2_39_riscv64`. The error now
    # says the name is unknown and lists what exists, rather than blaming
    # the config -- after 0045 the config is not consulted at all.
    assert main([str(tmp_path), "--only", "unix-riscv64"]) == 2
    err = capsys.readouterr().err
    assert "is not a known usermod identifier" in err
    assert f"{DEFAULT_MICROPYTHON}-unix-manylinux_2_39_riscv64" in err


def test_usermod_only_reaches_a_target_the_config_does_not_select(tmp_path, capsys):
    # **0045**, and the case that produced it: every musllinux cell is
    # opt-in, so before this `--only` could not name one without editing
    # cibuildmp.toml -- for the flag whose whole purpose is "build exactly
    # this one thing". cibuildwheel takes its own `--only` choices from
    # `read_all_configs()` for the same reason.
    make_module_dir(tmp_path)
    write(tmp_path, "[unix]\n")

    assert (
        main(
            [
                str(tmp_path),
                "--only",
                f"{DEFAULT_MICROPYTHON}-unix-musllinux_1_2_ppc64le",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == [
        f"{DEFAULT_MICROPYTHON}-unix-musllinux_1_2_ppc64le"
    ]


def test_usermod_only_overrides_skip(tmp_path, capsys):
    # The flag's own help has always claimed this ("overriding the
    # config's own build/skip selectors") and it was not true: `--only`
    # filtered a list `select()` had already narrowed, so a skipped target
    # was gone before it was reached. 0045 found the claim sitting in a
    # code comment as settled parity.
    make_module_dir(tmp_path)
    write(
        tmp_path,
        'skip = "*-manylinux_2_28_x86_64"\n[unix]\n',
    )

    assert (
        main(
            [
                str(tmp_path),
                "--only",
                f"{DEFAULT_MICROPYTHON}-unix-manylinux_2_28_x86_64",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == [
        f"{DEFAULT_MICROPYTHON}-unix-manylinux_2_28_x86_64"
    ]


def test_usermod_only_reaches_a_port_the_config_does_not_list(tmp_path, capsys):
    # Upstream computes the platform *from* the identifier rather than
    # checking it against configuration; the same reasoning reaches ports
    # here, so naming a webassembly identifier works from a unix-only
    # config.
    make_module_dir(tmp_path)
    write(tmp_path, "[unix]\n")

    assert (
        main(
            [
                str(tmp_path),
                "--only",
                f"{DEFAULT_MICROPYTHON}-webassembly",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == [f"{DEFAULT_MICROPYTHON}-webassembly"]


# ── the headline new capability: >1 platform, one invocation ────────────


def test_both_tables_without_platform_builds_both(tmp_path, capsys):
    write(tmp_path, '[natmod]\narchs = ["x64"]\n[unix]\n')

    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    identifiers = capsys.readouterr().out.split()
    assert "mpy6.3-natmod-x64" in identifiers
    assert any(i.startswith(f"{DEFAULT_MICROPYTHON}-unix-") for i in identifiers)


def test_both_tables_print_build_identifiers_json_is_one_array(tmp_path, capsys):
    write(tmp_path, '[natmod]\narchs = ["x64"]\n[unix]\n')

    assert main([str(tmp_path), "--print-build-identifiers", "--json"]) == 0
    identifiers = json.loads(capsys.readouterr().out)
    assert "mpy6.3-natmod-x64" in identifiers
    assert any(i.startswith(f"{DEFAULT_MICROPYTHON}-unix-") for i in identifiers)


def test_both_tables_dry_run_lists_both(tmp_path, capsys):
    write(tmp_path, '[natmod]\narchs = ["x64"]\n[unix]\n')

    assert main([str(tmp_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "mpy6.3-natmod-x64" in out
    assert "unix" in out


def test_both_tables_combined_exit_code_is_the_worse_of_the_two(tmp_path, capsys):
    # skip="*-unix-*" matches every unix identifier (they all carry
    # "-unix-") and no natmod one ("mpy6.3-natmod-x64"), so unix selects
    # zero targets while natmod still builds fine. No --allow-empty, so
    # the combined exit code must still be 2.
    write(tmp_path, 'skip = "*-unix-*"\n[natmod]\narchs = ["x64"]\n[unix]\n')

    assert main([str(tmp_path), "--dry-run"]) == 2


def test_only_with_both_tables_narrows_to_the_matching_side(tmp_path, capsys):
    write(tmp_path, '[natmod]\narchs = ["x64"]\n[unix]\n')

    assert (
        main(
            [
                str(tmp_path),
                "--only",
                "mpy6.3-natmod-x64",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == ["mpy6.3-natmod-x64"]


def test_three_platforms_at_once(tmp_path, capsys):
    write(tmp_path, '[natmod]\narchs = ["x64"]\n[unix]\n[esp32]\n')

    assert main([str(tmp_path), "--print-build-identifiers", "--json"]) == 0
    identifiers = json.loads(capsys.readouterr().out)
    assert "mpy6.3-natmod-x64" in identifiers
    assert any(i.startswith(f"{DEFAULT_MICROPYTHON}-unix-") for i in identifiers)
    assert f"{DEFAULT_MICROPYTHON}-esp32-ESP32_GENERIC" in identifiers


# ── --platform, now a filter over six names rather than a mode select ───


def test_both_tables_explicit_platform_natmod(tmp_path, capsys):
    write(tmp_path, '[natmod]\narchs = ["x64"]\n[unix]\n')

    assert (
        main([str(tmp_path), "--platform", "natmod", "--print-build-identifiers"]) == 0
    )
    assert capsys.readouterr().out.split() == ["mpy6.3-natmod-x64"]


def test_both_tables_explicit_platform_qemu(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, "[natmod]\n[qemu]\n")

    assert main([str(tmp_path), "--platform", "qemu", "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == [f"{DEFAULT_MICROPYTHON}-qemu"]


def test_both_tables_platform_env_var(tmp_path, capsys, monkeypatch):
    # CIBMP_PLATFORM, not a dedicated action.yml input -- the same generic
    # env-override every cibuildmp.toml key already has, matching
    # cibuildwheel's own CIBW_BUILD shape.
    monkeypatch.setenv("CIBMP_PLATFORM", "natmod")
    write(tmp_path, '[natmod]\narchs = ["x64"]\n[unix]\n')

    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == ["mpy6.3-natmod-x64"]


def test_platform_flag_wins_over_env_var(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CIBMP_PLATFORM", "natmod")
    make_module_dir(tmp_path)
    write(tmp_path, "[natmod]\n[qemu]\n")

    assert main([str(tmp_path), "--platform", "qemu", "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == [f"{DEFAULT_MICROPYTHON}-qemu"]


def test_platform_env_var_bad_value_is_an_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CIBMP_PLATFORM", "bogus")
    write(tmp_path, "[natmod]\n")

    assert main([str(tmp_path), "--print-build-identifiers"]) == 2
    assert "unknown platform(s) bogus" in capsys.readouterr().err


def test_platform_usermod_is_no_longer_a_valid_name(tmp_path, capsys):
    # `usermod` was the old mode name, never a platform -- rejected now,
    # the same as any other unknown name.
    write(tmp_path, "[natmod]\n")

    assert main([str(tmp_path), "--platform", "usermod"]) == 2
    assert "unknown platform(s) usermod" in capsys.readouterr().err


# ── the flattened config tree ────────────────────────────────────────────


def test_legacy_usermod_table_is_a_clear_error(tmp_path, capsys):
    write(tmp_path, '[usermod]\nports = ["unix"]\n')

    assert main([str(tmp_path)]) == 2
    assert "[usermod] no longer exists" in capsys.readouterr().err


def test_unknown_top_level_table_is_an_error(tmp_path, capsys):
    write(tmp_path, "[stm32]\n")

    assert main([str(tmp_path)]) == 2
    assert "unknown table(s) at the top level: [stm32]" in capsys.readouterr().err


def test_usermod_no_targets_needs_allow_empty(tmp_path, capsys):
    write(tmp_path, 'skip = "*"\n[unix]\n')

    assert main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "no targets selected" in err

    assert main([str(tmp_path), "--allow-empty"]) == 0


# ── record 0051 point 8: --enable ────────────────────────────────────────


def test_enable_flag_reaches_the_emulated_everywhere_cells(tmp_path, capsys):
    write(tmp_path, "[unix]\n")

    assert (
        main(
            [
                str(tmp_path),
                "--enable",
                "unix-emulated-everywhere",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    identifiers = capsys.readouterr().out.split()
    for arch in ("ppc64le", "s390x", "riscv64"):
        assert any(i.endswith(f"_{arch}") for i in identifiers), arch


def test_enable_flag_without_it_still_excludes_them(tmp_path, capsys):
    write(tmp_path, "[unix]\n")

    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    identifiers = capsys.readouterr().out.split()
    for arch in ("ppc64le", "s390x", "riscv64"):
        assert not any(i.endswith(f"_{arch}") for i in identifiers), arch


def test_archs_all_alone_does_not_reach_the_emulated_everywhere_group(tmp_path, capsys):
    # The one narrow, deliberate behaviour change 0051 point 8 makes:
    # --archs all resolves the axis to all fifteen cells, but the group
    # filter still applies on top -- matching upstream's own precedent
    # (CIBW_ARCHS=all does not alone build pypy; CIBW_ENABLE=pypy is
    # still required).
    write(tmp_path, "[unix]\n")

    assert main([str(tmp_path), "--archs", "all", "--print-build-identifiers"]) == 0
    identifiers = capsys.readouterr().out.split()
    assert len(identifiers) == 9
    for arch in ("ppc64le", "s390x", "riscv64"):
        assert not any(i.endswith(f"_{arch}") for i in identifiers), arch


def test_archs_all_with_enable_reaches_every_cell(tmp_path, capsys):
    write(tmp_path, "[unix]\n")

    assert (
        main(
            [
                str(tmp_path),
                "--archs",
                "all",
                "--enable",
                "unix-emulated-everywhere",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert len(capsys.readouterr().out.split()) == 15


def test_unknown_enable_group_is_an_error(tmp_path, capsys):
    write(tmp_path, "[unix]\n")

    assert main([str(tmp_path), "--enable", "bogus"]) == 2
    assert "unknown group" in capsys.readouterr().err
