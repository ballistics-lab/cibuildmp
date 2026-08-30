# 0068 — docker Dependabot grouping, and what the first grouped bump exposed

Status: Accepted (incident record — a mechanism fixed, a gap it exposed, not a new design)
Related: [0046], [0059]

## What was wrong

`.github/dependabot.yml`'s `github-actions` entry has always grouped every update into one PR
(`groups: github-actions: patterns: ["*"]`, added specifically so `directories:`'s own
per-directory fan-out didn't reopen the one-PR-per-dependency problem the old five-entry file
had). The `docker` entry never got the same treatment — no `groups:` block at all. Six of the
Dockerfiles under `docker/` pin a real digest under a differently-named `quay.io/pypa/...`
image (five `manylinux_2_28_*` arches plus `pypa-tracker.Dockerfile`), so to Dependabot each is
a distinct dependency: a single upstream pypa republish opened up to six separate PRs instead
of one. Fixed by adding the same catch-all `groups: docker-images: patterns: ["*"]` the
`github-actions` entry already had.

## What the first grouped bump did instead

The fix worked exactly as intended — PR #16 ("bump the docker-images group in /docker with 15
updates") landed nine routine `quay.io/pypa/...@sha256:...` digest bumps and `ubuntu:24.04` →
`ubuntu:26.04` in one PR, across ten `docker/*.Dockerfile` files. That grouping is also what
made the PR dangerous to merge blindly: the ten `ubuntu:26.04` files and the nine pypa digest
bumps carry completely different risk profiles, and a single PR gives no way to accept one
without the other through Dependabot's own UI (one branch, one commit).

`docker/manylinux_2_39_mipsel.Dockerfile`'s own `verify-docker-images` CI leg caught the real
break: `ubuntu:26.04`'s apt archive has no `gcc-mipsel-linux-gnu`/`libc6-dev-mipsel-cross`
package at all —

```
E: Package 'gcc-mipsel-linux-gnu' has no installation candidate
E: Unable to locate package libc6-dev-mipsel-cross
```

