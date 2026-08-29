# 0034. M0 — skeleton

- Status: Implemented (done)
- Related: [0009]

<!-- migrated verbatim from docs/BACKLOG.md lines 573-606 -->

### M0 — skeleton — **done**

- [x] Real CLI in `src/cibuildmp/cli.py`: `cibuildmp [package_dir]
      [--config-file] [--output-dir] [--only ID] [--print-build-identifiers]
      [--json] [--platform]`.
- [x] Config loader in `src/cibuildmp/options.py`: `cibuildmp.toml` →
      `pyproject.toml [tool.cibuildmp]` fallback; `CIBMP_*` env layer;
      `[[overrides]]` resolution. Full precedence chain implemented and
      covered by tests.
- [x] Identifier generation + `build`/`skip` glob filtering in
      `src/cibuildmp/targets.py`, including the arch→`CROSS` table and the
      release-tag→ABI table (both transcribed from MicroPython source, see
      the toolchain map above).
- [x] `--print-build-identifiers`, with `--json` for `fromJSON`.
- [x] `action.yml` installs from `${{ github.action_path }}` per **D8**, so
      the running version is exactly the ref the caller pinned.
- [x] `--dry-run`, printing the resolved plan and exiting 0 — the M0
      success path, since building itself is not implemented.
- [x] `--print-build-matrix`, emitting `{only, os}` objects, and a
      `runs-on` option resolved through the same override chain as
      everything else (`Target.default_runner` supplies the default).
- [x] `.github/actions/cibuildmp-matrix` composite action, emitting those
      objects as an `include` output. **Optional by D9**, not the default
      path: it exists for per-target failure isolation now, and for usermod's
      genuinely different runners later. Carrying the runner in the matrix
      entry is also the answer to the "a composite action cannot pick its own
      `runs-on`" limitation `README.md` documents for `build-usermod-unix`.

`--print-build-identifiers` alone removes the duplicated matrix from all
three repos, which is why M0 shipped before any build logic exists. Running
`cibuildmp` without `--dry-run` currently prints the resolved build plan and
exits 1 — deliberately, so the action fails loudly rather than appearing to
succeed while building nothing.
