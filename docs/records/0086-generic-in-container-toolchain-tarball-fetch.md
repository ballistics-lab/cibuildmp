# 0086 — a generic in-container tarball toolchain fetch, generalized out of `arm_embedded.Dockerfile`'s own build-time recipe

Status: Implemented. The mechanism itself only — see its own addendum below for exactly what
landed and what still does not call it.
Related: [0058], [0084], [0085], [0087], [0089]

## What this is splitting off, and why on its own

[0085] decided that `arm_embedded`/`riscv_embedded` stop baking their xpack cross compiler into
the image and instead fetch it at build time, per row, into a host-mounted cache — the same shape
[0058] already established for `esp32`'s toolchain ("the cache must be populated from inside the
container, not on the host"). Landing that decision needs one piece of machinery that does not
exist yet, and it is worth its own record because [0089] needs the identical piece for `natmod`'s
own `arm_embedded`/`riscv_embedded` rows: writing it twice, once per family, is exactly the
duplication CLAUDE.md's own top rule warns against.

## What exists today, read rather than assumed

- **The only place this fetch/verify/extract sequence exists is baked into
  `docker/arm_embedded.Dockerfile`'s own build-time `RUN`**: `curl` the tarball to `/tmp/tc.tar`,
  `sha256sum -c -` against a pinned `ARG TOOLCHAIN_SHA256`, `tar -xf ... --strip-components=1`.
  `riscv_embedded.Dockerfile` repeats the identical recipe against its own pin, plus a third `RUN`
  that symlinks `riscv-none-elf-*` to the `riscv64-unknown-elf-*` prefix MicroPython's makefiles
  expect. Neither is written as something callable at run time.
- **`usermod/espidf.py` is not a tarball mechanism at all.** `fetch_esp_idf()` does a host-side
  `git clone --depth 1` into `cache_root()/esp-idf/<version>/idf`; there is no sha256 verification
  anywhere in that module. The actual container-side provisioning script is
  `build_esp32.py`'s own `_esp32_container_script()`, and it is ESP-IDF-specific (exports `HOME`/
  `IDF_TOOLS_PATH`, runs `install.sh`, marks done with a `.installed` file in the mounted
  `tools_dir`) — a template for the *marker-file-in-a-mounted-cache* shape, not for a
  download-verify-extract one.
- **`src/cibuildmp/sources.py` already has the right primitives, unused outside itself.**
  `verify_sha256()`, `extract_archive()`, `download_file()`, and the atomic staging-dir +
  `.cibuildmp-complete`-marker pattern in `cached_dir()` are all generic and already used for
  MicroPython release tarballs — but every one of them is host-side Python, called nowhere in
  `usermod/`, `natmod/`, or `dockerrun.py`. A grep for any of the three across the tree outside
  `sources.py` returns nothing.

So there is no existing "container-side, sha256-verified, marker-cached tarball fetch" to call —
only a build-time shell recipe on one hand and host-side Python primitives on the other.

## What this record scopes

