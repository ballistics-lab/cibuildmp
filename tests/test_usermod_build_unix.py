import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from cibuildmp import dockerrun
from cibuildmp.platforms.usermod import build_unix
from cibuildmp.platforms.usermod.build_common import UsermodBuildError
from cibuildmp.platforms.usermod.build_unix import (
    UNIX_ARCH_SETTINGS,
    UnixBuildOptions,
    _dynamic_needed_libs,
    _non_baseline_needed_libs,
    repair_unix_binary,
    run_unix_deplibs,
    unix_make_command,
)
from cibuildmp.platforms.usermod.build_unix import build_unix as _build_unix


def build_unix_fn(*args, staging=None, **kwargs):
    """`build_unix()` with a staging directory supplied.

    Record 0095 made `staging` part of the contract -- the build tree lives
    inside the container now, so there is no host path to read a result
    from and the artifact is copied into this directory instead.
    `orchestrate.build_one()` supplies it in production; a test that does
    not care where it lands gets a throwaway one, and a test that does
    passes its own.
    """
    if staging is None:
        staging = Path(tempfile.mkdtemp(prefix="cibmp-test-staging-"))
    return _build_unix(*args, staging=staging, **kwargs)


def fake_elf(target: str = "manylinux_2_28_x86_64") -> bytes:
    """A 20-byte ELF header claiming `target`'s own architecture.

    `verify_unix_output()` (record 0043) reads `e_machine`, `EI_CLASS` and
    `EI_DATA` off the finished binary, so a stub build's output has to be
    a header rather than the four magic bytes these tests used to write.
    That is the check earning its keep: under the native-image model a
    wrong-platform image produces a *working* binary of the wrong
    architecture, which nothing else here would notice.
    """
    machine, elf_class, elf_data = UNIX_ARCH_SETTINGS[
        dockerrun.split_tag(target)[1]
    ].elf
    byteorder = "big" if elf_data == 2 else "little"
    return (
        b"\x7fELF"
        + bytes([elf_class, elf_data, 1, 0])
        + bytes(8)
        + (2).to_bytes(2, byteorder)
        + machine.to_bytes(2, byteorder)
    )


def _fake_docker_run(cmd, **kwargs):
    """A `dockerrun.subprocess.run` stand-in that behaves like the real
    thing when `capture_output=True` -- `probe_supported_cflags()` reads
    `.stdout` off whatever it gets back, and a real `subprocess.run` never
    returns `None`. Every candidate "passes" (empty stdout, so
    `probe_supported_cflags()` would normally drop it -- callers that care
    about which flags survive stub this out themselves).

    Since record 0095 the build runs inside one long-lived container, so
    this also stands in for the one step that used to happen implicitly on
    a bind mount: the `cp` of the finished binary into `staging`. Without
    it the artifact would exist nowhere a host-side check could read, which
    is exactly the real behaviour -- the container is the only place it
    lives until that copy.
    """
    if cmd[:2] == ["docker", "exec"] and "cp" in cmd:
        # Perform the copy for real. These tests already write a stub ELF at
        # the build directory the options name, and copying *that* is what
        # keeps a non-x86 target's own header (which `verify_unix_output()`
        # checks) rather than a default this helper would have to guess.
        source, dest = (Path(p) for p in cmd[cmd.index("cp") + 1 :][:2])
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            shutil.copy(source, dest)
    if kwargs.get("capture_output"):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return None


def opts(target: str = "manylinux_2_28_x86_64", **overrides) -> UnixBuildOptions:
    defaults = {
        "target": target,
        "user_c_modules": "/gh/ws/micropython/usermod",
        "frozen_manifest": "/gh/ws/a7p_manifest.py",
        "build_dir": Path("/gh/ws/usermod/build/x86_64"),
    }
    defaults.update(overrides)
    return UnixBuildOptions(**defaults)


def test_native_command_passes_an_empty_cross_compile():
    # Record 0043: the compiler inside a `manylinux_2_28_x86_64` image
    # already targets x86_64, so `CROSS_COMPILE=` is empty on purpose --
    # not missing. It is passed explicitly rather than omitted so the
    # Makefile's own default can never quietly supply a prefix.
    command = unix_make_command(opts(), Path("/gh/ws/mpy"))

    assert command == [
        "make",
        "-C",
        "/gh/ws/mpy/ports/unix",
        f"-j{os.cpu_count() or 1}",
        "VARIANT=standard",
        "BUILD=/gh/ws/usermod/build/x86_64",
        "CROSS_COMPILE=",
        "MICROPY_STANDALONE=1",
        "USER_C_MODULES=/gh/ws/micropython/usermod",
        "FROZEN_MANIFEST=/gh/ws/a7p_manifest.py",
    ]


