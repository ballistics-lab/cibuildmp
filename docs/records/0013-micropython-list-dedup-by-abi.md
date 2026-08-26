# 0013. micropython accepts a list, deduped by ABI, not by tag

- Status: Accepted, with a correction (see addendum)
- Related: [0023]

<!-- migrated verbatim from docs/BACKLOG.md lines 233-271 -->

**D13 — `micropython` accepts a list, deduped by ABI, not by tag.**
Resolves the open question this file used to carry under that name.
`micropython` takes either a string or a list, the same "accept a list, or
a shell-ish string" idiom `archs`/`build`/`skip`/`extra-make-args` already
use (`options._as_list`) — no new config convention.

Building against several tags is a real use case only when they cross an
ABI boundary (`py/persistentcode.h`'s `MPY_VERSION`/`MPY_SUB_VERSION`);
otherwise every one of them produces a byte-for-byte identical native
`.mpy`, since the identifier — and so the output — is keyed on ABI, not
tag. So `targets.resolve_micropython_tags()` collapses the list to one
`(tag, abi)` pair per distinct ABI, keeping whichever tag came first in
the list and silently dropping a later one whose ABI an earlier one
already covers. `micropython = ["v1.23.0", "v1.28.0"]` is one build
against `v1.23.0` (both are ABI 6.3), not two; `["v1.22.0", "v1.28.0"]`
is two (6.2 and 6.3) — the real case this exists for.

Each `(tag, abi)` pair is its own ABI group: `Target` now carries the
`tag` it was resolved against (identifiers stay ABI-only, unaffected), and
`cli.build()` fetches MicroPython and builds `mpy-cross` once per group
rather than once per invocation — the D9 sharing argument still holds
*within* a group, just not across a genuine ABI boundary, where the
source is different by construction and there is nothing to share.

Verified live against a real second ABI (`v1.22.0` + `v1.28.0`, ABI 6.2 and
6.3): two groups, `fetch_micropython` called once per tag, two correctly
named outputs. One caveat surfaced by that same test, unrelated to this
decision's own logic: an old enough tag can fail to build `mpy-cross`
under a modern host `gcc` on its own merits — tried with `v1.21.0`,
upstream's `py/emitinlinethumb.c`/`emitinlinextensa.c` initialise
fixed-size `char` arrays without room for the trailing NUL (`{10,
"r10"}`), which a recent `gcc`'s `-Werror=unterminated-string-initialization`
rejects. `mpy-cross` is a host build, not a cross-compile, so this is not
a toolchain-resolution problem cibuildmp can route around; it is a real
constraint on which old tags a multi-version config can list on a modern
runner. `examples/template/cibuildmp.toml` stays single-tag for exactly
this reason — its job is to keep CI green on M3's build path, not to
chase every historical tag's own build health.

## Addendum (2026-08-26): "byte-for-byte identical" is false; functional
## interchangeability is what actually holds, and was unverified until now

Surfaced during the [0052] design conversation, when the user pushed back
on treating `micropython`/tag as fully collapsible into the ABI-keyed
identifier: this record's own central justification for dropping a
same-ABI tag ("otherwise every one of them produces a byte-for-byte
identical native `.mpy`") was **never actually tested** — the "Verified
live" paragraph above only exercised two *different* ABIs (6.2 and 6.3),
never two different tags sharing the *same* ABI, which is the one case
the byte-identical claim is actually about.

Tested directly this session, not assumed: cloned `v1.28.0` and `v1.29.0`
(both ABI 6.3 per `resources/natmod.toml`'s own `[mpy-abi]` table),
confirmed `examples/natmod/features0/{features0.c,Makefile}` are
byte-identical between the two tags (no confound from the module's own
source changing), built `features0.mpy` from each. Result:

```
v1.28.0/features0.mpy   217 bytes   sha256 a085c6ff...
v1.29.0/features0.mpy   204 bytes   sha256 aac43026...
cmp: differ at byte 7 (right after the 4-byte .mpy header)
```

**Not byte-identical.** Root cause, found in `diff tools/mpy_ld.py`
between the two tags: the x64 GOT-jump encoding changed — v1.28.0 always
emits a 5-byte jump (`struct.pack("<BI", 0xE9, entry)`); v1.29.0 added a
compact 2-byte form when the offset fits in 7 signed bits, falling back
to the old 5-byte form otherwise. A real linker optimization, landed with
**no `MPY_VERSION`/`MPY_SUB_VERSION` bump** — internal tooling drifted
inside a single declared ABI group, confirming the risk this record's own
byte-identical claim had waved away without checking.

**But functional/load compatibility is real, and independently
verified**, not just inferred from `py/persistentcode.c`'s own subset
rule: built MicroPython's `unix` port from both tags (`v1.28.0` and
`v1.29.0`, host, unmodified) and cross-loaded every combination —

```
1.28-binary + mpy-from-1.28  -> factorial(5) = 120
1.28-binary + mpy-from-1.29  -> factorial(5) = 120   (cross)
1.29-binary + mpy-from-1.28  -> factorial(5) = 120   (cross)
1.29-binary + mpy-from-1.29  -> factorial(5) = 120
```

All four load and run correctly. So the two claims resolve to:

- **False**: same-ABI tags produce byte-identical output. They do not —
  internal tooling (`mpy_ld.py`, and by extension anything else gated
  only by "did `MPY_VERSION`/`MPY_SUB_VERSION` change", not by "did
  anything change") can drift within one ABI group.
- **True, and now actually verified rather than assumed**: same-ABI tags
  produce *functionally interchangeable* output — `py/persistentcode.c`'s
  loader only ever checks `MPY_VERSION`/`MPY_SUB_VERSION`/native arch/
  `arch_flags` (a subset check for the last one, not exact — see the
  `arch_flags = 0` note in [0052]), never anything about internal
  encoding, and the live cross-load test confirms this holds in practice,
  not just on paper.

**What this changes:** nothing about the dedup *decision* — collapsing a
list of same-ABI tags to one build for the "avoid needless, non-load-
bearing work" goal is still correct, because functional compatibility
(the thing that actually matters for whether a build serves its purpose)
is confirmed, independently, by a real cross-load test. What changes is
the *stated reason* (fixed above: "functionally interchangeable", not
"byte-for-byte identical") and how the "which tag survives" rule itself
works: because the literal tag chosen out of a same-ABI group is not
fully inert (it affects the exact bytes shipped, even if not what those
bytes do), silently keeping "whichever came first in the list" is no
longer good enough — [0052]'s own identifier-grammar section, after
working through and rejecting both "make tag visible in the identifier"
and "reposition it next to ABI", lands on turning ambiguity itself into
a loud `ConfigError` when two *distinct* tags share one ABI, with the
literal tag actually used recorded as build provenance (`package.json`),
never in the selector-facing identifier.

[0023]: 0023-usermod-identifier-scheme-config-output.md
[0052]: 0052-config-is-a-tree-not-a-selector-matrix.md
