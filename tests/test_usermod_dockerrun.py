"""`usermod/dockerrun.py` -- image/platform resolution and `run()`'s own
container handling.

Every case here is pure: no Docker daemon, no network. That is a property
of the resolver rather than of the tests -- `image_for()`/`platform_for()`
read the packaged pin tables and the environment and nothing else, which
is what lets the precedence rules be covered at all.

The pins themselves are stubbed through `_pins`/`pinned_pypa_images`
rather than asserted against `resources/pinned_docker_images.toml`'s real
contents: those values change every time a maintainer records a new digest
(record 0033's own publish cadence), and a test that has to be edited on
every republish is a test that will be edited without being read.
"""

import pytest

from cibuildmp import dockerrun
from cibuildmp.platforms.usermod.build import UsermodBuildError

_FAKE_PINS = {
    "image": {
        "x86_64": {
            "manylinux_2_28": "ghcr.io/example/manylinux_2_28_x86_64@sha256:"
            + "a" * 64,
            "musllinux_1_2": "",
        },
        "aarch64": {"manylinux_2_28": "", "musllinux_1_2": ""},
        "mipsel": {"manylinux_2_39": ""},
    },
    "port": {
        "qemu": "ghcr.io/example/qemu@sha256:" + "b" * 64,
        "windows": "ghcr.io/example/windows@sha256:" + "c" * 64,
        "webassembly": "",
    },
}