def test_every_native_manylinux_target_shares_that_shape():
    # aarch64, armv7l and i686 stay non-cross-compiling under the
    # native-image model (`MICROPY_FORCE_32BIT`, the old x86 row, is
    # still gone -- each image's gcc already targets its own arch).
    # `MICROPY_STANDALONE` is universal, but `-static` is not
    # (`UNIX_ARCH_SETTINGS`'s own header) -- a `manylinux` cell links
    # ordinary dynamic glibc, same as any manylinux wheel.
    for target in (
        "manylinux_2_28_aarch64",
        "manylinux_2_31_armv7l",
        "manylinux_2_28_i686",
    ):
        command = unix_make_command(opts(target), Path("/gh/ws/mpy"))

        assert "CROSS_COMPILE=" in command
        assert "MICROPY_FORCE_32BIT=1" not in command
        assert "MICROPY_STANDALONE=1" in command
        assert "LDFLAGS_EXTRA=-static" not in command


def test_musllinux_targets_stay_fully_static():
    # musl's own static story has no dynamic-NSS leak (record 0031), so
    # `-static` earns its keep there and stays -- `UNIX_ARCH_SETTINGS`'s
    # own header.
    command = unix_make_command(opts("musllinux_1_2_riscv64"), Path("/gh/ws/mpy"))

    assert "MICROPY_STANDALONE=1" in command
    assert "LDFLAGS_EXTRA=-static" in command


def test_riscv64_arch_cflags_suppress_clobbered():
    # main.c's own `path_remaining` -- a real GCC diagnostic tied to
    # s390x/riscv64's own register allocation around setjmp/longjmp,
    # found live on multiple tags on both architectures (record [0044]'s
    # own earlier, narrower finding was mpy-cross's `main.c`, one tag).
    from cibuildmp.platforms.usermod.build_unix import unix_extra_cflags

    assert "-Wno-error=clobbered" in unix_extra_cflags("manylinux_2_39_riscv64")
    assert "-Wno-error=clobbered" in unix_extra_cflags("musllinux_1_2_riscv64")
    assert "-Wno-error=clobbered" in unix_extra_cflags("manylinux_2_28_s390x")
    assert "-Wno-error=clobbered" not in unix_extra_cflags("manylinux_2_28_x86_64")


def test_riscv64_ffi_disabled_only_for_the_broken_tags():
    from cibuildmp.platforms.usermod.build_unix import _riscv64_ffi_unported

    # lib/libffi's own atgreen/libffi pin (every tag through v1.23.0) has
    # no riscv* case in configure.host at all -- verified directly
    # against the pinned commit, not assumed.
    assert _riscv64_ffi_unported("manylinux_2_39_riscv64", "v1.20.0")
    assert _riscv64_ffi_unported("musllinux_1_2_riscv64", "v1.23.0")
    # v1.24.0 moves the pin to the canonical libffi/libffi (v3.4.6),
    # which does have one.
    assert not _riscv64_ffi_unported("manylinux_2_39_riscv64", "v1.24.0")
    # Every other architecture's libffi builds clean on every tag --
    # this is not a stand-in for a broader per-tag capability check.
    assert not _riscv64_ffi_unported("manylinux_2_28_x86_64", "v1.20.0")


def test_riscv64_broken_tag_disables_ffi_and_skips_deplibs(monkeypatch, tmp_path):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / "build-manylinux_2_39_riscv64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf("manylinux_2_39_riscv64"))

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    build_unix_fn(
        opts("manylinux_2_39_riscv64", build_dir=build_dir, tag="v1.20.0"),
        tmp_path / "mpy",
    )

    # No `deplibs` call at all -- building lib/libffi on this (tag, arch)
    # pair is a hard `configure: error` regardless of what cibuildmp
    # does, so there is nothing for it to usefully attempt.
    assert not any(
        "deplibs" in (c[-1] if c[-3:-1] == ["sh", "-c"] else "") for c in calls
    )
    main_build = next(c for c in calls if "MICROPY_PY_FFI=0" in c)
    assert "MICROPY_PY_FFI=0" in main_build


