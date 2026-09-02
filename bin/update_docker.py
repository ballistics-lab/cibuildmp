#!/usr/bin/env -S uv run --script

"""Refresh cibuildmp's pinned container image digests.

cibuildmp's own equivalent of cibuildwheel's `bin/update_docker.py`, and
named after it deliberately: it does the same maintainer-only job against
the same registries, for the two tables record 0043 split the pins into.

    bin/update_docker.py                # both tables
    bin/update_docker.py --pypa         # resources/pinned_pypa_images.toml
    bin/update_docker.py --images       # resources/pinned_docker_images.toml
    bin/update_docker.py --check        # report drift, change nothing

`--pypa` re-resolves upstream's own manylinux/musllinux images from
quay.io: for each entry it reads the digest `:latest` currently points at
and the dated tag sharing that digest (`2026.08.15-1`), which is how
cibuildwheel's own script names its pins too. Bumping these is a real
decision, not routine hygiene -- a new base is a new libc *build*, and for
`manylinux_2_31_armv7l` versus `_2_35` it can be a different floor
entirely -- so this only ever rewrites a digest in place. Which floor each
architecture is curated onto stays where it takes effect: `build-platforms.
toml`'s own `[usermod.unix].images.<tag>` (record 0058 moved it out of this
file -- it is the *group name* a build target resolves to, not the pin).

`--images` re-resolves cibuildmp's own published layer from GHCR, reading
the digest each `<name>:latest` points at, against
`pinned_docker_images.toml`'s single flat `[image_group]` table (record
0058 flattened the old `[image.<arch>]`/`[port]` split into one table keyed
by group name). That digest is the same value
`.github/workflows/publish-docker-images.yml` prints in its "Record the
pinned digest" step; this script exists so a maintainer can recover it
afterwards -- or fill in a whole freshly-published matrix at once -- rather
than copying digests out of a job summary by hand. A group name that is
itself a unix platform tag with no `ghcr.io/...` image (fourteen of
`unix`'s own fifteen cells add nothing over pypa's own base -- every one
but `mipsel` -- so they were never published at all) is mirrored straight
from `pinned_pypa_images.toml`'s matching cell instead of queried on GHCR.

Neither table is rewritten by CI. Record 0033: cibuildmp never builds one
of these images itself and never repoints its own pins on its own; a pin
moves in a reviewed PR, which is the entire reason the digests live in a
data file that diffs cleanly.

Edits are line-oriented rather than a TOML round-trip, on purpose. Both
files carry more explanation than data -- why a floor was chosen, which
claim was verified live and how -- and a `tomllib`-read/`tomli_w`-write
cycle would silently delete every word of it. Only the quoted value on a
matched key changes; everything else in the file is left byte for byte.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

RESOURCES = Path(__file__).resolve().parent.parent / "src" / "cibuildmp" / "resources"
PYPA_PINS = RESOURCES / "pinned_pypa_images.toml"
IMAGE_PINS = RESOURCES / "pinned_docker_images.toml"

QUAY_API = "https://quay.io/api/v1/repository/{repo}/tag/"
GHCR_TOKEN = "https://ghcr.io/token?scope=repository:{repo}:pull&service=ghcr.io"
GHCR_MANIFEST = "https://ghcr.io/v2/{repo}/manifests/{reference}"

# Both single manifests and manifest lists have to be acceptable here.
# cibuildmp publishes single-platform images by design (record 0043: an
# image is native to one target, and a manifest list would reintroduce
# exactly the host-dependent resolution that record removes), but pypa's
# own bases are asked for by the same code path and nothing should break
# if an upstream image ever grows a list.
MANIFEST_TYPES = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)


class UpdateError(RuntimeError):
    pass


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[bytes, dict]:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"{url} -> HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"{url} -> {exc.reason}") from exc


def quay_digest(repo: str) -> tuple[str, str | None]:
    """`:latest`'s digest for a quay.io repo, plus the dated tag sharing it.

    The dated tag is what upstream's own pins are annotated with
    (`# 2026.08.15-1`) and is the only human-readable handle on a
    particular manylinux build, so it is carried through rather than
    dropped -- a digest alone makes "is this newer than what we pin?"
    unanswerable without another API call.
    """
    body, _ = _get(QUAY_API.format(repo=repo) + "?onlyActiveTags=true&limit=100")
    tags = json.loads(body)["tags"]
    digests = {tag["name"]: tag.get("manifest_digest") for tag in tags}
    latest = digests.get("latest")
    if not latest:
        raise UpdateError(f"quay.io/{repo} has no active :latest tag")
    dated = next(
        (
            name
            for name, digest in digests.items()
            if digest == latest and name != "latest"
        ),
        None,
    )
    return latest, dated


def ghcr_digest(repo: str, reference: str = "latest") -> str:
    """The digest `<repo>:<reference>` resolves to on GHCR.

    Anonymous pull token first: cibuildmp's own packages are public
    (confirmed live when they were first published), and a maintainer
    running this should not need to be logged in to read a digest they
    are about to pin publicly anyway.
    """
    token_body, _ = _get(GHCR_TOKEN.format(repo=repo))
    token = json.loads(token_body).get("token")
    _, headers = _get(
        GHCR_MANIFEST.format(repo=repo, reference=reference),
        headers={"Authorization": f"Bearer {token}", "Accept": MANIFEST_TYPES},
    )
    digest = headers.get("Docker-Content-Digest") or headers.get(
        "docker-content-digest"
    )
    if not digest:
        raise UpdateError(f"ghcr.io/{repo}:{reference} returned no content digest")
    return digest


def _repo_of(reference: str) -> str:
    """`ghcr.io/owner/name@sha256:...` -> `owner/name`."""
    without_registry = reference.split("/", 1)[1]
    return re.split(r"[@:]", without_registry)[0]


def _replace_value(text: str, key: str, old: str, new: str, comment: str | None) -> str:
    """Rewrite one `key = "value"` line, preserving indentation and any
    trailing comment unless a new one is given."""
    if old == new and comment is None:
        return text
    pattern = re.compile(
        rf'^(\s*{re.escape(key)}\s*=\s*)"{re.escape(old)}"(.*)$', re.MULTILINE
    )
    return pattern.sub(
        lambda m: (
            f'{m.group(1)}"{new}"' + (f"  # {comment}" if comment else m.group(2))
        ),
        text,
        count=1,
    )


def update_pypa(*, check: bool) -> int:
    data = tomllib.loads(PYPA_PINS.read_text())
    text = PYPA_PINS.read_text()
    drift = 0
    for arch, floors in data.items():
        for floor, reference in floors.items():
            repo = _repo_of(reference)
            current = reference.split("@", 1)[1]
            latest, dated = quay_digest(repo)
            if latest == current:
                continue
            drift += 1
            print(f"  {arch}/{floor}: {current[:19]}... -> {latest[:19]}... ({dated})")
            if not check:
                text = _replace_value(
                    text, floor, reference, f"{repo_url(repo)}@{latest}", dated
                )
    if not check and drift:
        PYPA_PINS.write_text(text)
    return drift


def repo_url(repo: str) -> str:
    return f"quay.io/{repo}"


def _pypa_mirror(name: str, pypa: dict[str, dict[str, str]]) -> str | None:
    """`name`'s own `pinned_pypa_images.toml` cell, or `None` when `name`
    is not a unix platform tag pypa has an opinion about.

    `name` is `[image_group]`'s own flat key -- for a unix cell that is a
    real PEP 600/656 tag, `<floor>_<arch>`, split against pypa's own arch
    list rather than on a separator (both halves contain underscores).
    None of the six toolchain groups or `windows`/`webassembly`/
    `esp_idf_base` end in a pypa arch suffix, so this is also how they are
    told apart from a unix cell without a second, parallel list of names.
    """
    for arch, floors in pypa.items():
        suffix = f"_{arch}"
        if name.endswith(suffix) and name[: -len(suffix)] in floors:
            return floors[name[: -len(suffix)]]
    return None


def update_images(*, check: bool) -> int:
    data = tomllib.loads(IMAGE_PINS.read_text())
    text = IMAGE_PINS.read_text()
    pypa = tomllib.loads(PYPA_PINS.read_text())
    owner = _owner()
    drift = 0

    for name, reference in data.get("image_group", {}).items():
        pypa_reference = _pypa_mirror(name, pypa)
        # A cell whose current reference is not `ghcr.io/...` has no
        # cibuildmp-published image behind it at all: fourteen `unix`
        # cells (`armv7l`'s `manylinux_2_31`, `riscv64`'s `manylinux_2_39`,
        # every `musllinux_1_2` floor, and -- once `MICROPY_STANDALONE=1`
        # went universal and `libffi-devel` stopped being read -- every
        # `manylinux_2_28_*` floor too) were verified to be a bare `FROM`
        # and nothing else, so their own Dockerfile and GHCR package were
        # deleted rather than kept as an idle copy -- their pin here is
        # just `pinned_pypa_images.toml`'s own cell, mirrored. Asking GHCR
        # about a package that was never published would only ever print
        # "not published yet" for these fourteen, forever.
        if pypa_reference is not None and not reference.startswith("ghcr.io/"):
            if pypa_reference == reference:
                continue
            drift += 1
            print(f"  {name}: pinned_pypa_images.toml moved -- mirroring")
            if not check:
                text = _replace_value(text, name, reference, pypa_reference, None)
            continue

        # The repository is derived from the table's own key, not read
        # back out of whatever the cell currently points at. That matters
        # during a rename and not only in theory: record 0044 dropped the
        # `cibuildmp-` prefix, so the three cross-compiling cells still
        # held `ghcr.io/<owner>/cibuildmp-windows@...` while the package
        # that had just been published was `<owner>/windows`. Trusting the
        # old reference would have refreshed the digest of the image being
        # replaced -- a successful-looking no-op, which is the worst kind.
        repo = f"{owner}/{name}"
        current = reference.split("@", 1)[1] if reference else ""
        try:
            latest = ghcr_digest(repo)
        except UpdateError as exc:
            print(f"  {name}: not published yet ({exc})")
            continue
        if latest == current:
            continue
        drift += 1
        print(f"  {name}: {current[:19] or '(unpinned)'} -> {latest[:19]}...")
        if not check:
            text = _replace_value(
                text, name, reference, f"ghcr.io/{repo}@{latest}", None
            )
    if not check and drift:
        IMAGE_PINS.write_text(text)
    return drift


def _owner() -> str:
    """The GHCR owner cibuildmp publishes under, read from whatever is
    already pinned rather than hardcoded -- a fork that republishes under
    its own owner should be able to run this unchanged."""
    data = tomllib.loads(IMAGE_PINS.read_text())
    for reference in data.get("image_group", {}).values():
        if reference and reference.startswith("ghcr.io/"):
            return _repo_of(reference).split("/", 1)[0]
    raise UpdateError(
        "cannot infer the GHCR owner: no ghcr.io/ reference in [image_group] "
        "is pinned yet"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--pypa", action="store_true", help="upstream pypa bases only")
    parser.add_argument("--images", action="store_true", help="cibuildmp images only")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit non-zero, changing nothing",
    )
    args = parser.parse_args()
    both = not (args.pypa or args.images)

    drift = 0
    try:
        if args.pypa or both:
            print(f"{PYPA_PINS.name}:")
            drift += update_pypa(check=args.check)
        if args.images or both:
            print(f"{IMAGE_PINS.name}:")
            drift += update_images(check=args.check)
    except UpdateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not drift:
        print("everything already pinned to its current digest")
        return 0
    if args.check:
        print(f"{drift} pin(s) out of date")
        return 1
    print(f"{drift} pin(s) updated -- review the diff before committing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
