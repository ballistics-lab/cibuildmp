# 0042 — `windows` wired to Docker; the last two host-side toolchain resolvers deleted

Status: Implemented

Closes the `windows` half of [0032]'s named gap ("`windows`/`qemu` never wired to
`ensure_image()`, despite [0030]'s Docker-only mandate — their `PORT_IMAGES` entries
are registered but currently dead code"). `qemu` is untouched and still bare-host;
that half of [0032] stays open.

## What was wrong

`dockerrun.PORT_IMAGES` had carried `windows-x64` and `windows-x86` entries since
[0033]'s publish run, and nothing ever read them: `build_windows()` still took the
bare-host path for every arch. Concretely that meant

- `x64`/`x86` — a `shutil.which("<prefix>gcc")` probe against the host's `PATH`, with
  an `apt install gcc-mingw-w64-…` hint when it missed;
- `arm64` — `llvmmingw.resolve_llvm_mingw()`, a real download of a ~600MB tarball onto
  the host per fresh cache, into `~/.cache/cibuildmp/`.

[0030]'s call is that a bare-host usermod build is exactly the persistent host mutation
containers exist to avoid, and it left no exception for this port.

## What changed

`build_windows()` now resolves `dockerrun.ensure_image("windows", opts.arch)` and runs
its existing `make` command list through `dockerrun.run()`, the same shape
`build_unix()`/`build_webassembly()` already had. No `libc` argument: [0031]'s
manylinux/musllinux axis is real for `unix` alone — there is no second Windows libc a
binary could be linked against — so all three arches key on `(port, arch)` only, and
all three share the one combined image [0028] step 3 already designed.

Both halves of the bare-host path are gone, `shutil` and `llvmmingw` with them.
`WindowsArchSettings` also lost its `apt_package` field, which nothing reads any more —
matching what `UnixArchSettings` already did when `unix` went Docker-only.

`docker/windows.Dockerfile` gained the llvm-mingw tarball as a baked layer, pinned to
the same version/URL/sha256 the deleted resolver read, exactly the way
`webassembly.Dockerfile` already bakes emsdk.

### The `ENV PATH` ordering is load-bearing

Found live, not reasoned about, and worth recording because the failure would have been
silent: llvm-mingw's own `bin/` ships `x86_64-w64-mingw32-gcc` and
`i686-w64-mingw32-gcc` wrapper names too, both really Clang. Prepending its directory
therefore shadows the apt mingw-w64 GCC for `x64`/`x86` as well — those two arches would
have quietly stopped being "the exact toolchain upstream MicroPython's own CI uses"
([0018]) and started being Clang, without any of the three `-Wno-*` suppressions or the
`COMPILER_TARGET=mingw-forced` that `WINDOWS_ARCH_SETTINGS` gives `arm64` alone.
The Dockerfile appends instead, and each prefix was checked with `command -v` inside a
real container rather than trusted to the ordering.

## Deleting `emsdk.py` and `llvmmingw.py` rather than keeping them

The first pass kept both resolvers as "the pin of record", on the precedent that
`emsdk.py` had already been kept as an uncalled module when `webassembly` moved into a
container. The user's call overrode that, and it is the better end state: with the last
caller gone, an uncalled resolver plus a TOML table only that resolver read is two
vestiges, not one pin.

So both modules are deleted, `tests/test_emsdk.py` with them, and the `[emsdk]` and
`[llvm-mingw]` tables are gone from `resources/usermod.toml` — which is otherwise
untouched, `[port.*]` (read by `portinfo.py`) being its only remaining content.

The pins did **not** disappear with them. Each port Dockerfile's own `RUN curl … |
sha256sum -c -` step already contains the version, URL and sha256 literally, so it
becomes the pin of record, and the provenance those TOML tables carried was migrated
into the Dockerfile headers rather than dropped: the emscripten-releases alias/hash/URL
template and the "no checksum sidecar published" note into `webassembly.Dockerfile`,
the mingw-w64-docs citation and the live-verification result into `windows.Dockerfile`.
The one piece that did *not* belong in a Dockerfile — why `arm64` needs three specific
`-Wno-*` flags and the `COMPILER_TARGET`/`STRIP`/`SIZE` overrides — moved into
`WINDOWS_ARCH_SETTINGS` next to the flags themselves, where it is Make-level detail
rather than a download pin.

`usermod/espidf.py` is now the last host-side resolver here, and says so in its own
header. It survives only because `esp32` still has no image at all ([0028]'s unstarted
`esp32.Dockerfile`); when it gets one, this module follows the other two.

## Verification

Real builds, not mocks: a v1.28.0 checkout and `examples/template` (whose
`module-dir = "."` is what puts `src/` inside the single `USER_C_MODULES` bind mount),
driven through `build_windows()` itself against a locally built image.

| arch | result |
| --- | --- |
| `x64` | `PE32+ … x86-64`, 11 sections |
| `x86` | `PE32 … Intel i386`, 10 sections |
| `arm64` | `PE32+ … ARM64`, 14 sections |

Re-run afterwards against the *published* image as a credential-less consumer sees it,
which is the part a locally built tag cannot prove: every local copy deleted, `docker
logout ghcr.io`, no `CIBMP_WINDOWS_*_DOCKER_IMAGE` override, so the only thing naming an
image was `PORT_IMAGES`' own digest. `x64` and `arm64` both pulled anonymously and built
a correct PE.

Each also had `build-*/usermod/template_usermod.o` present (the example's own
translation unit really compiled and linked, not just a stock binary) and its `template`
qstr in both `genhdr/qstrdefs.generated.h` and the linked `.exe`. A `strings` grep for
C symbol names is *not* a valid check here — these binaries are stripped to an external
PDB, so the symbol names are legitimately absent and the qstr pool is what proves
linkage.

The 258-test suite, `ruff check` and `ruff format` are green. Ruff caught one real thing
the test run could not: a duplicate `test_windows_build_failure_names_the_command`,
where the surviving bare-host copy was being silently shadowed by its replacement.

## Still open

- **The rebuilt image was pushed by hand, not by `publish-docker-images.yml`.** All
  three `windows` keys are pinned to
  `sha256:0adc927c7a837b1f58a74f52586bfc323a84bd66ba42bbc3ae8e5124e8062ba6`, which is a
  manual `docker push` of the llvm-mingw-bearing image, not a workflow artifact. That
  is the exception, not a new cadence — [0033] still owns publishing, and a later run
  of that workflow against the same Dockerfile should be reconciled against this pin
  (an identical rebuild will not necessarily produce an identical digest, so expect to
  re-pin rather than to confirm).
- `examples/template`'s `[usermod] ports` is still `["unix", "webassembly"]`. Adding
  `"windows"` is what would make `build-examples.yml` exercise this path on every push,
  and should follow the digest update rather than precede it.
- The GHCR packages are **public** as of this record — checked live (unauthenticated
  manifest fetch returns `200` for `unix-manylinux-x64`, `windows`, `qemu` and
  `webassembly`), correcting the "these packages are private" note `dockerrun.py` had
  carried since [0033]'s publish run.

[0018]: 0018-windows-provisioning-fourth-story.md
[0028]: 0028-container-per-port-migration-plan.md
[0030]: 0030-container-approach-natmod-and-docker-vs-qemu.md
[0031]: 0031-unix-musllinux-libc-axis.md
[0032]: 0032-unix-docker-default-and-webassembly-wiring.md
[0033]: 0033-cibuildmp-never-builds-docker-image-itself.md