def test_mipsel_is_the_one_target_that_still_cross_compiles():
    # 0043's documented exception -- no pypa image, no PEP 600 tag, no
    # Docker official image for 32-bit mipsel, so nothing to be native to.
    command = unix_make_command(opts("manylinux_2_41_mipsel"), Path("/gh/ws/mpy"))

    assert "CROSS_COMPILE=mipsel-linux-gnu-" in command
    assert "MICROPY_STANDALONE=1" in command
    assert "LDFLAGS_EXTRA=-static" in command


_FAKE_UNIX_IMAGE = "manylinux_2_28_x86_64:local"


def _mock_unix_image(monkeypatch, image=_FAKE_UNIX_IMAGE):
    """Docker-only (D30): every real build_unix() path needs
    ensure_image() to resolve something before it will run anything at
    all. Tests that only care about the make/deplibs command shape (not
    about image resolution itself) fake a resolved image this way and
    mock dockerrun's own subprocess.run -- not build_unix.subprocess,
    which build_unix() no longer calls under any circumstance now that
    there is no bare-host path left."""
    monkeypatch.setattr("cibuildmp.dockerrun.ensure_image", lambda *a, **k: image)
    # Neutralise the emulation/linux32 probe too (record 0043). It starts
    # a real throwaway container for any non-native platform, which every
    # target but one is on an x86_64 host -- and it has its own dedicated
    # coverage in test_usermod_dockerrun.py. These cases are about the
    # make/deplibs command shape, not about how the image is reached.
    monkeypatch.setattr("cibuildmp.dockerrun._probe_platform", lambda *a, **k: "")
    # ...and the in-container mpy-cross build (record 0043's own live
    # finding: the host's binary cannot run inside these images). It is a
    # second real container, and these cases are about the port build's
    # own command shape.
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )


def test_deplibs_command_shape(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )
    run_unix_deplibs(
        opts("manylinux_2_41_mipsel"), Path("/gh/ws/mpy"), docker_image=_FAKE_UNIX_IMAGE
    )

    # Wrapped in `sh -c` now, not a bare argv: the fixup that follows
    # `make ... deplibs` (see run_unix_deplibs()'s own docstring) has to
    # run in the same container invocation.
    assert calls[0][-3:-1] == ["sh", "-c"]
    script = calls[0][-1]
    assert "deplibs" in script
    assert "MICROPY_STANDALONE=1" in script


def test_deplibs_fixup_queries_the_real_multi_os_directory(monkeypatch):
    # Not hardcoded to `lib64`: `gcc -print-multi-os-directory` was
    # `../lib64` on every RHEL-family image this fixup was first written
    # against, but riscv64's own image answers `../lib64/lp64d` (its own
    # ABI-variant subdirectory) -- found live once a tag whose libffi
    # pin actually supports riscv64 reached this step, and a fixup that
    # only checked for `out/lib64/libffi.a` missed it entirely. The
    # script asks the compiler that will actually be used, not one
    # value predicted in advance.
    # riscv64 is non-native on this (x86_64) test host, so dockerrun.run()
    # would otherwise start a real emulation probe first -- irrelevant to
    # what this test checks (record 0043's own probe, its own coverage
    # in test_usermod_dockerrun.py).
    monkeypatch.setattr("cibuildmp.dockerrun._probe_platform", lambda *a, **k: "")
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )

    run_unix_deplibs(
        opts("manylinux_2_39_riscv64"),
        Path("/gh/ws/mpy"),
        docker_image=_FAKE_UNIX_IMAGE,
    )

    script = calls[0][-1]
    assert "gcc -print-multi-os-directory" in script
    assert "multi_os_dir" in script
    assert "lib64" not in script  # no hardcoded fallback value anywhere


def test_every_upstream_arch_plus_mipsel_has_settings():
    # cibuildwheel's own seven, under its own names (0043 step 4), plus
    # cibuildmp's own mipsel. `x64`/`x86`/`armhf` are gone as spellings.
    assert set(UNIX_ARCH_SETTINGS) == {
        "x86_64",
        "i686",
        "aarch64",
        "armv7l",
        "ppc64le",
        "s390x",
        "riscv64",
        "mipsel",
    }


def test_unknown_target_rejected():
    with pytest.raises(UsermodBuildError, match="unknown unix target"):
        build_unix_fn(opts("manylinux_2_28_sparc64"), Path("/gh/ws/mpy"))


def test_a_real_arch_under_an_undeclared_floor_is_rejected():
    # `manylinux_2_34` is a real upstream floor this project does not
    # curate for any arch, so it names no cell of the matrix -- and must
    # fail as an unknown *target*, not slip through on its arch alone.
    with pytest.raises(UsermodBuildError, match="unknown unix target"):
        build_unix_fn(opts("manylinux_2_34_x86_64"), Path("/gh/ws/mpy"))


