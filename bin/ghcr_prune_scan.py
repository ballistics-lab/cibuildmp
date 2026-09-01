#!/usr/bin/env python3
"""Scan ballistics-lab's GHCR container packages and print only the
package versions that are safe to delete. Prints gh api DELETE commands;
runs nothing.

A version is safe only if it is none of these three:

1. **Tagged.** Includes the `pre-<digest12>` tags
   `publish-docker-images.yml` leaves behind so the digest a pin still
   names keeps a tag of its own (record 0059).
2. **Referenced** as a child manifest -- a platform image or a buildx
   attestation -- inside any currently-tagged index. This is the one
   GHCR's own "delete untagged versions" cleanup gets wrong, and it
   deleted seven of fifteen published images once (record 0059).
3. **Named by a pin in any released version of cibuildmp**, read from
   `pinned_docker_images.toml` at every `v*` git tag plus the working
   tree. Deleting one of these breaks builds for everyone on that
   release, and rule 1 only protects them by luck: they are safe today
   because they happen to still carry a tag, which is not a property
   anything maintains on purpose.
"""

import json
import pathlib
import subprocess
import tomllib
import urllib.error
import urllib.request

ORG = "ballistics-lab"
ACCEPT = ",".join(  # noqa: FLY002
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


def gh_json(path):
    # `--paginate` because a `per_page` cap silently *hides* versions
    # rather than erroring, and a hidden **tagged** index is the dangerous
    # case: its children never make it into `referenced`, so they get
    # reported as safe to delete. No package is near the cap today (22 is
    # the largest); this is here so that staying under it is not a thing
    # anyone has to keep checking.
    out = subprocess.run(
        ["gh", "api", "--paginate", path], capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


def pinned_digests():
    """`(package, digest)` for every `ghcr.io/...` pin in every released
    version's own pin file, plus the working tree's."""
    tags = subprocess.run(
        ["git", "tag", "--list", "v*"], capture_output=True, text=True, check=True
    ).stdout.split()
    pins = {}
    for ref in [*tags, None]:
        path = "src/cibuildmp/resources/pinned_docker_images.toml"
        if ref is None:
            blob = pathlib.Path(path).read_text(encoding="utf-8")
        else:
            done = subprocess.run(
                ["git", "show", f"{ref}:{path}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if done.returncode:  # released before this file existed
                continue
            blob = done.stdout
        for reference in tomllib.loads(blob).get("image_group", {}).values():
            if reference.startswith("ghcr.io/") and "@" in reference:
                package, digest = reference.rsplit("@", 1)
                pins.setdefault((package.rsplit("/", 1)[-1], digest), set()).add(
                    ref or "working tree"
                )
    return pins


def ghcr_manifest(pkg, ref):
    token_url = f"https://ghcr.io/token?scope=repository:{ORG}/{pkg}:pull"
    token = json.loads(urllib.request.urlopen(token_url).read()).get("token", "")
    req = urllib.request.Request(
        f"https://ghcr.io/v2/{ORG}/{pkg}/manifests/{ref}",
        headers={"Authorization": f"Bearer {token}", "Accept": ACCEPT},
    )
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError:
        return None


owner_type = gh_json(f"repos/{ORG}/cibuildmp")["owner"]["type"]
base = f"orgs/{ORG}" if owner_type == "Organization" else f"users/{ORG}"

packages = gh_json(f"{base}/packages?package_type=container&per_page=100")
pins = pinned_digests()
safe = 0

for pkg in packages:
    name = pkg["name"]
    print(f"=== {name} ===")
    versions = gh_json(f"{base}/packages/container/{name}/versions?per_page=100")

    referenced = set()
    for v in versions:
        for tag in v.get("metadata", {}).get("container", {}).get("tags", []):
            manifest = ghcr_manifest(name, tag)
            if manifest:
                for m in manifest.get("manifests", []):
                    referenced.add(m["digest"])

    for v in versions:
        digest = v["name"]
        tags = v.get("metadata", {}).get("container", {}).get("tags", [])
        pinned_by = pins.get((name, digest))
        if tags:
            print(f"  KEEP (tagged {tags}): {digest}")
        elif digest in referenced:
            print(f"  KEEP (referenced):    {digest}")
        elif pinned_by:
            print(f"  KEEP (pinned by {','.join(sorted(pinned_by))}): {digest}")
        else:
            safe += 1
            print(
                f"  DELETE-SAFE: gh api --method DELETE "
                f"{base}/packages/container/{name}/versions/{v['id']}  # {digest}"
            )

print(f"\n{safe} version(s) safe to delete")
