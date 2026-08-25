# 0037. M3 — the build itself

- Status: Implemented (done)
- Related: [0014], [0015]; folds in what would have been a separate "M4" (publish)

<!-- migrated verbatim from docs/BACKLOG.md lines 726-812 -->

### M3 — the build itself — **done**

`src/cibuildmp/build.py`. Checked against cibuildwheel's own
`platforms/linux.py` rather than assumed: it is fail-fast per identifier too
(a `subprocess.CalledProcessError` from one platform config aborts the whole
invocation, no per-target continue-and-report), and its
`BuildProducedNoWheelError`/`RepairStepProducedMultipleWheelsError` are the
shape `collect_output()`/`verify_output()` copy.

- [x] Run `pre-build-command` in `module-dir` (`shell=True`, matching what
      `build-natmod`'s own `pre_build_command` input already does).
- [x] Invoke `make -C <module-dir> ARCH=<arch> MPY_DIR=<…>
      PYTHON=<sys.executable> <extra-make-args> <make-target>` — `mpy_ld.py`
      resolves `pyelftools`/`ar` from `cibuildmp`'s own dependencies
      (**D12**), verified for real against a live `make dist` run, not just
      by inspection.
- [x] Collect the produced `.mpy` into `output-dir/<identifier>/`
      (**D14**), named unambiguously within it too —
      `<module-stem>-<identifier>.mpy`, found by globbing
      `<module-dir>/build/<arch>*/*.mpy` — the layout `build-natmod`'s own
      artifact-upload step already assumes. Zero or more-than-one match is a
      `BuildError` naming what was found, cibuildwheel's
      `BuildProducedNoWheelError`/`RepairStepProducedMultipleWheelsError`
      shape. Cross-target collisions are structural, not a runtime check:
      distinct `Target`s (keyed on abi/mode/arch/tag/arch_flags) always
      produce distinct identifiers and therefore distinct directories, so
      there is no `AlreadyBuiltWheelError`-equivalent to run.
- [x] Verify each output's header arch against the requested identifier and
      fail loudly on mismatch — `cibuildmp`'s equivalent of `auditwheel`.
      `native-code` was added to `resources/natmod.toml`'s `[arch]` table
      (the `MP_NATIVE_ARCH_*` values `tools/mpy_ld.py` bakes into byte 2 of
      every native `.mpy`'s header, bits 2-5) so this reads the same pinned
      table the CROSS/toolchain resolution already does.
- [x] Readable per-target logging and a summary table, in `cli.build()`:
      each target prints its plan line and a `done in Ns` line as it
      finishes; a full run ends with a total duration and one line per
      built `.mpy` (identifier, filename, size) — cibuildwheel's
      `BuildInfo`/`print_summary` shape, minus the `humanize`/SHA256 parts
      that would cost a dependency for no real natmod need.

**Two bugs only a real end-to-end run against `examples/template` caught**
(both unit-tested in isolation, neither exercised the real failure mode):

- `run_make()` passed `-C <module-dir>` in the command *and*
  `cwd=<module-dir>` to `subprocess.run` — harmless when `module-dir` is
  absolute, broken when relative (the common case: `package_dir` defaults
  to `.`), since the process chdirs there and `-C` then looks for
  `<module-dir>` nested inside itself. Fixed by dropping `cwd=`; `-C`
  alone is sufficient and was already the right layer for it.
- `dynruntime.mk` defaults `BUILD ?= build`, not scoped by `$(ARCH)`. That
  is invisible to `build-natmod` (one job, one checkout, one arch each),
  but `cibuildmp` with no `--only` runs every target sequentially in the
  same `natmod/` tree (**D9**) — a second `ARCH=` finds the first arch's
  own object files "up to date" and skips rebuilding, so the merged
  `.mpy` silently stays the first arch's binary. Not a `cibuildmp` bug to
  fix in code (it is the consuming project's Makefile that owns this),
  but real enough that it needed becoming a documented requirement:
  `examples/template/natmod/Makefile` sets `BUILD = .obj/$(ARCH)` (kept
  outside `build/` so it cannot collide with the `dist` output
  `collect_output()` globs for), and README.md's "Conventions this repo
  assumes" now says so. `cibuildmp` still fails loudly instead of
  shipping the wrong arch either way — that is what the header
  verification above is for — this just avoids paying for the failed
  build at all.

**Publish, folded in (D14, D15) — this used to be a separate "M4":**

- [x] `package_target()` writes each identifier's own `package.json`
      (today's plain two-element `urls` schema, not the deferred
      compat-tag one) and copies `[publish] extra-files` into that same
      directory, gated on `version` being set — empty (the default)
      means an identifier's directory holds only its `.mpy`.
- [x] `arch-flags` (`rv32imc` only) resolved before target selection,
      folded into that arch's identifier as `+0x..`, and passed through to
      `make` as `ARCH_FLAGS=` — **D15**.
- [x] `verify_output()` also checks arch_flags, exact match. Fixed a
      latent header-decoding bug in the process: arch-code extraction was
      an unmasked `header[2] >> 2`; `py/persistentcode.h`'s own
      `MPY_FEATURE_DECODE_ARCH` masks with `0x2F` after the shift to
      exclude the arch-flags marker bit. Never triggered before D15 (no
      arch used the marker bit until now).
- [ ] Still open (**D14**): how the `output-dir/<identifier>/` tree gets
      deployed — flattening `package.json`'s own filename for a GitHub
      Release's flat asset list, vs. hosts that preserve real paths.
      Not blocking; the `.mpy` itself is already collision-safe either
      way.
