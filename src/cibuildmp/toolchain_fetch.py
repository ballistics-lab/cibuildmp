"""Generic in-container tarball toolchain fetch -- record 0086.

Generalizes what `docker/arm_embedded.Dockerfile`/`riscv_embedded.Dockerfile`
used to do only at *image build* time (curl a pinned tarball, verify its
sha256, `--strip-components=1` it into place) into something a real build can
also run at *container* time, against a host-mounted cache directory -- the
same shape `usermod/build_esp32.py`'s own `_esp32_container_script()` already
uses for ESP-IDF's own tools (a marker file inside a mounted, uid-owned
directory meaning "already installed, skip"). [0058]'s own rule is why this
has to run inside the container rather than on the host and then get
mounted in: a downloaded binary must be verified and extracted against the
same libc it will run against, and `build_common.container_mpy_cross()`'s
own docstring documents hitting the "built against one glibc, run against
another" mismatch for real when that rule is skipped.

`fetch_script()` mirrors `sources.cached_dir()`'s own staging-directory +
atomic move + stamp-file pattern, in shell text rather than host-side
Python -- the mechanism is the same, only the language it has to be
expressed in differs, since the fetch itself must run as a container
command rather than a host-side function call.

`resolve_toolchain()` is the one call a real caller needs: given a row's
own `cross` and resolved `toolchain_version`, it returns the cache
directory to mount and the script to fetch into it, host-side directory
creation included.

No caller yet -- nothing in `dockerrun.py` or any `build_<port>.py` calls
this module. [0087] wires it into `arm_embedded`/`riscv_embedded`'s six
shared `usermod` ports; [0089] wires the same mechanism into `natmod`'s own
rows on the same two images. Neither has landed -- see both records for why
this is worth writing once rather than twice.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from . import resources
from .sources import STAMP, cache_root


class ToolchainFetchError(Exception):
    pass


# The one real cross-compiler product each of these two toolchain-group
# images provides (record 0058's own "image groups are toolchains, not
# ports" design -- each image is keyed to exactly one compiler family).
# Shared between `usermod/targets.py` and `natmod/targets.py` rather than
# each keeping its own copy: both need the same `image -> cross` fact to
# turn a row's own `image`/`images` field into the key this module's own
# `resolve_pin()`/`toolchain_dir()` take. Not read off a row's own
# `cross` field -- that field is a Makefile grep
# (`parse_cross_compile()`/`parse_cross_prefixes()`) and is `None`
# wherever a port's own Makefile has no `CROSS_COMPILE` line to find
# (`rp2`'s CMake wrapper, confirmed directly), even though the image it
# runs in hosts exactly the toolchain named here regardless.
IMAGE_CROSS_PREFIX: dict[str, str] = {
    "arm_embedded": "arm-none-eabi-",
    "riscv_embedded": "riscv64-unknown-elf-",
}

# Where the canonical `cross` prefix above differs from what the fetched
# tarball's own binaries are actually named -- only `riscv_embedded`
# today: xpack ships `riscv-none-elf-*`, but `py/dynruntime.mk`/
# `ports/qemu` want `riscv64-unknown-elf-*`
# (`riscv_embedded.Dockerfile`'s own former build-time symlink loop, now
# `rename_prefix_script()` run at container time instead). Nothing for
# `arm_embedded`: xpack's own `arm-none-eabi-*` binaries already match
# the canonical prefix exactly, so no caller needs to consult this for
# it.
CROSS_RENAME_FROM: dict[str, str] = {
    "riscv64-unknown-elf-": "riscv-none-elf-",
}


def resolve_pin(cross: str, version: str) -> tuple[str, str]:
    """The `(url, sha256)` `resources/pinned_toolchains.toml` records for
    this `(cross, toolchain_version)` pair.

    `cross` is `build-platforms.toml`'s own existing per-row field (each
    port's real `CROSS_COMPILE` prefix, e.g. `"arm-none-eabi-"`), used
    verbatim -- not `image` (`arm_embedded`/`riscv_embedded`, record
    0058): that name is a Docker-packaging fact, while `cross` is a fact
    about the compiler itself, and the one that survives any future
    repackaging of the images (see `pinned_toolchains.toml`'s own
    header). `version` is a row's own `toolchain_version`/`gcc` string.

    The `(tag, port) -> version` half of this lookup is not this
    function's job and has no code yet -- `targets.py`'s own
    `_ESP32_IDF_INFO_BY_TAG_BOARD`/`esp32_idf_info()` do the analogous
    job for `esp32`'s `idf_version`, but keyed `(tag, board)`, one notch
    finer than what belongs here: `idf_version` genuinely varies by
    board at a fixed tag, while `toolchain_version` does not -- checked
    directly against `usermod.stm32`'s 76 boards, whose `gcc` field is
    identical across every board at a given tag. Whatever wires
    `arm_embedded`/`riscv_embedded` ([0087]/[0089]) needs a
    `(tag, port) -> version` lookup, one level up from here.

    Raises, naming both values, rather than a bare `KeyError` several
    frames from the row that asked: the same "declared but nothing
    resolves" shape `dockerrun.image_for()`'s own `None` already gives
    an unregistered image group, so a missing pin fails the same
    legible way a missing image reference does.
    """
    pins = resources.pinned_toolchains_data()
    entry = pins.get(cross, {}).get(version)
    if entry is None:
        raise ToolchainFetchError(
            f"no pinned (url, sha256) for {cross!r} toolchain version "
            f"{version!r} -- add it to resources/pinned_toolchains.toml"
        )
    return entry["url"], entry["sha256"]


def toolchain_dir(
    cross: str, kind: str, version: str, root: Path | None = None
) -> Path:
    """Where `cross`'s `kind` toolchain at `version` lives once fetched.

    `cross` is `build-platforms.toml`'s own existing per-row field (e.g.
    `"arm-none-eabi-"`, `"riscv64-unknown-elf-"`), not the port or the
    image: several ports share one compiler, and the tarball this caches
    is the same file regardless of which port asked for it. `kind` is
    the two toolchains a cross target can need ([0084]'s own finding) --
    "cross" for the firmware compiler, which is what [0087]/[0089]
    actually fetch; "native" is accepted rather than assumed away, even
    though nothing calls this with it yet, because `arm_embedded`'s own
    native compiler stays baked into the image (see [0087]) and this
    mechanism should not have to change shape the day something needs to
    fetch that one too.
    """
    return (root or cache_root()) / "toolchains" / cross / kind / version


def resolve_toolchain(
    cross: str, version: str, *, kind: str = "cross", root: Path | None = None
) -> tuple[Path, str]:
    """Resolve `cross`'s `version` toolchain to its cache directory and
    the shell script that fetches it there -- `resolve_pin()` +
    `toolchain_dir()` + `fetch_script()`, combined into the one call a
    real caller ([0087]/[0089]) needs, rather than three.

    Ensures `dest.parent` exists on the host before returning -- the
    same precondition `build_esp32()` meets for `tools_dir` by hand
    today, since the directory must exist and be writable before the
    container that mounts it starts.

    Returns `(dest, script)`: `dest` is the eventual `PATH` entry (joined
    with the toolchain's own `bin/`) once fetched; `script` is the shell
    text to run ahead of the real build command, in the same `bash -c`
    invocation. **The caller mounts `dest.parent`, not `dest` itself** --
    `fetch_script()`'s own docstring already states the precondition, and
    getting it backwards is a live, found-for-real failure, not a
    theoretical one: `dest` does not exist on the host until the script
    runs, so mounting it directly leaves Docker to synthesize every path
    component up to it *inside the container*, root-owned, and the
    script's own first `mkdir -p` then fails outright
    (`dockerrun.run(["bash", "-c", f"{script}\\n{command}"], mounts=[dest.parent, ...], ...)`).

    Still does not touch `dockerrun.py` or wire any port's own build
    driver -- see this module's own docstring for what remains
    [0087]'s/[0089]'s job.
    """
    url, sha256 = resolve_pin(cross, version)
    dest = toolchain_dir(cross, kind, version, root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest, fetch_script(dest, url, sha256)


def fetch_script(
    dest: Path, url: str, sha256: str, *, strip_components: int = 1
) -> str:
    """Shell text: fetch, sha256-verify and extract `url` into `dest`,
    doing nothing at all when `dest` already holds a complete tree.

    Meant to be embedded ahead of a real build command in one `bash -c`
    script -- `dockerrun.run(["bash", "-c", f"{fetch_script(...)}\\n{command}"],
    ...)`, the same way `build_esp32.py`'s own `_esp32_container_script()`
    already prefixes ESP-IDF's own install step ahead of `make`, in the one
    container invocation that needs both. Not a separate `dockerrun.run()`
    call: there is nothing to hand back to a second one, and the whole
    point is that `dest` -- and therefore whatever the real build command's
    own `PATH` needs to find inside it -- exists before that command runs,
    in the same container.

    Extraction lands in a staging directory next to `dest` first, then
    replaces `dest` in one `mv` -- mirroring `sources.cached_dir()`'s own
    staging + atomic-move + stamp-file shape exactly, so a container killed
    mid-fetch (the timeout `dockerrun.run()` already guards against, and
    kills for) never leaves a `dest` a later run's own marker check would
    wrongly trust. `dest.parent` must already exist, be writable by the
    container's own uid, and be one of the paths the caller mounts -- the
    same precondition `build_esp32()` already meets for `tools_dir` before
    its own container starts.

    The download/verify/extract steps run in a subshell with their own
    `ERR` trap, not inline: `sources.cached_dir()`'s own `try/finally`
    guarantees the staging directory it created is gone on any failure,
    and a plain top-level `set -e` here would not -- it stops the script,
    but stops it with the half-filled staging directory (and the
    downloaded archive) still sitting on disk. The `ERR` trap only fires
    on a real failure, never on the success path, so it never touches the
    tree `mv` is about to promote to `dest`.
    """
    marker = shlex.quote((dest / STAMP).as_posix())
    dest_q = shlex.quote(dest.as_posix())
    parent_q = shlex.quote(dest.parent.as_posix())
    staging = dest.parent / f".staging-{dest.name}"
    staging_q = shlex.quote(staging.as_posix())
    staging_marker = shlex.quote((staging / STAMP).as_posix())
    archive = dest.parent / f".fetch-{dest.name}.tar"
    archive_q = shlex.quote(archive.as_posix())
    url_q = shlex.quote(url)
    sha_q = shlex.quote(sha256)
    cleanup = f"rm -rf {staging_q} {archive_q}"
    return f"""\
set -euo pipefail
if [ ! -e {marker} ]; then
    mkdir -p {parent_q}
    (
        set -euo pipefail
        trap {shlex.quote(cleanup)} ERR
        {cleanup}
        mkdir -p {staging_q}
        curl -fsSL -o {archive_q} {url_q}
        echo "{sha_q}  {shlex.quote(archive.name)}" | (cd {parent_q} && sha256sum -c -)
        tar -xf {archive_q} --strip-components={strip_components} -C {staging_q}
        rm -f {archive_q}
        touch {staging_marker}
    )
    rm -rf {dest_q}
    mv {staging_q} {dest_q}
fi
"""


def rename_prefix_script(bin_dir: Path, old_prefix: str, new_prefix: str) -> str:
    """Shell text: symlink every `{old_prefix}*` tool already in `bin_dir`
    to a `{new_prefix}*` name, in the same directory.

    What `riscv_embedded.Dockerfile`'s own build-time `for` loop already
    does (xpack's real `riscv-none-elf-*` binaries -> the
    `riscv64-unknown-elf-*` names `py/dynruntime.mk`/`ports/qemu` actually
    invoke) -- moved to container-run time because the tarball is no
    longer extracted at image-build time, and `dockerrun.run()` always
    runs as the host's own non-root uid ([0087]'s own finding): the
    original loop wrote its symlinks into a root-owned `/usr/local/bin`,
    which a runtime fetch cannot do. Writing them into `bin_dir` itself
    instead needs no new mount or `PATH` entry beyond the one the fetched
    toolchain's own `bin/` already needs.

    Idempotent (`ln -sf`) and cheap enough to run on every invocation,
    warm cache or not -- gating it behind `fetch_script()`'s own marker
    would only add a second thing to get right for no real cost saved.
    Append this after `fetch_script()`'s own output in the same `bash -c`
    script, not a separate `dockerrun.run()` call.
    """
    bin_q = shlex.quote(bin_dir.as_posix())
    return f"""\
for src in {bin_q}/{old_prefix}*; do
    tool="${{src##*/{old_prefix}}}"
    ln -sf "$src" {bin_q}/"{new_prefix}${{tool}}"
done
"""
