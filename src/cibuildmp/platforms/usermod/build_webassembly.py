"""usermod build driver: `webassembly`.

Docker-only (**D30**), with its toolchain (`emsdk`) baked into
`docker/webassembly.Dockerfile` at image-build time. It used to have a
host-side resolver of its own (`usermod/emsdk.py`, not `toolchains.py`'s
`<prefix>gcc` shape); that went away with the bare-host path itself, and
that Dockerfile is now the pin of record.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from . import build_common
from .build_common import UsermodBuildError


@dataclass(frozen=True)
class WebassemblyBuildOptions:
    user_c_modules: str
    frozen_manifest: str
    build_dir: Path
    variant: str = "pyscript"
    tag: str = ""
    extra_make_args: tuple[str, ...] = ()


def webassembly_make_command(
    opts: WebassemblyBuildOptions, mpy_dir: Path, *, mpy_cross: Path | None = None
) -> list[str]:
    # `CFLAGS_EXTRA` here too, not just on `container_mpy_cross()` below:
    # `ports/webassembly` recompiles `py/` into the module itself, the
    # same class of diagnostic [0091] confirmed live on `arm_embedded`'s
    # native compiler (run 33697330722) for `-Wno-error=
    # unterminated-string-initialization`-shaped tags, and this image's
    # own native compiler is the same `ubuntu:26.04` `build-essential`.
    cflags = build_common.tag_cflags(opts.tag)
    return [
        "make",
        "-C",
        (mpy_dir / "ports" / "webassembly").as_posix(),
        f"VARIANT={opts.variant}",
        f"BUILD={opts.build_dir.as_posix()}",
        *([f"CFLAGS_EXTRA={' '.join(cflags)}"] if cflags else []),
        # py/mkenv.mk's own `MICROPY_MPYCROSS` override. Passed for the
        # same reason `build_unix()` passes it, arrived at from the other
        # direction (record 0044): this image is amd64, so on an **arm64
        # host** the host-built mpy-cross is an arm64 binary that cannot
        # run inside it, and `py/mkrules.mk` runs mpy-cross *inside* the
        # container to compile FROZEN_MANIFEST. Without this, this port
        # works on an amd64 runner and nowhere else -- which is exactly
        # the host-dependence record 0043 exists to remove.
        *([f"MICROPY_MPYCROSS={mpy_cross.as_posix()}"] if mpy_cross else []),
        f"USER_C_MODULES={opts.user_c_modules}",
        f"FROZEN_MANIFEST={opts.frozen_manifest}",
        *opts.extra_make_args,
    ]


def _webassembly_project_mounts(
    opts: WebassemblyBuildOptions, package_dir: Path | None
) -> list[Path]:
    """The user's own project, mounted so a module whose sources reach
    outside `USER_C_MODULES` still resolves -- `build_unix.py`'s own
    `_project_mounts()`, unchanged for a Make port. No entry at all when
    it is empty (record 0056) -- see `_project_mounts()`'s own comment."""
    mounts = [Path(opts.user_c_modules)] if opts.user_c_modules else []
    if package_dir is not None:
        mounts.append(package_dir.resolve())
    return mounts