@pytest.mark.parametrize(
    "arch",
    [
        "manylinux_2_28_x86_64",
        "manylinux_2_28_i686",
        "manylinux_2_28_aarch64",
        "manylinux_2_31_armv7l",
        "manylinux_2_41_mipsel",
    ],
)
def test_unix_no_image_registered_is_a_clear_error(monkeypatch, tmp_path, arch):
    # Docker-only (D30): no bare-host fallback for any unix target any
    # more -- with no override and nothing pinned in
    # resources/pinned_docker_images.toml, build_unix() must fail loudly,
    # the same shape build_webassembly() already has. That is the state
    # every `unix` cell is actually in on this branch (record 0044), not
    # a hypothetical.
    monkeypatch.setattr("cibuildmp.dockerrun.ensure_image", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )

    with pytest.raises(UsermodBuildError, match="no Docker image registered"):
        build_unix_fn(
            opts(arch, build_dir=tmp_path / f"build-{arch}"), tmp_path / "mpy"
        )

    assert calls == []


@pytest.mark.parametrize("arch", ["manylinux_2_41_mipsel"])
def test_mipsel_runs_deplibs_before_build(monkeypatch, tmp_path, arch):
    _mock_unix_image(monkeypatch)
    run_calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: run_calls.append(cmd) or _fake_docker_run(cmd, **k),
    )
    build_dir = tmp_path / f"build-{arch}"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf(arch))

    build_unix_fn(opts(arch, build_dir=build_dir), tmp_path / "mpy")

    # Ordering, not position: every step is a `docker exec` in one
    # container since record 0095, with `create`/`start`/the overlay mount
    # ahead of them, so `run_calls[0]` is no longer the first build step.
    deplibs = next(i for i, c in enumerate(run_calls) if "deplibs" in str(c[-1]))
    port_make = next(
        i for i, c in enumerate(run_calls) if any("USER_C_MODULES" in a for a in c)
    )
    assert deplibs < port_make


@pytest.mark.parametrize("arch", ["manylinux_2_41_mipsel"])
def test_mipsel_builds_and_returns_binary_path(monkeypatch, tmp_path, arch):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / f"build-{arch}"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf(arch))
    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", _fake_docker_run)

    staging = tmp_path / "staging"
    result = build_unix_fn(
        opts(arch, build_dir=build_dir), tmp_path / "mpy", staging=staging
    )

    # Record 0095: the build tree lives inside the container, so what comes
    # back is the staged copy, not a path into it.
    assert result == staging / "micropython"


def test_mipsel_probes_its_cross_compiler_not_the_images_native_gcc(
    monkeypatch, tmp_path
):
    # mipsel's own image is a Bootlin cross-toolchain: the real build
    # uses `mipsel-linux-gnu-gcc`, a different (and, found live, older --
    # gcc 14.3.0) binary than whatever bare `gcc` resolves to inside that
    # same image (its own native build tooling). A tag from
    # TAG_CFLAGS (v1.20.0) is needed here -- mipsel's own _ARCH_CFLAGS
    # entry is empty, so with no tag at all there would be nothing to
    # probe and this bug would stay invisible.
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / "build-manylinux_2_41_mipsel"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf("manylinux_2_41_mipsel"))

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    build_unix_fn(
        opts("manylinux_2_41_mipsel", build_dir=build_dir, tag="v1.20.0"),
        tmp_path / "mpy",
    )

    probe_scripts = [
        c[-1] for c in calls if c[-3:-1] == ["sh", "-c"] and "gcc" in c[-1]
    ]
    assert any(script.startswith('printf "" | gcc ') for script in probe_scripts), (
        probe_scripts
    )
    assert any(
        script.startswith('printf "" | mipsel-linux-gnu-gcc ')
        for script in probe_scripts
    ), probe_scripts


def test_x86_64_builds_and_returns_binary_path(tmp_path, monkeypatch):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / "build-x86_64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf())

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", _fake_docker_run)
    staging = tmp_path / "staging"
    result = build_unix_fn(
        opts(build_dir=build_dir), tmp_path / "mpy", staging=staging
    )

    assert result == staging / "micropython"


def test_missing_binary_after_success_is_an_error(tmp_path, monkeypatch):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / "build-x86_64"
    build_dir.mkdir()

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", lambda *a, **k: None)
    with pytest.raises(UsermodBuildError, match="build reported success but"):
        build_unix_fn(opts(build_dir=build_dir), tmp_path / "mpy")


