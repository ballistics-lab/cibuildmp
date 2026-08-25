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
        "unix-x64",
        "unix-x86",
        "unix-aarch64",
        "unix-armhf",
        "unix-mipsel",
        "esp32-ESP32_GENERIC",
    ]


def test_per_port_axis_override(tmp_path):
    write_config(
        tmp_path,
        """
        [usermod]
        ports = ["unix"]

        [usermod.unix]
        archs = ["aarch64"]
        """,
    )
    options = UsermodOptions.load(tmp_path)

    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == ["unix-aarch64"]


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
        ports = ["qemu"]

        [usermod.qemu]
        archs = ["armv7m"]
        """,
    )
    with pytest.raises(UsermodConfigError, match="no configurable axis"):
        UsermodOptions.load(tmp_path)


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
        build = "unix-x64 unix-x86"
        skip = "unix-x86"
        """,
    )
    options = UsermodOptions.load(tmp_path)

    identifiers = [t.identifier for t in options.targets()]
    assert identifiers == ["unix-x64"]


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

    assert build_options.identifier == "unix-x64"
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
