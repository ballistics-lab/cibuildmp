# 0059 — GHCR's "untagged version" cleanup deletes referenced multi-arch/attestation children

Status: Accepted (incident record — a mechanism to avoid, not a design decision)
Related: [0046], [0058]

## What happened

While publishing [0058]'s seven new toolchain images, `build-examples.yml` started failing
with `docker: manifest unknown` pulling `ghcr.io/ballistics-lab/manylinux_2_28_x86_64` at its
existing, unchanged pinned digest — a pin no commit this session had touched. Direct
`ghcr.io/v2/<repo>/manifests/<digest>` requests (anonymous pull token, no `gh`/Docker needed)
showed why: the digest resolves to an `application/vnd.oci.image.index.v1+json` **index**
(`docker/build-push-action`'s own output, which always publishes an index even for one
platform), and the index itself still returned `200 OK` — but every manifest it lists as a
child returned `404`. Not "one child missing", either: for three of the seven images hit
(`manylinux_2_39_mipsel`, `windows`, `webassembly`), **both** children 404'd — the real
per-platform manifest *and* the attestation-manifest buildx also attaches. The tag survived;
the content behind it did not.

Confirmed, not assumed: the same commit had never touched these pins, `bin/update_docker.py`
had never re-run against them, and republishing each broken image through
`publish-docker-images.yml` produced a **genuinely different** digest every time — proof the
prior one was truly gone, not a registry read glitch. Seven of the fifteen
`ghcr.io/ballistics-lab/...` images were hit across the session, discovered one push at a time
because each `build-examples.yml` run only exercises the specific images its own matrix
touches: `manylinux_2_28_x86_64`, `_aarch64`, `_i686`, `_ppc64le` (unix), then
`manylinux_2_39_mipsel`, `windows`, `webassembly` (the three amd64 cross-compile hosts).
`manylinux_2_28_s390x` and the seven brand-new toolchain-group images were checked the same
way and found intact.

## Root cause

An OCI index's child manifests carry no tag of their own — only the parent index does. GHCR's
package UI lists every manifest as its own "version," so a buildx multi-platform/attestation
child shows up there looking exactly like a disposable "untagged" artifact, indistinguishable
in the UI from genuine garbage (an old superseded digest with nothing pointing at it at all).
A cleanup pass — manual, in the UI, or an automated "delete untagged versions" action — that
removes anything without a tag, without first checking whether some other version's manifest
*references* it, deletes live content out from under a pin that was never touched and never
needed to change. The tag (and the index it points at) survives untouched, which is exactly
why this reads as "the pin broke" rather than "something got deleted": nothing about the
pinned reference itself is wrong.

## The check, and the fix

`GET https://ghcr.io/token?scope=repository:<owner>/<repo>:pull` (anonymous, no credentials)
gets a pull token for any public package; `GET
https://ghcr.io/v2/<owner>/<repo>/manifests/<digest>` with that token, `Accept:
application/vnd.oci.image.index.v1+json`, returns the index and its `manifests[].digest`
list. Checking each of those child digests the same way (`Accept:
application/vnd.oci.image.manifest.v1+json`) is the whole test: `200` on every child means the
pin is genuinely fine; any `404` means it needs republishing regardless of what the index
itself says. This is cheap enough to run as a sweep across every `image_group` entry at once,
which is how the three-image second wave (`mipsel`/`windows`/`webassembly`) was found in one
pass instead of one push at a time like the first four.

The fix is always the same and was applied seven times this session: republish via
`publish-docker-images.yml` (this session used the branch's own temporary `on.push.branches`
addition, since `workflow_dispatch` wasn't invokable from this session — see [0058]'s own
publish workflow for that mechanism), confirm the *new* digest's children resolve with the
same direct check before pinning, then `bin/update_docker.py --images` and commit.

## What this decides

**Never run "delete untagged versions" cleanup — manual or automated — against a container
package published by `docker/build-push-action` with multi-platform or attestation output.**
Every one of this project's images is exactly that shape. There is no cheap, correct filter
in GHCR's own UI for "untagged AND unreferenced" — only "untagged," which is not the same
question. Given these are public packages with no storage cost, the right default is to leave
them alone entirely; a maintainer who insists on pruning needs a script that walks every
currently tagged manifest's own children and excludes them first (one exists,
session-local, handed to a maintainer directly rather than committed here since it is a
one-off audit tool, not something cibuildmp runs).

This is a different failure from [0046]'s subject. [0046] is about a pin nobody notices has
gone *stale* — the reference is still valid, just old. This is a pin that was never stale at
all, valid the day it was written, whose *target* was deleted out from under it later by an
unrelated action. A staleness checker would not have caught this — the digest was exactly
what the last real publish produced — and there is no staleness *to* notice; only pulling
the actual bytes (or checking the child manifests directly, as above) surfaces it. Worth its
own record for that reason: the mitigation is a process rule ("don't run this class of
cleanup"), not a script to add to [0046]'s own inventory.

## Not decided here

- Whether to add an automated, scheduled version of the direct-manifest-check sweep (a
  "verify every pin's children still resolve" job), the way [0046] wants for staleness. Would
  have caught this within a week instead of via a build failure; not built.
- Whether GHCR's package settings offer a retention policy expressive enough to exclude
  manifest-list/index children automatically (some registries do). Not investigated —
  the operating rule above ("don't run untagged cleanup on these packages at all") makes it
  moot unless a maintainer wants automation later.

[0046]: 0046-pin-staleness-checker.md
[0058]: 0058-image-groups-are-toolchains-not-ports.md
