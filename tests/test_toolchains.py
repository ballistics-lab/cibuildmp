import pytest

from cibuildmp import toolchains
from cibuildmp.targets import NATMOD_ARCHS, NATMOD_CROSS
from cibuildmp.toolchains import (
    ARCH_TOOLCHAIN,
    TOOLCHAINS,
    ResolvedToolchain,
    ToolchainError,
    resolve,
    toolchain_for,
)


def test_every_arch_has_a_mapping():
    assert set(ARCH_TOOLCHAIN) == set(NATMOD_ARCHS)


def test_expected_prefixes_match_dynruntime():
    # toolchains._check_tables() asserts this at import; restated here so a
    # regression names the offending arch in a test report.
    for arch, cross in NATMOD_CROSS.items():
        spec = toolchain_for(arch)
        assert (spec.expected_prefix if spec else "") == cross, arch


def test_two_toolchains_need_prefix_reconciliation():
    # Espressif ships a unified xtensa-esp-elf-, xpack ships riscv-none-elf-,
    # and dynruntime.mk hardcodes neither.
    mismatched = {
        name
        for name, spec in TOOLCHAINS.items()
        if spec.expected_prefix != spec.provided_prefix
    }
    assert mismatched == {"xtensa-esp-elf", "riscv-none-elf"}


def test_make_overrides_only_when_prefixes_differ():
    same = ResolvedToolchain("download", "arm-none-eabi-", "arm-none-eabi-", None)
    assert same.make_overrides == []
    differs = ResolvedToolchain(
        "download", "xtensa-esp-elf-", "xtensa-esp32-elf-", None
    )
    assert differs.make_overrides == ["CROSS=xtensa-esp-elf-"]


def test_x64_needs_no_toolchain():
    resolved = resolve("x64")
    assert resolved.strategy == "none"
    assert resolved.make_overrides == []
    assert resolved.bin_dir is None


def test_unknown_arch_rejected():
    with pytest.raises(ToolchainError, match="aarch64"):
        resolve("aarch64")


def test_host_strategy_refuses_to_download(monkeypatch):
    monkeypatch.setattr(toolchains.shutil, "which", lambda _: None)
    with pytest.raises(ToolchainError, match="--toolchain=host"):
        resolve("armv7m", strategy="host")


def test_x86_cannot_self_provision(monkeypatch):
    # The host gcc is present but its 32-bit runtime is not: the probe fails,
    # and no tarball exists that could supply one.
    monkeypatch.setattr(toolchains, "_probe", lambda gcc, args: not args)
    monkeypatch.setattr(toolchains.shutil, "which", lambda name: "/usr/bin/gcc")
    with pytest.raises(ToolchainError, match="gcc-multilib"):
        resolve("x86")


def test_probe_is_skipped_without_args():
    assert toolchains._probe("/nonexistent/gcc", ()) is True


def test_probe_reports_failure_for_missing_compiler():
    assert toolchains._probe("/nonexistent/gcc", ("-m32",)) is False


def test_download_only_toolchains_name_no_apt_package():
    for name in ("xtensa-lx106-elf", "xtensa-esp-elf"):
        assert TOOLCHAINS[name].apt_packages == ""
        assert TOOLCHAINS[name].download is not None


def test_pins_are_complete():
    for name, spec in TOOLCHAINS.items():
        if spec.download is None:
            continue
        assert spec.download.url.startswith("https://"), name
        assert spec.download.version, name
        # riscv is the one that resolves its digest from an xpack .sha
        # sidecar rather than a literal pin.
        if name != "riscv-none-elf":
            assert len(spec.download.sha256) == 64, name