@pytest.fixture(autouse=True)
def _stub_pins(monkeypatch):
    monkeypatch.setattr(dockerrun, "_pins", lambda: _FAKE_PINS)
    for name in (
        "CIBMP_UNIX_MANYLINUX_2_28_X86_64_DOCKER_IMAGE",
        "CIBMP_UNIX_MANYLINUX_2_28_AARCH64_DOCKER_IMAGE",
        "CIBMP_UNIX_MANYLINUX_2_28_X86_64_DOCKER_PLATFORM",
        "CIBMP_QEMU_DOCKER_IMAGE",
        "CIBMP_WINDOWS_X64_DOCKER_IMAGE",
        "CIBMP_UNIX_MANYLINUX_2_28_X86_64_TIMEOUT",
        "CIBMP_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)


# ── split_tag() / unix_targets() -- the matrix vocabulary ────────────────


def test_split_tag_separates_floor_from_arch():
    # Both halves contain underscores, so this cannot be a split on a
    # separator -- it is a match against the known architecture list.
    assert dockerrun.split_tag("manylinux_2_28_x86_64") == ("manylinux_2_28", "x86_64")
    assert dockerrun.split_tag("musllinux_1_2_ppc64le") == ("musllinux_1_2", "ppc64le")
    assert dockerrun.split_tag("manylinux_2_39_mipsel") == (
        "manylinux_2_39",
        "mipsel",
    )


def test_split_tag_rejects_an_unknown_architecture():
    with pytest.raises(UsermodBuildError, match="does not name a known architecture"):
        dockerrun.split_tag("manylinux_2_28_sparc64")


def test_unix_targets_lists_declared_cells_including_unpublished_ones():
    # A declared-but-empty cell is still a real, nameable target:
    # `--print-build-identifiers` must list it, and asking to build it
    # must fail with "no image registered" rather than "unknown arch".
    targets = dockerrun.unix_targets()

    assert "manylinux_2_28_x86_64" in targets
    assert "musllinux_1_2_x86_64" in targets  # declared, value is ""
    assert "manylinux_2_39_mipsel" in targets


def test_unix_targets_comes_from_the_real_pin_file(monkeypatch):
    # The one case that deliberately reads the shipped resource rather
    # than the stub: the matrix is data, and a typo that drops a whole
    # architecture from it should fail here rather than at build time.
    monkeypatch.undo()
    targets = dockerrun.unix_targets()

    assert len(targets) == 15
    for arch in ("x86_64", "i686", "aarch64", "armv7l", "ppc64le", "s390x", "riscv64"):
        assert f"musllinux_1_2_{arch}" in targets
    assert "manylinux_2_39_mipsel" in targets


# ── image_for() ─────────────────────────────────────────────────────────


def test_published_cell_resolves_to_its_pinned_digest():
    assert dockerrun.image_for("unix", "manylinux_2_28_x86_64") == (
        "ghcr.io/example/manylinux_2_28_x86_64@sha256:" + "a" * 64
    )


def test_declared_but_unpublished_cell_resolves_to_none():
    # Empty string means "this target exists, nothing published for it
    # yet" and must behave exactly like an unknown one -- returning `""`
    # would sail straight into `docker run ... "" make`.
    assert dockerrun.image_for("unix", "musllinux_1_2_x86_64") is None
    assert dockerrun.image_for("unix", "manylinux_2_39_mipsel") is None


def test_env_override_wins_over_the_pinned_digest(monkeypatch):
    monkeypatch.setenv(
        "CIBMP_UNIX_MANYLINUX_2_28_X86_64_DOCKER_IMAGE", "manylinux_2_28_x86_64:local"
    )
    assert (
        dockerrun.image_for("unix", "manylinux_2_28_x86_64")
        == "manylinux_2_28_x86_64:local"
    )


def test_env_override_reaches_an_unpublished_cell(monkeypatch):
    # The documented way to work on a cell before it is published --
    # every `unix` cell is empty on this branch, so this is the path a
    # local build actually takes today.
    monkeypatch.setenv(
        "CIBMP_UNIX_MANYLINUX_2_28_AARCH64_DOCKER_IMAGE",
        "manylinux_2_28_aarch64:local",
    )
    assert (
        dockerrun.image_for("unix", "manylinux_2_28_aarch64")
        == "manylinux_2_28_aarch64:local"
    )


def test_each_cell_resolves_independently():
    # One cell landing does not silently switch every other cell on.
    assert dockerrun.image_for("unix", "manylinux_2_28_x86_64") is not None
    assert dockerrun.image_for("unix", "manylinux_2_28_aarch64") is None


def test_a_port_with_no_axis_needs_no_target_segment():
    assert dockerrun.image_for("qemu") == "ghcr.io/example/qemu@sha256:" + "b" * 64


def test_windows_arches_share_one_image_via_the_port_key(monkeypatch):
    # All three windows arches resolve the same image (D28 step 3), so
    # the arch only ever appears in the env override's own name.
    assert dockerrun.image_for("windows", "x64") == (
        "ghcr.io/example/windows@sha256:" + "c" * 64
    )
    assert dockerrun.image_for("windows", "arm64") == dockerrun.image_for(
        "windows", "x64"
    )
    monkeypatch.setenv("CIBMP_WINDOWS_X64_DOCKER_IMAGE", "windows:local")
    assert dockerrun.image_for("windows", "x64") == "windows:local"
    assert dockerrun.image_for("windows", "arm64") != "windows:local"


def test_unregistered_port_resolves_to_none():
    assert dockerrun.image_for("esp32") is None


# ── platform_for() / base_image_for() ───────────────────────────────────


def test_unix_platform_is_the_targets_own_architecture():
    # Record 0043's whole model: the image is native to its build target,
    # so the container platform and the target arch are one fact.
    assert dockerrun.platform_for("unix", "manylinux_2_28_x86_64") == "linux/amd64"
    assert dockerrun.platform_for("unix", "musllinux_1_2_aarch64") == "linux/arm64"
    assert dockerrun.platform_for("unix", "manylinux_2_31_armv7l") == "linux/arm/v7"
    assert dockerrun.platform_for("unix", "manylinux_2_39_riscv64") == "linux/riscv64"
    assert dockerrun.platform_for("unix", "manylinux_2_28_i686") == "linux/386"


def test_mipsel_is_an_amd64_cross_host_not_a_native_target():
    # 0043's documented exception: there is no 32-bit mipsel image to be
    # native to, so this cell keeps the old cross model and says so.
    assert dockerrun.platform_for("unix", "manylinux_2_39_mipsel") == "linux/amd64"


def test_cross_compiling_ports_are_amd64_hosts():
    # A statement about the image, not about any build target -- and what
    # lets these ports run on an arm64 host at all, emulated.
    assert dockerrun.platform_for("qemu") == "linux/amd64"
    assert dockerrun.platform_for("windows", "x64") == "linux/amd64"


def test_platform_override_exists_because_the_image_override_does(monkeypatch):
    monkeypatch.setenv(
        "CIBMP_UNIX_MANYLINUX_2_28_X86_64_DOCKER_PLATFORM", "linux/arm64"
    )
    assert dockerrun.platform_for("unix", "manylinux_2_28_x86_64") == "linux/arm64"


def test_base_image_comes_from_the_pypa_mirror(monkeypatch):
    monkeypatch.undo()
    assert dockerrun.base_image_for("manylinux_2_28_x86_64").startswith(
        "quay.io/pypa/manylinux_2_28_x86_64@sha256:"
    )
    assert dockerrun.base_image_for("musllinux_1_2_armv7l").startswith(
        "quay.io/pypa/musllinux_1_2_armv7l@sha256:"
    )


def test_mipsel_has_no_pypa_base(monkeypatch):
    # Its Dockerfile names its own base; pinning one in the pypa mirror
    # would imply a libc floor this arch does not claim.
    monkeypatch.undo()
    assert dockerrun.base_image_for("manylinux_2_39_mipsel") is None


# ── needs_linux32() ─────────────────────────────────────────────────────


def test_only_the_two_32bit_arches_are_linux32_candidates():
    assert dockerrun.needs_linux32("unix", "manylinux_2_28_i686")
    assert dockerrun.needs_linux32("unix", "musllinux_1_2_armv7l")
    assert not dockerrun.needs_linux32("unix", "manylinux_2_28_x86_64")
    assert not dockerrun.needs_linux32("unix", "manylinux_2_39_mipsel")
    assert not dockerrun.needs_linux32("windows", "x86")


# ── ensure_image() -- a thin alias, no build fallback ───────────────────


def test_ensure_image_matches_image_for():
    assert dockerrun.ensure_image("unix", "manylinux_2_28_x86_64") == (
        dockerrun.image_for("unix", "manylinux_2_28_x86_64")
    )
    assert dockerrun.ensure_image("esp32") is None


def test_ensure_image_never_shells_out(monkeypatch):
    calls = []
    monkeypatch.setattr(dockerrun.subprocess, "run", lambda *a, **k: calls.append(a))

    dockerrun.ensure_image("unix", "manylinux_2_28_x86_64")
    dockerrun.ensure_image("qemu")

    assert calls == []


# ── timeout_for() ───────────────────────────────────────────────────────


def test_timeout_for_unset_is_none():
    assert dockerrun.timeout_for("unix", "manylinux_2_28_x86_64") is None


def test_timeout_for_blanket_env_applies_to_every_container(monkeypatch):
    monkeypatch.setenv("CIBMP_TIMEOUT", "600")
    assert dockerrun.timeout_for("unix", "manylinux_2_28_x86_64") == 600.0
    assert dockerrun.timeout_for("webassembly") == 600.0


def test_timeout_for_specific_override_wins_over_blanket(monkeypatch):
    monkeypatch.setenv("CIBMP_TIMEOUT", "600")
    monkeypatch.setenv("CIBMP_UNIX_MANYLINUX_2_28_X86_64_TIMEOUT", "120")
    assert dockerrun.timeout_for("unix", "manylinux_2_28_x86_64") == 120.0
    # A different cell with no specific override still gets the blanket.
    assert dockerrun.timeout_for("unix", "musllinux_1_2_x86_64") == 600.0


# ── run() -- platform, emulation, linux32, timeout ──────────────────────


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    dockerrun._PROBED.clear()
    yield
    dockerrun._PROBED.clear()


def test_run_passes_the_platform_through(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(dockerrun, "host_oci_platform", lambda: "linux/amd64")
    monkeypatch.setattr(
        dockerrun.subprocess, "run", lambda cmd, **k: calls.append((cmd, k))
    )

    dockerrun.run(
        ["make"],
        mounts=[tmp_path],
        workdir=tmp_path,
        image="manylinux_2_28_x86_64:local",
        oci_platform="linux/amd64",
    )

    assert "--platform=linux/amd64" in calls[0][0]


def test_run_omits_platform_when_none_is_resolved(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        dockerrun.subprocess, "run", lambda cmd, **k: calls.append((cmd, k))
    )

    dockerrun.run(["make"], mounts=[tmp_path], workdir=tmp_path, image="img:local")

    assert not any(a.startswith("--platform") for a in calls[0][0])


def test_native_platform_is_not_probed(monkeypatch, tmp_path):
    # Nothing to emulate, so nothing to pay for -- the probe container
    # only ever runs for a non-native target.
    calls = []
    monkeypatch.setattr(dockerrun, "host_oci_platform", lambda: "linux/amd64")
    monkeypatch.setattr(dockerrun.subprocess, "run", lambda cmd, **k: calls.append(cmd))

    dockerrun.run(
        ["make"],
        mounts=[tmp_path],
        workdir=tmp_path,
        image="img:local",
        oci_platform="linux/amd64",
    )

    assert len(calls) == 1
    assert "uname" not in calls[0]


def test_missing_emulation_is_named_rather_than_exec_format_error(
    monkeypatch, tmp_path
):
    # 0043's own open question, and the one place this design goes beyond
    # parity: cibuildwheel lets `exec format error` surface from inside
    # the build. That message names nothing about architecture.
    import subprocess as sp

    monkeypatch.setattr(dockerrun, "host_oci_platform", lambda: "linux/amd64")
    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: sp.CompletedProcess(
            cmd, 1, stdout="", stderr="exec /bin/sh: exec format error"
        ),
    )

    with pytest.raises(UsermodBuildError, match="binfmt"):
        dockerrun.run(
            ["make"],
            mounts=[tmp_path],
            workdir=tmp_path,
            image="manylinux_2_28_aarch64:local",
            oci_platform="linux/arm64",
        )


def test_platform_mismatch_names_the_pin_rather_than_the_daemon(monkeypatch, tmp_path):
    import subprocess as sp

    monkeypatch.setattr(dockerrun, "host_oci_platform", lambda: "linux/amd64")
    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: sp.CompletedProcess(
            cmd, 1, stdout="", stderr="image ... does not match the specified platform"
        ),
    )

    with pytest.raises(UsermodBuildError, match="not published for"):
        dockerrun.run(
            ["make"],
            mounts=[tmp_path],
            workdir=tmp_path,
            image="manylinux_2_28_aarch64:local",
            oci_platform="linux/arm64",
        )


