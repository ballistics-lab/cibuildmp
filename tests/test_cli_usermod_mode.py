import json

from cibuildmp.cli import detect_mode, main


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

    assert main([str(tmp_path), "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == [
        "unix-x64",
        "unix-x86",
        "unix-aarch64",
    ]


def test_usermod_print_build_identifiers_json(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, '[usermod]\nports = ["esp32"]\n')

    assert main([str(tmp_path), "--print-build-identifiers", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == ["esp32-ESP32_GENERIC"]


def test_usermod_print_build_matrix_carries_runner(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, '[usermod]\nports = ["qemu"]\n')

    assert main([str(tmp_path), "--print-build-matrix"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"only": "qemu", "os": "ubuntu-latest"}
    ]


def test_usermod_dry_run_lists_every_target(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, '[usermod]\nports = ["webassembly"]\n')

    assert main([str(tmp_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "webassembly" in out
    assert "runs-on=ubuntu-latest" in out


def test_usermod_only_selects_one_target(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, '[usermod]\nports = ["unix"]\n')

    assert main([str(tmp_path), "--only", "unix-x86", "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == ["unix-x86"]


def test_usermod_only_unknown_identifier_is_an_error(tmp_path, capsys):
    make_module_dir(tmp_path)
    write(tmp_path, '[usermod]\nports = ["unix"]\n')

    assert main([str(tmp_path), "--only", "unix-riscv64"]) == 2
    assert "matches no usermod target" in capsys.readouterr().err


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
