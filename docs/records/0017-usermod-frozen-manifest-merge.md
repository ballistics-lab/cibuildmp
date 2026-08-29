# 0017. Combining FROZEN_MANIFEST with the port's own default manifest is real, per-port, and explicitly not solved by the action layer

- Status: Accepted
- Related: [0016], [0039]

<!-- migrated verbatim from docs/BACKLOG.md lines 941-991 -->

**D17 — combining `FROZEN_MANIFEST` with the port's own default manifest
is real, per-port, and explicitly *not* solved by the action layer.**
`build-usermod-webassembly`'s own header says so outright: "Combining
FROZEN_MANIFEST with the port's own default... is deliberately left to
the caller, not done here... Every consuming repo now writes its own
combined manifest first and passes that as frozen_manifest instead." In
`mp-usermod.yml` this is a hand-written `cat > manifest.py <<EOF` +
`include()` pair, duplicated three times for the differently-shaped ports
(`variants/<x>/manifest.py` for unix/webassembly, `boards/manifest.py` for
esp32/rp2040, nothing at all for qemu — `ports/qemu` ships no default
manifest, so combining is skipped there) and a fourth time for Windows
with its own escaping story (below). This is exactly the class of
hand-copied-and-drifting logic Positioning says `cibuildmp` exists to
absorb. Fix: record each port's default manifest path, and have
`cibuildmp` generate the combined manifest itself from that plus the
consumer's own module manifest — a consumer supplies only the fragment
that freezes their module, same shape `natmod`'s `pre-build-command`
already lets a consumer opt into project-specific setup without owning
the whole recipe.

Corrected twice now, which is itself the finding worth recording: reading
paths directly off a `v1.28.0` checkout is not the same as reading how a
real consumer resolves them. The first pass concluded "one shared
`manifest.py` per port, not per-board or per-variant" — true of the
*files on disk* (`ports/unix/variants/manifest.py` exists as one file),
false of what actually gets *built*: `unix`'s `Makefile` sets a
port-level default (`FROZEN_MANIFEST ?= variants/manifest.py`), but
`variants/standard/mpconfigvariant.mk` overrides that default to
`variants/standard/manifest.py` for exactly the variant `a7p`'s own
`mp-usermod.yml` builds (`webassembly`'s `pyscript` variant the same way;
`unix`'s own `minimal` variant overrides to *empty*, dropping the
manifest entirely). Board-based ports carry the identical shape one level
down — `rp2/CMakeLists.txt`'s own comment says the quiet part directly:
"Include board config, it may override MICROPY_FROZEN_MANIFEST" — most
`esp32`/`rp2` boards do ship their own `boards/<BOARD>/manifest.py`.
`qemu` was right both times — confirmed no `manifest.py` anywhere under
`ports/qemu` on disk, not assumed from the action's own behaviour.

What's pinned in `resources/usermod.toml` is therefore **not** a general
per-variant/per-board resolver — building one is real, unstarted work,
out of scope for the current six ports. It is the one fixed path each
port resolves to under exactly how `a7p`'s own `mp-usermod.yml` builds it
*today*: `unix` → `variants/standard/manifest.py`, `webassembly` →
`variants/pyscript/manifest.py` (both variant overrides, because that
workflow builds those specific variants), `windows`/`esp32`/`rp2` → each
port's own unmodified default (that workflow applies no variant/board
override for any of the three). Landed as `resources/usermod.toml` +
`usermod/portinfo.py`'s `default_manifest()`, alongside `build_system()`
from **D16** above — the generation step itself (the actual
`FROZEN_MANIFEST` combine) is still M7, not this.