def test_an_unattributable_probe_failure_is_left_to_the_real_run(monkeypatch, tmp_path):
    # A missing image, a dead daemon and a registry auth failure all have
    # perfectly clear errors of their own; the probe must not mangle them
    # into an emulation story.
    import subprocess as sp

    monkeypatch.setattr(dockerrun, "host_oci_platform", lambda: "linux/amd64")
    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        if "uname" in cmd:
            return sp.CompletedProcess(cmd, 1, stdout="", stderr="no such image")
        return sp.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)

    dockerrun.run(
        ["make"],
        mounts=[tmp_path],
        workdir=tmp_path,
        image="img:local",
        oci_platform="linux/arm64",
    )

    assert len(calls) == 2  # the probe, then the real run


def test_linux32_wraps_only_when_the_kernel_is_64bit(monkeypatch, tmp_path):
    # cibuildwheel's own probe-then-wrap: a 32-bit image on a 64-bit
    # kernel is the normal case, and the kernel reports its own word size
    # regardless of the image.
    import subprocess as sp

    monkeypatch.setattr(dockerrun, "host_oci_platform", lambda: "linux/amd64")
    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        if "uname" in cmd:
            return sp.CompletedProcess(cmd, 0, stdout="x86_64\n", stderr="")
        return sp.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)

    dockerrun.run(
        ["make"],
        mounts=[tmp_path],
        workdir=tmp_path,
        image="manylinux_2_28_i686:local",
        oci_platform="linux/386",
        linux32=True,
    )

    assert calls[-1][-2:] == ["linux32", "make"]


