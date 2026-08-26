from pathlib import Path

import pytest

from cibuildmp.usermod.options import UsermodConfigError, UsermodOptions
from cibuildmp.usermod.targets import KNOWN_PORTS


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "cibuildmp.toml"
    path.write_text(text)
    return path


def test_no_usermod_table_defaults_to_every_known_port(tmp_path):
    write_config(tmp_path, "[usermod]\n")
    options = UsermodOptions.load(tmp_path)

    assert options.ports == list(KNOWN_PORTS)
    assert options.module_dir == "usermod"
    assert options.manifest == ""


def test_ports_list_selects_a_subset(tmp_path):
    write_config(tmp_path, '[usermod]\nports = ["unix", "esp32"]\n')
    options = UsermodOptions.load(tmp_path)

    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == [
        "unix-manylinux_2_28_x86_64",
        "unix-manylinux_2_28_i686",
        "unix-manylinux_2_28_aarch64",
        "unix-manylinux_2_31_armv7l",
        "unix-manylinux_2_39_mipsel",
        "esp32-ESP32_GENERIC",
    ]


def test_per_port_axis_override(tmp_path):
    write_config(
        tmp_path,
        """
        [usermod]
        ports = ["unix"]

        [usermod.unix]
        archs = ["manylinux_2_28_aarch64"]
        """,
    )
    options = UsermodOptions.load(tmp_path)

    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == ["unix-manylinux_2_28_aarch64"]


def test_multiple_boards_same_port(tmp_path):
    # Answers the user's own question directly: yes, a list of boards for
    # one port produces one target each, built independently.
    write_config(
        tmp_path,
        """
        [usermod]
        ports = ["esp32"]

        [usermod.esp32]
        boards = ["ESP32_GENERIC", "ESP32_GENERIC_S3"]
        """,
    )
    options = UsermodOptions.load(tmp_path)

    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == ["esp32-ESP32_GENERIC", "esp32-ESP32_GENERIC_S3"]


def test_axis_table_on_axisless_port_rejected(tmp_path):
    write_config(
        tmp_path,
        """
        [usermod]
        ports = ["webassembly"]

        [usermod.webassembly]
        variant = ["pyscript"]
        """,
    )
    with pytest.raises(UsermodConfigError, match="no configurable axis"):
        UsermodOptions.load(tmp_path)


def test_axis_table_qemu_boards_selects_riscv(tmp_path):
    write_config(
        tmp_path,
        """
        [usermod]
        ports = ["qemu"]

        [usermod.qemu]
        boards = ["VIRT_RV32", "VIRT_RV64"]
        """,
    )
    options = UsermodOptions.load(tmp_path)

    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == ["qemu-VIRT_RV32", "qemu-VIRT_RV64"]


def test_module_dir_and_manifest_overridable(tmp_path):
    write_config(
        tmp_path,
        """
        [usermod]
        module-dir = "mymod"
        manifest = "extra_manifest.py"
        """,
    )
    options = UsermodOptions.load(tmp_path)

    assert options.module_dir == "mymod"
    assert options.manifest == "extra_manifest.py"


def test_build_skip_selectors(tmp_path):
    write_config(
        tmp_path,
        """
        [usermod]
        ports = ["unix"]
        build = "unix-manylinux_2_28_x86_64 unix-manylinux_2_28_i686"
        skip = "unix-manylinux_2_28_i686"
        """,
    )
    options = UsermodOptions.load(tmp_path)

    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == ["unix-manylinux_2_28_x86_64"]


def test_micropython_shared_top_level_key(tmp_path):
    write_config(tmp_path, 'micropython = "v1.24.0"\n\n[usermod]\n')
    options = UsermodOptions.load(tmp_path)

    assert options.micropython == "v1.24.0"


def test_micropython_list_takes_first_entry(tmp_path):
    # natmod's own D13 lets this be a list; usermod has no ABI axis to
    # span, so it must not str()-stringify the raw list into nonsense.
    write_config(tmp_path, 'micropython = ["v1.24.0", "v1.21.0"]\n\n[usermod]\n')
    options = UsermodOptions.load(tmp_path)

    assert options.micropython == "v1.24.0"


def test_build_options_carries_module_dir_and_manifest(tmp_path):
    write_config(
        tmp_path,
        """
        [usermod]
        ports = ["unix"]
        module-dir = "mymod"
        manifest = "extra.py"
        """,
    )
    options = UsermodOptions.load(tmp_path)
    target = options.targets()[0]
    build_options = options.build_options(target)

    assert build_options.identifier == "unix-manylinux_2_28_x86_64"
    assert build_options.port == "unix"
    assert build_options.module_dir == "mymod"
    assert build_options.manifest == "extra.py"


