"""Running the build itself: pre-build command, make, collect, verify,
package.

Fails fast, one target at a time -- matching cibuildwheel's own
build-in-container loop (platforms/linux.py), which lets a
`subprocess.CalledProcessError` from one identifier abort the whole
invocation rather than collecting per-target failures into a report.
`build_all()` already handles that: this module raises, cli.main() catches
alongside SourceError.

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
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .options import BuildOptions
from .targets import NATIVE_ARCH_CODE

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

    Every path here is written `.as_posix()` and every one of them is
    bind-mounted at its own identical absolute path inside the image, so
    this list is the same whether it is read on the host or run in the
    container -- D26's own reason for mounting that way.
    """
    return [
        "make",
        "-C",
        module_root.as_posix(),
        f"ARCH={build_options.target.arch}",
        f"MPY_DIR={mpy_dir.as_posix()}",
        # `python3`, not `sys.executable`. D12 made pyelftools and `ar`
        # cibuildmp's own dependencies and `PYTHON=<sys.executable>` was
        # how that reached make -- dynruntime.mk assigns PYTHON with a
        # plain `=`, so naming cibuildmp's own interpreter won over the
        # `python3` it would otherwise use.
        #
        # That mechanism cannot cross a container boundary: the path
        # `sys.executable` names is in the *host's* virtual environment
        # and does not exist inside the image. Record 0049 moved the
        # requirement into the image instead --
        # `docker/natmod.Dockerfile` installs `python3-pyelftools` and
        # `ar` comes with build-essential -- so the plain interpreter is
        # now sufficient, and it is the only one that is addressable
        # from both sides of the mount.
        "PYTHON=python3",
        *build_options.extra_make_args,
        build_options.make_target,
    ]


def _natmod_image() -> str:
    """The image every natmod build runs in, or a clear error.

    **There is no bare-host path any more** (record 0049). natmod resolved
    a toolchain onto whatever machine invoked it until then -- apt
    packages, downloaded tarballs, the host gcc's own multilib -- which is
    exactly the mutation D30 had already ruled out for usermod, and the
    reason `x86` could not be built on an arm64 runner at all. One
    `linux/amd64` image holds all ten arches' toolchains now, so the
    machine underneath stops mattering: what is not native to it is
    emulated, like every other port.
    """
    from ... import dockerrun

    image = dockerrun.ensure_image("natmod")
    if image is None:
        raise BuildError(
            "no image registered for natmod -- `pinned_docker_images.toml`'s "
            "own `[port] natmod` entry is empty until a real "
            "publish-docker-images.yml run fills it. Point "
            "CIBMP_NATMOD_DOCKER_IMAGE at a locally built tag to work "
            "without one."
        )
    return image


def _run_in_image(
    command: list[str], *, mounts: list[Path], workdir: Path, what: str
) -> None:
    from ... import dockerrun

    try:
        dockerrun.run(
            command,
            mounts=mounts,
            workdir=workdir,
            image=_natmod_image(),
            oci_platform=dockerrun.platform_for("natmod"),
        )
    except Exception as exc:  # UsermodBuildError, and anything docker raises
        raise BuildError(f"{what}: {exc}") from exc


def build_mpy_cross(mpy_dir: Path) -> Path:
    """Build mpy-cross **inside the natmod image** and return the binary.

    `py/dynruntime.mk` hardcodes `MPY_CROSS = $(MPY_DIR)/mpy-cross/build/mpy-cross`
    with no override (unlike ports/unix's `MICROPY_MPYCROSS=`) -- confirmed
    directly against v1.29.0's own dynruntime.mk, not assumed -- so the
    binary must exist at that exact path before `run_make()` invokes it.

    Building it on the host (`sources.build_mpy_cross()`, still used for
    usermod's `qemu`) worked here only because host glibc happened to
    match `docker/natmod.Dockerfile`'s own glibc -- the same coincidence
    `usermod/build.py`'s own `container_mpy_cross()` already documents and
    fixed for the port builds (a real `GLIBC_2.34' not found` failure). No
    `slug` scoping here the way that function needs: natmod has exactly
    one image for every arch, so there is only ever one binary to build,
    at the fixed path dynruntime.mk itself expects -- no `MPY_CROSS=`
    override to pass, unlike `MICROPY_MPYCROSS=`.

    Cached by existence, like `sources.build_mpy_cross()`/
    `usermod.build.container_mpy_cross()`: rebuilt only when the image
    itself changes (the image is digest-pinned).
    """
    binary = mpy_dir / "mpy-cross" / "build" / "mpy-cross"
    if binary.exists():
        return binary
    _run_in_image(
        ["make", "-C", (mpy_dir / "mpy-cross").as_posix(), f"-j{os.cpu_count() or 1}"],
        mounts=[mpy_dir],
        workdir=mpy_dir / "mpy-cross",
        what="mpy-cross",
    )
    if not binary.exists():
        raise BuildError(f"mpy-cross build reported success but {binary} is missing")
    return binary


