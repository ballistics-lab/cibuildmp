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

from ..natmod import sources
from . import manifests, portinfo
from .build import (
    Esp32BuildOptions,
    QemuBuildOptions,
    UnixBuildOptions,
    UsermodBuildError,
    WebassemblyBuildOptions,
    WindowsBuildOptions,
    build_esp32,
    build_qemu,
    build_unix,
    build_webassembly,
    build_windows,
)
from .options import UsermodBuildOptions, UsermodOptions
from .targets import UsermodTarget

# port -> the build_<port>() function, uniform signature across all five:
# build_x(opts, mpy_dir, *, toolchain_root=None, quiet=False) -> Path.
_BUILD_FN: dict[str, Callable[..., Path]] = {
    "unix": build_unix,
    "windows": build_windows,
    "qemu": build_qemu,
    "webassembly": build_webassembly,
    "esp32": build_esp32,
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
    """The port-specific `*BuildOptions` `usermod/build.py` wants, built
    from `build_options`' own generic ingredients: `user_c_modules`
    resolved (D16), a combined manifest written to a real file (D17,
    empty -- and no file at all -- when neither the port nor the config
    has one to include), a per-identifier `build_dir`."""
    target = build_options.target
    port = target.port
    identifier = target.identifier

    module_root = (package_dir / build_options.module_dir).resolve()
    user_c_modules = portinfo.resolve_user_c_modules(port, module_root.as_posix())

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
            user_c_modules=user_c_modules,
            frozen_manifest=frozen_manifest,
            build_dir=_resolved_build_dir(mpy_dir, port, identifier),
            extra_make_args=extra_make_args,
        )
    if port == "windows":
        return WindowsBuildOptions(
            arch=target.arch,
            user_c_modules=user_c_modules,
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
            user_c_modules=user_c_modules,
            frozen_manifest=frozen_manifest,
            build_dir=_resolved_build_dir(mpy_dir, port, identifier),
            board=target.arch or "MPS2_AN385",
            extra_make_args=extra_make_args,
        )
    if port == "webassembly":
        return WebassemblyBuildOptions(
            user_c_modules=user_c_modules,
            frozen_manifest=frozen_manifest,
            build_dir=_resolved_build_dir(mpy_dir, port, identifier),
            extra_make_args=extra_make_args,
        )
    if port == "esp32":
        return Esp32BuildOptions(
            user_c_modules=user_c_modules,
            frozen_manifest=frozen_manifest,
            board=target.arch,
            extra_make_args=extra_make_args,
        )
    raise UsermodBuildError(f"no build_options builder wired for port {port!r}")


def _dest_name(produced: Path, identifier: str) -> str:
    # Identifier-qualified even though the file already lives in its own
    # identifier/ directory -- same reasoning natmod's own output_name()
    # gives: stays unambiguous if a caller later flattens several
    # identifiers' directories into one namespace (a GitHub Release's own
    # flat asset list, which cannot nest directories).
    return f"{produced.stem}-{identifier}{produced.suffix}"


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
# those.
#
# `esp32` and `qemu` still need it. `esp32`'s `make` runs outside Docker
# entirely (ESP-IDF is provisioned, not containerised -- D19), and
# `qemu` passes no `MICROPY_MPYCROSS`, so both reach
# `mpy-cross/build/mpy-cross` on the host through `py/mkrules.mk`'s own
# default. Neither is in the default port set any more -- `esp32` is out
# of it entirely pending [0028], and `qemu` has no `ensure_image()`
# caller yet ([0032]) -- so in practice this now skips for every default
# invocation, which is the point.
#
# Built once for the whole run rather than per target, unchanged -- this
# only stops building it for runs that will never look at it.
_HOST_MPY_CROSS_PORTS = frozenset({"esp32", "qemu"})


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
    # cli.build()'s own comment), just one layer deeper (MicroPython's own
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
    dest = identifier_dir / _dest_name(produced, target.identifier)
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

    MicroPython is fetched and mpy-cross built once, shared across every
    target -- the same D9 reasoning `cli.build()` already applies for
    natmod, and for the same reason: nothing here needs a different
    checkout or a different mpy-cross per target, since none of the five
    ports' own axes (arch/board) change which MicroPython release is
    being built, only how it is cross-compiled.
    """
    mpy_dir = sources.fetch_micropython(options.micropython)
    if any(t.port in _HOST_MPY_CROSS_PORTS for t in targets):
        sources.build_mpy_cross(mpy_dir, quiet=quiet)

    results = []
    for target in targets:
        results.append(
            build_one(
                options, target, mpy_dir, toolchain_root=toolchain_root, quiet=quiet
            )
        )
    return results
