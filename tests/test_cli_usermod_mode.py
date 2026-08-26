import json

from cibuildmp.cli import detect_mode, main
from cibuildmp.usermod.targets import default_axis_values


def write(tmp_path, text):
    (tmp_path / "cibuildmp.toml").write_text(text)
    return str(tmp_path)


# ── detect_mode() unit cases ─────────────────────────────────────────────


def test_detect_mode_no_tables_defaults_natmod():
    assert detect_mode({}, None) == "natmod"


def test_detect_mode_natmod_table_only():
    assert detect_mode({"natmod": {}}, None) == "natmod"


def test_detect_mode_usermod_table_only():
    assert detect_mode({"usermod": {}}, None) == "usermod"


def test_detect_mode_both_tables_ambiguous_without_explicit():
    assert detect_mode({"natmod": {}, "usermod": {}}, None) is None


def test_detect_mode_explicit_platform_always_wins():
    assert detect_mode({"natmod": {}}, "usermod") == "usermod"
    assert detect_mode({"usermod": {}}, "natmod") == "natmod"
    assert detect_mode({"natmod": {}, "usermod": {}}, "usermod") == "usermod"


# ── main() dispatch, end to end ──────────────────────────────────────────


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


def test_usermod_table_dispatches_to_usermod_cli(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, '[usermod]\nports = ["unix"]\n')

    # This test is about dispatch -- a `[usermod]` table reaching the
    # usermod CLI at all -- not about which unix cells the default axis
    # holds, so it derives them. See test_usermod_targets.py for the one
    # place that asserts the list itself.
    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == [
        f"unix-{value}" for value in default_axis_values("unix")
    ]


def test_usermod_print_build_identifiers_json(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, '[usermod]\nports = ["esp32"]\n')

    assert main([str(tmp_path), "--print-build-identifiers", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == ["esp32-ESP32_GENERIC"]


def test_usermod_dry_run_lists_every_target(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, '[usermod]\nports = ["webassembly"]\n')

    assert main([str(tmp_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "webassembly" in out
    # No runner in the plan line any more -- cibuildmp does not choose a
    # host for anything (record 0049).
    assert "runs-on" not in out


def test_usermod_only_selects_one_target(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, '[usermod]\nports = ["unix"]\n')

    assert (
        main(
            [
                str(tmp_path),
                "--only",
                "unix-manylinux_2_28_i686",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == ["unix-manylinux_2_28_i686"]


def test_usermod_only_unknown_identifier_is_an_error(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, '[usermod]\nports = ["unix"]\n')

    # `unix-riscv64` is the bare-arch spelling records 0043/0044 retired;
    # the real identifier is `unix-manylinux_2_39_riscv64`. The error now
    # says the name is unknown and lists what exists, rather than blaming
    # the config -- after 0045 the config is not consulted at all.
    assert main([str(tmp_path), "--only", "unix-riscv64"]) == 2
    err = capsys.readouterr().err
    assert "is not a known usermod identifier" in err
    assert "unix-manylinux_2_39_riscv64" in err


def test_usermod_only_reaches_a_target_the_config_does_not_select(tmp_path, capsys):
    # **0045**, and the case that produced it: every musllinux cell is
    # opt-in, so before this `--only` could not name one without editing
    # cibuildmp.toml -- for the flag whose whole purpose is "build exactly
    # this one thing". cibuildwheel takes its own `--only` choices from
    # `read_all_configs()` for the same reason.
    make_module_dir(tmp_path)
    write(tmp_path, '[usermod]\nports = ["unix"]\n')

    assert (
        main(
            [
                str(tmp_path),
                "--only",
                "unix-musllinux_1_2_ppc64le",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == ["unix-musllinux_1_2_ppc64le"]


def test_usermod_only_overrides_skip(tmp_path, capsys):
    # The flag's own help has always claimed this ("overriding the
    # config's own build/skip selectors") and it was not true: `--only`
    # filtered a list `select()` had already narrowed, so a skipped target
    # was gone before it was reached. 0045 found the claim sitting in a
    # code comment as settled parity.
    make_module_dir(tmp_path)
    write(
        tmp_path,
        '[usermod]\nports = ["unix"]\nskip = "unix-manylinux_2_28_x86_64"\n',
    )

    assert (
        main(
            [
                str(tmp_path),
                "--only",
                "unix-manylinux_2_28_x86_64",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == ["unix-manylinux_2_28_x86_64"]


def test_usermod_only_reaches_a_port_the_config_does_not_list(tmp_path, capsys):
    # Upstream computes the platform *from* the identifier rather than
    # checking it against configuration; the same reasoning reaches ports
    # here, so naming a webassembly identifier works from a unix-only
    # config.
    make_module_dir(tmp_path)
    write(tmp_path, '[usermod]\nports = ["unix"]\n')

    assert (
        main([str(tmp_path), "--only", "webassembly", "--print-build-identifiers"]) == 0
    )
    assert capsys.readouterr().out.split() == ["webassembly"]


def test_both_tables_without_platform_is_an_error(tmp_path, capsys):
    write(tmp_path, "[natmod]\n[usermod]\n")

    assert main([str(tmp_path), "--print-build-identifiers"]) == 2
    assert "both [natmod] and [usermod]" in capsys.readouterr().err


def test_both_tables_explicit_platform_natmod(tmp_path, capsys):
    write(tmp_path, '[natmod]\narchs = ["x64"]\n[usermod]\n')

    assert (
        main([str(tmp_path), "--platform", "natmod", "--print-build-identifiers"]) == 0
    )
    assert capsys.readouterr().out.split() == ["mpy6.3-natmod-x64"]


def test_both_tables_explicit_platform_usermod(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, '[natmod]\n[usermod]\nports = ["qemu"]\n')

    assert (
        main([str(tmp_path), "--platform", "usermod", "--print-build-identifiers"]) == 0
    )
    assert capsys.readouterr().out.split() == ["qemu"]


def test_both_tables_platform_env_var(tmp_path, capsys, monkeypatch):
    # CIBMP_PLATFORM, not a dedicated action.yml input -- the same generic
    # env-override every cibuildmp.toml key already has, matching
    # cibuildwheel's own CIBW_BUILD shape.
    monkeypatch.setenv("CIBMP_PLATFORM", "natmod")
    write(tmp_path, '[natmod]\narchs = ["x64"]\n[usermod]\n')

    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == ["mpy6.3-natmod-x64"]


def test_platform_flag_wins_over_env_var(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CIBMP_PLATFORM", "natmod")
    make_module_dir(tmp_path)
    write(tmp_path, '[natmod]\n[usermod]\nports = ["qemu"]\n')

    assert (
        main([str(tmp_path), "--platform", "usermod", "--print-build-identifiers"]) == 0
    )
    assert capsys.readouterr().out.split() == ["qemu"]


def test_platform_env_var_bad_value_is_an_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CIBMP_PLATFORM", "windows")
    write(tmp_path, "[natmod]\n")

    assert main([str(tmp_path), "--print-build-identifiers"]) == 2
    assert "CIBMP_PLATFORM" in capsys.readouterr().err


def test_usermod_bad_port_is_an_error(tmp_path, capsys):
    write(tmp_path, '[usermod]\nports = ["stm32"]\n')

    assert main([str(tmp_path)]) == 2
    assert "unknown usermod port" in capsys.readouterr().err


def test_usermod_no_targets_needs_allow_empty(tmp_path, capsys):
    write(tmp_path, '[usermod]\nports = ["unix"]\nskip = "*"\n')

    assert main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "no targets selected" in err

    assert main([str(tmp_path), "--allow-empty"]) == 0