One generic, callable mechanism: given a URL, its expected sha256, a host-mounted cache directory
(`dockerrun.run()`'s existing `mounts=` mechanism), and an extraction target inside it, produce
the command a container runs to download, verify, extract (`--strip-components` where the tarball
needs it), and mark completion with a file inside the mounted directory — so a second invocation
against a warm cache does nothing. It mirrors `sources.py`'s own logic rather than reinventing it,
even though the container-facing form has to be a shell command rather than an in-process Python
call.

**Two toolchain kinds, not one**, per [0084]'s own finding that a cross target needs its `mpy-cross`
built by the image's *native* compiler while the firmware itself needs the *cross* one: the
mechanism takes a kind as a parameter rather than assuming there is exactly one tarball per row,
even though [0087] only exercises the cross kind at first (`arm_embedded`'s native compiler stays
baked into the image, unaffected by this record — see [0087]).

## What this does not do

No Dockerfile changes, no `build-platforms.toml` schema change, no port wired to this yet. [0087]
is the first real caller, for the six shared `usermod` ports; [0089] is the second, for `natmod`'s
own cross arches on the same two images.

## Addendum: what landed

`src/cibuildmp/toolchain_fetch.py` — two functions, no caller yet, matching this record's own
"what this does not do" exactly:

- `toolchain_dir(image, kind, version, root=None)` -- the cache path a fetch of this shape lands
  at, keyed by the toolchain-group image name (not the port -- several ports share one image),
  a `kind` ("cross" today, "native" accepted but uncalled, per this record's own two-kinds
  finding above), and the version string a row's own `toolchain_version` field will carry.
- `fetch_script(dest, url, sha256, *, strip_components=1)` -- the shell text a caller embeds
  ahead of its own real build command in one `bash -c` invocation (the same shape
  `build_esp32.py`'s own `_esp32_container_script()` already uses to run ESP-IDF's install step
  ahead of `make`), rather than a second `dockerrun.run()` call — there is nothing to hand back
  to one.

One thing the scoping above did not spell out, found while actually writing the shell rather than
describing it: `sources.cached_dir()`'s own guarantee is a Python `try/finally` around the
staging directory it creates, so a failed populate() never leaves that half-built directory
behind. A bare `set -e` in shell stops the script on the same failures, but does not clean up
after itself — the staging directory and the partial download both survive a failed `curl` or a
failed `sha256sum -c` unless something explicitly removes them. `fetch_script()`'s own
download/verify/extract steps therefore run in a subshell with `trap '...' ERR` doing that
cleanup, rather than inline: the trap only fires on a real failure, never on the success path, so
it never touches the tree the outer script's own `mv` is about to promote to `dest`.

Verified for real, not just read as plausible shell: `tests/test_toolchain_fetch.py` runs
`fetch_script()`'s own output with a real `bash -c`, against real `file://` tarballs (no Docker
daemon needed -- nothing here is image-specific) -- a first fetch extracting and stamping a real
tarball, a second run against a warm cache doing nothing (the source tarball is deleted first, to
prove it), a sha256 mismatch and an unreachable URL both failing with no cache entry and no
leftover staging directory, a stale partial tree (`dest` present, no marker) being discarded
rather than trusted, and `--strip-components` being honoured.

What still does not call any of this: `arm_embedded.Dockerfile`/`riscv_embedded.Dockerfile` are
unchanged, no row carries a resolved `(url, sha256)` pair yet, and `PATH`/`env=` wiring into
`dockerrun.run()` is entirely [0087]'s/[0089]'s own remaining work, not touched here.

## Addendum: the pin table and the combining call

Two more pieces landed after the first pass above, both still inside this record's own
boundary (a mechanism nothing calls yet, no Dockerfile touched, no row read):

- **`resources/pinned_toolchains.toml` + `resources.pinned_toolchains_data()`** -- the
  `(cross, version) -> (url, sha256)` table `resolve_pin()` reads. Keyed by `cross`
  (`build-platforms.toml`'s own existing `CROSS_COMPILE`-prefix field, e.g.
  `"arm-none-eabi-"`, used verbatim), not by `image`: `image` is a Docker-packaging fact
  on track to matter less once nothing bakes a toolchain into it any more, while `cross`
  is a fact about the compiler itself. Every value in it is verified live this session
  against each release's own sidecar (xpack's `.sha`), not copied from
  `build-platforms.toml`'s own `gcc` values on faith -- doing that caught a real, live
  mismatch: `natmod`'s own `rv32imc`/`rv64imc` rows recorded `gcc = "14.3.0-1.1"`, a tag
  `riscv-none-elf-gcc-xpack` has never published (its own suffix scheme is bare `-1`/`-2`,
  not `arm-none-eabi`'s `-1.1`); the real tag is `v14.3.0-1`, fixed in both places.
- **`resolve_pin(cross, version)`** and **`resolve_toolchain(cross, version, *, kind,
  root)`** -- the latter combines `resolve_pin()` + `toolchain_dir()` + `fetch_script()`
  into the one call a real caller needs, including creating `dest.parent` on the host
  first (the same precondition `build_esp32()` meets for `tools_dir` by hand today).

Also verified live, off to the side of this record's own scope but using the same
no-Docker-needed method (the toolchain is a plain x86_64 Linux tarball, run directly on
the host): `xtensa_esp`'s own single baked version builds `examples/natmod/features0`
for `ARCH=xtensawin` cleanly across five tags spanning the whole matrix, including the
exact `v1.25.0`/`v1.26.0` boundary that breaks `arm_embedded`/`riscv_embedded` -- so
`natmod.xtensawin` rows should **not** gain a `gcc`/`toolchain_version` field the way
[0087]/[0089] give `arm_embedded`/`riscv_embedded` rows one: there is nothing here for a
per-row fact to disambiguate. `pinned_toolchains.toml` carries `xtensa-esp32-elf-`'s one
version for this same reason -- present for completeness, not because anything reads it
per row.

13 tests now, all real (`bash -c` against `file://` tarballs, no mocked shell); still
zero callers in `dockerrun.py` or any `build_<port>.py`.
