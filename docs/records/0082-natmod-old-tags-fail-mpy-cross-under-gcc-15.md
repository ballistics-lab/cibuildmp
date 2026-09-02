# 0082 — nine MicroPython tags fail `mpy-cross` under gcc 15, on every image whose native compiler is unpinned — bisected exactly

Status: Proposed — the failure, its exact boundary, and its reach across `natmod`/`windows` are
confirmed; the fix is not chosen here.
Related: [0013], [0044], [0068]

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
