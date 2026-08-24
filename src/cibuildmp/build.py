"""Running the build itself: pre-build command, make, collect, verify.

Fails fast, one target at a time -- matching cibuildwheel's own
build-in-container loop (platforms/linux.py), which lets a
`subprocess.CalledProcessError` from one identifier abort the whole
invocation rather than collecting per-target failures into a report.
`cli.build()` already handles that: this module raises, cli.main() catches
alongside SourceError/ToolchainError.

Also cibuildwheel-shaped: `collect_output()`/`verify_output()` mirror its
"exactly one artifact, or a named error" checks (BuildProducedNoWheelError,
RepairStepProducedMultipleWheelsError) and its AlreadyBuiltWheelError, and
the BuildResult accumulated per target mirrors its BuildInfo summary line.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .options import BuildOptions
from .targets import NATIVE_ARCH_CODE
from .toolchains import ResolvedToolchain

MPY_HEADER_MAGIC = ord("M")


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
    command = make_command(build_options, mpy_dir, module_root)
    try:
        subprocess.run(command, cwd=module_root, env=env, check=True)
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


def read_native_arch(mpy_path: Path) -> int:
    """The MP_NATIVE_ARCH_* code baked into a native .mpy's own header.

    Layout from tools/mpy_ld.py's build_mpy(): byte 0 is 'M', byte 1 is
    MPY_VERSION, byte 2 packs MPY_SUB_VERSION in its low 2 bits and the arch
    code shifted left 2 above that, byte 3 is MP_SMALL_INT_BITS.
    """
    header = mpy_path.read_bytes()[:4]
    if len(header) < 4 or header[0] != MPY_HEADER_MAGIC:
        raise BuildError(f"{mpy_path}: does not look like a compiled .mpy (bad header)")
    return header[2] >> 2


def verify_output(build_options: BuildOptions, mpy_path: Path) -> None:
    """cibuildmp's equivalent of auditwheel: the header the linker actually
    wrote must name the arch this target was building for, not just live in
    the right build/<arch>*/ directory -- catches "built the wrong thing
    into the right directory" the way a wheel tag/platform mismatch would.
    """
    arch = build_options.target.arch
    expected = NATIVE_ARCH_CODE[arch]
    actual = read_native_arch(mpy_path)
    if actual != expected:
        raise BuildError(
            f"{build_options.identifier}: {mpy_path.name}'s header encodes native "
            f"arch code {actual}, expected {expected} ({arch})"
        )


def output_name(build_options: BuildOptions, mpy_path: Path) -> str:
    return f"{mpy_path.stem}-{build_options.identifier}{mpy_path.suffix}"


def build_target(
    build_options: BuildOptions,
    chain: ResolvedToolchain,
    mpy_dir: Path,
    module_root: Path,
    output_dir: Path,
    seen_names: set[str],
) -> BuildResult:
    """Run one target's build end to end and collect its result.

    `seen_names` is shared across every target in the invocation -- the
    natmod equivalent of cibuildwheel's AlreadyBuiltWheelError, catching two
    targets that would silently overwrite each other's output.
    """
    start = time.time()
    env = chain.env()

    run_pre_build_command(module_root, build_options.pre_build_command, env)
    run_make(build_options, mpy_dir, module_root, env)

    produced = collect_output(build_options, module_root)
    verify_output(build_options, produced)

    name = output_name(build_options, produced)
    if name in seen_names:
        raise BuildError(
            f"{build_options.identifier}: two targets both produced {name!r}"
        )
    seen_names.add(name)

    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / name
    dest.write_bytes(produced.read_bytes())

    return BuildResult(
        identifier=build_options.identifier, output=dest, duration=time.time() - start
    )
