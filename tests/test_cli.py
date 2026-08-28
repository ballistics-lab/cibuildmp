import json
import os
import stat
from pathlib import Path

from cibuildmp.cli import main
from cibuildmp.platforms import natmod as natmod_cli
from cibuildmp.platforms.natmod.build import BuildResult
from cibuildmp.platforms.natmod.targets import (
    newest_known_abi,
    newest_stable_tag_for_abi,
    newest_tag_for_abi,
)

# No `micropython =` key any more (record 0052, A2): the version axis is a
# static domain, narrowed by `build`/`skip` matching identifiers -- an
# unconfigured `build` already narrows to the newest known ABI by itself,
# so this config's own real, resolved tag is whatever
# newest_stable_tag_for_abi("6.3") currently says (narrow_to_newest_tag()
# prefers a stable release over a preview sharing the same ABI, record
# 0052's own live-caught correction), not a literal string pinned here
# that would go stale on its own schedule.
ABI = newest_known_abi()


def write(tmp_path, text):
    (tmp_path / "cibuildmp.toml").write_text(text)
    return str(tmp_path)


# No `archs` config key any more either (record 0052's own live-caught
# correction): it duplicated exactly what a build/skip glob over the
# identifier already expresses, so narrowing to x64/armv6m is spelled out
# via `build` directly, still against the single newest known ABI.
CONFIG = f"""
build = "mpy{ABI}-*-{{x64,armv6m}}"
"""


def test_print_build_identifiers(tmp_path, capsys):
    assert main([write(tmp_path, CONFIG), "--print-build-identifiers"]) == 0
    tag = newest_stable_tag_for_abi("6.3")
    assert capsys.readouterr().out.split() == [
        f"mpy6.3-{tag}-x64",
        f"mpy6.3-{tag}-armv6m",
    ]


def test_print_build_identifiers_json(tmp_path, capsys):
    assert main([write(tmp_path, CONFIG), "--print-build-identifiers", "--json"]) == 0
    tag = newest_stable_tag_for_abi("6.3")
    assert json.loads(capsys.readouterr().out) == [
        f"mpy6.3-{tag}-x64",
        f"mpy6.3-{tag}-armv6m",
    ]


