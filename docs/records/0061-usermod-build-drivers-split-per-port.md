# 0061 — usermod build drivers split per port, cibuildwheel-style

Status: Implemented
Related: [0060], [0053]

## What this decides

`usermod/build.py` held every port's `build_<port>()` driver in one file. Landing [0060]'s
`rp2` driver pushed it to 1628 lines across seven ports (`unix`, `qemu`, `webassembly`,
`esp32`, `rp2`, `windows`, plus the shared `container_mpy_cross()`/`UsermodBuildError`), with
nine more ports ([0053]) still to come. Split it, per-port, one module each:

- `usermod/build_common.py` — `UsermodBuildError`, `container_mpy_cross()`: the two things
  every driver shares.
- `usermod/build_unix.py`, `build_qemu.py`, `build_webassembly.py`, `build_esp32.py`,
  `build_rp2.py`, `build_windows.py` — one port each, its own `*BuildOptions` dataclass, its
  own `*_make_command()`, its own `build_<port>()`, and whatever port-specific verification
  it carries (`verify_unix_output()`/`verify_unix_floor()`, `verify_windows_output()`).

This is the same shape cibuildwheel itself uses — `cibuildwheel/linux.py`, `macos.py`,
`windows.py`, `pyodide.py`, plus a shared `util.py` — read directly from an installed copy
before choosing this layout rather than recalled, per this repo's own CLAUDE.md rule on
that. `platforms/__init__.py`'s own docstring used to argue explicitly *against* mirroring
that shape ("cibuildmp's five usermod ports already share one real implementation... keyed
data, not five independently-authored pipelines") — updated alongside this split, since a
1600-line single file with six real port sections was no longer "keyed data" in any useful
sense, whatever the original argument's merits at five ports and a few hundred lines.

## What did not change

The dispatch shape: `orchestrate.py`'s `_BUILD_FN` table and `_port_build_options()`'s
`if port == ...` chain are unchanged in structure, just importing from six modules instead
of one. No behavior changed anywhere — every `build_<port>()`/`*_make_command()`/
`*BuildOptions` function and dataclass moved verbatim, byte-for-byte body, only the module
boundary and the resulting import lines changed. `container_mpy_cross()`'s callers now
reach it via `from . import build_common; build_common.container_mpy_cross(...)` rather than
a bare imported name — chosen deliberately, not for style: it keeps exactly one patchable
name (`cibuildmp.platforms.usermod.build_common.container_mpy_cross`) for every port's own
tests to monkeypatch, regardless of which port module calls it, rather than six separate
per-module bindings a test would have to know to target individually.

## Test split mirrors the source split

`tests/test_usermod_build.py` (1202 lines, six ports' worth of cases in one file) became
`test_usermod_build_unix.py`/`_qemu.py`/`_webassembly.py`/`_esp32.py`/`_windows.py`,
one per port, same reasoning as the source split — otherwise the split leaves one giant test
file mapped to six small source files, which is the same problem in the other direction.
`rp2` has no test file of its own yet; [0060]'s own record says why (live-build-verified,
no mocked-command-shape tests written). 371 tests passed before and after both splits, same
count — nothing lost, nothing duplicated.

Two naming collisions the split introduced, both resolved the same way: a module named
`build_esp32.py`/`build_windows.py` containing a function of the identical name
(`build_esp32()`/`build_windows()`) cannot be imported as a bare module alongside that
function without shadowing one or the other. `usermod/espidf.py` is imported directly by
its own name in the `esp32` test file instead of reached via `build_esp32.espidf` (it was
always the same shared module object either way — `build_esp32.py`'s own `from . import
espidf` just binds a local name to it, so patching it directly by its real path is no
different in effect, just avoids the alias). `verify_windows_output()` is imported directly
by name in the `windows` test file instead of reached via a `build_windows.` prefix, for the
same reason.

[0060]: 0060-rp2-build-driver.md
[0053]: 0053-usermod-ports-without-a-build-driver.md