def test_build_failure_names_the_command(tmp_path, monkeypatch):
    import subprocess as sp

    _mock_unix_image(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)
    with pytest.raises(UsermodBuildError, match="failed with exit code"):
        build_unix_fn(opts(build_dir=tmp_path / "build-x86_64"), tmp_path / "mpy")


def test_aarch64_no_longer_cross_compiles():
    # It did until record 0043 (`CROSS_COMPILE=aarch64-linux-gnu-`, an apt
    # cross toolchain in an amd64 image, plus a ports.ubuntu.com mirror
    # rewrite). That whole setup encoded "the host is x86_64" as a
    # constant, which is false on an arm64 runner -- so the image is
    # native now and the prefix is empty. `MICROPY_STANDALONE=1` is back
    # (every arch's own `UnixArchSettings`, not a cross-compile artifact
    # -- see that table's own header), so it is not what distinguishes
    # aarch64 from mipsel any more; `CROSS_COMPILE=` being empty is.
    command = unix_make_command(opts("manylinux_2_28_aarch64"), Path("/gh/ws/mpy"))

    assert "CROSS_COMPILE=" in command
    assert "CROSS_COMPILE=aarch64-linux-gnu-" not in command


def test_aarch64_builds_and_returns_binary_path(monkeypatch, tmp_path):
    _mock_unix_image(monkeypatch)
    build_dir = tmp_path / "build-manylinux_2_28_aarch64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf("manylinux_2_28_aarch64"))

    # aarch64 carries a real `-Wno-error=array-bounds` candidate
    # (`_ARCH_CFLAGS`), so `build_unix()` now probes it against this
    # image's own gcc first -- a real `subprocess.run` always returns a
    # `CompletedProcess`, never `None`, so the fake has to as well once
    # `capture_output=True` is in play.
    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", _fake_docker_run)

    result = build_unix_fn(
        opts("manylinux_2_28_aarch64", build_dir=build_dir),
        tmp_path / "mpy",
        staging=tmp_path / "staging",
    )

    assert result == tmp_path / "staging" / "micropython"


# ── docker strategy (D26 proof-of-concept) ──────────────────────────────


def test_unix_docker_image_skips_host_toolchain_probe(monkeypatch, tmp_path):
    # CIBMP_UNIX_MANYLINUX_2_28_AARCH64_DOCKER_IMAGE set: the toolchain lives
    # inside the image, not on this host's PATH, so build_unix() must not
    # call shutil.which() at all -- a bare-host probe would reject a
    # perfectly good docker build.
    monkeypatch.setenv(
        "CIBMP_UNIX_MANYLINUX_2_28_AARCH64_DOCKER_IMAGE",
        "manylinux_2_28_aarch64:local",
    )
    # `build_unix` no longer imports shutil at all -- with no bare-host
    # path left for any port there is nothing to probe PATH with, which
    # is a stronger guarantee than mocking shutil.which to fail was.
    assert not hasattr(build_unix, "shutil")
    # This case resolves its image through the real env-var path rather
    # than `_mock_unix_image`, so it has to silence the emulation probe
    # itself -- aarch64 is non-native on an x86_64 host, and the probe
    # would otherwise start a real container.
    monkeypatch.setattr("cibuildmp.dockerrun._probe_platform", lambda *a, **k: "")
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build-stub" / "mpy-cross",
    )
    build_dir = tmp_path / "build-manylinux_2_28_aarch64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf("manylinux_2_28_aarch64"))

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _fake_docker_run(cmd, **kwargs)

    monkeypatch.setattr("cibuildmp.dockerrun.subprocess.run", fake_run)

    result = build_unix_fn(
        opts("manylinux_2_28_aarch64", build_dir=build_dir),
        tmp_path / "mpy",
        staging=tmp_path / "staging",
    )

    assert result == tmp_path / "staging" / "micropython"
    # Since record 0095 the image is named once, at `docker create`, and
    # every step is a `docker exec` into that one container -- which is the
    # stronger version of what this used to assert by checking the image
    # appeared in all three `docker run`s: they now *cannot* disagree.
    create = [c for c in calls if c[:2] == ["docker", "create"]]
    assert len(create) == 1
    assert "manylinux_2_28_aarch64:local" in create[0]
    assert not any(c[:2] == ["docker", "run"] for c in calls)

    execs = [c for c in calls if c[:2] == ["docker", "exec"]]
    # deplibs (standalone=True on every arch), aarch64's own
    # `-Wno-error=array-bounds` candidate probed against this image's gcc,
    # and the main build -- in that order, with the overlay mount ahead of
    # them and the staging copy after.
    assert any("deplibs" in str(c[-1]) for c in execs)
    assert any("array-bounds" in str(c[-1]) for c in execs)
    assert any(c[-1].startswith("make") or "make" in c for c in execs)