def run_pre_build_command(
    module_root: Path,
    command: str,
    mpy_dir: Path,
    package_dir: Path,
) -> None:
    """A project's own `pre-build-command`, inside the same image the
    build itself runs in.

    On the host until record 0049, which is where it stopped making
    sense: a7p's own `make fetch-nanopb` is a *build* step, and running
    it against a different set of tools than the compile that follows is
    the kind of difference that shows up as a link error three steps
    later. Same image, same mounts, same working directory.
    """
    if not command:
        return
    # Absolute, because a bind mount and a container workdir both have to
    # be. `module_root` is routinely relative on the host -- it is
    # `options.package_dir / module_dir` and `package_dir` is very often
    # "." -- which the old bare-host `subprocess.run` never cared about.
    # Docker cares: it refuses a relative `-w` outright.
    module_root = module_root.resolve()
    _run_in_image(
        ["bash", "-c", command],
        mounts=[mpy_dir.resolve(), package_dir.resolve()],
        workdir=module_root,
        what=f"pre-build-command {command!r}",
    )


def run_make(
    build_options: BuildOptions,
    mpy_dir: Path,
    module_root: Path,
    package_dir: Path,
) -> None:
    # Both paths are mounted at their own identical absolute paths inside
    # the container (dockerrun's own contract), so the command built for a
    # bare-host invocation needs no rewriting -- the same property that
    # let usermod's own make/deplibs command lists move into containers
    # untouched (D26).
    #
    # No cwd/workdir subtlety left either: `-C module_root` already makes
    # make chdir there, and the workdir below is only where the container
    # starts.
    mpy_dir = mpy_dir.resolve()
    module_root = module_root.resolve()
    # **The package root, not the module directory.** A project's own
    # Makefile is entitled to reach outside `natmod/` -- the documented
    # downstream layout has `natmod/`, `usermod/` and `src/` as siblings,
    # and `examples/template/natmod/Makefile` compiles
    # `../src/template_core.c` precisely to prove the two modes share one
    # implementation. Mounting only the module directory made that file
    # not exist, which surfaced as "No rule to make target
    # '../src/template_core.c'" -- a missing *mount* reported as a
    # missing rule, three layers down.
    #
    # `module_root` is not mounted separately: it is underneath this.
    command = make_command(build_options, mpy_dir, module_root)
    _run_in_image(
        command,
        mounts=[mpy_dir, package_dir.resolve()],
        workdir=module_root,
        what=build_options.identifier,
    )


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


def output_name(
    build_options: BuildOptions, mpy_path: Path, *, name: str = "", version: str = ""
) -> str:
    # Identifier-qualified even though the file already lives in its own
    # identifier/ directory: package.json's own urls stay unambiguous even
    # if a caller later flattens several identifiers' directories into one
    # namespace (e.g. a GitHub Release's own asset list, which cannot nest
    # directories -- see D14's "still open" deployment note).
    #
    # `name`/`version` (record 0052, A3) give the file real project
    # identity -- `mpy_path.stem` alone is a side effect of the user's own
    # Makefile, not a config value. Gated on `name` being set at all: a
    # project that has not set it yet keeps exactly today's filename
    # rather than gaining a bare leading `-`.
    if not name:
        return f"{mpy_path.stem}-{build_options.identifier}{mpy_path.suffix}"
    prefix = f"{name}-{version}-" if version else f"{name}-"
    return f"{prefix}{build_options.identifier}{mpy_path.suffix}"


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
    mpy_dir: Path,
    module_root: Path,
    output_dir: Path,
    *,
    package_dir: Path,
    extra_files: Sequence[Path] = (),
    name: str = "",
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

    run_pre_build_command(
        module_root, build_options.pre_build_command, mpy_dir, package_dir
    )
    run_make(build_options, mpy_dir, module_root, package_dir)

    produced = collect_output(build_options, module_root)
    verify_output(build_options, produced)

    identifier_dir = output_dir / build_options.identifier
    identifier_dir.mkdir(parents=True, exist_ok=True)
    dest = identifier_dir / output_name(
        build_options, produced, name=name, version=version
    )
    dest.write_bytes(produced.read_bytes())

    package_target(
        build_options, identifier_dir, produced.name, dest, list(extra_files), version
    )

    return BuildResult(
        identifier=build_options.identifier, output=dest, duration=time.time() - start
    )
