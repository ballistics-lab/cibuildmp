# 0025. Both Dockerfiles now bake in every unix cross toolchain — six real apt/gcc bugs

- Status: Implemented
- Related: [0024], [0026], [0028]

<!-- migrated verbatim from docs/BACKLOG.md lines 1617-1795 -->

**D25 — both Dockerfiles now bake in every `unix` cross toolchain
(`aarch64`/`armhf`/`mipsel`) closing D23/D24's own open item, and the
first real `docker build` of either image (neither had ever actually
been built before this -- both predate real usermod CLI usage
entirely) surfaced six genuine, non-obvious apt/gcc problems no amount
of reading package lists would have caught -- one of them (the
`i386-linux-gnu` symlink) initially "fixed" wrong and only caught by a
later, unrelated real build failure, and two of them (`libc6-dev-<arch>-cross`,
`libtool`) sharing the exact same root shape: a package only
`Recommends:`, not `Depends:`, what `--no-install-recommends` then
silently drops -- and both masked, at first, by this project's own dev
sandbox happening to have them installed from unrelated earlier work.** `examples/usermod-unix`
(a real `USER_C_MODULES` module, `cibuildmp.toml` defaulting to all
five `unix` arches) wired into `build-examples.yml`'s own `uses: ./`
step is what proved it -- this project's dev sandbox has no Docker
daemon at all (**D19**'s own finding), so every ingredient was
verified individually there and the actual `docker build` had to run
for real on CI, exactly the same "only a real build catches this"
lesson **D18**'s own `action.Dockerfile`-location bug already taught.

- **`gcc-multilib` unconditionally `Conflicts:` every single
  `gcc-N-<target>-linux-gnu` cross-compiler package, every GCC major
  version 4.9 through 15** -- confirmed directly from `apt-cache show
  gcc-multilib`'s own `Conflicts:` field, not a resolver quirk a
  differently-ordered `apt-get install` would sidestep: installing
  `gcc-multilib` after the cross packages are already present offers
  to *remove all three of them*. This dev sandbox never surfaced it
  while every individual cross-compiler was being verified earlier
  (**D20**/**D24**) because `gcc-multilib` itself was never actually
  installed there at all (`dpkg -s gcc-multilib` said so directly) --
  only the versioned sub-packages from separate, earlier installs.
  Fix: `gcc-13-multilib` (the real, versioned package `gcc-multilib`
  itself only wraps) carries no such `Conflicts:` and provides the
  identical `-m32` support -- verified live, installed alongside all
  three cross packages in one transaction with no conflict, then a
  real `gcc -m32` compile-and-run.
- **`gcc -m32` cannot find `<asm/errno.h>` after that substitution**
  -- a second, separate real failure, this time inside natmod's own
  `x86` arch build (`examples/template`), not usermod at all: `gcc -m32
  -E -v`'s own header search list names `/usr/include/i386-linux-gnu`
  as a search directory (`gcc -m32 -print-multiarch` names the same
  path) but no apt package actually creates it by default -- gcc simply
  skips the nonexistent directory and fails to find the header at all.
  First fix tried: `ln -sf /usr/include/x86_64-linux-gnu
  /usr/include/i386-linux-gnu` -- confirmed live, a real `-m32` compile
  and run succeeding immediately after. **Later found wrong** -- see
  the next bullet -- and replaced.
- **`unix/x86`'s own `modffi.c` (`MICROPY_PY_FFI`) needs `pkg-config`
  and the *native* `libffi-dev`, not just the target-arch
  `libffi-dev:arm64` already installed for `aarch64`/`armhf`/`mipsel`**
  -- a third real failure, `fatal error: ffi.h: No such file or
  directory`, caught only once `examples/usermod-unix` started
  exercising `unix/x64` inside the real Docker image (nothing needed
  `libffi-dev` at all before usermod's own unix arches built here for
  the first time). Two combined gaps: plain `libffi-dev` (native amd64)
  had never been added, only the `:arm64` one; and
  `ports/unix/Makefile`'s own `LIBFFI_CFLAGS`/`LIBFFI_LDFLAGS` resolve
  via `pkg-config --cflags/--libs libffi` (confirmed directly from the
  real cached `Makefile`), so even with `libffi-dev` present, no
  `pkg-config` on the image left those flags empty. Fix: add both
  `libffi-dev` and `pkg-config`.
- **The `i386-linux-gnu` symlink above was itself wrong, not just
  incomplete -- a fourth real failure, on `unix/x86` specifically,
  once `pkg-config`/`libffi-dev` made `modffi.c` actually reach
  `ffi.h`:** `#warning ... X86 IS DEFINED [-Werror=cpp]` out of
  libffi's own `ffitarget.h`, turned fatal by `-Werror`. Root cause:
  libffi's `ffitarget.h` is genuinely word-size/ABI-specific (it
  encodes the target's calling convention), so serving the *64-bit*
  package's `ffitarget.h` under a 32-bit `-m32` compile is a real
  correctness bug, not a missing-file one -- it happened to compile
  (with warnings) rather than silently miscompiling, only because
  `-Werror` was on. The symlink's only genuinely correct job was
  `asm/errno.h` (Linux UAPI kernel headers, which *are* arch-generic
  enough for this to be harmless); it was never the right tool for
  `ffi.h`. Fix, verified live end-to-end (a real `unix/x86` build with
  a custom C module, run and returning the right value): drop the
  symlink entirely, and instead
  `dpkg --add-architecture i386 && apt install libffi-dev:i386
  linux-libc-dev:i386`. Unlike `arm64`, `i386` is **not** a "ports"
  architecture -- it already lives on the regular
  `archive.ubuntu.com`/`security.ubuntu.com` mirrors (confirmed live:
  `apt-cache madison libffi-dev:i386` resolved there directly, no
  `ports.ubuntu.com` stanza needed), so this only widens the existing
  stanzas' own `Architectures:` line to `amd64,i386`, the same stanzas
  `arm64`'s own fix above already restricts to `amd64`.
  `linux-libc-dev:i386` is what actually ships a real, arch-correct
  `asm/errno.h` under `i386-linux-gnu/` -- the symlink's one genuine
  job, now done by a real package instead of a borrowed path.
- **A fifth real failure, on `unix/aarch64` -- the first arch past the
  two x86 fixes above to ever actually reach its own compiler in
  either image:** the same `fatal error: asm/errno.h`, this time out
  of the *cross* compiler (`aarch64-linux-gnu-gcc`), not `-m32`.
  Root cause: `gcc-aarch64-linux-gnu` only `Recommends:` its own
  `libc6-dev-arm64-cross` (confirmed via `apt-cache depends`), not a
  hard `Depends:` -- and both Dockerfiles use
  `apt-get install --no-install-recommends` throughout, which silently
  skips it. The cross-compiler itself still installs and runs; only
  the target's own kernel/libc headers are missing, so anything
  touching `<asm/errno.h>` (most of `ports/unix`) fails to even
  preprocess -- link-time problems would have been obvious immediately,
  a missing-header compile failure only shows up once a real build is
  attempted. `gcc-arm-linux-gnueabihf`/`gcc-mipsel-linux-gnu` carry the
  identical gap (`libc6-dev-armhf-cross`/`libc6-dev-mipsel-cross`,
  same `Recommends:`-not-`Depends:` shape) -- neither `armhf` nor
  `mipsel` had been reached yet in either image (`aarch64` fails
  first, alphabetically/list-order before them), so this was caught
  and fixed for all three at once, not discovered arch-by-arch.
  Verified live end to end for all three: purged the cross-libc
  packages, reproduced the exact failure reinstalling with
  `--no-install-recommends` alone, then fixed it by naming
  `libc6-dev-arm64-cross`/`libc6-dev-armhf-cross`/
  `libc6-dev-mipsel-cross` explicitly (each pulls its own
  `linux-libc-dev-<arch>-cross` as a hard `Depends`, so naming these
  three is enough) -- followed by a full real `unix/aarch64`,
  `unix/armhf`, `unix/mipsel` build each, with a custom C module, three
  genuine linked binaries (`ARM aarch64`, `ARM armhf`, `MIPS32`) with
  no header errors at all.
- **A sixth real failure, on `unix/armhf`'s own `deplibs` step,
  immediately past the fifth fix landing on real CI:** `libtoolize: No
  such file or directory`, then (once `libtoolize` itself is on PATH
  but never actually invoked to regenerate the vendored `lib/libffi`
  tree's own macros) `Makefile.am:39: error: Libtool library used but
  'LIBTOOL' is undefined`. Exactly the same shape as the fifth bug,
  one package over: `libltdl-dev` only `Recommends:` `libtool`
  (confirmed via `apt-cache depends`), not a hard `Depends:` --
  `--no-install-recommends` skips it. This project's own dev sandbox
  already had `libtool` installed from unrelated earlier work in this
  session, which is exactly why **D24**'s own `armhf`/`mipsel` live
  verification (and this very D25 entry's fifth-bug verification,
  above) looked complete at the time -- neither ever actually
  exercised a sandbox without it. Caught for real only once a
  genuinely libtool-free image (the real `docker build`/`docker run`
  from the previous commit) tried the same step. Verified live the
  same rigorous way this time, specifically to avoid repeating the
  false-positive: purged `libtool`, *and* deleted the already-generated
  `lib/libffi/configure` this session's own earlier runs had left
  behind (its own Makefile rule only regenerates `configure` when it is
  missing or older than `autogen.sh` -- reusing a stale, already-good
  `configure` is exactly how the first "live verification" of this
  fix silently proved nothing), reproduced the exact CI failure,
  installed `libtool`, deleted the stale `configure` again, and only
  then confirmed a genuine fresh `unix/armhf` and `unix/mipsel` build
  each -- two real statically-linked binaries (`ARM EABI5`, `MIPS32`)
  with the custom C module built in.
- All six fixes are Dockerfile-only, not `cibuildmp` itself: none
  affect a bare `ubuntu-latest` runner running the CLI directly
  (**M9b**'s own live verification, and every `build-examples.yml` run
  before this one, already exercised `gcc -m32` successfully outside
  Docker) -- only these two custom images, which now need
  `gcc-13-multilib`, `libffi-dev`, `pkg-config`, the real `:i386`
  packages (not a symlink), the three `libc6-dev-<arch>-cross`
  packages, and `libtool` -- everything `--no-install-recommends` was
  silently dropping -- to combine x86 multilib support with three
  cross-compilers in one filesystem. README's own bare-metal install
  instructions get the same fixes, at the point a reader would
  actually hit them -- though a reader running a plain `apt install`
  (recommends on by default) would never have hit the fifth or sixth
  bug at all; both are purely a consequence of
  `--no-install-recommends`, which only these two Dockerfiles use.
- **cibuildwheel's own answer to "many architectures, one toolchain
  set" is structurally different, not comparably fixed** -- asked and
  answered directly, not assumed: cibuildwheel never combines
  cross-compilers in one image at all. Linux wheels build inside one
  container *per target architecture* (`manylinux_x86_64`,
  `manylinux_aarch64`, ...), each with only its own architecture's
  native toolchain; non-x86 targets on an x86 runner go through QEMU
  user-mode emulation (registered via `docker/setup-qemu-action` on
  GitHub Actions) rather than cross-compiling, so the *emulated*
  container's own gcc is always native to what it's building for.
  macOS wheels build natively via one Xcode toolchain's own
  `-arch x86_64 -arch arm64` (`universal2`), no container or conflict
  surface at all. `cibuildmp`'s own choice -- real cross-compilation
  from one x86_64 host, not a container/QEMU per target -- is
  deliberate (**D2**/**M2**'s own "why not docker for x86" reasoning:
  MicroPython's build is light enough that cross-compiling beats
  emulation) and it is exactly what both bugs above are the real,
  concrete cost of; not a flaw unique to this project's own approach,
  a structural tradeoff already made with eyes open.
