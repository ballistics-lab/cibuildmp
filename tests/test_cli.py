import json
from pathlib import Path

from cibuildmp.cli import main
from cibuildmp.natmod import cli as natmod_cli
from cibuildmp.natmod.build import BuildResult
from cibuildmp.natmod.toolchains import ResolvedToolchain


def write(tmp_path, text):
    (tmp_path / "cibuildmp.toml").write_text(text)
    return str(tmp_path)


CONFIG = """
micropython = "v1.28.0"
[natmod]
archs = ["x64", "armv6m"]
"""


def test_print_build_identifiers(tmp_path, capsys):
    assert main([write(tmp_path, CONFIG), "--print-build-identifiers"]) == 0
    assert capsys.readouterr().out.split() == [
        "mpy6.3-natmod-x64",
        "mpy6.3-natmod-armv6m",
    ]


def test_print_build_identifiers_json(tmp_path, capsys):
    assert main([write(tmp_path, CONFIG), "--print-build-identifiers", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        "mpy6.3-natmod-x64",
        "mpy6.3-natmod-armv6m",
    ]


def test_dry_run_covers_every_target_and_succeeds(tmp_path, capsys):
    assert main([write(tmp_path, CONFIG), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "[1/2]" in out and "[2/2]" in out
    assert "ARCH=x64" in out and "ARCH=armv6m" in out


def test_dry_run_spans_multiple_micropython_tags(tmp_path, capsys):
    config = """
    micropython = ["v1.22.0", "v1.28.0"]
    [natmod]
    archs = ["x64"]
    """
    assert main([write(tmp_path, config), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "v1.22.0, v1.28.0" in out
    assert "mpy6.2-natmod-x64" in out and "mpy6.3-natmod-x64" in out


def test_only_overrides_skip(tmp_path, capsys):
    # `skip` goes **above** `[natmod]`, not appended to CONFIG. This test
    # used to append it, which put it inside the `[natmod]` table -- where
    # natmod never reads it (`opt()` resolves against the top level, while
    # `archs` alone also falls back to `natmod.get("archs")`). The skip was
    # therefore never applied and this case passed without testing
    # anything. Found while writing 0045; the placement asymmetry itself is
    # its own bug, see 0048.
    config = 'micropython = "v1.28.0"\nskip = "*-armv6m"\n'
    config += '[natmod]\narchs = ["x64", "armv6m"]\n'
    argv = [write(tmp_path, config), "--only", "mpy6.3-natmod-armv6m", "--dry-run"]
    assert main(argv) == 0
    assert "ARCH=armv6m" in capsys.readouterr().out


def test_only_unknown_identifier_is_an_error(tmp_path, capsys):
    # A real arch under a real ABI is *not* the unknown case any more
    # (0045) -- see test_only_reaches_an_arch_outside_the_config below.
    # This is a name no config can produce at all.
    assert main([write(tmp_path, CONFIG), "--only", "mpy6.3-natmod-sparc"]) == 2
    err = capsys.readouterr().err
    assert "is not a known identifier" in err
    assert "mpy6.3-natmod-xtensa" in err


def test_only_reaches_an_arch_outside_the_config(tmp_path, capsys):
    # **0045**: `--only` overrides `archs`/`build`/`skip` and resolves
    # against every identifier this config can name, matching what the
    # flag's own help always claimed. `xtensa` is not in CONFIG's own
    # `archs = ["x64", "armv6m"]`, and naming it directly must still work
    # -- cibuildwheel's `--only` takes its choices from
    # `read_all_configs()` and its `--arch` is *computed from* the
    # identifier rather than checked against it.
    assert (
        main(
            [
                write(tmp_path, CONFIG),
                "--only",
                "mpy6.3-natmod-xtensa",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == ["mpy6.3-natmod-xtensa"]


def test_only_overrides_skip_for_print_build_identifiers(tmp_path, capsys):
    # Same override, exercised through --print-build-identifiers rather
    # than --dry-run. Note the placement again: top level, above
    # `[natmod]`, because that is the only place natmod reads `skip` at
    # all (0048).
    config = 'micropython = "v1.28.0"\nskip = "mpy6.3-natmod-x64"\n'
    config += '[natmod]\narchs = ["x64", "armv6m"]\n'
    assert (
        main(
            [
                write(tmp_path, config),
                "--only",
                "mpy6.3-natmod-x64",
                "--print-build-identifiers",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.split() == ["mpy6.3-natmod-x64"]


def test_bad_arch_is_an_error(tmp_path, capsys):
    config = '[natmod]\narchs = ["x64", "aarch64"]\n'
    assert main([write(tmp_path, config), "--print-build-identifiers"]) == 2
    assert "aarch64" in capsys.readouterr().err


def test_real_build_writes_github_step_summary_when_set(monkeypatch, tmp_path):
    # Integration check for D29's own wiring, not just stepsummary.py in
    # isolation: a real (mocked-at-the-edges) build through main() must
    # actually call write_step_summary with the same results/duration the
    # plain-text summary above it already prints -- x64 only, host gcc, to
    # keep the mocking surface minimal (no cross-toolchain resolution).
    config = '\nmicropython = "v1.28.0"\n[natmod]\narchs = ["x64"]\n'
    package_dir = Path(write(tmp_path, config))

    monkeypatch.setattr(
        natmod_cli, "resolve", lambda arch, **k: ResolvedToolchain("none", "", "", None)
    )
    monkeypatch.setattr(
        natmod_cli, "fetch_micropython", lambda tag, **k: tmp_path / "mpy"
    )
    monkeypatch.setattr(natmod_cli, "build_mpy_cross", lambda mpy_dir, **k: None)
    monkeypatch.setattr(natmod_cli, "read_mpy_abi", lambda mpy_dir: "6.3")

    produced = tmp_path / "template-mpy6.3-natmod-x64.mpy"
    produced.write_bytes(b"\x00" * 42)

    def fake_build_target(build_options, chain, mpy_dir, module_root, output_dir, **k):
        return BuildResult(
            identifier=build_options.identifier, output=produced, duration=0.5
        )

    monkeypatch.setattr(natmod_cli, "build_target", fake_build_target)

    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    assert main([str(package_dir)]) == 0

    text = summary_path.read_text()
    assert "1 target(s) built in 0.5s" in text
    assert "mpy6.3-natmod-x64" in text
    assert "42 bytes" in text


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
