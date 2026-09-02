# 0086 — a generic in-container tarball toolchain fetch, generalized out of `arm_embedded.Dockerfile`'s own build-time recipe

Status: Proposed — scoped, not designed in code.
Related: [0058], [0084], [0085]

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