def test_unix_container_binds_the_checkout_read_only_and_the_project_rw(
    monkeypatch, tmp_path
):
    """Record 0095: the checkout is an overlay lower layer, so it is bound
    **read-only and out of the way** while the writable view goes over its
    own host path; the user's own module tree stays an ordinary read-write
    bind at its own path, since a module whose sources reach outside
    `USER_C_MODULES` has to resolve."""
    monkeypatch.setenv(
        "CIBMP_UNIX_MANYLINUX_2_28_X86_64_DOCKER_IMAGE", "manylinux_2_28_x86_64:local"
    )
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_common.container_mpy_cross",
        lambda mpy_dir, **k: mpy_dir / "mpy-cross" / "build" / "mpy-cross",
    )
    build_dir = tmp_path / "build-x86_64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf())

    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )

    mpy_dir = tmp_path / "mpy"
    staging = tmp_path / "staging"
    build_unix_fn(opts(build_dir=build_dir), mpy_dir, staging=staging)

    create = next(c for c in calls if c[:2] == ["docker", "create"])
    assert f"{mpy_dir}:/cibuildmp-lower-1:ro" in create
    assert "/gh/ws/micropython/usermod:/gh/ws/micropython/usermod" in create
    assert f"{staging}:{staging}" in create
    # The old bind of the checkout at its own path is exactly what would
    # let a build write into the cache again.
    assert f"{mpy_dir}:{mpy_dir}" not in create


# test_unix_no_image_registered_is_a_clear_error (above) already covers
# "no CIBMP_UNIX_<TARGET>_DOCKER_IMAGE, no pinned digest" for every
# target -- unix has no bare-host fallback left to fall back to (D30).


# ── unix_extra_cflags() -- four axes, and which one each rule is on ────


def test_the_tag_axis_carries_a_flag_a_whole_micropython_release_needs():
    """`v1.20.0` needs `-Wno-error=dangling-pointer` in every cell *and*
    every port, which none of the other three axes can say: they key on
    platform tag, architecture and libc (record 0084). Measured, not
    predicted -- gcc 14 rejects `py/stackctrl.c` on a tag that shipped
    before that diagnostic existed. It also carries
    `-Wno-error=unterminated-string-initialization`, same shape, a
    different gcc-15 diagnostic every tag before `v1.26.0` shares
    ([0082]/[0085]; live-caught here on `v1.20.0`'s own sweep)."""
    assert build_unix.unix_extra_cflags("manylinux_2_28_x86_64", "v1.20.0") == (
        "-Wno-error=unterminated-string-initialization",
        "-Wno-error=dangling-pointer",
    )


def test_the_tag_axis_composes_with_the_libc_and_arch_rules():
    # musl contributes `-Wno-error=cpp`, aarch64 `-Wno-error=array-bounds`,
    # and the tag axis its own two flags -- each from a different axis,
    # none of them repeating another.
    assert build_unix.unix_extra_cflags("musllinux_1_2_aarch64", "v1.20.0") == (
        "-Wno-error=cpp",
        "-Wno-error=array-bounds",
        "-Wno-error=unterminated-string-initialization",
        "-Wno-error=dangling-pointer",
    )


def test_no_other_tag_carries_a_relaxation():
    assert build_unix.unix_extra_cflags("manylinux_2_28_x86_64", "v1.29.0") == ()


def test_omitting_the_tag_still_resolves_the_other_three_axes():
    # A caller with no MicroPython version in hand must not lose the libc
    # and architecture rules.
    assert build_unix.unix_extra_cflags("musllinux_1_2_aarch64") == (
        "-Wno-error=cpp",
        "-Wno-error=array-bounds",
    )


def test_the_musl_rule_covers_the_whole_musllinux_column():
    # `-Wno-error=cpp` is a property of the libc: musl's own
    # `sys/cdefs.h` is a bare `#warning`, reached through berkeley-db's
    # `db.h` from extmod/modbtree.c. glibc has no such header warning, so
    # no manylinux cell may carry it.
    for target in dockerrun.unix_targets():
        floor, _arch = dockerrun.split_tag(target)
        flags = build_unix.unix_extra_cflags(target)
        assert ("-Wno-error=cpp" in flags) == floor.startswith("musllinux"), target


