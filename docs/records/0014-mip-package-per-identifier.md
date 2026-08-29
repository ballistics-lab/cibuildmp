# 0014. cibuildmp itself writes one self-contained mip package per identifier as part of the normal build

- Status: Accepted
- Related: [0007], [0023]

<!-- migrated verbatim from docs/BACKLOG.md lines 272-351 -->

**D14 — `cibuildmp` itself writes one self-contained mip package per
identifier as part of the normal build, in today's stable schema — there
is no separate `cibuildmp publish` command.**
Originally scoped as a separate `cibuildmp publish` absorbing bclibc's
`tools/build_release_assets.py`, and around the "per-entry native code
compatibility tag" schema — [micropython#19532](https://github.com/micropython/micropython/pull/19532)
/ [micropython-lib#1144](https://github.com/micropython/micropython-lib/pull/1144)
— which would let one `package.json` list every arch's `.mpy`, each
tagged, and let `mip` pick the right one at install time. Both revisited:

- **No separate command.** `mpyhouse/` is the thing to fix, not a second
  step that reorganises it afterwards: `cli.build()` writes each target
  straight into `output-dir/<identifier>/` from the start, so an
  identifier's directory already holds its `.mpy`, any `extra-files`
  companions, and its own `package.json` the moment that target's build
  finishes. Consistent with cibuildwheel, which has no publish step
  either — `wheelhouse/` is immediately `twine upload`-able, no
  intermediate packaging command. Creating a release or uploading the
  tree stays the caller's own CI step (**Non-goals**), same as
  `wheelhouse/*` → `twine upload` is the caller's job, never
  cibuildwheel's.
- **No compat-tag schema dependency.** Both upstream PRs are
  self-authored (by this project's own maintainer), open, with no
  reviewers, and each explicitly says "not yet tested ... on real
  hardware ... before merge." That is a materially weaker foundation than
  "a proposal pending review" suggested — depending on an unmerged,
  hardware-untested, zero-review-traction PR of one's own is premature,
  however directionally sound the schema itself is.

Each identifier's `package.json` uses the plain two-element
`["path", "url"]` `urls` schema `mip` has always supported — no compat
tag, no upstream change needed, works with every `mip` in the wild today.
A consumer picks which identifier's `package.json` to `mip.install()` by
URL, the same way `--only <identifier>` already picks one target to
build; the tag-matching problem #19532/#1144 solve is sidestepped by the
*URL* being the selector instead of runtime tag matching on-device. A
single unified, tag-matching manifest stays possible as a later, additive
mode on top of the per-identifier one — gated on those two PRs actually
picking up review traction or landing, not on a fixed date.

**Companion files, the original reason for this decision:** found
inspecting a real second module in `../micropython-bclibc` — `ffimod/`
builds a native `.so` plus facade `.py` files (`ffi.py`,
`_tiny_bclibc.py`) that stay separate, unlike `natmod/`, where
`SRC = tiny_bclibc_mp.c tiny_bclibc.py` already gets merged by
`dynruntime.mk`'s own `SRC_MPY`/`--merge` rule into one `.mpy` per arch —
that merged case needs nothing from `cibuildmp`, it is `natmod/Makefile`'s
own business (**D2**). What is not covered: a facade or any other file
meant to install identically regardless of target arch. Per-identifier
packages resolve this for free: `[publish] extra-files` gets copied into
*every* identifier's directory and listed in that identifier's own
`package.json` — no separate "untagged entry" case to design, since every
entry in the (untagged) per-identifier schema already installs
unconditionally. Confirmed as a real need, not hypothetical (bclibc's own
`ffimod/` wants exactly this), but bclibc does not publish `ffimod`'s
output today, so there is no existing package.json to match against — the
shape is designed and tested against `examples/template`, not yet
verified against a real consumer's actual release.

`version` (top-level config key / `CIBMP_VERSION`) gates the whole
packaging step: empty (the default) means an identifier's directory holds
only its `.mpy` — still useful on its own (a Makefile-driven consumer
downstream just wants the file), just not mip-installable yet. Set it
(`CIBMP_VERSION: ${{ github.ref_name }}` in CI) and `extra-files` +
`package.json` are written too. No CLI flag: `--version` was already
taken (prints `cibuildmp`'s own version).

Still open: how the local `output-dir/<identifier>/` tree gets deployed.
Each `.mpy` is already named `<module>-<identifier>.mpy` (**M3**, kept
even though the directory alone would disambiguate it locally) so it
never collides even if a caller later flattens several identifiers into
one namespace — a GitHub Release's own asset list is necessarily flat
(no real subdirectories) — but `package.json` itself is not yet
identifier-qualified and would still need renaming to
`<identifier>_package.json` (or similar) on that specific upload path. A
host that preserves real paths (GitHub Pages, S3, a raw git tree) can
take the tree as-is. Not decided which target `cibuildmp` should make
easiest first — bclibc's own `release.yml` today only does GitHub
Releases.
