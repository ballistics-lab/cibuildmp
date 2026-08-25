from cibuildmp.usermod import dockerrun


def test_no_override_and_no_registration_means_host_build(monkeypatch):
    monkeypatch.delenv("CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})
    assert dockerrun.image_for("unix", "x64", "manylinux") is None


def test_registered_default_is_used_when_no_env_override(monkeypatch):
    monkeypatch.delenv("CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(
        dockerrun,
        "PORT_IMAGES",
        {"unix-x64-manylinux": "ghcr.io/example/cibuildmp-unix-manylinux-x64:latest"},
    )
    assert (
        dockerrun.image_for("unix", "x64", "manylinux")
        == "ghcr.io/example/cibuildmp-unix-manylinux-x64:latest"
    )


def test_env_override_wins_over_registered_default(monkeypatch):
    monkeypatch.setenv(
        "CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", "cibuildmp-unix-manylinux-x64:local"
    )
    monkeypatch.setattr(
        dockerrun,
        "PORT_IMAGES",
        {"unix-x64-manylinux": "ghcr.io/example/cibuildmp-unix-manylinux-x64:latest"},
    )
    assert (
        dockerrun.image_for("unix", "x64", "manylinux")
        == "cibuildmp-unix-manylinux-x64:local"
    )


def test_unregistered_arch_with_no_override_is_host_build(monkeypatch):
    # "unix-x64-manylinux" registered, but "unix-aarch64-manylinux" is
    # not -- each (port, arch, libc) triple is independent, one image
    # landing does not silently switch every other arch onto Docker too.
    monkeypatch.delenv("CIBMP_UNIX_AARCH64_MANYLINUX_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(
        dockerrun,
        "PORT_IMAGES",
        {"unix-x64-manylinux": "ghcr.io/example/cibuildmp-unix-manylinux-x64:latest"},
    )
    assert dockerrun.image_for("unix", "aarch64", "manylinux") is None


def test_unregistered_port_with_no_override_is_host_build(monkeypatch):
    monkeypatch.delenv("CIBMP_WINDOWS_X64_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})
    assert dockerrun.image_for("windows", "x64") is None


def test_libc_omitted_uses_a_two_part_key_and_env_name(monkeypatch):
    # Ports with no manylinux/musllinux-shaped axis (windows, qemu,
    # webassembly, esp32) call image_for() with no libc at all -- the key
    # and env var name both drop that segment entirely rather than
    # defaulting to a "manylinux" label that means nothing for them.
    monkeypatch.setenv("CIBMP_WINDOWS_X64_DOCKER_IMAGE", "cibuildmp-windows:local")
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})
    assert dockerrun.image_for("windows", "x64") == "cibuildmp-windows:local"

    monkeypatch.delenv("CIBMP_WINDOWS_X64_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(
        dockerrun,
        "PORT_IMAGES",
        {"windows-x64": "ghcr.io/example/cibuildmp-windows:latest"},
    )
    assert (
        dockerrun.image_for("windows", "x64")
        == "ghcr.io/example/cibuildmp-windows:latest"
    )
