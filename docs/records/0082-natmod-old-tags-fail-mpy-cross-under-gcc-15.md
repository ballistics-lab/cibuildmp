# 0082 — nine MicroPython tags fail `mpy-cross` under gcc 15, on every image whose native compiler is unpinned — bisected exactly

Status: **Implemented (closed 2026-09-03).** The failure, its exact boundary, and its reach across
`natmod`/`windows` were confirmed when this was written; the fix it deliberately left unchosen was
chosen in [0084]/[0091] and finished here. **Two of this record's own numbers were wrong and are
corrected in the closing addendum**: the affected range is 18 of 24 tags, not 9, and the four
"inferred, not built" tags are now a source-level fact rather than an inference.
Related: [0013], [0044], [0068], [0084], [0091], [0093]

## What this closes out

`docs/reference/open-questions.md`'s "Old tags vs. a modern host `gcc`" entry, open since [0013]
first hit this by accident while verifying D13 live, on a bare host, with no real gcc version or
tag range recorded — "unclear yet how far back tags stay buildable". This record answers that
question directly, against this project's own real build image rather than an arbitrary host
gcc, and gives it an exact tag boundary instead of "old enough".

## Why this project's own toolchain is the right thing to test, not an arbitrary host gcc

[0068]'s own addenda already established that `docker/natmod_host.Dockerfile` (`ubuntu:26.04`)
hands `x64`'s native path straight to whatever gcc `build-essential` resolves to on that base —
**gcc 15.2.0-16ubuntu1**, unpinned, by design (only the `x86` multilib side effect got pinned,
after the link-time break [0068] itself documents). So this is not "does some hypothetical gcc
15 break this" — it is the exact compiler every real `x64`/`x86` natmod build on this project's
own `main` branch runs today.

Built locally: `docker build -t cibuildmp-natmod_host -f docker/natmod_host.Dockerfile .`, then
`make -C mpy-cross` inside it (bind-mounted, not copied into the image) for a bisection set of
real MicroPython tags cloned straight from `micropython/micropython`.

## Result, bisected exactly

| tag | ABI (`build-platforms.toml`) | `mpy-cross` under `natmod_host` (gcc 15.2.0) |
| --- | --- | --- |
| `v1.20.0` | 6.1 | **FAIL** |
| `v1.21.0` | 6.1 | **FAIL** — the tag [0013] originally hit |
| `v1.22.2` | 6.2 | **FAIL** |
| `v1.24.0` | 6.3 | **FAIL** |
| `v1.25.0` | 6.3 | **FAIL** |
| `v1.26.0` | 6.3 | OK |
| `v1.28.0` | 6.3 | OK |

Same error at every failing tag, `py/emitinlinethumb.c`:

```
error: initializer-string for array of 'char' truncates NUL terminator but
destination lacks 'nonstring' attribute (4 chars into 3 available)
[-Werror=unterminated-string-initialization]
```

— fixed-size `char`/`unsigned char` arrays initialised with a 3-character mnemonic
(`"lsl"`, `"add"`, ...) with no room left for the trailing NUL, upstream's own code, unchanged
across this whole range. Upstream fixed it somewhere between `v1.25.0` (still fails) and
`v1.26.0` (clean) — not bisected to the exact commit here, the tag boundary is what this
project's own `build`/`skip` selection actually addresses.