def test_dry_run_covers_every_target_and_succeeds(tmp_path, capsys):
    assert main([write(tmp_path, CONFIG), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "[1/2]" in out and "[2/2]" in out
    assert "ARCH=x64" in out and "ARCH=armv6m" in out


def test_dry_run_spans_multiple_abis_via_build_selector(tmp_path, capsys):
    # record 0052, A2: spanning an ABI boundary is no longer a
    # micropython = [...] config statement -- it is build/skip matching
    # more than one ABI's own identifiers, exactly like any other
    # selector-narrowed set. mpy6.2 and mpy6.3 are two real, distinct
    # ABIs build-platforms.toml records (verified live via known_abis()
    # elsewhere), each resolving to its own newest known tag rather than
    # a literal version string that would go stale on its own schedule.
    config = """
    build = "mpy6.2-*-x64 mpy6.3-*-x64"
    """
    assert main([write(tmp_path, config), "--dry-run"]) == 0
    out = capsys.readouterr().out
    tag_62 = newest_stable_tag_for_abi("6.2")
    tag_63 = newest_stable_tag_for_abi("6.3")
    assert f"{tag_62}, {tag_63}" in out
    assert f"mpy6.2-{tag_62}-x64" in out and f"mpy6.3-{tag_63}-x64" in out


def test_cli_build_overrides_the_config(tmp_path, capsys):
    # Replaces the old --only (record 0052): --build/--skip override the
    # config's own build/skip outright, so naming a glob specific enough
    # to match exactly one identifier is how "build exactly this one
    # thing" is spelled now.
    tag = newest_tag_for_abi("6.3")
    argv = [
        write(tmp_path, CONFIG),
        "--build",
        f"mpy6.3-{tag}-armv6m",
        "--dry-run",
    ]
    assert main(argv) == 0
    assert "ARCH=armv6m" in capsys.readouterr().out


def test_cli_build_unreachable_identifier_is_an_error(tmp_path, capsys):
    assert main([write(tmp_path, CONFIG), "--build", "mpy6.3-sparc"]) == 2
    assert "matches no known identifier" in capsys.readouterr().err


def test_cli_build_reaches_an_arch_outside_the_config(tmp_path, capsys):
    # `xtensa` is not in CONFIG's own `build = "mpy{ABI}-*-{x64,armv6m}"`,
    # and naming it directly via --build must still work -- --build is
    # not checked against the config's own build/skip, only against every
    # real identifier that exists at all (the same reachability audit
    # every other build value gets).
    identifier = f"mpy6.3-{newest_tag_for_abi('6.3')}-xtensa"
    assert (
        main(
            [
                write(tmp_path, CONFIG),
                "--build",
                identifier,
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == [identifier]


def test_cli_skip_can_be_combined_with_cli_build(tmp_path, capsys):
    tag = newest_tag_for_abi("6.3")
    identifiers = [f"mpy6.3-{tag}-x64", f"mpy6.3-{tag}-armv6m"]
    assert (
        main(
            [
                write(tmp_path, CONFIG),
                "--build",
                " ".join(identifiers),
                "--skip",
                identifiers[1],
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == [identifiers[0]]


def test_bad_arch_is_an_error(tmp_path, capsys):
    # No `archs` config key to validate any more -- the reachability
    # audit already catches an arch dynruntime.mk has never heard of, the
    # same way it catches any other pattern that can never match anything
    # (record 0052, A5). Two space-separated patterns, not one brace
    # group: a brace-expanded "*-{x64,aarch64}" is checked as one whole
    # pattern string, and would pass reachability on the x64 alternative
    # alone, hiding the aarch64 typo entirely.
    config = f'build = "mpy{ABI}-*-x64 mpy{ABI}-*-aarch64"\n'
    assert main([write(tmp_path, config), "--print-build-identifiers"]) == 2
    assert "aarch64" in capsys.readouterr().err


def test_real_build_writes_github_step_summary_when_set(monkeypatch, tmp_path):
    # Integration check for D29's own wiring, not just stepsummary.py in
    # isolation: a real (mocked-at-the-edges) build through main() must
    # actually call write_step_summary with the same results/duration the
    # plain-text summary above it already prints -- x64 only, to keep the
    # mocking surface minimal.
    #
    # No toolchain resolution to mock any more: record 0049 deleted it
    # along with the bare-host path, so there is nothing between the CLI
    # and `build_target` but the container call `_stub_build` replaces.
    config = f'\nbuild = "mpy{ABI}-*-x64"\n'
    package_dir = Path(write(tmp_path, config))

    monkeypatch.setattr(
        natmod_cli, "fetch_micropython", lambda tag, **k: tmp_path / "mpy"
    )
    monkeypatch.setattr(natmod_cli, "build_mpy_cross", lambda mpy_dir, arch, **k: None)
    monkeypatch.setattr(natmod_cli, "read_mpy_abi", lambda mpy_dir: "6.3")

    produced = tmp_path / "template-mpy6.3-x64.mpy"
    produced.write_bytes(b"\x00" * 42)

    def fake_build_target(build_options, mpy_dir, module_root, output_dir, **k):
        return BuildResult(
            identifier=build_options.identifier, output=produced, duration=0.5
        )

    monkeypatch.setattr(natmod_cli, "build_target", fake_build_target)

    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    assert main([str(package_dir)]) == 0

    text = summary_path.read_text()
    assert "1 target built in 0.5 seconds" in text
    assert "mpy6.3-x64" in text
    assert "42 Bytes" in text


def test_output_is_line_buffered_and_survives_a_stream_without_reconfigure(
    tmp_path, monkeypatch, capsys
):
    # Two things at once, because they are the same line. First: every
    # `print()` in this tool is progress output, and block buffering made
    # all of it arrive at interpreter exit -- run 32958683512 stamps
    # "downloaded micropython.tar.xz" with the same timestamp as the final
    # summary, ninety seconds after the download and after `make`'s own
    # output, which wrote straight through the inherited fd.
    #
    # Second: `reconfigure()` is not on every stream object (pytest's own
    # capture, an embedding host), and buffering is never worth an
    # exception at the entry point of the whole CLI.
    class NoReconfigure:
        def __init__(self):
            self.text = ""

        def write(self, s):
            self.text += s
            return len(s)

        def flush(self):
            pass

    calls = []

    class Reconfigurable(NoReconfigure):
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("sys.stdout", Reconfigurable())
    monkeypatch.setattr("sys.stderr", NoReconfigure())
    assert main([write(tmp_path, CONFIG), "--print-build-identifiers"]) == 0

    assert calls == [{"line_buffering": True}]


def test_clean_cache_removes_readonly_entries(tmp_path, monkeypatch, capsys):
    # Real failure, not hypothetical: autoconf's own autom4te.cache
    # (created under ports/unix's libffi build, MICROPY_STANDALONE=1)
    # leaves entries some platforms create without the owner write bit,
    # so a plain shutil.rmtree(root) raises PermissionError even though
    # this process owns the whole cache tree.
    cache_dir = tmp_path / "cibuildmp-cache"
    stale = cache_dir / "micropython" / "v1.28.0" / "lib" / "libffi" / "autom4te.cache"
    stale.mkdir(parents=True)
    readonly_file = stale / "requests"
    readonly_file.write_text("stale")
    os.chmod(stale, stat.S_IREAD | stat.S_IEXEC)  # no write bit -- the real trigger

    monkeypatch.setattr("cibuildmp.cli.cache_root", lambda: cache_dir)
    assert main(["--clean-cache"]) == 0
    assert not cache_dir.exists()
    assert f"removed {cache_dir}" in capsys.readouterr().out