def test_extra_make_args_shared_across_targets(tmp_path):
    write_config(
        tmp_path,
        """
        [usermod]
        ports = ["unix"]
        extra-make-args = ["DEBUG=1"]
        """,
    )
    options = UsermodOptions.load(tmp_path)
    build_options = options.build_options(options.targets()[0])

    assert build_options.extra_make_args == ["DEBUG=1"]


# ── record 0048: where build/skip live, and typos in mode tables ────────


def test_skip_is_read_from_the_top_level(tmp_path):
    # The canonical placement in both modes as of 0048. natmod already
    # read it here; usermod read it from `[usermod]` and from nowhere
    # else, so the same key meant the same thing and was read from
    # opposite places with no diagnostic either way.
    write_config(
        tmp_path,
        """
        skip = "unix-manylinux_2_28_i686"
        [usermod]
        ports = ["unix"]
        """,
    )
    identifiers = [t.identifier for t in UsermodOptions.load(tmp_path).targets()]

    assert "unix-manylinux_2_28_i686" not in identifiers
    assert "unix-manylinux_2_28_x86_64" in identifiers


def test_the_old_usermod_placement_still_works_and_says_so(tmp_path, capsys):
    # Kept working rather than broken: it was the documented placement
    # for every usermod config written so far. Reported so it does not
    # stay the documented one by inertia.
    write_config(
        tmp_path,
        """
        [usermod]
        ports = ["unix"]
        skip = "unix-manylinux_2_28_i686"
        """,
    )
    identifiers = [t.identifier for t in UsermodOptions.load(tmp_path).targets()]
    captured = capsys.readouterr()

    assert "unix-manylinux_2_28_i686" not in identifiers
    assert "deprecated" in captured.err
    # stdout carries --print-build-identifiers / --print-build-matrix
    # output, and cibuildmp-matrix's own action does json.loads() on it.
    # A warning there would corrupt a matrix rather than merely clutter.
    assert captured.out == ""


def test_the_top_level_wins_when_both_are_written(tmp_path, capsys):
    write_config(
        tmp_path,
        """
        skip = "unix-manylinux_2_28_x86_64"
        [usermod]
        ports = ["unix"]
        skip = "unix-manylinux_2_28_i686"
        """,
    )
    identifiers = [t.identifier for t in UsermodOptions.load(tmp_path).targets()]

    assert "unix-manylinux_2_28_x86_64" not in identifiers
    assert "unix-manylinux_2_28_i686" in identifiers
    assert "deprecated" in capsys.readouterr().err


def test_an_unknown_key_in_the_usermod_table_is_an_error(tmp_path):
    write_config(tmp_path, '[usermod]\nports = ["unix"]\nmodule-dr = "."\n')

    with pytest.raises(UsermodConfigError, match="unknown key `module-dr`"):
        UsermodOptions.load(tmp_path)


def test_an_unknown_key_in_a_port_table_is_an_error(tmp_path):
    # `arch` for `archs` builds the whole default axis instead of the one
    # cell asked for -- a wrong build, not a missing one.
    write_config(
        tmp_path,
        """
        [usermod]
        ports = ["unix"]
        [usermod.unix]
        arch = ["manylinux_2_28_x86_64"]
        """,
    )

    with pytest.raises(UsermodConfigError, match=r"\[usermod\.unix\]: unknown key"):
        UsermodOptions.load(tmp_path)


def test_a_port_sub_table_is_not_an_unknown_key_in_usermod(tmp_path):
    write_config(
        tmp_path,
        """
        [usermod]
        ports = ["unix"]
        [usermod.unix]
        archs = ["manylinux_2_28_x86_64"]
        """,
    )
    options = UsermodOptions.load(tmp_path)

    assert [t.identifier for t in options.targets()] == ["unix-manylinux_2_28_x86_64"]


def test_shared_top_level_keys_honour_the_environment_in_usermod_mode(
    tmp_path, monkeypatch
):
    # This module's docstring claimed micropython/output-dir were read
    # "the same env-aware way options.py's own opt() does" while the code
    # consulted no environment at all, so CIBMP_MICROPYTHON silently did
    # nothing in usermod mode and worked in natmod mode. Same defect as
    # the one 0048 is named for, one layer up.
    write_config(tmp_path, 'micropython = "v1.21.0"\n[usermod]\nports = ["unix"]\n')
    monkeypatch.setenv("CIBMP_MICROPYTHON", "v1.28.0")
    monkeypatch.setenv("CIBMP_OUTPUT_DIR", "elsewhere")
    options = UsermodOptions.load(tmp_path)

    assert options.micropython == "v1.28.0"
    assert options.output_dir == Path("elsewhere")
