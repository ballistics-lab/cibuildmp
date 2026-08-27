from cibuildmp.platforms.usermod.targets import (
    KNOWN_PORTS,
    UsermodTarget,
    all_usermod_targets,
)


def test_known_ports_matches_the_five_wired_drivers():
    assert set(KNOWN_PORTS) == {"unix", "windows", "qemu", "webassembly", "esp32"}


def test_identifier_bare_port_name_when_no_axis_and_no_tag():
    # Hand-built, tag-less targets (most build/orchestrate tests) fall
    # back to the plain pre-0052 {port}[-{arch}] shape rather than a real
    # row lookup.
    assert UsermodTarget(port="qemu", arch="").identifier == "qemu"
    assert UsermodTarget(port="webassembly", arch="").identifier == "webassembly"
    assert (
        UsermodTarget(port="unix", arch="manylinux_2_28_x86_64").identifier
        == "unix-manylinux_2_28_x86_64"
    )


def test_real_row_identifiers_are_read_verbatim_not_rebuilt():
    # The real, live-caught finding: resources/build-platforms.toml's own
    # identifier_format is NOT uniform across ports -- unix/windows/
    # webassembly carry no port name at all ("{tag}-{arch}"), qemu/esp32
    # do ("{tag}-{port}-{board}"). A tagged UsermodTarget looks its own
    # identifier up from the real row rather than reconstructing it, so
    # both shapes come out correctly.
    assert (
        UsermodTarget(
            port="unix", arch="manylinux_2_28_x86_64", tag="v1.29.0"
        ).identifier
        == "v1.29.0-manylinux_2_28_x86_64"
    )
    assert (
        UsermodTarget(port="webassembly", arch="wasm32", tag="v1.29.0").identifier
        == "v1.29.0-wasm32"
    )
    assert (
        UsermodTarget(port="qemu", arch="MICROBIT", tag="v1.24.0").identifier
        == "v1.24.0-qemu-MICROBIT"
    )
    assert (
        UsermodTarget(port="esp32", arch="ESP32_GENERIC", tag="v1.29.0").identifier
        == "v1.29.0-esp32-ESP32_GENERIC"
    )


def test_all_usermod_targets_covers_every_port_and_tag():
    targets = all_usermod_targets()
    by_port = {}
    for t in targets:
        by_port.setdefault(t.port, set()).add(t.tag)
    assert set(by_port) == set(KNOWN_PORTS)
    for port in KNOWN_PORTS:
        assert "v1.29.0" in by_port[port]


def test_all_usermod_targets_unix_v1_29_0_is_the_full_fifteen_cells():
    targets = [
        t for t in all_usermod_targets() if t.port == "unix" and t.tag == "v1.29.0"
    ]
    identifiers = [t.identifier for t in targets]
    assert identifiers == [
        "v1.29.0-manylinux_2_28_x86_64",
        "v1.29.0-musllinux_1_2_x86_64",
        "v1.29.0-manylinux_2_28_i686",
        "v1.29.0-musllinux_1_2_i686",
        "v1.29.0-manylinux_2_28_aarch64",
        "v1.29.0-musllinux_1_2_aarch64",
        "v1.29.0-manylinux_2_28_ppc64le",
        "v1.29.0-musllinux_1_2_ppc64le",
        "v1.29.0-manylinux_2_28_s390x",
        "v1.29.0-musllinux_1_2_s390x",
        "v1.29.0-manylinux_2_31_armv7l",
        "v1.29.0-musllinux_1_2_armv7l",
        "v1.29.0-manylinux_2_39_riscv64",
        "v1.29.0-musllinux_1_2_riscv64",
        "v1.29.0-manylinux_2_39_mipsel",
    ]


def test_all_usermod_targets_products_over_every_tag():
    # Two tags of the same port/board produce two distinct identifiers,
    # in order, not one collision (0051's own headline regression).
    identifiers = [
        t.identifier
        for t in all_usermod_targets()
        if t.port == "qemu" and t.arch == "MICROBIT"
    ]
    assert identifiers[:2] == ["v1.24.0-qemu-MICROBIT", "v1.24.1-qemu-MICROBIT"]
    assert len(set(identifiers)) == len(identifiers)


def test_all_usermod_targets_order_is_port_outer_row_order_inner():
    targets = all_usermod_targets()
    ports_seen = [t.port for t in targets]
    assert ports_seen == sorted(ports_seen, key=KNOWN_PORTS.index)
