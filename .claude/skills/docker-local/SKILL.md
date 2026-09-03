---
name: docker-local
description: Get `docker build`/`docker run` actually working against this repo's own docker/*.Dockerfile files inside a Claude Code on the web / cloud container session — starting the daemon, and the specific network-proxy gotchas that make a build fail even once the daemon is up. Use before claiming a local Docker verification "doesn't work here". Does not apply to a real local machine (a developer's own laptop/desktop, or a self-hosted runner) — there is no such proxy there and Docker generally works unmodified.
---

# Running Docker in a Claude Code on the web / cloud container session

**Scope: this is about the ephemeral cloud container a Claude Code on the
web (claude.ai/code) session runs in — ballistics-lab/cibuildmp's own
managed remote execution environment — not a real machine.** Everything
below (the daemon not auto-starting, the allowlisted egress proxy, the
proxy's own TLS interception) is a property of that sandbox. A session
running on an actual local machine — a contributor's own laptop, or a
self-hosted CI runner — has none of this: Docker Desktop/`dockerd` is
already running, there is no `$HTTPS_PROXY`, and `docker build` behaves
the way its own documentation says. Check `$HTTPS_PROXY` and
`/root/.ccr/README.md`'s existence before assuming this skill applies;
don't "fix" a real machine's working Docker setup with anything here.

Written after a real *cloud-container* session hit every failure mode
below, one at a time, against this repo's own
`docker/ppc64le_linux.Dockerfile` and `docker/natmod_host.Dockerfile`. Do
not re-derive these from first principles — they were each verified live,
and re-guessing costs a session the way CLAUDE.md's own top rule warns
about for cibuildwheel.

## 1. The daemon is not running by default

`docker` (the CLI) is installed, but `dockerd` is not started. `docker
info` fails with `connect: no such file or directory` until you start it
yourself:

```bash
dockerd > /tmp/dockerd.log 2>&1 &
sleep 3
docker info   # should now show a Server: section
```

No special flags needed — this environment already runs as root and the
default `overlayfs` storage driver works. `podman` is not installed; don't
bother checking for it.

## 2. Outbound network is allowlisted, and it is enforced on the *daemon's*
   own pulls too

This session's HTTPS egress goes through a proxy (`$HTTPS_PROXY`,
`/root/.ccr/README.md`), and it only permits configured hosts. `dockerd`'s
own registry pulls go through it too — a `docker build` failing with

```
failed to resolve source metadata for docker.io/library/ubuntu:26.04:
... Forbidden
```

or the proxy status (`curl -sS "$HTTPS_PROXY/__agentproxy/status"`)
showing a `recentRelayFailures` entry with `"kind": "connect_rejected"` and
`"detail": "gateway answered 403 to CONNECT (policy denial...)"` means the
*host*, not Docker or the daemon, is the blocker. Ask whoever owns this
session's network policy to add it — do not try to work around it.

**The registry's API host and its blob/CDN storage host are frequently
different domains, and both are required.** This is the one gotcha that
actually cost time in the session that wrote this skill:

