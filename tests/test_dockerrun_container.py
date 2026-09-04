"""`dockerrun.Container` -- the long-lived container record 0095's addendum 2
introduced, and the command lines it builds.

Every test here asserts on the *arguments*, because the interesting part of
this class is which flags reach `docker` and when: the privilege pair the
overlay needs was measured on real runners
(`.github/workflows/probe-overlay.yml`, run 33866525827) and silently
dropping one of them would not fail any build until it reached CI, where the
mount would refuse and the failure would look like a build error.

The end-to-end behaviour -- a real overlay, a real `unix` build, the
artifact copied out -- is verified live rather than here; see the record's
own addenda for those numbers.
"""

from pathlib import Path, PurePosixPath

import pytest

from cibuildmp import dockerrun
from cibuildmp.platforms.usermod.build_common import UsermodBuildError


class _FakeCompleted:
    returncode = 0
    stdout = ""


@pytest.fixture
def calls(monkeypatch):
    """Every `subprocess.run()` argv `dockerrun` issues, in order."""
    recorded: list[list[str]] = []

    def fake_run(command, **kwargs):
        recorded.append(list(command))
        return _FakeCompleted()

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
    # No real image exists in these tests, so the platform probe must not
    # try to run one. It only fires for a non-host platform anyway.
    monkeypatch.setattr(dockerrun, "_probe_platform", lambda image, platform: "")
    return recorded


def _create(calls: list[list[str]]) -> list[str]:
    return next(c for c in calls if c[:2] == ["docker", "create"])


def test_create_requests_exactly_the_measured_overlay_privileges(calls):
    with dockerrun.Container(image="img"):
        pass

    create = _create(calls)
    assert "--cap-add" in create
    assert create[create.index("--cap-add") + 1] == "SYS_ADMIN"
    assert "apparmor=unconfined" in create
    # The probe found both of these unnecessary. Granting either anyway
    # would be a real widening of what every cibuildmp build runs as.
    assert "seccomp=unconfined" not in create
    assert "--privileged" not in create


def test_no_user_flag_unlike_run(calls):
    """`run()` passes `--user` so host-bind-mounted build output stays
    host-owned. Nothing here writes to the host, and the overlay mount needs
    a capability a non-root user does not keep -- so the flag must be gone,
    not merely optional."""
    with dockerrun.Container(image="img"):
        pass

    assert "--user" not in _create(calls)


def test_overlay_disabled_asks_for_no_extra_privileges(calls):
    with dockerrun.Container(image="img", overlay=False):
        pass

    create = _create(calls)
    assert "--cap-add" not in create
    assert dockerrun.OVERLAY_SCRATCH not in " ".join(create)


def test_keep_alive_is_not_sleep_infinity(calls):
    """busybox's own `sleep` (the musllinux/Alpine images) rejects
    `infinity`, so the keep-alive has to be a loop over a finite one."""
    with dockerrun.Container(image="img"):
        pass
    create = _create(calls)

    assert "infinity" not in " ".join(create)
    assert create[-3:] == ["sh", "-c", "while :; do sleep 3600; done"]


def test_ro_mounts_are_bound_read_only_and_plain_mounts_are_not(calls):
    with dockerrun.Container(
        image="img", mounts=[Path("/rw")], ro_mounts=[Path("/ro")]
    ):
        pass

    create = _create(calls)
    assert "/rw:/rw" in create
    assert "/ro:/cibuildmp-lower-1:ro" in create


def test_overlay_container_binds_the_lower_out_of_the_way(calls):
    """Not at its own host path, unlike every other mount: `overlay()` needs
    that path free to mount the writable view on."""
    with dockerrun.overlay_container(Path("/checkout"), image="img"):
        pass

    assert "/checkout:/cibuildmp-lower-1:ro" in _create(calls)


def test_overlay_mounts_the_writable_view_at_the_trees_own_host_path(calls):
    """The whole point: a `make` command line built from host paths runs
    unchanged inside, the same convention `run()` already established. A
    fixed `/mp` would make every driver translate `mpy_dir`, `BUILD=`,
    `USER_C_MODULES` and `MICROPY_MPYCROSS` on the way in."""
    with dockerrun.overlay_container(Path("/checkout"), image="img") as container:
        container.overlay(Path("/checkout"))

    script = next(c for c in calls if "lowerdir=" in c[-1])[-1]
    assert "lowerdir=/cibuildmp-lower-1" in script
    assert f"upperdir={dockerrun.OVERLAY_SCRATCH}/up-1" in script
    assert f"workdir={dockerrun.OVERLAY_SCRATCH}/work-1" in script
    assert script.rstrip().endswith("/checkout")


