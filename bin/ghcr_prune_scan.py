#!/usr/bin/env python3
"""Scan ballistics-lab's GHCR container packages and print only the
package versions that are safe to delete: not tagged, and not referenced
as a child manifest (platform image or buildx attestation) inside any
currently-tagged index. Prints gh api DELETE commands; runs nothing."""

import json
import subprocess
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
    out = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


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
        if tags:
            print(f"  KEEP (tagged {tags}): {digest}")
        elif digest in referenced:
            print(f"  KEEP (referenced):    {digest}")
        else:
            print(
                f"  DELETE-SAFE: gh api --method DELETE "
                f"{base}/packages/container/{name}/versions/{v['id']}  # {digest}"
            )