**The warning flag itself is gcc-15-only**, confirmed on the plain host (not the project image)
earlier this session: neither `gcc 13.3.0` (this session's base) nor `gcc 14.2.0` (installed
from Ubuntu 24.04's own archive) even recognise `-Wunterminated-string-initialization` —
`--help=warnings` finds nothing. `open-questions.md`'s original "recent gcc" wording undersold
how narrow this is: it is not "old toolchains are fine, modern ones aren't", it is specifically
gcc 15+.

## Scope against the real tag table

`resources/build-platforms.toml`'s own `natmod.identifiers` groups tags by ABI:

```
6.1  v1.20.0, v1.21.0
6.2  v1.22.0, v1.22.1, v1.22.2
6.3  v1.23.0, v1.24.0, v1.24.1, v1.25.0, v1.26.0, v1.26.1, v1.27.0, v1.28.0, v1.29.0, v1.30.0-preview
```

Every tag through `v1.25.0` is on the same side of the boundary the five directly-built rows
above establish, and every tag from `v1.26.0` on is on the other. **Not individually built:**
`v1.22.0`/`v1.22.1` (same release era as the confirmed-failing `v1.22.2`), `v1.23.0`/`v1.24.1`
(bracketed on both sides by confirmed-failing tags, same era of `emitinlinethumb.c`) — inferred
from the bisected boundary and the unchanged source, not separately verified. If that inference
is ever wrong for one of these four, this table is the place to correct it, not silently.

**Net: 9 of the 24 tags this project knows about (all of ABI 6.1, all of ABI 6.2, and the
`v1.23.0`-through-`v1.25.0` prefix of ABI 6.3) cannot build `mpy-cross` on this project's own
`natmod_host` image today.** `x64` and `x86` are both hit identically — this is a host *compile*
failure in `mpy-cross` itself, before any target-arch code is touched at all, so the [0068]
multilib fix (a link-time, `x86`-only problem) does nothing for it and could not have.

## What this does not affect

**The zero-config default build is untouched.** Natmod's default selects only the newest known
ABI (6.3, [0052]), and `newest_tag_for_abi()` resolves that to a tag well past the `v1.26.0`
boundary (`v1.29.0`/`v1.30.0-preview`). This only bites a config that explicitly selects an old
ABI or an old `v1.2x.0`-range 6.3 tag (`build = "mpy6.1-*"`, `build = "mpy6.2-*"`, or an explicit
old-tag pin once [0052]'s pin syntax exists) — exactly the scenario [0013] was exercising when
it first found this, by accident, on a bare host with no real gcc version pinned down.

## Confirmed to reach `windows` too, not just `natmod`

`usermod`'s `windows` port builds `mpy-cross` through `container_mpy_cross()` — a *host* tool
that must run on the machine doing the build, so it compiles with `docker/windows.Dockerfile`'s
own native `build-essential` gcc, not either of the two mingw cross-compilers the same image
also carries (`ENV PATH="${PATH}:/opt/llvm-mingw/bin"` **appends**, so `/usr/bin`'s native gcc
stays first and is what actually runs `make -C mpy-cross`).

`windows.Dockerfile`'s own `llvm-mingw` fetch layer failed to build in this sandbox (TLS
interception on the outbound proxy, a property of this session's own container per the
`docker-local` skill, not of the Dockerfile) — worked around by isolating the one relevant
layer: a throwaway `FROM ubuntu:26.04` + `apt-get install build-essential python3` image,
identical to `windows.Dockerfile`'s own first `RUN` and unaffected by the failed second one.
Confirmed: **same gcc, `15.2.0-16ubuntu1`** (same base image tag, same unversioned
`build-essential` package — deterministic), and **`v1.21.0`'s `mpy-cross` fails there with the
identical error**, same file, same line.

**Not confirmed, and worth checking before assuming either way:** `webassembly` (emsdk/Clang,
almost certainly unaffected — not a gcc build at all), `unix` (every cell is a pypa
`manylinux`/`musllinux` image with its own pinned devtoolset gcc, not this base image, so
likely unaffected the same way [0068]'s own audit found for everything except `natmod_host`/
`ppc64le_linux` — but not independently re-verified against `mpy-cross` specifically here),
`esp32`/`rp2` (their own per-port images, not inspected in this session at all).

## Not decided here

- Whether to suppress the warning (`-Wno-error=unterminated-string-initialization`) for the
  affected tag range, the same shape [0044] already used for `musllinux`'s `-Wno-error=cpp` and
  `manylinux_2_28_aarch64`'s `-Werror=array-bounds=` suppression — cheapest, but a per-tag-range
  CFLAGS rule that today exists only for `usermod` (`unix_extra_cflags()`), not for natmod's
  `build_mpy_cross()` or `windows`'s own `container_mpy_cross()` call.
- Whether to pin an older gcc for the affected native paths specifically (`natmod_host`'s `x64`,
  `windows`'s `container_mpy_cross()`), both of which are unpinned by design today — [0068]
  already made that choice deliberately for `natmod_host`, and this is the cost of it.
- Whether to just document these 9 tags as a known, unsupported range (README ⚠️-style, the same
  shape [0044] used for the two unix cells it descoped) and do nothing in code.
- `webassembly`/`unix`/`esp32`/`rp2` against the same 9-tag range — reasoned above as probably
  unaffected, not independently verified.

[0013]: 0013-micropython-list-dedup-by-abi.md
[0044]: 0044-unix-native-images-landed.md
[0068]: 0068-docker-dependabot-grouping-and-mipsel-ubuntu-26-04.md

## Addendum, 2026-09-03 — closing this record: what was chosen, what was verified, and the two numbers above that were wrong

### The four options under "Not decided here", resolved

1. **Suppress the warning for the affected tag range — chosen, and shipped.** [0084] landed it for
   `unix` alone (`build_common.TAG_CFLAGS`, keyed by tag, reaching both `container_mpy_cross()` and
   the port's own make); [0091] threaded the same table through every other port's own
   `container_mpy_cross()` call and make invocation, and moved the table itself out of a Python
   dict into `resources/tag_cflags.toml` ([0010]'s rule). This addendum completes the entries.
2. **Pin an older gcc for `natmod_host`'s `x64` / `windows`'s `container_mpy_cross()` — not taken.**
   The relaxation makes it unnecessary, and [0068] had already made the unpinned choice
   deliberately. Nothing about that changed.
3. **Document the tags as a known-unsupported range — not taken.** They build.
4. **`webassembly`/`unix`/`esp32`/`rp2` against the same range — verified, except `esp32`.**
   [0091] checked `webassembly`'s own `emcc` live (accepts the flags — not assumed from "Clang"),
   built `unix` live at `v1.22.2-manylinux_2_28_x86_64` with `examples/usercmodule`'s real C++, and
   built `rp2`'s own full `v1.20.0` firmware. `esp32` is still not exercised live: ESP-IDF's tool
   installer cannot fetch through this session's own proxy CA, which is a sandbox property, not an
   `esp32` finding. **And one image family this record never named at all was checked and does
   fail**: `arm_embedded`/`riscv_embedded`, in CI run `33697330722` — the seven `usermod` ports
   sharing that image plus `natmod`'s own arm/riscv cross arches.

### The scope number above is wrong: 18 of 24 tags, not 9

**"Scope against the real tag table" quoted `natmod.identifiers`' ABI 6.1/6.2/6.3 groups and
silently omitted ABI 5 (`v1.12`-`v1.18`) and ABI 6 (`v1.19`, `v1.19.1`) entirely.** Those nine tags
are real rows in `build-platforms.toml` — 8 identifiers each — and they are on the *failing* side of
the boundary this record bisected, not outside its reach. The evidence was already printed and not
read as such: [0091]'s own live table shows `mpy5-v1.18-armv7emsp` and `mpy6-v1.19.1-armv7emsp`
failing `mpy-cross` with exit 2, and both job logs carry the identical
`-Werror=unterminated-string-initialization` diagnostic in `py/emitinlinethumb.c`, confirmed by
re-reading that run's own log while closing this record rather than trusting its summary line.

**Source-level, across every tag rather than at the two ends** (`micropython/micropython`,
read directly): `py/emitinlinethumb.c`'s `reg_name_table` and `cc_name_table` carry exactly-filling
string initializers (`{10, "r10"}` into `byte name[3]`, `{ ASM_THUMB_CC_EQ, "eq" }` into
`byte name[2]`) unchanged from `v1.12` through `v1.25.0`, and `v1.26.0` replaces every one with a
char-array initializer (`{10, {'r', '1', '0' }}`). That is upstream's own fix, and it lands exactly
at the boundary this record bisected by building.

**So this record's own "not individually built" caveat is now settled, not still open.**
`v1.22.0`/`v1.22.1`/`v1.23.0`/`v1.24.1` were inferred from the boundary; they are now a source fact,
along with the other nine. Nothing in the table above needed correcting — only its scope.

### Two further diagnostics on the older nine, found by building rather than by reasoning

Adding `-Wno-error=unterminated-string-initialization` to the nine ABI 5/6 tags was not enough, and
the next two failures came one at a time out of a real `v1.18` build on `arm_embedded`:

- **`-Wno-error=dangling-pointer`.** `py/stackctrl.c`'s `MP_STATE_THREAD(stack_top) = (char *)&stack_dummy;`
  trips `-Werror=dangling-pointer=` on gcc 12+. Upstream's fix is a
  `#pragma GCC diagnostic ignored "-Wdangling-pointer"` guard added **in `v1.21.0`** — so
  `v1.12`-`v1.20.0` need the flag and `v1.21.0`+ do not, which is exactly the shape
  `tag_cflags.toml` already had for `v1.20.0` alone ([0084]) without anyone noticing the eight
  older tags on the same side of that boundary.
- **`-Wno-error=enum-int-mismatch`.** `mpy-cross/main.c` declares `uint mp_import_stat(const char *path)`
  against `py/lexer.h`'s `mp_import_stat_t` return type through `v1.19.1`; `v1.20.0` fixes the
  declaration. gcc 13+ makes that an error. This one is confined to exactly the nine tags.

**Neither flag can reach a Clang toolchain from these entries, checked rather than assumed**: the
only `usermod` ports with rows in the `v1.12`-`v1.19.1` range are `esp8266`, `cc3200`, `renesas-ra`
and `nrf` (`build-platforms.toml`, read directly) — all GCC, and none of them has a build driver
today ([0053]). `windows`' own `win_arm64` Clang and `webassembly`'s `emcc` have no rows there at
all, and `windows` probes its candidates anyway since [0091]'s own addendum.

### Live verification of the closure

`examples/template`, local Docker, `arm_embedded`: `mpy5-v1.12-armv7emsp`, `mpy5-v1.18-armv7emsp`
and `mpy6-v1.19.1-armv7emsp` each build end to end to a real `.mpy` — the first time any ABI 5/6
tag has built in this project at all — and `mpy6.3-v1.29.0-armv7emsp` still builds clean beside
them, from a clean object tree, as the regression check.

**Getting there needed three non-gcc fixes that are not this record's subject**, each a
pre-`v1.20.0` upstream layout fact this project had hardcoded the modern shape of: `mpy-cross`'s own
output path, `MPY_SUB_VERSION`'s absence, and the example Makefile's object scoping. They are
[0093], written separately, and they are the reason these nine tags had never built even before the
gcc 15 diagnostic existed.

[0010]: 0010-pinned-data-in-resources.md
[0053]: 0053-usermod-ports-without-a-build-driver.md
[0084]: 0084-per-identifier-toolchain-tarballs-and-the-end-of-shared-images.md
[0091]: 0091-tag-cflags-into-every-ports-mpy-cross.md
[0093]: 0093-pre-v1-20-0-tags-had-never-built.md
