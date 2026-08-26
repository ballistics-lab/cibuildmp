#!/usr/bin/env -S uv run --script

"""Build and push cibuildmp's container images from this machine.

The same work `.github/workflows/publish-docker-images.yml` does, runnable
by hand. Two reasons it exists rather than the workflow being the only
way:

* **Visibility.** Record 0033 hit this once for real: eight images
  pushed, every one private, an anonymous pull of a freshly-pinned digest
  answering `401`. It cannot be *fixed* from here -- there is no REST
  resource for a container package's visibility, only the settings UI --
  but `--make-visible` reads it back for every cell, so the state is one
  command away instead of a surprise in a consumer's build.
* **Emulation cost.** Thirteen of the eighteen cells are foreign-arch
  images whose `dnf`/`apk` step runs under binfmt. On a slow runner that
  is a long job; on a workstation with the images half-cached it is often
  faster, and `--only` lets you publish one cell at a time.

Usage:

    docker login ghcr.io                     # PAT with write:packages
    docker run --privileged --rm tonistiigi/binfmt --install all

    bin/publish_images.py --dry-run          # print what would run
    bin/publish_images.py                    # build + push everything
    bin/publish_images.py --only manylinux_2_28_x86_64 musllinux_1_2_x86_64
    bin/publish_images.py --no-push          # build locally, push nothing
    bin/publish_images.py --public           # also report visibility
    bin/publish_images.py --make-visible     # ONLY report it, no rebuild

Afterwards, record the digests:

    bin/update_docker.py --images

which reads them straight back off GHCR rather than having you copy them.

**The matrix is not written here.** Cells come from
`resources/pinned_docker_images.toml` (its `[image.<arch>]` keys are the
matrix, record 0044) and platforms from `usermod/dockerrun.py`'s own
`ARCH_OCI_PLATFORM`. A fourth hand-maintained copy of that list is
exactly the drift this project keeps deriving things to avoid -- so this
script imports both rather than restating them, and a cell added to the
pin file appears here with no edit.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cibuildmp.dockerrun import (
    _PORT_OCI_PLATFORM,
    ARCH_OCI_PLATFORM,
)
from cibuildmp.resources import pinned_docker_images


def cells() -> list[tuple[str, str]]:
    """Every (image name, OCI platform) pair to publish, pin-file order.

    `unix` cells are named by their platform tag and are native to their
    own architecture; the cross-compiling ports keep plain port names and
    are amd64 Linux hosts (record 0043).
    """
    pins = pinned_docker_images()
    out = [
        (f"{floor}_{arch}", ARCH_OCI_PLATFORM[arch])
        for arch, floors in pins["image"].items()
        for floor in floors
    ]
    out += [(port, _PORT_OCI_PLATFORM) for port in pins["port"]]
    return out


def build_command(name: str, platform: str, owner: str, push: bool) -> list[str]:
    command = [
        "docker",
        "buildx",
        "build",
        f"--platform={platform}",
        "-t",
        f"ghcr.io/{owner}/{name}:latest",
        "-f",
        f"docker/{name}.Dockerfile",
    ]
    # `--push` and `--load` are mutually exclusive in buildx, and without
    # either the result stays in the build cache only. `--load` keeps
    # `--no-push` genuinely useful: the image lands in the local store
    # under the same name, so a `CIBMP_*_DOCKER_IMAGE` override can point
    # at it immediately.
    command.append("--push" if push else "--load")
    return [*command, "."]


def current_visibility(name: str, owner: str, *, user_account: bool) -> str | None:
    """`"public"` / `"private"`, or `None` if the package cannot be read.

    Checked before trying to change anything, because the interesting
    answer is usually "already public". `publish-docker-images.yml` has
    its own visibility step, and when that step works there is nothing
    left to do here -- reporting eighteen failures for eighteen packages
    that are already in the desired state is worse than useless, since it
    reads exactly like the real failure this script exists to fix.
    """
    endpoint = (
        f"user/packages/container/{name}"
        if user_account
        else f"orgs/{owner}/packages/container/{name}"
    )
    probe = subprocess.run(
        ["gh", "api", endpoint], check=False, capture_output=True, text=True
    )
    if probe.returncode:
        return None
    try:
        return json.loads(probe.stdout).get("visibility")
    except json.JSONDecodeError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--owner",
        default="ballistics-lab",
        help="GHCR owner to publish under (default: ballistics-lab)",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="IMAGE",
        help="publish just these image names (e.g. manylinux_2_28_x86_64)",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="build and load locally, push nothing",
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="after each push, read the package's visibility back and warn "
        "if it is not public (it cannot be changed from any API)",
    )
    parser.add_argument(
        "--user-account",
        action="store_true",
        help="owner is a personal account, not an organisation (picks the "
        "other visibility endpoint)",
    )
    parser.add_argument(
        "--make-visible",
        action="store_true",
        help="ONLY report each package's visibility -- build and push "
        "nothing. Visibility cannot be changed from an API at all (the "
        "PATCH endpoint does not exist); this tells you which packages "
        "need the settings UI, without rebuilding anything.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print commands, run nothing"
    )
    args = parser.parse_args()

    selected = cells()
    if args.only:
        known = {name for name, _ in selected}
        unknown = [name for name in args.only if name not in known]
        if unknown:
            print(
                f"error: not in the pin table: {', '.join(unknown)}\n"
                f"known: {', '.join(sorted(known))}",
                file=sys.stderr,
            )
            return 2
        selected = [cell for cell in selected if cell[0] in set(args.only)]

    def check_visible(name: str) -> bool:
        """Report whether `name` is publicly pullable. Cannot change it.

        There is no REST resource for a container package's visibility --
        `PATCH .../packages/container/<name>/visibility` answers 404 with
        a token carrying `write:packages` and `delete:packages` both, and
        the same 404 comes back inside Actions. The package settings UI is
        the only way to change it. An earlier version of this script tried
        that endpoint anyway and reported eighteen confident failures for
        eighteen packages that were already public, which is worse than
        doing nothing.

        Reading it back is still worth a flag of its own: record 0033's
        failure was real once (eight images published private, an
        anonymous pull answering 401), and this turns that into a
        one-line answer instead of a surprise in someone else's build.
        """
        if args.dry_run:
            print("  (would read visibility)")
            return True
        visibility = current_visibility(
            name, args.owner, user_account=args.user_account
        )
        if visibility == "public":
            print("  public")
            return True
        if visibility is None:
            print(f"  !! cannot read {name} -- not published, or no access")
            return False
        print(
            f"  !! {name} is '{visibility}' -- anonymous pulls will fail. "
            f"Make it public in the package settings UI; there is no API "
            f"for this."
        )
        return False

    failed: list[str] = []

    if args.make_visible:
        for index, (name, _platform) in enumerate(selected, start=1):
            print(f"\n[{index}/{len(selected)}] {name}")
            if not check_visible(name):
                failed.append(name)
        if failed:
            print(f"\n{len(failed)} not publicly pullable: {', '.join(failed)}")
            return 1
        print("\nAll selected packages are public.")
        return 0

    for index, (name, platform) in enumerate(selected, start=1):
        print(f"\n[{index}/{len(selected)}] {name}  ({platform})")
        command = build_command(name, platform, args.owner, push=not args.no_push)
        print("  $ " + " ".join(command))
        if (
            not args.dry_run
            and subprocess.run(command, cwd=ROOT, check=False).returncode
        ):
            # Not fatal: these cells are independent, and one
            # architecture's base going missing upstream should not stop
            # the other seventeen -- the same reason the workflow sets
            # `fail-fast: false`.
            failed.append(name)
            print(f"  !! {name} failed, continuing")
            continue
        if args.public and not args.no_push:
            check_visible(name)

    if failed:
        print(f"\n{len(failed)} failed: {', '.join(failed)}")
        return 1
    if not args.dry_run and not args.no_push:
        print("\nNow record the digests:  bin/update_docker.py --images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