def build_webassembly(
    opts: WebassemblyBuildOptions,
    mpy_dir: Path,
    *,
    toolchain_root: Path | None = None,
    quiet: bool = False,
    package_dir: Path | None = None,
    staging: Path | None = None,
) -> Path:
    """Build ports/webassembly for `opts.variant`, returning the produced
    `micropython.mjs`.

    Docker-only (D30's own later call: no bare-host path for any usermod
    port, `unix` included). `dockerrun.ensure_image("webassembly")`
    resolves an explicit `CIBMP_WEBASSEMBLY_DOCKER_IMAGE` override or a
    `dockerrun.resources/pinned_docker_images.toml`-registered, digest-pinned default published
    by `publish-docker-images.yml` -- cibuildmp itself never builds
    `docker/webassembly.Dockerfile` (see usermod/dockerrun.py's own
    docstring for why). emsdk itself is baked into that image, which is
    also the pin of record for it -- there is no `sdk.env()` to inject,
    the image's own `ENV PATH` already covers it. `toolchain_root`/`quiet`
    are accepted only for the same call shape every `build_<port>()`
    shares (`orchestrate.py`'s `build_one()` passes them uniformly);
    neither is used on this Docker-only path. `package_dir`, when given,
    is bind-mounted alongside `USER_C_MODULES` itself -- see
    `_webassembly_project_mounts()`.

    **`Container`/overlay, not `dockerrun.run()`** ([0095]): the checkout
    arrives read-only, `container.overlay(mpy_dir)` gives the build a
    writable view of it that dies with the container, and `BUILD=` (still
    `opts.build_dir`, unchanged) is never mounted, so it lives purely
    inside the container's own ephemeral filesystem -- see
    `build_windows()`'s identical comment for why the overlay is needed
    regardless (`container_mpy_cross()`'s own in-container path). `staging`
    is the one thing that survives: both `micropython.mjs` and its own
    `micropython.wasm` companion (the `.mjs` loads that literal name --
    record 0070) are `cp`'d there before the container exits, since a
    build that produced the JS half without the wasm blob would collect
    an artifact that cannot load at all. `micropython.wasm` is copied only
    when it exists, matching `webassembly_companions()`'s own tolerance
    for a build shape that never has one (nothing here passes emscripten
    `-sSINGLE_FILE`, but this driver does not assume that stays true).

    The output path is `staging / "micropython.mjs"`, copied out of
    `opts.build_dir / "micropython.mjs"` -- `ports/webassembly/Makefile`'s
    own `all:` target.
    """
    from ... import dockerrun

    docker_image = dockerrun.ensure_image("webassembly")
    if docker_image is None:
        raise UsermodBuildError(
            "webassembly: no Docker image registered for this port "
            "and usermod builds are Docker-only -- set "
            "CIBMP_WEBASSEMBLY_DOCKER_IMAGE, or wait for "
            "publish-docker-images.yml to publish one and register it in "
            "resources/pinned_docker_images.toml"
        )
    oci_platform = dockerrun.platform_for("webassembly")
    timeout = dockerrun.timeout_for("webassembly")

    if staging is None:
        msg = (
            "webassembly builds need a staging directory to hand the "
            "artifact back through ([0095]); orchestrate.build_one() "
            "provides one"
        )
        raise UsermodBuildError(msg)

    with dockerrun.overlay_container(
        mpy_dir,
        image=docker_image,
        # `linux/amd64` -- a statement about this *image* (an emsdk cross
        # host), not about the build target, which is wasm and which no
        # container is ever native to. Passing it is what lets this port
        # run on an arm64 host at all (**0043**): emulated, explicitly,
        # instead of resolving by accident-of-host and failing with a
        # bare `exec format error` from inside `make`.
        oci_platform=oci_platform,
        mounts=[staging, *_webassembly_project_mounts(opts, package_dir)],
    ) as container:
        container.overlay(mpy_dir)

        mpy_cross = build_common.container_mpy_cross(
            mpy_dir,
            timeout=timeout,
            extra_cflags=build_common.tag_cflags(opts.tag),
            container=container,
        )
        command = webassembly_make_command(opts, mpy_dir, mpy_cross=mpy_cross)
        container.call(
            command, workdir=mpy_dir / "ports" / "webassembly", timeout=timeout
        )

        # Both files exist only inside the container until this copy --
        # see `build_unix()`'s identical reasoning. Each is copied only
        # when present -- **including the `.mjs`** -- rather than letting
        # a missing one fail this `cp` outright: the check below
        # (`produced.exists()`) is what turns a missing primary into the
        # informative "build reported success but ... is missing" error;
        # a hard `cp` failure here would instead surface as an opaque
        # "failed with exit code" naming this copy step, not the build.
        # `micropython.wasm`'s own tolerance additionally matches
        # `webassembly_companions()`'s host-side check.
        mjs_src = (opts.build_dir / "micropython.mjs").as_posix()
        wasm_src = (opts.build_dir / "micropython.wasm").as_posix()
        mjs_dest = (staging / "micropython.mjs").as_posix()
        wasm_dest = (staging / "micropython.wasm").as_posix()
        script = (
            f"[ -e {shlex.quote(mjs_src)} ] && "
            f"cp {shlex.quote(mjs_src)} {shlex.quote(mjs_dest)} || true\n"
            f"[ -e {shlex.quote(wasm_src)} ] && "
            f"cp {shlex.quote(wasm_src)} {shlex.quote(wasm_dest)} || true\n"
        )
        container.call(
            ["sh", "-c", script],
            workdir=mpy_dir / "ports" / "webassembly",
            timeout=timeout,
        )

    produced = staging / "micropython.mjs"
    if not produced.exists():
        raise UsermodBuildError(
            f"webassembly/{opts.variant}: build reported success but "
            f"{produced} is missing"
        )
    return produced


def webassembly_companions(produced: Path) -> list[Path]:
    """`micropython.wasm` -- the larger half of what this port builds.

    `ports/webassembly/README.md` says it plainly: the build produces
    `micropython.mjs` (the JS runtime) *and* `micropython.wasm`
    (MicroPython itself). Nothing passes emscripten `-sSINGLE_FILE`, so
    the `.mjs` carries only the literal string `micropython.wasm`,
    resolved against whatever directory the `.mjs` is loaded from.

    Collecting the `.mjs` alone shipped an artifact that could not load
    at all -- record 0070's failure, one port over:

        failed to asynchronously prepare wasm: Error: ENOENT:
        no such file or directory, open '.../micropython.wasm'

    -- a real `node` run of a real `mpyhouse/v1.28.0-wasm32/` collected
    by a real local build (2026-08-31): 217,344 bytes collected out of
    the 680,703 the build actually produced.

    Kept under its own name, never `_dest_name()`-renamed -- the `.mjs`
    looks for exactly `micropython.wasm`. Renaming the `.mjs` itself is
    fine; that name is the caller's own entry point.
    """
    wasm_blob = produced.parent / "micropython.wasm"
    return [wasm_blob] if wasm_blob.is_file() else []
