# 0007. usermod vendors mpbuild's board database, not depends on the package

- Status: Accepted
- Related: [0016], [0022]

<!-- migrated verbatim from docs/BACKLOG.md lines 81-139 -->

**D7 — usermod vendors `mpbuild`'s board database, not depends on the
package.**
[`mattytrentini/mpbuild`](https://github.com/mattytrentini/mpbuild) (PyPI
`mpbuild`, 1.2.0) has a board database worth reusing, but the package itself
is not worth the dependency it costs. `board_database.py` is 293 lines,
stdlib-only (`glob`, `json`, `dataclasses`, `Path`), MIT-licensed (© 2024
Matt Trentini) — not enough code to justify pulling `mpbuild` itself, which
drags in `rich` + `textual` + `typer` and requires Python ≥3.12, a TUI stack
on top of a build driver that has stayed standard-library-only since M1/M2
for exactly this reason.

Extract into one vendored module (`usermod/boards.py`, MIT header kept, with
a comment naming the origin repo and the commit it was taken from — the same
discipline **D14** applies to the `package.json` schema):

- `Port`/`Board`/`Variant` plus the `ports/*/boards/*/board.json` scan,
- `check_board_json`.

Do **not** take the port → Docker-image map or command construction: that
layer is exactly what **D3** wants `cibuildmp` to resolve itself, and it is
coupled to mpbuild's own CLI.

Verified directly against mpbuild's source (`src/mpbuild/build.py` and
`board_database.py`), not assumed: the boundary above holds exactly at the
file level. `board_database.py` has zero Docker references — its own
`Board.images` field is board *photographs* from the `micropython-media`
repo, easy to misread as a hit on first grep, not container images. The
port → image resolution mpbuild actually uses lives entirely in
`build.py`, as a small, mostly-static `BUILD_CONTAINERS` dict keyed by
**port**, not by board: `"stm32"`/`"rp2"` → `micropython/build-micropython-arm`
(`ARM_BUILD_CONTAINER`), `"esp32"` → `espressif/idf:v5.4.2`
(`ESP_IDF_CONTAINER:ESP_IDF_FALLBACK_VERSION`), and so on per port. Two
special cases sit on top of the static table rather than folding into it:
`rp2` switches to `micropython/build-micropython-rp2350riscv` when its
`variant == "RISCV"` (the ARM image otherwise), and `esp32` runs a
three-tier version probe (lockfile → CI workflow → the hardcoded `v5.4.2`
fallback above) instead of one fixed tag — the only place this map is not
pure data. `docker_build_cmd()` then assembles an ordinary `docker run
--rm -v <mpy_dir>:<mpy_dir> -w <mpy_dir> --user <uid>:<gid> -e HOME=/tmp
<image> ...` — nothing mpbuild-specific in the invocation shape itself.

This narrows what "do not take the command construction" means in
practice: the `docker run` shape is generic enough not to need
transcribing at all, and the image table is small enough to fit **D10**'s
pattern directly rather than D7's own vendored-module treatment — a
`resources/usermod-images.toml` (port → image, with the `rp2` RISCV
variant as an override entry) plus one small hand-written function for the
esp32 version probe, sourced by hand from `build.py` rather than imported.
Feeds directly into **D19**: the same table this describes is exactly what
an eventual `docker` strategy for `esp32` (and `rp2`/`stm32` too, if D20's
runner story puts them on it) would pin.

Honest tradeoff: `board.json`'s schema and the variant convention drift
upstream, and vendoring means tracking that drift by hand. Pinning
`mpbuild==1.2.0` would not avoid tracking it either, just tie it to someone
else's release cadence instead. This is not pinned data in the **D10**
sense — it is read from the checkout at runtime, so nothing goes into
`resources/`.
