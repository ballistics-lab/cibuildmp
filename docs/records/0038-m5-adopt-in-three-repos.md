# 0038. M5 — adopt in the three repos

- Status: Implemented
- Related: [0011]

<!-- migrated verbatim from docs/BACKLOG.md lines 813-843 -->

### M5 — adopt in the three repos

- [x] The same three repos: replace the natmod matrix with `cibuildmp`.
      a7p was the interesting one, exactly as anticipated — non-default
      `module-dir` (`micropython/natmod`) and a `pre-build-command`
      (`test -f nanopb/pb.h || make fetch-nanopb`, guarding against a
      re-fetch on every arch since `cibuildmp`'s own D9 runs one job
      sequentially through all of them). All three (`micropython-bclibc`,
      `a7p`, `micropython-wasm3`) verified green on real CI, arch by arch —
      not `--dry-run`. Surfaced two real, previously-unknown bugs along the
      way, one per repo: a stale-facade-collision in `a7p`'s and
      `micropython-wasm3`'s own `dist:` targets (same shape as the one
      already fixed in `micropython-bclibc`'s own Makefile under M3), and
      `micropython-wasm3`'s `dist:` never cleaning up
      `$(BUILD)/$(MOD).native.mpy`, which made `cibuildmp`'s own
      `collect_output()` correctly refuse an ambiguous two-`.mpy` result
      instead of silently picking one. Neither is a `cibuildmp` bug; both
      are now fixed in their own repos' Makefiles.
- [x] `micropython-bclibc`, `a7p`, `micropython-wasm3`: repinned every
      `uses:` path from the interim `cibuildmp@<commit-sha>` pin (used
      while no tag existed past `v0.3.0a1`) to `cibuildmp@v0.3.0`
      (**D11**), now that it's cut — mechanical, no behaviour change.
      Not yet pushed/re-verified against the tag at the time of this
      note; the SHA it points to is the same commit already confirmed
      green in all three repos' CI.
- [x] Archive `ballistics-lab/micropython-native-ci` once all three have
      repinned.
- [ ] ~~Reduce `build-natmod` to a wrapper over `cibuildmp --only <id>` so
      there is one implementation of the toolchain logic, not two.~~
      Rejected 2026-08-30 — see addendum below.

---

## Addendum, 2026-08-28 — the archive item is closed; the wrapper item got worse

Verified rather than assumed, since both open items above were written months of
sessions ago and one of them had quietly become true.

**`ballistics-lab/micropython-native-ci` is archived** — `archived: true` from the
API, last touched 2026-08-24. Its precondition ("once all three have repinned") was
met at the same time: every one of the three repos' `origin/main` carries only
`ballistics-lab/cibuildmp@v0.3.0` references and not one `uses:` of
`micropython-native-ci`. `micropython-bclibc` 13, `micropython-wasm3` 15, `a7p` its
own set; a7p's single remaining textual mention is a comment explaining the move.
(Worth recording that a stale local checkout of `micropython-bclibc` showed the
opposite — `main` one commit behind `Ci/cibuildmp (#17)` — which is exactly the shape
of a false "this was never done" conclusion.)

**The `build-natmod` wrapper item is still open, and the reason to do it is stronger
than when it was written.** The action moved into this repo with [0011] and is now
`.github/actions/build-natmod/action.yml`: 133 lines that do not mention `cibuildmp`
once, carrying their own per-`ARCH` apt package list, their own xtensa toolchain
install, their own esp-idf install, and a bare `make ARCH=<arch> dist`.

The original argument was "one implementation of the toolchain logic, not two". That
argument has since inverted: [0050] deleted cibuildmp's bare-host toolchain path
entirely and made natmod Docker-only, so this action is no longer the *second*
implementation of something — it is the *only* remaining bare-host natmod toolchain
implementation in the project, and nothing tests, pins or updates it. The four
toolchain tarballs it would have shared with cibuildmp now live in
`docker/natmod.Dockerfile` and are themselves unwatched ([0046]).

Also still open, and unchanged: the repin itself. All three repos pin `v0.3.0`, and
HEAD has since renamed every `unix` identifier ([0044]), deleted `--toolchain` and
`--print-build-matrix` ([0049]/[0050]), and made natmod require Docker. With [0044]'s
own row closed on 2026-08-28 there is nothing left to wait for, and every further
commit on HEAD widens the single migration these repos should have to do once.

[0011]: 0011-one-repo-absorbs-micropython-native-ci.md
[0044]: 0044-unix-native-images-landed.md
[0046]: 0046-pin-staleness-checker.md
[0049]: 0049-no-matrix-generation-archs-vocabulary.md
[0050]: 0050-natmod-is-docker-only.md

---

## Addendum, 2026-08-30 — the repin is done, and `micropython-bclibc` is green

Verified live rather than assumed, prompted by a tracker row (below) that still read
"`micropython-bclibc` pushed, awaiting its first CI run" — stale by the time it was
checked. All three repos' current `origin/main` HEAD:

- `ballistics-lab/micropython-bclibc` @ `a865480` (`ci/cibuildmp (#18)`) — 31/31 check
  runs green, natmod and usermod both, `unix-mipsel, static` included.
- `o-murphy/micropython-wasm3` @ `beecf67` (`ci/cibuildmp (#6)`) — 32/32 green.
- `o-murphy/a7p` @ `110d571` (`use cibuildmp for ci cross build (#86)`) — 29/29 green.

All three also carry `uses: ballistics-lab/cibuildmp@v0.4.0` throughout (grepped their
workflow files directly), not the `v0.3.0` the 2026-08-28 addendum flagged as stale —
the repin item above is done too, not just the archive.

Only real open item left: the `build-natmod` wrapper, unchanged from the 2026-08-28
addendum.

## Addendum, 2026-08-30 — the `build-natmod` wrapper item is rejected

Rejected by explicit user call: the action stays as its own bare-host natmod
toolchain implementation, not folded into a `cibuildmp --build "<glob>"` wrapper.
With that, this record has no open items left; status above moves to
`Implemented`.

## Addendum, 2026-08-31 — this record is the only place consuming-repo status lives

`README.md`, `docs/ACTIONS.md` and `docs/reference/design.md` all used to answer
"which repo still calls the legacy composite actions" themselves, and all of them
got it wrong from one bad tracker note copied five times ([0076], [0077]). They
point here now, so it has to be *here*, dated, with the method.

**Checked 2026-08-31 against each repo's own default branch, by reading the
workflow files:**

| repo | composite actions on `main` |
| --- | --- |
| `o-murphy/a7p` | none — fully on the CLI |
| `ballistics-lab/micropython-bclibc` | 4 (`fetch-micropython` ×3, `build-usermod-unix` for `unix-mipsel`) |
| `o-murphy/micropython-wasm3` | 6 (`fetch-micropython` ×5, `build-usermod-unix` for `unix-mipsel`) |

Migrations off the remaining two are written and pushed to a `bump-cibuildmp`
branch in each, **unmerged and never run in their own CI**. The action pin those
repos carry is a separate question from this repo's own released version — do not
infer one from the other; grep their workflows.

Anything below this line about pins or migration state is that date's answer, not
today's. This table is what a living document is allowed to point at; nothing in
this repository can verify it, which is the whole reason it is dated.

