# 0015. rv32imc's ARCH_FLAGS= is part of the identifier, not an invisible extra-make-args string

- Status: Accepted
- Related: [0014]

<!-- migrated verbatim from docs/BACKLOG.md lines 352-432 -->

**D15 — `rv32imc`'s `ARCH_FLAGS=` is part of the identifier, not an
invisible extra-make-args string.**
Found reading [micropython#19479](https://github.com/micropython/micropython/issues/19479)
carefully, as flagged directly: `py/dynruntime.mk` (line 197-198) turns a
consuming Makefile's `ARCH_FLAGS=` into `mpy_ld.py --arch-flags`, which
packs a variable-length uint into the `.mpy` header (feature-byte bit 6
set, the value follows as a big-endian 7-bit-group varint). Two rv32imc
builds that differ only in this value are **not** interchangeable —
`py/persistentcode.c`'s `mp_raw_code_load()` validates it as `required ⊆
available` against `asm_rv32_allowed_extensions()` (confirmed in the
issue thread: an exact-int match, the obvious first idea, does not work
for this reason) — but before this decision `Target.identifier` had no
way to say two such builds were different at all.

`arch-flags` (top-level config key, `[natmod]`-nested also accepted,
matching how `archs` itself is read) accepts a string *or a list*, the
same "accept a list, or a shell-ish string" idiom `archs`/`micropython`/
`extra-make-args` already use — because "build every arch-flags variant"
turned out to be a real, distinct request from "build every arch" (a
consuming project wanting both a baseline `rv32imc` and a
`Zba`/`Zcmp`-optimised one, say), not something a single value could ever
express. Each entry is parsed the way `mpy_ld.py`'s own
`validate_arch_flags()` does — a numeric string (`0b`/`0x`/decimal) or a
comma-separated list of named extensions (`RV32_ARCH_FLAGS` in
`resources/natmod.toml`, transcribed from `mpy_ld.py`'s
`RV32_EXTENSIONS`) — and `natmod_targets()` emits one `rv32imc` `Target`
*per entry*, side by side with every other selected arch's single Target.
Resolved before `build`/`skip`/`[[overrides]]` selection either way, since
it changes the identifier those glob against: `mpy6.3-natmod-rv32imc+0x3`,
the `+0x..` suffix present only when nonzero. Opaque hex, not named flags
reconstructed from the int: a named encoding would have to stay in
lockstep with `RV32_ARCH_FLAGS` to remain accurate, and the identifier
must still mean the same thing if that table gains a flag a given build
predates. `arch-flags` can only be set at this one place (like `archs`,
not per-`[[overrides]]`) for exactly that reason — an override selects by
identifier, and the identifier cannot depend on which override already
matched it.

`mpy_ld.py` itself restricts `--arch-flags` to `rv32imc` only (raises for
every other arch), and `persistentcode.c` only ever validates arch_flags
for `MP_NATIVE_ARCH_RV32IMC` (any other arch with the header bit set is
an unconditional `"incompatible .mpy file"` on load) — not `rv64imc`
despite the name similarity. `cibuildmp` mirrors that restriction
exactly: `natmod_targets()` only ever puts a nonzero `arch_flags` on the
`rv32imc` `Target`, zero on every other arch regardless of config.

`verify_output()` (**M3**'s `auditwheel` equivalent) now checks
arch_flags too, exact match — that is a different question from mip's
own subset check above: this asks whether the *linker* encoded what the
config asked for, not whether a *device* can run the result.

Caught while implementing this: `build.py`'s existing arch-decoding was
`header[2] >> 2`, no mask. `py/persistentcode.h`'s own
`MPY_FEATURE_DECODE_ARCH` is `((feat) >> 2) & 0x2F` — bit 6 (the
arch-flags marker) becomes bit 4 after the shift, and `0x2F` is the mask
that excludes it. Without it, `rv32imc` (native-code 11) with the
arch-flags bit set decoded as 27. Latent until now — no arch besides
`rv32imc` sets the marker bit, and nothing set it for `rv32imc` either
until this decision — but a real bug in already-shipped M3 code,
findable only by reading the upstream macro precisely rather than
inferring the shift from bclibc's own script, which carries the same
mask but not a citation of where `0x2F` comes from.

Also caught, running the list variant for real rather than trusting the
single-value case already worked: the `BUILD=` scoping fix from M3's own
"two bugs" note (`BUILD = .obj/$(ARCH)`) only accounts for `$(ARCH)`, not
`$(ARCH_FLAGS)`. `rv32imc`'s own object file does not depend on
`ARCH_FLAGS` at all, so building `arch-flags = ["", "zba", "zba,zcmp"]`
back to back in one invocation reused the *first* variant's cached
`.o`/`.mpy` for the second and third just as silently as the original
`$(ARCH)` bug did — `$(ARCH)` never changes across these three targets, so
the earlier fix alone does nothing here. `examples/template/natmod/Makefile`
now scopes `BUILD` by both:
`BUILD = .obj/$(ARCH)$(if $(ARCH_FLAGS),+$(ARCH_FLAGS))`, and README.md's
"Conventions this repo assumes" says so for every arch-flags-using natmod
Makefile too. Same class of bug, same fix shape, second axis — worth
noting as a pattern: *any* build-relevant variable dynruntime.mk does not
already fold into `BUILD` on its own needs to be added by the consuming
Makefile, or D9's one-sequential-invocation model silently serves stale
output for it.
