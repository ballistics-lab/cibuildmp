# 0038. M5 — adopt in the three repos

- Status: In progress (two items still open)
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
- [ ] Archive `ballistics-lab/micropython-native-ci` once all three have
      repinned.
- [ ] Reduce `build-natmod` to a wrapper over `cibuildmp --only <id>` so
      there is one implementation of the toolchain logic, not two. Do not let
      the two coexist for long.
