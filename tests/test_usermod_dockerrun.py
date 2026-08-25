import pytest

from cibuildmp.usermod import dockerrun
from cibuildmp.usermod.build import UsermodBuildError


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


def test_arch_omitted_resolves_a_no_axis_port(monkeypatch):
    # qemu/webassembly have no per-build axis at all -- image_for(port)
    # with no arch must not grow a stray "-" in the key/env name.
    monkeypatch.setenv("CIBMP_QEMU_DOCKER_IMAGE", "cibuildmp-qemu:local")
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})
    assert dockerrun.image_for("qemu") == "cibuildmp-qemu:local"


# ── ensure_image() -- image_for() plus the local-build fallback ────────────


def test_ensure_image_prefers_an_explicit_override_over_building(monkeypatch):
    monkeypatch.setenv(
        "CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", "cibuildmp-unix-manylinux-x64:local"
    )
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})
    calls = []
    monkeypatch.setattr(dockerrun.subprocess, "run", lambda *a, **k: calls.append(a))

    assert (
        dockerrun.ensure_image("unix", "x64", "manylinux")
        == "cibuildmp-unix-manylinux-x64:local"
    )
    assert calls == []


def test_ensure_image_prefers_a_registered_default_over_building(monkeypatch):
    monkeypatch.delenv("CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(
        dockerrun,
        "PORT_IMAGES",
        {"unix-x64-manylinux": "ghcr.io/example/cibuildmp-unix-manylinux-x64:latest"},
    )
    calls = []
    monkeypatch.setattr(dockerrun.subprocess, "run", lambda *a, **k: calls.append(a))

    assert (
        dockerrun.ensure_image("unix", "x64", "manylinux")
        == "ghcr.io/example/cibuildmp-unix-manylinux-x64:latest"
    )
    assert calls == []


def test_ensure_image_builds_the_packaged_dockerfile_when_nothing_is_named(
    monkeypatch,
):
    # Forces the plain-`docker build` branch of _build_command()
    # deterministically -- GITHUB_ACTIONS is set by the runner itself
    # whenever this suite actually runs in real CI, which would otherwise
    # make this exact test flip to the buildx+gha-cache branch depending
    # on where it's run from. See the GITHUB_ACTIONS=true test below for
    # that branch's own coverage.
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})
    calls = []
    monkeypatch.setattr(
        dockerrun.subprocess, "run", lambda cmd, **k: calls.append(cmd) or None
    )

    tag = dockerrun.ensure_image("unix", "x64", "manylinux")

    assert tag == "cibuildmp-unix-x64-manylinux:local"
    assert len(calls) == 1
    command = calls[0]
    assert command[:2] == ["docker", "build"]
    assert command[2] == "-f"
    assert command[3].endswith("unix-manylinux-x64.Dockerfile")
    assert command[4:6] == ["-t", tag]


def test_ensure_image_uses_buildx_gha_cache_inside_github_actions(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("CIBMP_UNIX_X64_MANYLINUX_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})
    calls = []
    # inspect (returncode used, not check=True) then use (check=True) --
    # a bare lambda covers both call shapes; only .returncode is read off
    # the inspect call's own result, and it always reports "found" here
    # (0) so create never gets a call to assert on separately.
    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: calls.append(cmd) or type("R", (), {"returncode": 0})(),
    )

    tag = dockerrun.ensure_image("unix", "x64", "manylinux")

    assert tag == "cibuildmp-unix-x64-manylinux:local"
    # inspect, use, then the real buildx build -- create is skipped since
    # inspect above reports the builder already exists.
    assert [c[:3] for c in calls[:2]] == [
        ["docker", "buildx", "inspect"],
        ["docker", "buildx", "use"],
    ]
    build_command = calls[2]
    assert build_command[:3] == ["docker", "buildx", "build"]
    assert "--cache-from" in build_command
    assert "type=gha,scope=unix-manylinux-x64" in build_command
    assert "--cache-to" in build_command
    assert "type=gha,mode=max,scope=unix-manylinux-x64" in build_command
    assert "--load" in build_command


def test_ensure_image_is_none_when_no_dockerfile_is_packaged(monkeypatch):
    # windows/arm64 and esp32's real case today: no override, nothing
    # registered, and cibuildmp ships no Dockerfile for this key either --
    # ensure_image() must not invent a build, it has to defer to a bare
    # host build the same way image_for() alone already did.
    monkeypatch.delenv("CIBMP_WINDOWS_ARM64_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})
    calls = []
    monkeypatch.setattr(dockerrun.subprocess, "run", lambda *a, **k: calls.append(a))

    assert dockerrun.ensure_image("windows", "arm64") is None
    assert calls == []


def test_ensure_image_reports_a_failed_build(monkeypatch):
    import subprocess

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CIBMP_QEMU_DOCKER_IMAGE", raising=False)
    monkeypatch.setattr(dockerrun, "PORT_IMAGES", {})

    def boom(cmd, **k):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(dockerrun.subprocess, "run", boom)

    with pytest.raises(UsermodBuildError, match="docker build .* failed"):
        dockerrun.ensure_image("qemu")
