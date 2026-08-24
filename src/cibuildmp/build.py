"""Running the build itself: pre-build command, make, collect, verify,
package.

Fails fast, one target at a time -- matching cibuildwheel's own
build-in-container loop (platforms/linux.py), which lets a
`subprocess.CalledProcessError` from one identifier abort the whole
invocation rather than collecting per-target failures into a report.
`cli.build()` already handles that: this module raises, cli.main() catches
alongside SourceError/ToolchainError.

Also cibuildwheel-shaped: `collect_output()`/`verify_output()` mirror its
"exactly one artifact, or a named error" check (BuildProducedNoWheelError/
RepairStepProducedMultipleWheelsError), and the BuildResult accumulated per
target mirrors its BuildInfo summary line.

No separate `cibuildmp publish` step (see docs/BACKLOG.md D14): each
target's own directory under `output-dir` already holds everything mip
needs -- the `.mpy`, any `extra-files` companions, and a `package.json` --
the moment the build finishes. Assembling a ready-to-upload tree is as far
as this goes; creating a release or uploading it stays the caller's own CI
step, the same way cibuildwheel never runs `twine upload` itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .options import BuildOptions
from .targets import NATIVE_ARCH_CODE
from .toolchains import ResolvedToolchain

MPY_HEADER_MAGIC = ord("M")
MPY_ARCH_FLAGS_BIT = 0x40


class BuildError(Exception):
    pass


@dataclass(frozen=True)
class BuildResult:
    identifier: str
    output: Path
    duration: float

    @property
    def size(self) -> int:
        return self.output.stat().st_size


def make_command(
    build_options: BuildOptions, mpy_dir: Path, module_root: Path
) -> list[str]:
    """The make invocation for one target.

    PYTHON=<sys.executable> is what makes pyelftools/ar cibuildmp's own
    dependencies rather than something installed at build time (D12):
    py/dynruntime.mk assigns PYTHON with a plain `=`, never `override`, so
    this wins over the `python3` it would otherwise default to -- the same
    mechanism already used for CROSS= in toolchains.ResolvedToolchain.
    """
    return [
        "make",
        "-C",
        str(module_root),
        f"ARCH={build_options.target.arch}",
        f"MPY_DIR={mpy_dir}",
        f"PYTHON={sys.executable}",
        *build_options.extra_make_args,
        build_options.make_target,
    ]


def run_pre_build_command(module_root: Path, command: str, env: dict[str, str]) -> None:
    if not command:
        return
    try:
        subprocess.run(command, shell=True, cwd=module_root, env=env, check=True)
    except subprocess.CalledProcessError as exc:
        raise BuildError(f"pre-build-command failed: {command!r} ({exc})") from exc


def run_make(
    build_options: BuildOptions, mpy_dir: Path, module_root: Path, env: dict[str, str]
) -> None:
    # No cwd= here: `-C module_root` in the command itself already makes
    # make chdir there, and module_root can be relative (it usually is --
    # options.package_dir is often "."), so also passing it as cwd would
    # chdir twice and have make look for module_root nested inside itself.
    command = make_command(build_options, mpy_dir, module_root)
    try:
        subprocess.run(command, env=env, check=True)
    except subprocess.CalledProcessError as exc:
        raise BuildError(
            f"{build_options.identifier}: `{' '.join(command)}` failed with exit "
            f"code {exc.returncode}"
        ) from exc


def collect_output(build_options: BuildOptions, module_root: Path) -> Path:
    """Find the one .mpy the `dist` target produced.

    Every natmod Makefile in the wild drops it under build/<arch>*/ -- the
    same layout build-natmod's own artifact-upload step already assumes
    (`path: natmod/build/${{ matrix.arch }}*/`), not something cibuildmp
    invents here.
    """
    arch = build_options.target.arch
    candidates = sorted(module_root.glob(f"build/{arch}*/*.mpy"))
    if not candidates:
        raise BuildError(
            f"{build_options.identifier}: `{build_options.make_target}` produced no "
            f".mpy under {module_root}/build/{arch}*/"
        )
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise BuildError(
            f"{build_options.identifier}: ambiguous output -- found "
            f"{len(candidates)} .mpy files under {module_root}/build/{arch}*/: {names}"
        )
    return candidates[0]


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    """MicroPython's own uint encoding: big-endian 7-bit groups, MSB=more.

    Same format tools/mpy_ld.py's MPYOutput.write_uint() writes and
    py/persistentcode.c's read_uint() reads. Returns (value, bytes consumed).
    """
    value = 0
    consumed = 0
    while True:
        if offset + consumed >= len(data):
            raise BuildError("truncated .mpy header (arch-flags field cut off)")
        byte = data[offset + consumed]
        value = (value << 7) | (byte & 0x7F)
        consumed += 1
        if not byte & 0x80:
            return value, consumed


def read_mpy_header(mpy_path: Path) -> tuple[int, int, int]:
    """(MPY_VERSION, native-arch code, arch_flags) from a compiled .mpy.

    Layout from tools/mpy_ld.py's build_mpy() / py/persistentcode.h: byte 0
    is 'M', byte 1 is MPY_VERSION, byte 2 packs MPY_SUB_VERSION in bits 0-1,
    the native-arch code in bits 2-6 (`MPY_FEATURE_DECODE_ARCH`, mask 0x2F
    *after* the shift -- bit 6 is the arch-flags marker, not part of the
    arch code, and must be excluded or a flagged file decodes as a bogus
    arch), byte 3 is MP_SMALL_INT_BITS. A variable-length uint (arch_flags)
    follows when that marker bit is set.
    """
    data = mpy_path.read_bytes()
    if len(data) < 4 or data[0] != MPY_HEADER_MAGIC:
        raise BuildError(f"{mpy_path}: does not look like a compiled .mpy (bad header)")
    feat = data[2]
    arch_code = (feat >> 2) & 0x2F
    arch_flags = 0
    if feat & MPY_ARCH_FLAGS_BIT:
        arch_flags, _consumed = _read_varint(data, 4)
    return data[1], arch_code, arch_flags


def read_native_arch(mpy_path: Path) -> int:
    """The MP_NATIVE_ARCH_* code baked into a native .mpy's own header."""
    return read_mpy_header(mpy_path)[1]


