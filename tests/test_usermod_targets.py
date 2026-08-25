import pytest

from cibuildmp.usermod.targets import (
    KNOWN_PORTS,
    UnknownAxisError,
    UnknownPortError,
    UsermodTarget,
    axis_key,
    default_axis_values,
    usermod_targets,
)


def test_known_ports_matches_the_five_wired_drivers():
    assert set(KNOWN_PORTS) == {"unix", "windows", "qemu", "webassembly", "esp32"}


def test_identifier_bare_port_name_when_no_axis():
    assert UsermodTarget(port="qemu", arch="").identifier == "qemu"
    assert UsermodTarget(port="webassembly", arch="").identifier == "webassembly"


def test_identifier_includes_axis_when_present():
    assert UsermodTarget(port="unix", arch="x64").identifier == "unix-x64"
    assert UsermodTarget(port="esp32", arch="ESP32_GENERIC").identifier == (
        "esp32-ESP32_GENERIC"
    )


def test_default_runner_is_ubuntu_latest_for_every_port():
    for port in KNOWN_PORTS:
        assert UsermodTarget(port=port).default_runner == "ubuntu-latest"


def test_axis_key_names():
    assert axis_key("unix") == "archs"
    assert axis_key("windows") == "archs"
    assert axis_key("esp32") == "boards"
    assert axis_key("qemu") == "boards"
    assert axis_key("webassembly") is None


def test_axis_key_unknown_port_rejected():
    with pytest.raises(UnknownPortError, match="unknown usermod port"):
        axis_key("stm32")


def test_default_axis_values_unix_includes_all_five_archs():
    # armhf/mipsel were pinned-but-unbuildable for a while (build_unix()
    # used to raise "not buildable yet"); now real, live-verified
    # cross-compiles like every other unix arch, so the default includes
    # them the same way aarch64 was added once it was proven simple.
    assert default_axis_values("unix") == ("x64", "x86", "aarch64", "armhf", "mipsel")


def test_default_axis_values_windows_includes_all_three():
    assert set(default_axis_values("windows")) == {"x64", "x86", "arm64"}


def test_default_axis_values_esp32_is_generic_only():
    assert default_axis_values("esp32") == ("ESP32_GENERIC",)


def test_usermod_targets_uses_defaults_when_no_override():
    targets = usermod_targets(["unix"], {})
    assert [t.identifier for t in targets] == [
        "unix-x64",
        "unix-x86",
        "unix-aarch64",
        "unix-armhf",
        "unix-mipsel",
    ]


def test_usermod_targets_axis_override_replaces_default():
    targets = usermod_targets(["unix"], {"unix": ["aarch64"]})
    assert [t.identifier for t in targets] == ["unix-aarch64"]


def test_usermod_targets_multiple_ports_preserve_order():
    targets = usermod_targets(["esp32", "qemu"], {})
    assert [t.identifier for t in targets] == ["esp32-ESP32_GENERIC", "qemu"]


def test_usermod_targets_unknown_port_rejected():
    with pytest.raises(UnknownPortError, match="unknown usermod port"):
        usermod_targets(["stm32"], {})


def test_usermod_targets_axis_override_on_axisless_port_rejected():
    with pytest.raises(UnknownAxisError, match="no configurable axis"):
        usermod_targets(["webassembly"], {"webassembly": ["pyscript"]})


def test_usermod_targets_qemu_default_stays_bare_identifier():
    # qemu's own default axis value is the "" sentinel, not "MPS2_AN385"
    # -- an unconfigured build must keep its original bare "qemu"
    # identifier (see targets.py's own _PORT_AXES comment for why).
    targets = usermod_targets(["qemu"], {})
    assert [t.identifier for t in targets] == ["qemu"]


def test_usermod_targets_qemu_board_override_selects_riscv():
    targets = usermod_targets(["qemu"], {"qemu": ["VIRT_RV32", "VIRT_RV64"]})
    assert [t.identifier for t in targets] == ["qemu-VIRT_RV32", "qemu-VIRT_RV64"]
