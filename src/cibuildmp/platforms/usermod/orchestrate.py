"""Running a usermod build end to end: resolve a target's port-specific
`*BuildOptions`, write its combined manifest, call the matching
`build_<port>()`, collect the result.

Mirrors `build.build_target()`'s own shape (mpy-cross built once, shared
across targets; `output_dir/<identifier>/` per target) but simpler: no
`verify_output()` (there is no `.mpy` header to check a full port binary
against) and no `package_target()`/`package.json` at all -- a usermod
build's output is a full port binary meant to be flashed or run
directly, not `mip.install()`-ed into a running MicroPython, so D14's
packaging step does not apply (confirmed with the user directly, not
assumed).

Not yet supported, deliberately, same as `usermod/options.py`'s own
docstring already flags:
- No `extra-files` equivalent (natmod's own `[publish] extra-files`) --
  a real, cheap follow-up, just not attempted in this first slice.
- No per-target `pre-build-command`.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ... import sources
from . import manifests, portinfo
from .build_common import UsermodBuildError
from .build_esp32 import Esp32BuildOptions, build_esp32
from .build_qemu import QemuBuildOptions, build_qemu
from .build_rp2 import RP2_SUBMODULES, Rp2BuildOptions, build_rp2
from .build_unix import UnixBuildOptions, build_unix
from .build_webassembly import WebassemblyBuildOptions, build_webassembly
from .build_windows import WindowsBuildOptions, build_windows
from .options import UsermodBuildOptions, UsermodOptions
from .targets import UsermodTarget, esp32_idf_info

# port -> the build_<port>() function, uniform signature across all six:
# build_x(opts, mpy_dir, *, toolchain_root=None, quiet=False) -> Path.
_BUILD_FN: dict[str, Callable[..., Path]] = {
    "unix": build_unix,
    "windows": build_windows,
    "qemu": build_qemu,
    "webassembly": build_webassembly,
    "esp32": build_esp32,
    "rp2": build_rp2,
}


@dataclass(frozen=True)
class UsermodBuildResult:
    identifier: str
    output: Path
    duration: float

    @property
    def size(self) -> int:
        return self.output.stat().st_size


def _resolved_build_dir(mpy_dir: Path, port: str, identifier: str) -> Path:
    # One build directory per identifier, not the port's own bare default
    # -- so building unix-manylinux_2_28_x86_64 and
    # unix-manylinux_2_28_aarch64 against the same checkout
    # in one invocation never has one overwrite the other mid-build.
    return mpy_dir / "ports" / port / f"build-{identifier}"


def _manifest_path(mpy_dir: Path, port: str, identifier: str) -> Path:
    return mpy_dir / "ports" / port / f"cibuildmp-manifest-{identifier}.py"


def _port_build_options(
    build_options: UsermodBuildOptions,
    mpy_dir: Path,
    package_dir: Path,
) -> Any:
    """The port-specific `*BuildOptions` each `usermod/build_<port>.py` wants, built
    from `build_options`' own generic ingredients: `user_c_modules`
    resolved (D16), a combined manifest written to a real file (D17,
    empty -- and no file at all -- when neither the port nor the config
    has one to include), a per-identifier `build_dir`."""
    target = build_options.target
    port = target.port
    identifier = target.identifier

    # `build_options.user_c_modules` is the raw, unresolved value from
    # config (record 0051's ninth addendum -- was `module_dir`, renamed
    # to match the literal TOML key now that it no longer collides with
    # natmod's own). `resolve_user_c_modules()` below turns it into the
    # actual `USER_C_MODULES=` value each port's own build wants --
    # unchanged for Make ports, `/micropython.cmake` appended for CMake
    # ports -- kept under its own name so the two are never conflated.
    module_root = (package_dir / build_options.user_c_modules).resolve()
    resolved_user_c_modules = portinfo.resolve_user_c_modules(
        port, module_root.as_posix()
    )

    module_manifest = (
        (package_dir / build_options.manifest).resolve().as_posix()
        if build_options.manifest
        else ""
    )
    manifest_text = manifests.combined_manifest(port, module_manifest)
    frozen_manifest = ""
    if manifest_text:
        manifest_path = _manifest_path(mpy_dir, port, identifier)
        manifest_path.write_text(manifest_text)
        frozen_manifest = manifest_path.as_posix()

    extra_make_args = tuple(build_options.extra_make_args)

    if port == "unix":
        return UnixBuildOptions(
            # `UsermodTarget.arch` is the port's generic axis value; for
            # `unix` that value is a platform tag (`manylinux_2_28_x86_64`)
            # rather than a bare architecture -- record 0043. The axis
            # itself stays one field on the target, so only the name of
            # the parameter it feeds changes here.
            target=target.arch,
            user_c_modules=resolved_user_c_modules,
            frozen_manifest=frozen_manifest,
            build_dir=_resolved_build_dir(mpy_dir, port, identifier),
            extra_make_args=extra_make_args,
        )
    if port == "windows":
        return WindowsBuildOptions(
            arch=target.arch,
            user_c_modules=resolved_user_c_modules,
            frozen_manifest=frozen_manifest,
            build_dir=_resolved_build_dir(mpy_dir, port, identifier),
            extra_make_args=extra_make_args,
        )
    if port == "qemu":
        # target.arch is "" unless a caller opts into [usermod.qemu]
        # boards = [...] (targets.py's own _PORT_AXES default keeps the
        # bare "" sentinel precisely so an unconfigured build's own
        # identifier/board stay unchanged -- see that module's own
        # comment) -- `or "MPS2_AN385"` is what turns the empty default
        # back into QemuBuildOptions' own default board instead of
        # overriding it with an empty string.
        return QemuBuildOptions(
            user_c_modules=resolved_user_c_modules,
            frozen_manifest=frozen_manifest,
            build_dir=_resolved_build_dir(mpy_dir, port, identifier),
            board=target.arch or "MPS2_AN385",
            extra_make_args=extra_make_args,
        )
    if port == "webassembly":
        return WebassemblyBuildOptions(
            user_c_modules=resolved_user_c_modules,
            frozen_manifest=frozen_manifest,
            build_dir=_resolved_build_dir(mpy_dir, port, identifier),
            extra_make_args=extra_make_args,
        )
    if port == "esp32":
        # `esp32_idf_info()` needs a real tag -- a hand-built target with
        # none (most of this project's own build/orchestrate tests, per
        # `UsermodTarget.identifier`'s own docstring) falls back to
        # `Esp32BuildOptions`' own defaults instead of a lookup that
        # would only ever `KeyError` for it.
        idf_kwargs = {}
        if target.tag:
            idf_version, idf_target = esp32_idf_info(target.tag, target.arch)
            idf_kwargs = {"idf_version": idf_version, "idf_target": idf_target}
        return Esp32BuildOptions(
            user_c_modules=resolved_user_c_modules,
            frozen_manifest=frozen_manifest,
            board=target.arch,
            extra_make_args=extra_make_args,
            **idf_kwargs,
        )
    if port == "rp2":
        # Same "" -> real default fallback qemu's own branch above uses --
        # a hand-built target with no board names none, and `Rp2BuildOptions`'
        # own default ("PICO") should apply rather than an empty BOARD=.
        return Rp2BuildOptions(
            user_c_modules=resolved_user_c_modules,
            frozen_manifest=frozen_manifest,
            board=target.arch or "PICO",
            extra_make_args=extra_make_args,
        )
    raise UsermodBuildError(f"no build_options builder wired for port {port!r}")


def _dest_name(
    produced: Path, identifier: str, *, name: str = "", version: str = ""
) -> str:
    # Identifier-qualified even though the file already lives in its own
    # identifier/ directory -- same reasoning natmod's own output_name()
    # gives: stays unambiguous if a caller later flattens several
    # identifiers' directories into one namespace (a GitHub Release's own
    # flat asset list, which cannot nest directories).
    #
    # `name`/`version` (record 0052, A3) replace `produced.stem` entirely
    # when set, rather than prefixing it: `produced.stem` is always
    # literally "micropython"/"micropython.exe", and restating that a
    # usermod build produces MicroPython firmware is noise a project name
    # already displaces (the same reason `natmod` was dropped from
    # natmod's own identifier). Gated on `name` alone, same as natmod's
    # own output_name() -- a project that has not set it yet keeps
    # exactly today's filename.
    if not name:
        return f"{produced.stem}-{identifier}{produced.suffix}"
    prefix = f"{name}-{version}-" if version else f"{name}-"
    return f"{prefix}{identifier}{produced.suffix}"


# Ports whose build still runs a *host* mpy-cross, and therefore the only
# ones that need one built.
#
# Record 0044 gave `unix`, `windows` and `webassembly` their own
# `container_mpy_cross()`, because a host-built mpy-cross cannot run
# inside a container that is a different architecture or a different
# libc -- which is every one of their images. They pass
# `MICROPY_MPYCROSS=` at the one built inside the image instead, so the
# host copy is dead weight for them: seven seconds of compiling, plus a
# bare-host build in a mode whose whole point is that it does not do
# those. `esp32` joined them 2026-08-28 (`build_esp32()` went Docker,
# `usermod/espidf.py`'s own docstring has the full reasoning) -- it is no
# longer in this set.
#
# `qemu` is the one port left here: it passes no `MICROPY_MPYCROSS`, so it
# reaches `mpy-cross/build/mpy-cross` on the host through
# `py/mkrules.mk`'s own default even though `build_qemu()` *is* wired to
# `ensure_image()` like every other port -- this frozenset is about which
# port still needs a *host* mpy-cross alongside its containerised build,
# not about which ports reach a container at all. Whether this is exactly
# the mismatch `container_mpy_cross()` exists to prevent, just not yet hit
# for `qemu` specifically, or a real difference between its targets and
# `esp32`'s, is not established here -- not touched by this change,
# flagged rather than assumed either way.
#
# Built once for the whole run rather than per target, unchanged -- this
# only stops building it for runs that will never look at it.
_HOST_MPY_CROSS_PORTS = frozenset({"qemu"})


def build_one(
    options: UsermodOptions,
    target: UsermodTarget,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
) -> UsermodBuildResult:
    start = time.time()
    build_options = options.build_options(target)
    port_opts = _port_build_options(build_options, mpy_dir, options.package_dir)

    # `build_dir` (unix/windows/qemu/webassembly only -- esp32 has none,
    # see Esp32BuildOptions, and uses ESP-IDF's own CMake-based staleness
    # tracking instead of a raw Makefile) is `mpy_dir/ports/<port>/
    # build-<identifier>/`, already scoped per identifier, but nothing
    # ever removes it *between* separate `cibuildmp` invocations. Found
    # for real: a leftover build-unix-x64/ from an earlier run (built
    # against a different, or no, USER_C_MODULES) carried a stale
    # genhdr/qstrdefs.generated.h missing this run's own module's QSTRs --
    # `'MP_QSTR_mymod' undeclared` -- the exact same "nothing cleans
    # between invocations" bug natmod's own build/ scratch space had (see
    # natmod.build_all()'s own comment), just one layer deeper (MicroPython's own
    # qstr pipeline, not cibuildmp's glob). Only safe to delete host-side
    # now that dockerrun.run() passes --user (see its own comment) --
    # every port build here runs in a sibling container as root otherwise,
    # which leaves build-<identifier>/ root-owned and unremovable by a
    # plain host-side rmtree.
    build_dir = getattr(port_opts, "build_dir", None)
    if build_dir is not None:
        shutil.rmtree(build_dir, ignore_errors=True)

    build_fn = _BUILD_FN[target.port]
    produced = build_fn(port_opts, mpy_dir, toolchain_root=toolchain_root, quiet=quiet)

    # options.output_dir is deliberately relative ("mpyhouse" by default,
    # D-shared with natmod's own DEFAULT_OUTPUT_DIR) -- resolved against
    # package_dir, not the process's own cwd, the same join natmod's own
    # cli.py does (`options.package_dir / build_options.output_dir`)
    # before calling collect_output(). A real Docker-action run is what
    # caught this: cwd there is always the repo root, not package_dir, so
    # an unjoined output_dir silently wrote to <repo-root>/mpyhouse
    # instead of <package_dir>/mpyhouse -- invisible in every earlier
    # verification in this session, which always ran with cwd ==
    # package_dir.
    identifier_dir = options.package_dir / options.output_dir / target.identifier
    identifier_dir.mkdir(parents=True, exist_ok=True)
    dest = identifier_dir / _dest_name(
        produced, target.identifier, name=options.name, version=options.version
    )
    # shutil.copy(), not copyfile(): unlike natmod's own .mpy (always
    # mip.install()-ed or imported, never executed directly -- D23), a
    # usermod build's own output IS a runnable binary. copyfile() only
    # copies content, not the executable bit `produced` already has --
    # confirmed live, a real collected unix-x64 binary silently coming
    # out `-rw-r--r--` and failing "Permission denied" on the very first
    # attempt to run it.
    shutil.copy(produced, dest)

    return UsermodBuildResult(
        identifier=target.identifier, output=dest, duration=time.time() - start
    )


def build(
    options: UsermodOptions,
    targets: list[UsermodTarget],
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
) -> list[UsermodBuildResult]:
    """Build every selected target in one invocation.

    Grouped by MicroPython tag (**0051**), the same D9/D13 reasoning
    natmod's own `build_all()` already applies: fetching a checkout (and,
    for the two ports that still need one, a host mpy-cross) is identical
    for every target sharing a release -- none of the five ports' own
    axes (arch/board) change which MicroPython release is being built,
    only how it is cross-compiled -- so paying for it once per tag beats
    paying for it once per target. Almost always one group, since that is
    the common case, but `targets` can span more than one release since
    `micropython` stopped being silently truncated to its first entry.
    """
    results = []
    # Preserves first-appearance order (usermod_targets() emits one tag
    # group at a time), not sorted -- matches natmod's own
    # dict.fromkeys(bo.target.tag for bo in resolved) idiom exactly.
    build_tags = list(dict.fromkeys(t.tag for t in targets))
    for tag in build_tags:
        group = [t for t in targets if t.tag == tag]
        # `RP2_SUBMODULES` only ever matters on `fetch_micropython()`'s own
        # clone path (a preview tag with no release tarball) -- the
        # tarball path already vendors every lib/ submodule for every
        # port, rp2 included. Threaded here, not hardcoded into
        # `fetch_micropython()` itself, since no other port needs one yet.
        rp2_submodules = list(RP2_SUBMODULES) if any(t.port == "rp2" for t in group) else None
        mpy_dir = sources.fetch_micropython(tag, submodules=rp2_submodules)
        if any(t.port in _HOST_MPY_CROSS_PORTS for t in group):
            sources.build_mpy_cross(mpy_dir, quiet=quiet)
        for target in group:
            results.append(
                build_one(
                    options, target, mpy_dir, toolchain_root=toolchain_root, quiet=quiet
                )
            )
    return results