def test_linux32_is_not_used_on_a_genuinely_32bit_kernel(monkeypatch, tmp_path):
    import subprocess as sp

    monkeypatch.setattr(dockerrun, "host_oci_platform", lambda: "linux/amd64")

    def fake_run(cmd, **k):
        if "uname" in cmd:
            return sp.CompletedProcess(cmd, 0, stdout="i686\n", stderr="")
        return sp.CompletedProcess(cmd, 0)

    calls = []
    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: (calls.append(cmd), fake_run(cmd, **k))[1],
    )

    dockerrun.run(
        ["make"],
        mounts=[tmp_path],
        workdir=tmp_path,
        image="manylinux_2_28_i686:local",
        oci_platform="linux/386",
        linux32=True,
    )

    assert "linux32" not in calls[-1]


def test_run_passes_no_timeout_by_default(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        dockerrun.subprocess, "run", lambda cmd, **k: calls.append((cmd, k))
    )

    dockerrun.run(["make"], mounts=[tmp_path], workdir=tmp_path, image="qemu:local")

    (cmd, kwargs) = calls[0]
    assert kwargs.get("timeout") is None
    assert "--name" in cmd


def test_run_forwards_the_resolved_timeout(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        dockerrun.subprocess, "run", lambda cmd, **k: calls.append((cmd, k))
    )

    dockerrun.run(
        ["make"],
        mounts=[tmp_path],
        workdir=tmp_path,
        image="qemu:local",
        timeout=45.0,
    )

    assert calls[0][1].get("timeout") == 45.0


