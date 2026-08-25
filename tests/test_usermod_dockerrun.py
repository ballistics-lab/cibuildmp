from cibuildmp.usermod import dockerrun


def test_no_override_and_no_registration_means_no_image(monkeypatch):
    monkeypatch.delenv("CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})
    assert dockerrun.image_for("unix", "x64", "manylinux") is None


def test_registered_default_is_used_when_no_env_override(monkeypatch):
    monkeypatch.delenv("CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(
        dockerrun,
        "PORT_IMAGES",
        {
            "unix-x64-manylinux": "ghcr.io/example/cibuildmp-unix-manylinux-x64"
            "@sha256:" + "a" * 64
        },
    )
    assert dockerrun.image_for("unix", "x64", "manylinux") == (
        "ghcr.io/example/cibuildmp-unix-manylinux-x64@sha256:" + "a" * 64
    )


def test_env_override_wins_over_registered_default(monkeypatch):
    monkeypatch.setenv(
        "CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", "cibuildmp-unix-manylinux-x64:local"
    )
    monkeypatch.setattr(
        dockerrun,
        "PORT_IMAGES",
        {
            "unix-x64-manylinux": "ghcr.io/example/cibuildmp-unix-manylinux-x64"
            "@sha256:" + "a" * 64
        },
    )
    assert (
        dockerrun.image_for("unix", "x64", "manylinux")
        == "cibuildmp-unix-manylinux-x64:local"
    )


def test_unregistered_arch_with_no_override_is_none(monkeypatch):
    # "unix-x64-manylinux" registered, but "unix-aarch64-manylinux" is
    # not -- each (port, arch, libc) triple is independent, one image
    # landing does not silently switch every other arch onto Docker too.
    monkeypatch.delenv("CIBMP_UNIX_AARCH64_MANYLINUX_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(
        dockerrun,
        "PORT_IMAGES",
        {
            "unix-x64-manylinux": "ghcr.io/example/cibuildmp-unix-manylinux-x64"
            "@sha256:" + "a" * 64
        },
    )
    assert dockerrun.image_for("unix", "aarch64", "manylinux") is None


def test_unregistered_port_with_no_override_is_none(monkeypatch):
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
        {"windows-x64": "ghcr.io/example/cibuildmp-windows@sha256:" + "b" * 64},
    )
    assert dockerrun.image_for("windows", "x64") == (
        "ghcr.io/example/cibuildmp-windows@sha256:" + "b" * 64
    )


def test_arch_omitted_resolves_a_no_axis_port(monkeypatch):
    # qemu/webassembly have no per-build axis at all -- image_for(port)
    # with no arch must not grow a stray "-" in the key/env name.
    monkeypatch.setenv("CIBMP_QEMU_DOCKER_IMAGE", "cibuildmp-qemu:local")
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})
    assert dockerrun.image_for("qemu") == "cibuildmp-qemu:local"


# ── ensure_image() -- a thin alias for image_for(), no build fallback ──────
#
# cibuildmp never builds a Docker image itself any more (see
# dockerrun.py's own module docstring, checked directly against
# cibuildwheel's real source before deciding) -- ensure_image() only
# resolves which reference to use; run()'s own `--pull missing` is what
# actually fetches it. These cases exist mainly to pin that ensure_image()
# really is just image_for() under another name, with no extra
# subprocess call hiding behind it.


def test_ensure_image_matches_image_for_when_overridden(monkeypatch):
    monkeypatch.setenv(
        "CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", "cibuildmp-unix-manylinux-x64:local"
    )
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})

    assert (
        dockerrun.ensure_image("unix", "x64", "manylinux")
        == "cibuildmp-unix-manylinux-x64:local"
    )


def test_ensure_image_matches_image_for_when_registered(monkeypatch):
    monkeypatch.delenv("CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(
        dockerrun,
        "PORT_IMAGES",
        {
            "unix-x64-manylinux": "ghcr.io/example/cibuildmp-unix-manylinux-x64"
            "@sha256:" + "a" * 64
        },
    )

    assert dockerrun.ensure_image("unix", "x64", "manylinux") == (
        "ghcr.io/example/cibuildmp-unix-manylinux-x64@sha256:" + "a" * 64
    )


def test_ensure_image_is_none_when_nothing_resolves(monkeypatch):
    # Every port's real state today: publish-docker-images.yml has not
    # published anything yet, so PORT_IMAGES is empty and there is no
    # override -- ensure_image() must return None, not invent a build.
    monkeypatch.delenv("CIBMP_WINDOWS_ARM64_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})

    assert dockerrun.ensure_image("windows", "arm64") is None


def test_ensure_image_never_shells_out(monkeypatch):
    monkeypatch.setattr(
        dockerrun,
        "PORT_IMAGES",
        {
            "unix-x64-manylinux": "ghcr.io/example/cibuildmp-unix-manylinux-x64"
            "@sha256:" + "a" * 64
        },
    )
    calls = []
    monkeypatch.setattr(dockerrun.subprocess, "run", lambda *a, **k: calls.append(a))

    dockerrun.ensure_image("unix", "x64", "manylinux")
    dockerrun.ensure_image("windows", "arm64")

    assert calls == []
