# 0013. micropython accepts a list, deduped by ABI, not by tag

- Status: Accepted
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