def test_run_kills_the_container_on_timeout(monkeypatch, tmp_path):
    import subprocess as sp

    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        if cmd[:2] == ["docker", "run"]:
            raise sp.TimeoutExpired(cmd, k.get("timeout"))

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)

    with pytest.raises(UsermodBuildError, match="timed out"):
        dockerrun.run(
            ["make"],
            mounts=[tmp_path],
            workdir=tmp_path,
            image="qemu:local",
            timeout=1.0,
        )

    # The `docker run` attempt, then a `docker kill <name>` naming the
    # exact same --name this run passed -- not a plain `subprocess.run`
    # timeout left to (not) clean up the container on its own.
    assert calls[0][:2] == ["docker", "run"]
    run_name = calls[0][calls[0].index("--name") + 1]
    assert calls[1] == ["docker", "kill", run_name]


# ── the probe reports what it measured ──────────────────────────────────


def test_the_probed_machine_reaches_stdout(monkeypatch, tmp_path, capsys):
    # Record 0044's addendum: `i686` and `armv7l` both went green on CI
    # while `linux32` stayed exactly as unverified as before, because the
    # only input to that decision -- this `uname -m` -- was captured and
    # never printed. A passing build is not evidence about a branch whose
    # output nothing can see, so the value itself is the assertion here.
    import subprocess as sp

    monkeypatch.setattr(dockerrun, "host_oci_platform", lambda: "linux/arm64")

    def fake_run(cmd, **k):
        if "uname" in cmd:
            return sp.CompletedProcess(cmd, 0, stdout="armv8l\n", stderr="")
        return sp.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)

    dockerrun.run(
        ["make"],
        mounts=[tmp_path],
        workdir=tmp_path,
        image="manylinux_2_31_armv7l:local",
        oci_platform="linux/arm/v7",
        linux32=True,
    )

    out = capsys.readouterr().out
    assert "uname -m = armv8l" in out
    assert "32-bit kernel" in out


def test_the_silent_pull_is_announced_before_it_happens(monkeypatch, tmp_path, capsys):
    # The probe's own `docker run` is `capture_output=True`, so it is
    # where the first fetch of a non-native image happens and where it
    # stays invisible -- nineteen seconds of nothing on run 32958683512's
    # armv7l leg. The announcement has to precede the call, not follow it.
    import subprocess as sp

    monkeypatch.setattr(dockerrun, "host_oci_platform", lambda: "linux/amd64")
    seen_before_probe = []

    def fake_run(cmd, **k):
        if "uname" in cmd:
            seen_before_probe.append(capsys.readouterr().out)
            return sp.CompletedProcess(cmd, 0, stdout="x86_64\n", stderr="")
        return sp.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dockerrun.subprocess, "run", fake_run)

    dockerrun.run(
        ["make"],
        mounts=[tmp_path],
        workdir=tmp_path,
        image="manylinux_2_28_aarch64@sha256:deadbeef",
        oci_platform="linux/arm64",
    )

    assert "linux/arm64: probing" in seen_before_probe[0]
    assert "manylinux_2_28_aarch64@sha256:deadbeef" in seen_before_probe[0]


def test_a_cached_probe_says_nothing_a_second_time(monkeypatch, tmp_path, capsys):
    # Two containers per build is the normal shape (unix/armhf's own
    # deplibs pre-step plus the main build), and `_PROBED` exists so the
    # probe runs once. The reporting has to be cached with it rather than
    # repeating a line about a container that never started.
    import subprocess as sp

    monkeypatch.setattr(dockerrun, "host_oci_platform", lambda: "linux/amd64")
    monkeypatch.setattr(
        dockerrun.subprocess,
        "run",
        lambda cmd, **k: sp.CompletedProcess(cmd, 0, stdout="x86_64\n", stderr=""),
    )

    for _ in range(2):
        dockerrun.run(
            ["make"],
            mounts=[tmp_path],
            workdir=tmp_path,
            image="img:local",
            oci_platform="linux/arm64",
        )

    assert capsys.readouterr().out.count("uname -m") == 1
