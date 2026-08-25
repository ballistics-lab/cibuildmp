# 0023. usermod's own identifier scheme, config shape, and output convention are each genuinely different from natmod's

- Status: Accepted
- Related: [0005], [0013], [0014], [0022]

<!-- migrated verbatim from docs/BACKLOG.md lines 1494-1566 -->

**D23 — usermod's own identifier scheme, config shape, and output
convention are each genuinely different from natmod's, not reused
unmodified, and each difference is deliberate.**

- **No ABI axis in the identifier.** natmod's `Target.identifier` is
  `mpy{abi}-{mode}-{arch}` because a `.mpy` is compiled *against* a
  specific running MicroPython's compatibility tag -- the whole reason
  D14's packaging step exists at all is to let `mip` match a `.mpy` to
  a device's own ABI. A usermod build has no such relationship: it *is*
  the MicroPython, a full port binary meant to be flashed or run
  directly, not installed into one already running. `UsermodTarget`'s
  own identifier is just `{port}` or `{port}-{arch}` -- reusing
  natmod's `Target` dataclass (even just its `mode` field, which does
  read as though it was left generic for exactly this) would have
  carried an ABI axis that means nothing here, so a new, smaller
  dataclass instead.
- **No `package.json` in `output-dir/<identifier>/` either, for the
  same reason** -- confirmed with the user directly before writing any
  of `usermod/orchestrate.py`, not assumed either way from D14's own
  text alone. The identifier-scoped *directory* convention is kept
  (same "no reorganising step between building and having the output"
  reasoning D14 already gives), just without the `mip`-specific
  manifest next to it.
- **Config is scoped by build mode a second time, genuinely, not just
  cited.** D5 already named cibuildwheel's own `[tool.cibuildwheel.
  android]`/`.pyodide` sub-tables as the model for *natmod's* own
  `[natmod]` table; `[usermod]` plus its own per-port
  `[usermod.<port>]` sub-tables (`archs` for `unix`/`windows`,
  `boards` for `esp32`, nothing yet for `qemu`/`webassembly`, which
  have no configurable axis at all today) follow the same model a
  second time, for a second axis cibuildwheel itself has no equivalent
  of at all (which *port*, not which OS).
- **Mode is auto-detected, not asked for.** The user's own question,
  asked directly rather than assumed away: "isn't it obvious from the
  config already?" -- yes, almost always. `cli.detect_mode()` reads
  which top-level table (`natmod`/`usermod`) the config actually has
  and picks that; `--platform` (previously a `choices=["natmod"]` stub
  that did nothing real) becomes an explicit override, needed only
  when a config genuinely defines both tables at once (a real,
  legitimate case: one module shipping both a natmod extension and a
  full usermod port build) -- ambiguity is the one case a flag earns
  its keep for, not the common one.
- **One MicroPython tag, not D13's own list-spanning-an-ABI-boundary
  mechanism.** A usermod build has no ABI to span in the first place,
  so `UsermodOptions.micropython` is a plain `str`; the shared
  top-level `micropython` key can still be a list (natmod's own D13
  case), and only its first entry is taken -- explicit, not a silent
  `str()` of a Python list into nonsense (a real bug caught and fixed
  while writing `UsermodOptions.load()`, before it shipped).
- **A target's own build directory is `mpy_dir/ports/<port>/
  build-<identifier>/`, not the port's own bare default.** Two arches
  of the same port (`unix-x64` and `unix-aarch64`, say) share one
  MicroPython checkout and one `mpy-cross` (the same D9 sharing
  natmod's own `build()` already does, and for the same reason: none
  of usermod's own axes change which MicroPython release is being
  built) -- without a per-identifier build directory, building both in
  one invocation would have the second overwrite the first mid-build.
  `esp32` is the one exception: it has no `build_dir` field at all
  (`usermod/build.py`'s own `Esp32BuildOptions`), since its own
  CMake-driven build already keys its directory on `BOARD=` alone
  (`build-<BOARD>/`) and passing a competing `BUILD=` override breaks
  its internal mpy-cross sub-build (that module's own docstring has the
  real CI failure this caused, found before **M9**'s own esp32 work
  shipped).
- **`qemu`'s board is never passed through as `board=""`.** `qemu` has
  no configurable axis yet, so `UsermodTarget.arch` is always `""` for
  it -- a real bug caught while writing this (and now covered by
  `test_build_one_qemu_uses_default_board_not_empty_string`): passing
  that empty string through to `QemuBuildOptions(board=...)` would have
  silently overridden its own `"MPS2_AN385"` default with nothing,
  instead of just not passing `board=` at all and letting the
  dataclass default apply.