— not a version mismatch (the Dockerfile already pins `libc6-dev-mipsel-cross=2.39-*`
deliberately, exactly so an Ubuntu bump that moves the glibc-cross line fails loudly rather
than silently drifting past what the `manylinux_2_39_mipsel` tag claims), but the package
itself gone from the archive. Root cause, confirmed against Debian's own bug tracker: Debian 13
"Trixie" (released August 2025) is the first release with no `mipsel` port at all —
[Debian bug #1043114](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1043114) cites the
32-bit 2GB user-space limit, the unresolved Y2038 problem (which needs a near-total
architecture rebootstrap), and insufficient porter manpower. Ubuntu's own
`gcc-*-cross-mipsen` packages are built from that same Debian source, so once Ubuntu's archive
moved past Trixie's cutover, the cross-toolchain packages had nothing upstream to build from.
`mips64el` followed the same path out of Debian unstable/experimental in November 2025.

The other nine `ubuntu:26.04` bumps in the PR built cleanly through `verify-docker-images`
(`esp_idf_base`, `webassembly`, `windows` confirmed green; the rest still running when this was
written) — this is not a blanket "ubuntu:26.04 is broken" finding, only a `mipsel`-specific one.

## What this decides

**The docker Dependabot group stays one group** (matching `github-actions`'s own shape) for
routine same-name digest bumps — that half of the fix is right and stays. **A major-version
bump of a floating tag (`ubuntu:24.04` → `26.04`) needs a human decision before merge, every
time**, the same way [0033] already requires a reviewed PR before a pypa base repoints rather
than trusting Dependabot's own judgment. Two ways to get there, not chosen yet (see below):
Dependabot's own `ignore` directive on `ubuntu`'s major version, or a second `docker` entry
scoped to `docker/manylinux_2_39_mipsel.Dockerfile` alone so it never shares a PR — and,
independently of Dependabot's own config, splitting `.github/dependabot.yml`'s single
`docker-images` group into a `pypa-digests` group (safe to merge routinely) and a
`base-os-major-bumps` group (always reviewed) would keep the one-PR benefit for the routine
half without re-bundling it with the risky half.

**`manylinux_2_39_mipsel`'s apt-based cross-toolchain is now a standing liability, not a
one-time incident.** It is the one `unix` image that never adopted the pinned-tarball model
[0025]'s own embedded Dockerfiles (`arm_embedded`, `riscv_embedded`, `xtensa_esp`,
`xtensa_lx106`) already use — every one of those pins a toolchain by version + URL + sha256,
independent of whatever the base OS's package archive currently carries. `mipsel`'s reliance on
`apt install gcc-mipsel-linux-gnu` ties its buildability to an upstream (Debian/Ubuntu) that
has explicitly abandoned the architecture; the same failure would resurface on the next Ubuntu
LTS bump regardless of Dependabot, and eventually on a security-only apt mirror pruning old
packages even without a base bump at all. A pinned-tarball cross-toolchain (e.g. one of
Bootlin's `mips32el--glibc--stable-*` releases, the shape a sibling project's own
`Dockerfile.bin` already uses for the same architecture) would decouple this image from
Ubuntu's archive the same way the embedded images already are — at the cost of picking a
specific Bootlin release and re-deriving what glibc floor it actually provides, since
`manylinux_2_39_mipsel`'s own `2_39` is a claim about the *current* apt package's version, not
something a different toolchain vendor is guaranteed to match.

## Not decided here

- Whether to actually move `manylinux_2_39_mipsel` onto a pinned tarball toolchain, and if so
  which release and what floor it claims. A real design decision (new toolchain, likely a new
  or renamed identifier), not a docs fix.
- PR #16 itself — still open as of this record, not merged, not closed.

**Addendum, 2026-08-30.** The group split is implemented: `docker-images`' own `patterns: ["*"]`
gained `exclude-patterns: ["ubuntu"]`, so `ubuntu` gets its own PR (still one, since every
Dockerfile referencing it collapses onto that one dependency name already) and never shares a
PR with a pypa digest bump again. Chosen over a second `dependabot.yml` entry or an `ignore`
directive: `exclude-patterns` keeps the fix inside the one group block that already explains
itself, and — unlike `ignore` — still lets Dependabot open the (now-isolated) `ubuntu` PR for a
human to look at, rather than silently never proposing the bump at all.

Two more things this incident's own CI runs surfaced, fixed alongside since they're the same
"a Dependabot PR pays for CI it gets nothing from" shape: `publish.yml`'s `deploy` job ran its
own `checkout` on every `pull_request` even though every real step behind it was already gated
to `push`/`workflow_dispatch` — confirmed live doing nothing useful and once flaking red on this
repo's own PR #17 for exactly that reason; now `if: github.event_name != 'pull_request'`, so it
doesn't run there at all. `test-all-platforms.yml`'s `paths-ignore` excludes `**.md`/`docs/**`/
`LICENSE` but not `docker/**` or `.github/dependabot.yml`, so any Dependabot docker PR (or a
docs PR that happens to also touch `dependabot.yml`, as this record's own PR did) fired the full
200+-identifier matrix for a change `verify-docker-images.yml` already covers; `plan` and
`aggregate-results` both gained `if: github.actor != 'dependabot[bot]'` (the latter alongside its
existing `always()`, so a skipped `plan` doesn't leave it aggregating zero buckets).

## Why this belongs next to [0046]

[0046] ("nothing notices when a pin goes stale, except container images") already named
Dependabot as the mechanism that watches `docker/`'s own `FROM` lines, with `bin/update_docker.py`
covering the two pypa/GHCR pin tables it does *not* reach. This incident is a live demonstration
of exactly the gap [0046] describes as still open — a pin (here, the base OS tag, not one of
the two tables [0046] inventories) went stale in a way nothing caught until a scheduled
Dependabot bump forced the question, and the checker workflow's own `--check` mode still runs
on no schedule at all (confirmed this session: `grep -rn "cron:" .github/workflows/*.yml` finds
exactly one cron in the whole repo, unrelated to any of this). [0046]'s own tracker row is
updated to point here as the concrete proof this is not hypothetical.

[0046]: 0046-pin-staleness-checker.md
[0059]: 0059-ghcr-untagged-cleanup-deletes-referenced-manifests.md
