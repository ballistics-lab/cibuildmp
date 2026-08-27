import fnmatch

import pytest

from cibuildmp.platforms.usermod.targets import (
    GROUPS,
    KNOWN_PORTS,
    UnknownAxisError,
    UnknownPortError,
    UsermodTarget,
    all_axis_values,
    axis_key,
    default_axis_values,
    host_arch,
    parse_axis_values,
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


def test_identifier_leads_with_the_tag_when_present():
    # 0051: the compatibility axis usermod was missing entirely -- leads
    # the identifier, the same position natmod's own `mpy6.3-` slot holds.
    assert (
        UsermodTarget(
            port="unix", arch="manylinux_2_28_x86_64", tag="v1.29.0"
        ).identifier
        == "v1.29.0-unix-manylinux_2_28_x86_64"
    )
    assert UsermodTarget(port="qemu", tag="v1.29.0").identifier == "v1.29.0-qemu"


def test_axis_key_names():
    assert axis_key("unix") == "archs"
    assert axis_key("windows") == "archs"
    assert axis_key("esp32") == "boards"
    assert axis_key("qemu") == "boards"
    assert axis_key("webassembly") is None


def test_axis_key_unknown_port_rejected():
    with pytest.raises(UnknownPortError, match="unknown usermod port"):
        axis_key("stm32")


def test_default_axis_values_unix_is_now_the_full_axis():
    # 0051 point 8: the six emulated-everywhere cells stopped being held
    # out of the axis itself (they used to be absent from a hardcoded
    # nine-cell default, pre-0051) -- default_axis_values("unix") is
    # exactly all_axis_values("unix") now. What still keeps a bare
    # `build = "*"` at nine cells is GROUPS, checked inside select(), not
    # axis membership -- test_usermod_options.py covers that end to end.
    assert default_axis_values("unix") == all_axis_values("unix")
    assert len(default_axis_values("unix")) == 15


def test_the_emulated_everywhere_group_covers_exactly_those_six_cells():
    # ppc64le/s390x/riscv64, both libcs -- emulated on every runner
    # GitHub offers, never built here or by hand (tracker [0044]). The
    # glob patterns in GROUPS are what select() checks against enable;
    # prove they match exactly this set and nothing else.
    targets = usermod_targets(["v1.29.0"], ["unix"], {})
    identifiers = [t.identifier for t in targets]
    patterns = GROUPS["unix-emulated-everywhere"]
    covered = {i for i in identifiers if any(fnmatch.fnmatch(i, p) for p in patterns)}
    assert covered == {
        i for i in identifiers if i.endswith(("_ppc64le", "_s390x", "_riscv64"))
    }
    assert len(covered) == 6


def test_default_axis_values_windows_includes_all_three():
    assert set(default_axis_values("windows")) == {"x64", "x86", "arm64"}


def test_default_axis_values_esp32_is_generic_only():
    assert default_axis_values("esp32") == ("ESP32_GENERIC",)


def test_usermod_targets_uses_defaults_when_no_override():
    # usermod_targets() itself applies no group filtering (that's
    # select()'s job -- 0051 point 8), so a bare call here returns the
    # full fifteen-cell axis, not the nine build="*" trims to.
    targets = usermod_targets(["v1.28.0"], ["unix"], {})
    assert [t.identifier for t in targets] == [
        "v1.28.0-unix-manylinux_2_28_x86_64",
        "v1.28.0-unix-musllinux_1_2_x86_64",
        "v1.28.0-unix-manylinux_2_28_i686",
        "v1.28.0-unix-musllinux_1_2_i686",
        "v1.28.0-unix-manylinux_2_28_aarch64",
        "v1.28.0-unix-musllinux_1_2_aarch64",
        "v1.28.0-unix-manylinux_2_28_ppc64le",
        "v1.28.0-unix-musllinux_1_2_ppc64le",
        "v1.28.0-unix-manylinux_2_28_s390x",
        "v1.28.0-unix-musllinux_1_2_s390x",
        "v1.28.0-unix-manylinux_2_31_armv7l",
        "v1.28.0-unix-musllinux_1_2_armv7l",
        "v1.28.0-unix-manylinux_2_39_riscv64",
        "v1.28.0-unix-musllinux_1_2_riscv64",
        "v1.28.0-unix-manylinux_2_39_mipsel",
    ]


def test_usermod_targets_products_over_every_tag():
    # The regression 0051 exists to fix: two tags of the same port/arch
    # must produce two distinct identifiers, in order, not one collision.
    targets = usermod_targets(["v1.28.0", "v1.29.0"], ["qemu"], {})
    assert [t.identifier for t in targets] == ["v1.28.0-qemu", "v1.29.0-qemu"]


def test_every_default_unix_cell_has_a_published_image():
    # The default axis is what a bare `ports = ["unix"]` resolves to, so
    # a cell in here with an empty pin fails at build time with "no image
    # registered" for every consumer at once. Cheap to assert, and the
    # exact failure mode `pinned_docker_images.toml`'s own "a key with an
    # empty value is a declared cell with nothing published yet" comment
    # describes.
    from cibuildmp import dockerrun

    for target in default_axis_values("unix"):
        assert dockerrun.image_for("unix", target), target


def test_usermod_targets_axis_override_replaces_default():
    targets = usermod_targets(
        ["v1.28.0"], ["unix"], {"unix": ["manylinux_2_28_aarch64"]}
    )
    assert [t.identifier for t in targets] == ["v1.28.0-unix-manylinux_2_28_aarch64"]


def test_usermod_targets_multiple_ports_preserve_order():
    targets = usermod_targets(["v1.28.0"], ["esp32", "qemu"], {})
    assert [t.identifier for t in targets] == [
        "v1.28.0-esp32-ESP32_GENERIC",
        "v1.28.0-qemu",
    ]


def test_usermod_targets_unknown_port_rejected():
    with pytest.raises(UnknownPortError, match="unknown usermod port"):
        usermod_targets(["v1.28.0"], ["stm32"], {})


def test_usermod_targets_axis_override_on_axisless_port_rejected():
    with pytest.raises(UnknownAxisError, match="no configurable axis"):
        usermod_targets(["v1.28.0"], ["webassembly"], {"webassembly": ["pyscript"]})


def test_usermod_targets_qemu_default_stays_bare_identifier():
    # qemu's own default axis value is the "" sentinel, not "MPS2_AN385"
    # -- an unconfigured build must keep its original bare "qemu"
    # identifier (see targets.py's own _PORT_AXES comment for why).
    targets = usermod_targets(["v1.28.0"], ["qemu"], {})
    assert [t.identifier for t in targets] == ["v1.28.0-qemu"]


def test_usermod_targets_qemu_board_override_selects_riscv():
    targets = usermod_targets(
        ["v1.28.0"], ["qemu"], {"qemu": ["VIRT_RV32", "VIRT_RV64"]}
    )
    assert [t.identifier for t in targets] == [
        "v1.28.0-qemu-VIRT_RV32",
        "v1.28.0-qemu-VIRT_RV64",
    ]


# ── default_runner (records 0043/0044) ──────────────────────────────────

# ── auto / native / all (record 0049) ───────────────────────────────────


def test_native_is_this_machines_architecture_only():
    assert parse_axis_values("unix", ["native"], machine="aarch64") == [
        "manylinux_2_28_aarch64",
        "musllinux_1_2_aarch64",
    ]


def test_auto_adds_the_32bit_sibling_the_host_can_execute():
    # The only difference between the two words, upstream too: an x86_64
    # host runs i686 directly, an aarch64 host runs armv7l directly (on
    # parts implementing AArch32 at EL0, which GitHub's arm64 runners do
    # -- 0044 measured it).
    auto = parse_axis_values("unix", ["auto"], machine="aarch64")
    assert "manylinux_2_31_armv7l" in auto
    assert "musllinux_1_2_armv7l" in auto


def test_mipsel_is_native_to_an_amd64_host_despite_its_name():
    # The case that makes "ask the image, not the tag" load-bearing:
    # manylinux_2_39_mipsel names mipsel and runs in a linux/amd64
    # container, because pypa publishes no mipsel image and there is
    # nothing for it to be native to. Matching the tag suffix would call
    # it non-native on the one host it is actually native on.
    assert "manylinux_2_39_mipsel" in parse_axis_values(
        "unix", ["native"], machine="x86_64"
    )
    assert "manylinux_2_39_mipsel" not in parse_axis_values(
        "unix", ["auto"], machine="aarch64"
    )


def test_all_is_every_cell_regardless_of_host():
    from cibuildmp.dockerrun import unix_targets

    for machine in ("x86_64", "aarch64", "s390x"):
        assert parse_axis_values("unix", ["all"], machine=machine) == list(
            unix_targets()
        )


def test_a_port_with_no_arch_axis_is_still_filtered_by_its_image():
    # The correction that cost a CI run. `windows`, `webassembly` and
    # `qemu` have no architecture axis, and an earlier cut exempted them
    # from `auto` on those grounds. But their images are `linux/amd64`,
    # so on an arm64 runner they run emulated exactly like a non-native
    # `unix` cell -- and `auto` kept selecting them. `webassembly` was
    # built three times in one run as a result.
    #
    # The question they lack is which *axis value* is native; the
    # question they have is whether their one image is.
    for port in ("windows", "webassembly", "qemu"):
        assert parse_axis_values(port, ["auto"], machine="x86_64"), port
        assert parse_axis_values(port, ["auto"], machine="aarch64") == [], port


def test_all_still_selects_those_ports_on_any_host():
    # `all` means every cell, emulated or not -- it is the word that
    # exists for saying "I do not care what this machine is".
    for port in ("windows", "webassembly", "qemu"):
        for machine in ("x86_64", "aarch64", "s390x"):
            assert parse_axis_values(port, ["all"], machine=machine) == list(
                default_axis_values(port)
            ), (port, machine)


def test_a_keyword_and_an_explicit_cell_can_be_mixed():
    # "what runs here, plus this one" is a legitimate thing to write, and
    # the result should not depend on which side of the comma a cell
    # appeared on.
    values = parse_axis_values(
        "unix", ["auto", "manylinux_2_28_s390x"], machine="x86_64"
    )
    assert "manylinux_2_28_s390x" in values
    assert "manylinux_2_28_x86_64" in values
    assert values == sorted(values, key=list(all_axis_values("unix")).index)


def test_an_unknown_axis_value_is_left_alone_to_fail_where_it_did():
    assert parse_axis_values("unix", ["not-a-cell"]) == ["not-a-cell"]


def test_host_arch_maps_kernel_spellings_to_the_projects_names():
    # pypa's names are the project's (0043) and a kernel does not always
    # agree: an arm/v7 container on an arm64 kernel reports armv8l.
    assert host_arch("aarch64") == "aarch64"
    assert host_arch("arm64") == "aarch64"
    assert host_arch("armv8l") == "armv7l"
    assert host_arch("AMD64") == "x86_64"