def test_the_array_bounds_rule_is_per_architecture_not_per_cell():
    # Both aarch64 cells trip gcc 14's `-Werror=array-bounds=` false
    # positive in mbedtls's own `mbedtls_xor`, from two different bases
    # and two different libcs -- AlmaLinux 8/glibc and Alpine/musl. It
    # started as a per-tag entry for `manylinux_2_28_aarch64` alone, on
    # the reasoning that bounds analysis differs by target; the second
    # aarch64 cell ever built (run 32960761641) showed the axis was the
    # architecture. Every non-aarch64 cell built so far is clean.
    for target in dockerrun.unix_targets():
        _floor, arch = dockerrun.split_tag(target)
        flags = build_unix.unix_extra_cflags(target)
        assert ("-Wno-error=array-bounds" in flags) == (arch == "aarch64"), target


def test_musl_aarch64_carries_both_rules_at_once():
    # The cell that proved the two axes are independent: it needs the
    # libc rule *and* the architecture rule, and neither table knows
    # about the other.
    assert build_unix.unix_extra_cflags("musllinux_1_2_aarch64") == (
        "-Wno-error=cpp",
        "-Wno-error=array-bounds",
    )


def test_a_cell_needing_nothing_gets_nothing():
    assert build_unix.unix_extra_cflags("manylinux_2_28_x86_64") == ()


# ── the repair step (this project's own `auditwheel repair`) ───────────


def test_dynamic_needed_libs_reads_a_real_elf(tmp_path):
    # A real, plain-dynamic gcc output always needs at least libc -- no
    # need to link anything exotic in to prove DT_NEEDED parses at all.
    src = tmp_path / "t.c"
    src.write_text("int main(void) { return 0; }\n")
    binary = tmp_path / "t"
    subprocess.run(["gcc", "-o", str(binary), str(src)], check=True)

    assert "libc.so.6" in _dynamic_needed_libs(binary)


def test_dynamic_needed_libs_empty_for_a_header_only_stub():
    # fake_elf() is exactly what verify_unix_output()'s own tests build:
    # a 20-byte header with no section table at all. A static real build
    # (mipsel) reaches the same outcome for a different reason -- no
    # `.dynamic` section either -- so both share this expectation.
    assert _dynamic_needed_libs(Path("/dev/null")) == []


def _stub_no_interpreter(monkeypatch):
    # `_non_baseline_needed_libs()` always consults `_elf_interpreter_name()`
    # too now -- stubbed to `None` in every test that fakes
    # `_dynamic_needed_libs()` against a `Path("/x")` that was never a real
    # ELF file to begin with, so nothing here tries to actually open it.
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_unix._elf_interpreter_name",
        lambda binary: None,
    )


def test_non_baseline_filters_manylinux_whitelist(monkeypatch):
    _stub_no_interpreter(monkeypatch)
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_unix._dynamic_needed_libs",
        lambda binary: ["libc.so.6", "libz.so.1", "libffi.so.6", "libm.so.6"],
    )
    assert _non_baseline_needed_libs("manylinux_2_28_x86_64", Path("/x")) == [
        "libffi.so.6"
    ]


def test_non_baseline_filters_musllinux_whitelist(monkeypatch):
    # musl's own baseline is far narrower than glibc's -- libm is *not*
    # in it, unlike manylinux's, so the same DT_NEEDED list produces a
    # different (larger) non-baseline result here.
    _stub_no_interpreter(monkeypatch)
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_unix._dynamic_needed_libs",
        lambda binary: ["libc.so", "libz.so.1", "libffi.so.6", "libm.so"],
    )
    assert _non_baseline_needed_libs("musllinux_1_2_x86_64", Path("/x")) == [
        "libffi.so.6",
        "libm.so",
    ]


def test_non_baseline_empty_when_nothing_needed(monkeypatch):
    _stub_no_interpreter(monkeypatch)
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_unix._dynamic_needed_libs",
        lambda binary: ["libc.so.6"],
    )
    assert _non_baseline_needed_libs("manylinux_2_28_x86_64", Path("/x")) == []