def verify_output(build_options: BuildOptions, mpy_path: Path) -> None:
    """cibuildmp's equivalent of auditwheel: the header the linker actually
    wrote must name the arch (and, for rv32imc, the arch-flags) this target
    was building for, not just live in the right build/<arch>*/ directory --
    catches "built the wrong thing into the right directory" the way a wheel
    tag/platform mismatch would.

    Exact match on arch_flags, not the "required subset of available" rule
    mip applies when installing (micropython/micropython#19479) -- that
    rule is about whether a *device* can run this file; this check is about
    whether the *linker* encoded what the config actually asked for.
    """
    target = build_options.target
    _version, actual_arch, actual_flags = read_mpy_header(mpy_path)
    expected_arch = NATIVE_ARCH_CODE[target.arch]
    if actual_arch != expected_arch:
        raise BuildError(
            f"{build_options.identifier}: {mpy_path.name}'s header encodes native "
            f"arch code {actual_arch}, expected {expected_arch} ({target.arch})"
        )
    if actual_flags != target.arch_flags:
        raise BuildError(
            f"{build_options.identifier}: {mpy_path.name}'s header encodes "
            f"arch_flags {actual_flags:#x}, expected {target.arch_flags:#x}"
        )


def output_name(build_options: BuildOptions, mpy_path: Path) -> str:
    # Identifier-qualified even though the file already lives in its own
    # identifier/ directory: package.json's own urls stay unambiguous even
    # if a caller later flattens several identifiers' directories into one
    # namespace (e.g. a GitHub Release's own asset list, which cannot nest
    # directories -- see D14's "still open" deployment note).
    return f"{mpy_path.stem}-{build_options.identifier}{mpy_path.suffix}"


def _write_package_json(path: Path, urls: list[tuple[str, str]], version: str) -> None:
    manifest = {
        "urls": [[target_path, url] for target_path, url in urls],
        "version": version,
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def package_target(
    build_options: BuildOptions,
    identifier_dir: Path,
    install_name: str,
    mpy_dest: Path,
    extra_files: list[Path],
    version: str,
) -> None:
    """Copy `extra-files` alongside the built `.mpy` and write this
    identifier's own `package.json` (**D14**): today's plain, always-
    supported two-element `urls` schema, not a unified multi-arch manifest
    -- see build.__doc__ and docs/BACKLOG.md D14 for why.

    `urls` entries are `[target_path, url]`, deliberately not the same
    string twice: `target_path` is what `import <module>` needs on-device
    -- the project's own original basename (e.g. `template.mpy`), not the
    identifier-qualified one `mpy_dest` was stored under -- while `url` is
    that qualified, collision-safe filename actually sitting next to this
    `package.json`. Conflating the two would make mip install the file
    under its long, arch-qualified name, and `import template` would not
    find it.

    A no-op when `version` is unset: an identifier directory with a `.mpy`
    and no `package.json` is still useful (the file itself is what a
    Makefile-driven consumer wants), it just is not mip-installable yet.
    """
    if not version:
        return
    urls = [(install_name, mpy_dest.name)]
    for extra in extra_files:
        if not extra.is_file():
            raise BuildError(
                f"{build_options.identifier}: extra-files entry not found: {extra}"
            )
        dest = identifier_dir / extra.name
        dest.write_bytes(extra.read_bytes())
        urls.append((extra.name, extra.name))
    _write_package_json(identifier_dir / "package.json", urls, version)


def build_target(
    build_options: BuildOptions,
    chain: ResolvedToolchain,
    mpy_dir: Path,
    module_root: Path,
    output_dir: Path,
    *,
    extra_files: Sequence[Path] = (),
    version: str = "",
) -> BuildResult:
    """Run one target's build end to end: pre-build-command, make, collect,
    verify, package.

    Writes into `output_dir/<identifier>/`, not a flat `output_dir/` --
    every identifier gets its own directory from the start (D14), so there
    is no separate reorganising step between building and having something
    mip can install. Two targets can never collide here: `Target` is keyed
    on (abi, mode, arch, tag, arch_flags), and natmod_targets()/tag_groups()
    both dedupe by construction, so distinct targets always get distinct
    identifiers and therefore distinct directories.
    """
    start = time.time()
    env = chain.env()

    run_pre_build_command(module_root, build_options.pre_build_command, env)
    run_make(build_options, mpy_dir, module_root, env)

    produced = collect_output(build_options, module_root)
    verify_output(build_options, produced)

    identifier_dir = output_dir / build_options.identifier
    identifier_dir.mkdir(parents=True, exist_ok=True)
    dest = identifier_dir / output_name(build_options, produced)
    dest.write_bytes(produced.read_bytes())

    package_target(
        build_options, identifier_dir, produced.name, dest, list(extra_files), version
    )

    return BuildResult(
        identifier=build_options.identifier, output=dest, duration=time.time() - start
    )
