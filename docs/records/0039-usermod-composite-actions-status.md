# 0039. usermod: existing composite-action layer, and the two selector axes

- Status: Informational (context for D16-D33)
- Related: [0016], [0017], [0018], [0019], [0020], [0021], [0022]

<!-- migrated verbatim from docs/BACKLOG.md lines 844-901 -->

### Later — usermod

Not scheduled as tool work, but the prerequisite layer is **done and
proven**, which changes what "not scheduled" means here. `.github/actions/
build-usermod-{unix,windows,webassembly,armv7m,esp32,rp2040}` all exist in
this repo, and `o-murphy/a7p`'s own `.github/workflows/mp-usermod.yml` now
drives all six directly, across twelve identifiers (`unix` × x64/x86/
aarch64, `windows` × x86/x64/arm64, `webassembly`, `unix-cross` × armhf/
mipsel, `qemu`/armv7m, `esp32`, `rp2040`) — every job green. That is
exactly the position natmod was in before M0: a working low-level layer,
hand-driven per consumer, nothing yet absorbing the parts that are
identical across all of them. The difference is usermod now has a real
reference implementation to design the identifier/config scheme against,
instead of reasoning from the cibuildwheel analogy alone the way natmod's
M0 had to.

`cibuildmp` drives every usermod port itself, not just the ones `mpbuild`
has a board database for. Every composite action here is the low-level
layer until `cibuildmp` covers its ground, then becomes a thin wrapper
over it (**M5**'s own open item for `build-natmod`) — no port gets
carved out as a permanent exception.

Two different selector axes, not the same thing under two names:

- **Board-based ports** (`qemu`/`esp32`/`rp2040`, and `stm32`/etc. when
  added) select a `board:` (`MPS2_AN385`, `ESP32_GENERIC`, `RPI_PICO`, …)
  and resolve it to a toolchain via the data vendored from `mpbuild`
  (**D7**) — confirmed as a real, present-tense input on all three
  existing board-based actions, each with its own default.
- **`unix`/`windows`/`webassembly` have no board concept at all** — they
  select a `variant:` instead: `ports/unix/variants/` (`standard` default;
  `build-usermod-unix`'s own `variant` input), `ports/webassembly`'s
  `standard`/`pyscript` (`build-usermod-webassembly`'s `variant` input,
  `pyscript` default since `standard`'s `-s ASYNCIFY` is broken on modern
  emsdk, tracked upstream at micropython/micropython#19380).
  `build-usermod-windows` carries a `variant` input too, but every real
  caller leaves it empty and it is omitted from the command line entirely
  — `ports/windows` has no `variants/<name>/` split in any consumer today,
  just one `variants/manifest.py`; the input exists for a future fork that
  adds one, not a fourth real value alongside `standard`/`pyscript`.
  `mpbuild`'s board database was never going to cover these regardless of
  the dependency-vs-vendor question **D7** is actually about — a variant
  isn't a board missing from the list, it's a different axis entirely.
- **`zephyr` fits neither axis above** — no `board.json`, no `variant:`,
  and no `mpbuild` coverage at all. See **D22**.

`cibuildmp` drives `unix`/`windows`/`webassembly`'s own port Makefile
directly, the same delegate-the-compile shape **D2** already uses for
natmod, with `variant` as their own config axis parallel to `boards` for
the board-based ports. Either way `cibuildmp` resolves the port → build
command itself and treats firmware as a verification output rather than a
published artifact by default.

Six more findings, real rather than anticipated, surfaced by the actions
themselves and by a7p's workflow actually driving them — worth locking now
even though M6+ isn't scheduled, so the eventual tool absorbs what's
already known instead of re-deriving it:
