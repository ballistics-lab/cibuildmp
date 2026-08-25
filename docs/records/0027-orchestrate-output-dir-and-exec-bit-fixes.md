# 0027. The sixth Dockerfile fix got real CI past every unix arch, surfacing two genuine orchestrate.py bugs

- Status: Implemented
- Related: [0025], [0023]

<!-- migrated verbatim from docs/BACKLOG.md lines 1889-1941 -->

**D27 — the sixth Dockerfile fix (libtool) finally got real CI past every
`unix` arch's own build, and immediately surfaced two genuine `cibuildmp`
bugs of its own -- not Dockerfile/apt gaps this time, but real defects in
`usermod/orchestrate.py`, invisible in every prior verification in this
whole session because none of it had ever run the real CLI with
`package_dir != cwd`, or actually tried to execute a collected binary.**
`cibuildmp` itself reported all five `unix` arches built successfully
(`cibuildmp: 5 usermod target(s) built in 209.7s`, real byte sizes for
each) -- CI still failed, on the unrelated "List built artifacts" step,
because the output never landed where it should have.

- **`build_one()`'s own `identifier_dir = options.output_dir /
  target.identifier` never joined `package_dir` in** -- `output_dir`
  defaults to the bare relative string `"mpyhouse"` (`DEFAULT_OUTPUT_DIR`,
  shared with natmod), meant to resolve *against `package_dir`*, exactly
  the join natmod's own `cli.py` already does
  (`options.package_dir / build_options.output_dir`) before ever calling
  `collect_output()`. `orchestrate.py` skipped that join entirely, so the
  usermod build wrote to `<process cwd>/mpyhouse/...` instead of
  `<package_dir>/mpyhouse/...`. Invisible until now because every earlier
  verification in this session -- direct `build_unix()` calls, the M9b
  CLI proof, D20/D24's own live checks -- happened to run with cwd already
  equal to `package_dir`; a real Docker-action run is what caught it, since
  `action.yml`'s own container always has cwd at the repo root
  (`/github/workspace`) while `package-dir` points at
  `examples/usermod-unix`, a genuinely different directory. Fixed by
  making `orchestrate.py` do the identical join natmod's `cli.py` already
  proved correct: `options.package_dir / options.output_dir /
  target.identifier`. Verified live: a real CLI invocation with
  `package_dir` pointed at a tree copied well outside the repo and cwd
  left at `/`, confirming the output landed under `package_dir/mpyhouse/`
  and nothing at all appeared at the bare cwd-relative path.
- **`build_one()`'s own `shutil.copyfile(produced, dest)` doesn't
  preserve the executable bit `produced` already has** -- `copyfile()`
  copies content only, by Python's own documented contract; the
  collected binary came out `-rw-r--r--` and failed "Permission denied"
  on the very first attempt to run it. Harmless for natmod's own `.mpy`
  output (never executed directly -- always `mip.install()`-ed or
  imported, **D23**'s own distinction), a real, user-facing defect for
  usermod: the whole point of a usermod build's output is that it's a
  runnable binary. Fixed by switching to `shutil.copy()` (copies mode
  along with content). Verified live in the same run as the fix above --
  the collected `mpyhouse/unix-x64/micropython-unix-x64` ran immediately,
  no manual `chmod` needed, and the custom C module inside it still
  returned the right value.
- Both are genuine `cibuildmp` defects, not Dockerfile issues -- unlike
  every fix in **D25**, neither is scoped to the two custom images; both
  would misbehave identically for any caller running the bare CLI with
  `package_dir` set to something other than the process's own cwd, or
  ever trying to run a collected usermod binary directly. Two new
  regression tests cover each (`tests/test_usermod_orchestrate.py`),
  confirmed to fail without their respective fix before being confirmed
  to pass with it, not just written and trusted.