def test_two_overlays_in_one_container_do_not_share_upper_dirs(calls):
    with dockerrun.Container(
        image="img", ro_mounts=[Path("/a"), Path("/b")]
    ) as container:
        container.overlay(Path("/a"))
        container.overlay(Path("/b"))

    scripts = [c[-1] for c in calls if "lowerdir=" in c[-1]]
    assert len(scripts) == 2
    assert "up-1" in scripts[0] and "up-2" in scripts[1]


def test_overlay_refuses_a_lower_that_was_never_bound(calls):
    with (
        dockerrun.Container(image="img") as container,
        pytest.raises(UsermodBuildError, match="read-only bind"),
    ):
        container.overlay(Path("/never-mounted"))


def test_overlay_refuses_when_the_container_asked_for_none(calls):
    with (
        dockerrun.Container(image="img", overlay=False) as container,
        pytest.raises(UsermodBuildError, match="overlay=False"),
    ):
        container.overlay(Path("/x"))


def test_call_outside_the_with_block_is_an_error():
    container = dockerrun.Container(image="img")
    with pytest.raises(UsermodBuildError, match="outside the `with` block"):
        container.call(["true"], workdir=PurePosixPath("/"))


def test_exit_force_removes_the_container_and_its_volumes(calls):
    with dockerrun.Container(image="img") as container:
        name = container.name

    assert ["docker", "rm", "--force", "--volumes", name] in calls


def test_exit_still_removes_the_container_when_the_body_raises(calls):
    with pytest.raises(RuntimeError), dockerrun.Container(image="img") as container:
        name = container.name
        raise RuntimeError("build blew up")

    assert ["docker", "rm", "--force", "--volumes", name] in calls


def test_call_passes_workdir_and_env_to_exec(calls):
    with dockerrun.Container(image="img") as container:
        container.call(
            ["make", "-C", "/mp"], workdir=PurePosixPath("/mp"), env={"K": "V"}
        )

    exec_call = next(c for c in calls if c[:2] == ["docker", "exec"])
    assert exec_call[:4] == ["docker", "exec", "--workdir", "/mp"]
    assert "K=V" in exec_call
    assert exec_call[-3:] == ["make", "-C", "/mp"]


def test_a_timed_out_call_kills_the_container_rather_than_only_the_cli(
    monkeypatch, calls
):
    """The same reasoning `run()` documents: killing the `docker` CLI leaves
    the container itself running under `dockerd`, several process hops
    away."""
    real_run = dockerrun.subprocess.run

    def fake_run(command, **kwargs):
        if command[:2] == ["docker", "exec"]:
            raise dockerrun.subprocess.TimeoutExpired(command, 1.0)
        return real_run(command, **kwargs)

    with dockerrun.Container(image="img") as container:
        monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
        with pytest.raises(UsermodBuildError, match="timed out"):
            container.call(["sleep", "99"], workdir=PurePosixPath("/"), timeout=1.0)

    assert ["docker", "kill", container.name] in calls


def test_copy_out_uses_exec_tar_not_docker_cp(monkeypatch, tmp_path):
    """`docker cp` cannot see a mount the container made itself -- the
    daemon reads the container's filesystem through its own graph driver.
    Live-caught: copying a built binary out of an overlay failed with
    "Could not find the file ... in container" while `docker cp` of an
    ordinary container path in the same container worked."""
    recorded: list[list[str]] = []

    class _FakePopen:
        def __init__(self, command, **kwargs):
            recorded.append(list(command))
            self.stdout = open(  # noqa: SIM115 -- closed by copy_out's `with`
                tmp_path / "empty", "wb+"
            )

        def wait(self):
            return 0

    def fake_run(command, **kwargs):
        recorded.append(list(command))
        if command[0] == "tar":
            # Stand in for the extraction, which copy_out then moves.
            staged = Path(command[command.index("-C") + 1]) / "micropython"
            staged.write_bytes(b"ELF")
        return _FakeCompleted()

    (tmp_path / "empty").write_bytes(b"")
    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)
    monkeypatch.setattr(dockerrun.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(dockerrun, "_probe_platform", lambda image, platform: "")

    with dockerrun.Container(image="img") as container:
        container.copy_out(
            PurePosixPath("/mp/ports/unix/build/micropython"), tmp_path / "out" / "bin"
        )

    assert not any(c[:2] == ["docker", "cp"] for c in recorded)
    producer = next(c for c in recorded if c[:2] == ["docker", "exec"])
    assert producer[-5:] == ["-cf", "-", "-C", "/mp/ports/unix/build", "micropython"]
    extractor = next(c for c in recorded if c[0] == "tar")
    assert "--no-same-owner" in extractor
    assert (tmp_path / "out" / "bin").read_bytes() == b"ELF"
