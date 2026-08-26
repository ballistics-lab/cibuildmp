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
    assert (
        UsermodTarget(port="unix", arch="manylinux_2_28_x86_64").identifier
        == "unix-manylinux_2_28_x86_64"
    )
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


def test_default_axis_values_unix_is_everything_proven_and_nothing_else():
    # The rule is "default = everything actually proven", not "everything
    # buildable": record 0043 took this matrix from five cells to
    # fifteen and the default did not grow with it, because defaulting to
    # all fifteen turns one `ports = ["unix"]` line into fifteen mostly
    # emulated container builds.
    #
    # The five manylinux entries are the pre-0043 default translated
    # one-for-one. The four musl entries joined on 2026-08-26, when they
    # went green and required in CI -- exactly the musl cells with a
    # runner they are native to. Holding them out at that point would
    # have meant the rule said one thing and this tuple another.
    assert default_axis_values("unix") == (
        "manylinux_2_28_x86_64",
        "musllinux_1_2_x86_64",
        "manylinux_2_28_i686",
        "musllinux_1_2_i686",
        "manylinux_2_28_aarch64",
        "musllinux_1_2_aarch64",
        "manylinux_2_31_armv7l",
        "musllinux_1_2_armv7l",
        "manylinux_2_39_mipsel",
    )


def test_the_emulated_everywhere_cells_are_still_not_defaulted():
    # `ppc64le`, `s390x` and `riscv64` -- both columns -- are emulated on
    # every runner GitHub offers and have never been built. The rule that
    # let musl in is the same rule that keeps these out, so assert the
    # other half of it explicitly rather than trusting the tuple above to
    # stay short by accident.
    defaults = set(default_axis_values("unix"))
    for arch in ("ppc64le", "s390x", "riscv64"):
        assert not any(d.endswith(f"_{arch}") for d in defaults), arch


def test_default_axis_values_windows_includes_all_three():
    assert set(default_axis_values("windows")) == {"x64", "x86", "arm64"}


def test_default_axis_values_esp32_is_generic_only():
    assert default_axis_values("esp32") == ("ESP32_GENERIC",)


def test_usermod_targets_uses_defaults_when_no_override():
    targets = usermod_targets(["unix"], {})
    assert [t.identifier for t in targets] == [
        "unix-manylinux_2_28_x86_64",
        "unix-musllinux_1_2_x86_64",
        "unix-manylinux_2_28_i686",
        "unix-musllinux_1_2_i686",
        "unix-manylinux_2_28_aarch64",
        "unix-musllinux_1_2_aarch64",
        "unix-manylinux_2_31_armv7l",
        "unix-musllinux_1_2_armv7l",
        "unix-manylinux_2_39_mipsel",
    ]


def test_every_default_unix_cell_has_a_published_image():
    # The default axis is what a bare `ports = ["unix"]` resolves to, so
    # a cell in here with an empty pin fails at build time with "no image
    # registered" for every consumer at once. Cheap to assert, and the
    # exact failure mode `pinned_docker_images.toml`'s own "a key with an
    # empty value is a declared cell with nothing published yet" comment
    # describes.
    from cibuildmp.usermod import dockerrun

    for target in default_axis_values("unix"):
        assert dockerrun.image_for("unix", target), target


def test_usermod_targets_axis_override_replaces_default():
    targets = usermod_targets(["unix"], {"unix": ["manylinux_2_28_aarch64"]})
    assert [t.identifier for t in targets] == ["unix-manylinux_2_28_aarch64"]


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


# ── default_runner (records 0043/0044) ──────────────────────────────────


def test_native_arm_targets_ask_for_an_arm_runner():
    # An aarch64 image on an amd64 runner is emulated, measured at ~20x a
    # native build (0044). Naming an arm64 runner makes it native.
    for tag in ("manylinux_2_28_aarch64", "musllinux_1_2_aarch64"):
        assert UsermodTarget(port="unix", arch=tag).default_runner == "ubuntu-24.04-arm"


def test_armv7l_is_grouped_with_aarch64_despite_the_aarch32_caveat():
    # Deliberate and uncertain: 32-bit ARM is native on an arm64 host only
    # if that CPU implements AArch32 at EL0, which server-class parts
    # generally do not -- cibuildwheel carries an explicit check for this
    # in `bitness_archs()`. Grouped here because the downside is nil
    # (emulated either way); this case exists so moving it back is a
    # visible decision rather than a silent edit.
    assert (
        UsermodTarget(port="unix", arch="manylinux_2_31_armv7l").default_runner
        == "ubuntu-24.04-arm"
    )


def test_every_other_target_stays_on_the_default_runner():
    for target in (
        UsermodTarget(port="unix", arch="manylinux_2_28_x86_64"),
        UsermodTarget(port="unix", arch="manylinux_2_28_i686"),
        UsermodTarget(port="unix", arch="manylinux_2_39_mipsel"),
        UsermodTarget(port="unix", arch="manylinux_2_39_riscv64"),
        UsermodTarget(port="webassembly", arch=""),
        UsermodTarget(port="qemu", arch=""),
    ):
        assert target.default_runner == "ubuntu-latest"


def test_cross_compiling_ports_never_ask_for_arm():
    # `windows`'s own arch axis contains "arm64", and it must not be
    # confused with a native ARM build: that image is an amd64 Linux
    # cross host targeting Windows, so an arm64 runner would only emulate
    # it for no gain.
    assert UsermodTarget(port="windows", arch="arm64").default_runner == "ubuntu-latest"