def test_non_baseline_excludes_the_elf_interpreter_itself(monkeypatch):
    # Live-caught on a real manylinux_2_31_armv7l build: 32-bit ARM
    # glibc's own ld.so lists itself as a DT_NEEDED entry, not just as
    # PT_INTERP -- neither baseline table names it (it is not a fixed
    # SONAME the way libc.so.6 is; it varies by architecture), so without
    # this exclusion it would be treated as "needs repair" and the
    # container script's own ldd/awk parse would fail outright, since
    # ldd's line for the loader itself carries no `name => path` arrow.
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_unix._dynamic_needed_libs",
        lambda binary: ["libc.so.6", "libffi.so.7", "ld-linux-armhf.so.3"],
    )
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_unix._elf_interpreter_name",
        lambda binary: "ld-linux-armhf.so.3",
    )
    assert _non_baseline_needed_libs("manylinux_2_31_armv7l", Path("/x")) == [
        "libffi.so.7"
    ]


def test_elf_interpreter_name_reads_a_real_elf(tmp_path):
    src = tmp_path / "t.c"
    src.write_text("int main(void) { return 0; }\n")
    binary = tmp_path / "t"
    subprocess.run(["gcc", "-o", str(binary), str(src)], check=True)

    interp = build_unix._elf_interpreter_name(binary)

    assert interp is not None
    assert interp.startswith(("ld-linux", "ld-musl"))


def test_elf_interpreter_name_none_for_a_header_only_stub():
    assert build_unix._elf_interpreter_name(Path("/dev/null")) is None


def test_repair_is_a_noop_when_nothing_non_baseline(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_unix._non_baseline_needed_libs",
        lambda target, binary: [],
    )
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run", lambda *a, **k: calls.append(a)
    )

    repair_unix_binary(
        "manylinux_2_28_x86_64",
        tmp_path / "micropython",
        docker_image=_FAKE_UNIX_IMAGE,
        oci_platform=None,
        linux32=False,
        timeout=None,
        mounts=[tmp_path],
    )

    assert calls == []


def test_repair_runs_ldd_and_patchelf_inside_the_container(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_unix._non_baseline_needed_libs",
        lambda target, binary: ["libffi.so.6"],
    )
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd),
    )
    binary = tmp_path / "build-manylinux_2_28_x86_64" / "micropython"

    repair_unix_binary(
        "manylinux_2_28_x86_64",
        binary,
        docker_image=_FAKE_UNIX_IMAGE,
        oci_platform="linux/amd64",
        linux32=False,
        timeout=30,
        mounts=[tmp_path],
    )

    assert len(calls) == 1
    docker_command = calls[0]
    assert docker_command[0] == "docker"
    assert _FAKE_UNIX_IMAGE in docker_command
    script = docker_command[-1]
    assert "ldd" in script
    assert "libffi.so.6" in script
    # $ORIGIN is patchelf's/the loader's own runtime token, not a shell
    # variable -- it must reach the container single-quoted, unexpanded.
    assert "patchelf --set-rpath '$ORIGIN/lib'" in script
    assert str(binary) in script


def test_build_unix_calls_repair_when_libffi_is_needed(monkeypatch, tmp_path):
    _mock_unix_image(monkeypatch)
    monkeypatch.setattr(
        "cibuildmp.platforms.usermod.build_unix._non_baseline_needed_libs",
        lambda target, binary: ["libffi.so.6"],
    )
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )
    build_dir = tmp_path / "build-x86_64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf())
    staging = tmp_path / "staging"

    build_unix_fn(opts(build_dir=build_dir), tmp_path / "mpy", staging=staging)

    # Counting `docker run`s stopped meaning anything once record 0095 put
    # every step in one container -- what matters is that a repair ran, and
    # that it ran against the *staged* copy, which is the one both sides can
    # see. (`repair_unix_binary()`'s own script test covers its content.)
    patchelf = [c for c in calls if c and "patchelf" in str(c[-1])]
    assert len(patchelf) == 1
    assert str(staging / "micropython") in patchelf[0][-1]


def test_build_unix_skips_repair_when_nothing_non_baseline(monkeypatch, tmp_path):
    # The everyday path: fake_elf()'s header-only stub has no `.dynamic`
    # section at all, so _non_baseline_needed_libs() (unmocked here) finds
    # nothing and repair_unix_binary() never reaches a docker run.
    _mock_unix_image(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "cibuildmp.dockerrun.subprocess.run",
        lambda cmd, **k: calls.append(cmd) or _fake_docker_run(cmd, **k),
    )
    build_dir = tmp_path / "build-x86_64"
    build_dir.mkdir()
    (build_dir / "micropython").write_bytes(fake_elf())

    build_unix_fn(opts(build_dir=build_dir), tmp_path / "mpy")

    # Counting calls stopped meaning anything once every step became a
    # `docker exec` in one container -- the claim is that no repair ran.
    assert not any("patchelf" in str(c[-1]) for c in calls)