| Registry | API/manifest host (small requests) | Blob storage host (the actual layer bytes) |
|---|---|---|
| Docker Hub (`ubuntu:*` — 10 of this repo's 17 `docker/*.Dockerfile`) | `registry-1.docker.io`, `auth.docker.io` | `production.cloudfront.docker.com` (a `*.docker.com` subdomain — different domain from the `.docker.io` API host) |
| `quay.io` (pypa/manylinux bases) | `quay.io` | `cdn01.quay.io` (a `*.quay.io` subdomain — bare `quay.io` alone is not enough, confirmed live: manifest resolution passed, then the layer fetch failed `Forbidden` against `cdn01.quay.io` until `*.quay.io` was added) |
| `ghcr.io` (this repo's own published images, `pinned_docker_images.toml`) | `ghcr.io` | Azure Blob Storage (`*.blob.core.windows.net`) — worked immediately once that wildcard was present, no separate `ghcr.io`-specific CDN host needed |

Allow both the bare API host **and** the wildcard for its storage domain,
not just the bare registry name — `quay.io` without `*.quay.io` looks
allowed and still fails on the actual pull.

**Docker Hub anonymous pulls are rate-limited (429) on top of all this,**
and this session's egress IP is shared, so the limit can already be spent
by someone else's pulls: `unexpected status from HEAD request to
https://registry-1.docker.io/...: 429 Too Many Requests`, reproducible
seconds apart. Don't loop-retry it — that's diagnosis-by-hope, and the
window this shares across is out of this session's control. Treat a local
`FROM ubuntu:*` build as best-effort; `verify-docker-images.yml` (GitHub's
own runners, no such shared limit) is the authoritative check when local
Docker Hub pulls are stuck on this.

**Check reachability before attempting a build that needs a new host, and ask the user to add
whatever fails — don't guess, don't silently work around it, and don't declare the build
"impossible here" without having asked.** Before a `docker build`/`docker run` that touches a
host not already in section 5's table below, probe it directly first — plain `curl -sS -o
/dev/null -w '%{http_code}\n' https://<host>/<a-real-path>` (a real path, not just the bare
domain — some hosts 200 the root and still reject the actual resource path) is enough, cheaper
than a full build. A 403/`Forbidden` (or a `recentRelayFailures` "connect_rejected" entry in the
proxy status) means the host, not the Dockerfile or the network stack, is the blocker — tell the
user exactly which domain(s) are missing and ask them to add it, the same way this skill's own
table grew one incident at a time. Don't spend a session's budget rewriting a Dockerfile or
inventing a workaround (a mirror, a vendored copy, a different registry) to route around a host
that was simply never asked for.

**A host enabled for this session is not automatically enabled for Docker's own network path —
verify both, separately, before trusting either.** Confirmed live: after a user enabled
`almalinux.org`/`*.almalinux.org` mid-session, a plain `curl` from this session's own shell
reached `repo.almalinux.org` immediately (`HTTP 200`) — but the identical URL, requested from
*inside* a running container (`docker run ... curl ...`, CA already trusted per section 4), kept
returning `403` at the same moment. Two different enforcement points, not one — the session's own
tool-call egress and whatever `dockerd`/container network path routes through evidently don't
share a single allowlist state, or don't update it on the same schedule. **Never infer "it works
in Docker" from a host-level `curl` succeeding, and never infer "it's still blocked" from a
container-level 403 alone if the host just got enabled** — retest the container path directly
(a scratch `docker run` with the CA installed, per section 4) rather than assuming either result
carries over, and say so plainly if the two disagree rather than picking whichever answer is
convenient.

**When the container path is the one still blocked, `$HTTPS_PROXY/__agentproxy/status`'s own
`recentRelayFailures` can come back empty even though the 403 is real** — confirmed live in the
same incident: the container's `curl` returned a genuine `403`, and the very next status check
showed `"recentRelayFailures": []`, nothing recorded. That means the block is happening at a
layer *before* this agent-proxy's own relay logic even sees the request — some lower,
docker/daemon-specific network policy, not the same allowlist the status endpoint reports on.
Don't treat an empty `recentRelayFailures` as proof a container-level 403 isn't real or has
resolved; trust the container's own curl exit code over the status endpoint for this specific
path, and tell the user the container-level route needs its own fix, distinct from whatever they
just enabled at the session level.

**Confirmed a second time, a different host, and this time `recentRelayFailures` *did* record
it** — so the previous paragraph's "can come back empty" is a possibility to check for, not the
only shape this takes. After a user added `dl-cdn.alpinelinux.org` (investigating whether Alpine
carries `gcc-arm-none-eabi` with working C++ support, `docs/records/0085`'s own arm_embedded
question), the session's own `curl` reached it immediately (`200`), but `docker build`'s `apk
update` against the identical host kept failing — first `TLS: server certificate not trusted`
(section 4's own class, before the CA fix), then, once the CA was fixed, a bare `HTTP 403:
Forbidden` from `apk` itself. The status endpoint's `recentRelayFailures` this time did carry a
live entry naming it exactly:

```json
{"kind": "connect_rejected", "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)", "host": "dl-cdn.alpinelinux.org:443"}
```

So check the status endpoint when a container-level 403 shows up, but do not treat its absence as
clearance — both an empty list and a populated one have now been observed for a real, live block.
Either way the fix is the same: tell the user the container network path needs the host added
separately from whatever they just enabled at the session level, and wait for them to confirm
rather than guessing at a workaround.

**The block can outlive the session-level fix by more than a few seconds — re-verify with a live
request, not a status snapshot, before declaring it resolved.** Same `dl-cdn.alpinelinux.org`
incident, continued: minutes after `alpinelinux.org`/`*.alpinelinux.org` were both confirmed
present in the session's own allowed-hosts list, a container-level `wget` still got a clean `HTTP
403 Forbidden` (TLS trust already fixed per section 4, so this was the request itself being
refused, not a cert problem) — reproduced twice, a few minutes apart. One intermediate `wget`
attempt failed at the TLS-handshake stage before the CA fix had been applied *in that specific
container invocation*, which briefly looked like "the 403 is gone, now it's just cert trust" —
wrong: that run never reached the point where a 403 could show up at all, so it proved nothing
about whether the block had lifted. Re-ran with the CA fix actually in place and got 403 again,
immediately. **Don't infer resolution from one ambiguous data point** — confirm with a request
that both trusts the cert *and* reaches the application-layer response before concluding either
"still blocked" or "now fine".

## 3. Plain HTTP needs nothing from the allowlist at all — for `archive.ubuntu.com` specifically, not as a universal rule

`apt-get update`/`install` inside a `RUN` step reaches
`http://archive.ubuntu.com` and friends over plain HTTP and just works,
unconditionally, verified live inside a real pulled image with zero hosts
added for it. The proxy/allowlist machinery there is HTTPS-only for that
host; don't spend time adding apt mirror hosts to any allowlist for a
Ubuntu/Debian base, and don't assume an `apt-get` failure inside a
container is a network policy problem — look elsewhere first.

**Do not generalize this to "plain HTTP is always exempt" — confirmed live it is not, for
`dl-cdn.alpinelinux.org`.** `apk`'s repositories default to HTTPS; rewriting
`/etc/apk/repositories` to `http://` (the same trick that works for `archive.ubuntu.com`) still
got a hard `HTTP 403: Forbidden` from the proxy for this host, not a pass-through. Whether a given
host's plain-HTTP path is exempt is apparently a per-host policy choice on the proxy's own side,
not a blanket HTTPS-only rule — check live (`curl -sS -o /dev/null -w '%{http_code}\n'
http://<host>/<real-path>`) rather than assuming either answer from `archive.ubuntu.com`'s own
precedent.

## 4. HTTPS *inside* a `RUN` step fails on cert trust, not on network

## reachability — and the fix is two lines, not a Dockerfile redesign

This is the one that looks like "containers can't reach the network" and
is not that. A plain `curl https://github.com` inside a `RUN` step, even
against an already-allowed host, fails:

```
curl: (60) SSL certificate OpenSSL verify result: self-signed certificate
in certificate chain
```

The request *reaches* the proxy (it is doing TLS interception/re-signing,
same as it does for this session's own tool calls) — the container's
default trust store just doesn't carry the proxy's CA
(`/root/.ccr/ca-bundle.crt`). Confirmed live: installing it fixes the
identical `RUN` step against both `github.com` and
`toolchains.bootlin.com` with no other change.

```dockerfile
COPY ca-bundle.crt /usr/local/share/ca-certificates/agent-proxy.crt
RUN update-ca-certificates
```

**Do this in a scratch build, not in the committed `docker/*.Dockerfile`.**
None of this repo's real images should carry a step that only makes sense
inside this one sandboxed session — a real user's `docker build` has no
such proxy and no such CA to trust. To test a real Dockerfile change that
has its own `curl`/`RUN`-time HTTPS fetch (the Bootlin/xpack/emsdk/llvm-mingw
pattern several images already use):

```bash
cp /root/.ccr/ca-bundle.crt /tmp/dockertest-ctx/
# copy or symlink the Dockerfile in question into the same directory, then
# insert the two lines above right after its FROM line (sed, or a small
# throwaway copy) before running:
docker build -t local-test -f /tmp/dockertest-ctx/patched.Dockerfile /tmp/dockertest-ctx
```

Once the image builds clean this way, the CA-injection was only ever a
local-testing shim — nothing about the result implies the real Dockerfile
needs changing.

**Alpine needs a different two lines — `update-ca-certificates` is not there to run, and `apk add
ca-certificates` is the chicken-and-egg trap.** Confirmed live probing whether Alpine carries a
usable `gcc-arm-none-eabi` (a real question for `docs/records/0085`'s own arm_embedded
investigation, not a hypothetical): the section-4 recipe above assumes Ubuntu/Debian's shape
(`ca-certificates` package already present, `update-ca-certificates` merges a new cert into the
system bundle) — Alpine's `alpine:3.24.1` base has neither. It *does* already ship a static,
baked-in bundle at `/etc/ssl/certs/ca-certificates.crt` (no package install needed to have one at
all), so appending to that file directly is the whole fix, no tool to run afterward:

```dockerfile
COPY ca-bundle.crt /tmp/agent-proxy.crt
RUN cat /tmp/agent-proxy.crt >> /etc/ssl/certs/ca-certificates.crt
```

Reaching for `apk add --no-cache ca-certificates && update-ca-certificates` instead (the Alpine
equivalent someone would reasonably try first) fails before it can help:

```
WARNING: fetching https://dl-cdn.alpinelinux.org/.../APKINDEX.tar.gz: TLS: server certificate not trusted
ERROR: unable to select packages:
  ca-certificates (no such package):
    required by: world[ca-certificates]
```

`apk` itself needs the network to fetch the very package meant to make the network trusted —
`apk`'s own package index fetch is not exempt from the same TLS-interception problem section 4
describes, so the ordinary Debian/Ubuntu fix routes through the one thing that cannot succeed yet.
Appending directly to the file already on disk sidesteps the whole cycle.

## 5. Hosts this repo's own `docker/*.Dockerfile` files actually fetch from

Grepped directly (`grep -rhoE 'https?://[a-zA-Z0-9.-]+' docker/*.Dockerfile`),
not recalled — re-run that grep after editing any Dockerfile rather than
trusting this table if it might have drifted:

| Host | Used by |
|---|---|
| `toolchains.bootlin.com` | `manylinux_2_41_mipsel`, `ppc64le_linux` |
| `github.com` (+ its release-asset redirect, `*.githubusercontent.com`) | `arm_embedded`/`riscv_embedded` (xpack), `xtensa_esp` (Espressif crosstool-NG), `windows` (llvm-mingw, `arm64` frontend) |
| `micropython.org` | `xtensa_lx106` |
| `storage.googleapis.com` | `webassembly` (pinned emsdk tarball) |
| `quay.io` (+ `*.quay.io`) | every `manylinux_2_28_*` and `pypa-tracker` base |
| `docker.io`/`docker.com` (+ wildcards) | every `ubuntu:26.04`-based image (10 of 17) |
| `ghcr.io` (+ `*.blob.core.windows.net`) | this repo's own published images, `resources/pinned_docker_images.toml` |

## 6. Running a real cibuildmp build against a locally-built image

Once an image builds, point `cibuildmp` at the local tag instead of the
pinned digest — this is what actually proves a Dockerfile change (a real
link/build through it), not just that `docker build` exits 0:

```bash
docker build -t local-ppc64le_linux -f docker/ppc64le_linux.Dockerfile .
CIBMP_QEMU_POWERNV9_DOCKER_IMAGE=local-ppc64le_linux \
  cibuildmp examples/template --build v1.29.0-qemu-POWERNV9
```

The env var name is `CIBMP_<GROUP>_DOCKER_IMAGE` uppercased
(`dockerrun.image_for()` checks it before ever consulting
`pinned_docker_images.toml`) — for a `usermod` port keyed by board rather
than by group directly (`qemu`), it's `CIBMP_QEMU_<BOARD>_DOCKER_IMAGE`,
confirmed against `build_qemu.py`'s own error message
(`no image registered for qemu board ... -- see ... or point
CIBMP_QEMU_<BOARD>_DOCKER_IMAGE at a local tag`).

This whole recipe (daemon start, allowlist, CA-patched scratch build, env
override) is not theoretical — it is exactly how `docs/records/0068`'s
own fourth addendum closed out `ppc64le_linux`'s Bootlin-toolchain
verification: a real `ports/qemu` build, `shared/readline/readline.c`
included (the file whose link originally broke), produced a genuine
`firmware-v1.29.0-qemu-POWERNV9.elf` this way, no CI needed.
