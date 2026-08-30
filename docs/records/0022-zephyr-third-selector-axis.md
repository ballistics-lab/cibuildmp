# 0022. zephyr is a third selector axis, not a board-based port that just needs its boards added

- Status: Accepted (zephyr itself not scheduled); phase outline M6-M9b substantially
  implemented, M8's own `rp2` gap closed by [0060]
- Related: [0007], [0016], [0017], [0060]

<!-- migrated verbatim from docs/BACKLOG.md lines 1164-1493 -->

**D22 — `zephyr` is a third selector axis, not a board-based port that
just needs its boards added, and has no reference implementation to
design against.** Checked directly against upstream
(`ports/zephyr/boards/`), not assumed: there is no `board.json` anywhere
in it — board selection is `<board>.conf` (a Kconfig fragment) plus an
optional `<board>.overlay` (devicetree), a flat per-board-name file pair
that is MicroPython's own zephyr-specific convention, unrelated to the
`board.json` shape **D7**'s vendored `board_database.py` scans for. The
"two selector axes" split above (board.json vs. `variant:`) does not have
a third slot for this — enumerating zephyr's boards means globbing
`boards/*.conf` directly, not extending the vendored scanner, since there
is nothing in that shape for the scanner to find.

`mpbuild` itself has no opinion here either: checked its `BUILD_CONTAINERS`
dict directly (the same one **D7**'s own addendum above transcribes for
`stm32`/`rp2`/`esp32`/…) — fifteen port keys, no `zephyr` among them. So
unlike the six ports **D16–D21** rest on (all live, all proven in
`a7p`'s `mp-usermod.yml`), zephyr has neither an existing composite
action nor a working consumer workflow to design the identifier/config
scheme against — the exact position natmod's own M0 was in before it had
`cibuildwheel` to reason from by analogy, except here there is no
analogous tool at all to lean on, mpbuild included.

Build tooling is a fourth story on top of **D3**'s `host`/`download`/
`docker`, not a variant of the three already known: `west` (Zephyr's own
meta-tool) driving CMake, which in turn expects a full Zephyr SDK /
module workspace on the machine — heavier than **D19**'s ESP-IDF case,
which at least resolves to one `--recursive` clone plus one installer
script; `west`'s own workspace model pulls in Zephyr's own multi-repo
manifest. `boards/manifest.py` does exist (confirms **D17**'s
default-manifest-per-port pattern generalizes here too), but whether
`CMakeLists.txt` accepts a `USER_C_MODULES`-style entry point the way
esp32/rp2040 do (**D16**) is unverified — not read yet, and should not be
assumed either way before it is.

Not scheduled, and deliberately left out of the **M6–M12** outline below
rather than folded into `boards.py`'s (D7) or the build driver's (M8)
work: doing either now would repeat the mistake D16–D21 just corrected
in this section, reasoning about a fourth axis as if it were already
understood before any of it has been read from `west`/CMake directly.
Revisit once a real consumer wants a zephyr usermod build, the same way
the six existing ports got their own findings from `a7p` actually driving
them rather than from reading upstream cold.

**Rough phase outline.** Still names-and-one-line for M7 onward, so they
don't get reasoned about before any code exists — the exact mistake
D16–D21 corrected above. M6 gets its first real checkbox, in M0–M5's own
style, now that a slice of it is actually implemented:

- **M6** — extend the **D7** vendored board/variant database with each
  port's default-manifest path and its Make-vs-CMake `USER_C_MODULES`
  shape (**D16**).
  - [x] `src/cibuildmp/usermod/boards.py`: `Port`/`Board`/`Variant`/
        `Database` + `check_board_json`, vendored from `mpbuild` commit
        `972d8319f90dd5a70e3ab6fd1660b9d5a01017fe` (v1.2.0) per **D7** —
        MIT header and provenance kept in the module's own docstring, not
        just here. `tests/test_boards.py` (13 cases, hermetic fixtures)
        plus a live check against a real `v1.28.0` checkout (M1's own
        `fetch_micropython()`, not a second fetcher): 13 ports, 215
        boards found; `zephyr` correctly absent from both (**D22** —
        confirmed live, not just read from upstream source); `unix`
        alone already has 5 real variants (`minimal`, `longlong`,
        `nanbox`, `coverage`, `standard`), more than the two this file's
        own "Two different selector axes" section illustrates.
  - [x] The two fields **D16**/**D17** ask for, kept as their own pinned
        table rather than folded into `boards.py`: `resources/usermod.toml`
        (`build-system` per port, `default-manifest` per port) +
        `usermod/portinfo.py` (`build_system()`, `default_manifest()`,
        `known_ports()`). Scoped to exactly the six ports **D16–D21**
        cover — `unix`, `webassembly`, `windows`, `qemu`, `esp32`, `rp2` —
        not every port MicroPython ships. Verified live against the same
        `v1.28.0` checkout as the boards.py slice above: grepped
        `USER_C_MODULES` in `py/py.mk` and `py/usermod.cmake` directly
        rather than trusting a composite action's doc comment (which
        corrected **D16**'s own "file, not directory" framing — see its
        own addendum above), and `find`-verified every `manifest.py` path
        on disk — which turned out not to be enough on its own: reading
        paths off the checkout alone concluded one shared file per port,
        which cross-checking against `a7p`'s real `mp-usermod.yml` then
        corrected again (per-variant/per-board overrides are real; see
        **D17**'s own addendum, now written twice, for the full story).
        `tests/test_portinfo.py` (10 cases) covers both accessors and the
        unknown-port error path. **Not** in this slice: the actual
        combined-`FROZEN_MANIFEST` generation this data feeds — that stays
        M7.
- **M7** — combined-`FROZEN_MANIFEST` generation + `USER_C_MODULES`
  resolution off that database (**D17**).
  - [x] `usermod/manifests.py`'s `combined_manifest(port, module_manifest)`
        and `usermod/portinfo.py`'s `resolve_user_c_modules(port,
        module_dir)`. Verified byte-for-byte against `a7p`'s own
        `mp-usermod.yml` — its `cat > manifest.py <<EOF ... EOF` bodies
        and `user_c_modules:` inputs, not just the paths already pinned in
        **D16**/**D17** — before writing either function, at the user's
        own request: that check is what caught the `default-manifest` bug
        one commit up (see **D17**'s own addendum), so it ran again here
        rather than trusting the now-corrected table alone.
        `tests/test_manifests.py` and the new cases in
        `tests/test_portinfo.py` assert the exact literal strings that
        workflow's own heredocs and `with:` blocks produce today, for
        every one of the six ports, `qemu`'s no-default-line case
        included.
  - [ ] Not in this slice: actually writing the combined manifest to a
        file and invoking a build with it (**M8**'s own job) — `M7` stops
        at generating the *text* and the *value*, the same string-in
        string-out shape `targets.py`'s own resolvers already have.
- **M8** — the build driver itself, for the ports that need no exotic
  provisioning first (`unix`, `windows` once MSYS2 is handled, `webassembly`,
  `qemu`/armv7m) — the natmod `build.py` shape, pointed at the composite
  actions' own recipes.
  - [x] `usermod/build.py`: `build_unix()`, for `x64`/`x86`/`aarch64` only.
        `UNIX_ARCH_SETTINGS` (`CROSS_COMPILE`/`link_opts`/`standalone` per
        arch) is transcribed from `.github/actions/build-usermod-unix`'s
        own case statement and cross-checked against a real `v1.28.0`
        `ports/unix/Makefile` directly — `CROSS_COMPILE`,
        `MICROPY_FORCE_32BIT`, `MICROPY_STANDALONE` are that Makefile's
        own variables, not the action's invention. `x86` reuses
        `toolchains.resolve("x86")` — natmod's own `-m32` multilib probe
        — rather than re-implementing detection, since "x86" means the
        same thing in both places. Output collection is a plain
        `$(BUILD)/micropython` path check (`PROG ?= micropython`'s own
        default), no globbing needed the way natmod's `.mpy` collection
        needs. `tests/test_usermod_build.py` (13 cases, hermetic,
        `subprocess.run` mocked the same way `tests/test_build.py`
        already does) plus a live build: a real `v1.28.0` checkout, `make
        -C ports/unix` run for real (not `--dry-run`), 40s, a genuine
        825768-byte linked binary.
  - [x] `armhf`/`mipsel` (**D24**): both apt-provisioned
        (`gcc-arm-linux-gnueabihf`/`gcc-mipsel-linux-gnu`, same
        `shutil.which()`-plus-named-package probe `aarch64`/`windows`
        already use), both verified live end to end — real `deplibs`
        run (a genuine static `libffi.a`, `MICROPY_STANDALONE=1`), real
        main build, a genuine linked `ARM`/`EABI5` and `MIPS32` ELF
        each with a real custom C module built in. `UNIX_RUNNABLE_ARCHS`
        now covers every arch `UNIX_ARCH_SETTINGS` pins — the
        `"not buildable yet"` branch `build_unix()` used to have is
        gone, unreachable once it did.
  - [x] `usermod/build.py`: `build_qemu()`, `MPS2_AN385` only. Reuses
        natmod's own `armv7m` toolchain (`toolchains.resolve("armv7m")`,
        `arm-none-eabi-`) rather than pinning a second copy —
        `ports/qemu/Makefile`'s default-board `CROSS_COMPILE` is exactly
        that prefix, verified directly against a real `v1.28.0` checkout.
        `ports/qemu/Makefile` also has RISC-V boards
        (`riscv64-unknown-elf-`, natmod's own `rv32imc`/`rv64imc`
        toolchain) — a real, cheap extension later, not attempted since
        nothing here exercises it yet. `CROSS_COMPILE=` is qemu's own
        variable name, not natmod's `CROSS=`, so this builds its own
        override from `chain.prefix` rather than reusing
        `ResolvedToolchain.make_overrides` (that property is
        `dynruntime.mk`-specific). Output is `$(BUILD)/firmware.elf`
        (`ports/qemu/Makefile`'s own `all:` target), no globbing needed,
        same shape as `unix`'s. 6 new hermetic cases in
        `tests/test_usermod_build.py` (19 total in that file) plus a live
        build: real `v1.28.0` checkout, `make -C ports/qemu` run for
        real, 44s, a genuine 321904-byte `firmware.elf` — and the
        toolchain it linked against was the exact
        `~/.cache/cibuildmp/toolchains/arm-none-eabi/15.2.1-1.1/` M2
        already downloaded for natmod earlier, confirming the reuse
        actually works end to end, not just past a mock.
  - [x] `usermod/build.py`: `build_webassembly()`, `pyscript` variant.
        The toolchain (`emsdk`) does not fit `toolchains.py`'s
        `ToolchainSpec`/`resolve()` shape at all — no `<prefix>gcc`
        binary, two directories need to land on `PATH`
        (`emscripten/` for the `emcc`/`em++` driver scripts,
        `bin/` for the LLVM/wasm binaries they invoke) — so
        `usermod/emsdk.py` is a small, dedicated resolver instead, reusing
        `sources.py`'s own `cached_dir`/`download_file`/`verify_sha256`/
        `extract_archive` primitives rather than duplicating them.
        Pinned to one resolved version (`resources/usermod.toml`'s
        `[emsdk]` table, `6.0.8`/`linux-x64` today) rather than floating
        on `latest` the way `build-usermod-webassembly`'s own
        `emsdk_ref: latest` default does — a deliberate divergence from
        that action, argued in the table's own header comment and tied to
        the **"Toolchain pinning vs. reproducibility"** open question
        below. Bypasses `emsdk`'s own installer (`git clone emsdk` +
        `./emsdk install/activate`) entirely: downloads
        Emscripten's own `wasm-binaries.tar.xz` release asset directly
        (`storage.googleapis.com/webassembly/emscripten-releases-builds/
        {os}/{hash}/...`, resolved from `emsdk`'s own
        `emscripten-releases-tags.json` at pin time, not at build time),
        the same "verify and switch to the standalone tarball" move M2
        already made for `xtensawin` vs. the full ESP-IDF installer.
        Verified live, not assumed: extracting the tarball and
        prepending `emscripten/`+`bin/` to `PATH` is sufficient on its
        own — `emcc`'s own `tools/config.py` auto-derives `LLVM_ROOT`
        (from `clang`) and `BINARYEN_ROOT` (from `wasm-opt`) by
        searching `PATH` when no `.emscripten` config file exists, so
        none needs writing. 5 hermetic cases in `tests/test_emsdk.py` (real
        `verify_sha256`/`extract_archive`/`cached_dir` exercised against
        a small fake tarball, not mocked away) + 5 more in
        `tests/test_usermod_build.py`, plus two separate live checks: a
        real ~300 MiB download+extract+verify of the pinned tarball
        through `resolve_emsdk()` itself, and a full
        `build_webassembly()` run against a real `v1.28.0` checkout — 31s,
        a genuine `micropython.mjs` (217344 bytes, byte-identical to an
        earlier manual PATH-only proof done before any of this code
        existed) plus its `.wasm` — through the actual production code
        path, not the manual proof.
  - [x] `windows` — `usermod/build.py`'s `build_windows()`, one function
        dispatching per arch (`WINDOWS_ARCH_SETTINGS`), all three (`x64`/
        `x86`/`arm64`) now cross-compiling from a plain `ubuntu-latest`
        host, no Windows runner or MSYS2 for any of them: `x64`/`x86` via
        an apt-installed mingw-w64 GCC, `arm64` via a downloaded
        `llvm-mingw` toolchain (`usermod/llvmmingw.py`) — no Linux distro
        packages a GCC targeting `aarch64-w64-mingw32` at all, and
        `llvm-mingw` is the one alternative mingw-w64's own documentation
        names. Three approaches investigated in sequence, not assumed
        away, each corrected by the next live finding rather than
        guessed past — see **D18**'s own addenda for the full history:
        MSVC (no `USER_C_MODULES`/`FROZEN_MANIFEST` hook at all, ruled
        out for every arch), MSYS2 for all three arches (worked, proven
        live on real `windows-latest` CI), narrowed to `x64`/`x86`
        cross-compiling from Linux once upstream's own CI showed that
        works too (`arm64` kept on MSYS2 at that point — reasoned to be
        an acceptable gap, which was wrong, corrected the same session
        once a real consumer requirement was stated directly), then
        `arm64` itself moved off MSYS2 once `llvm-mingw` was confirmed
        live to build it from Linux too, with the exact Clang-vs-GCC
        `CFLAGS_EXTRA` fixes that took.
  - [x] `rp2` — was **not started** as of this bullet's original text
        below (kept verbatim as the historical record of the gap); closed
        2026-08-29 by [0060]'s own `build_rp2()`, live-verified against a
        real `examples/template` build producing a genuine `firmware.uf2`
        — see that record for the resolver and the submodules-provisioning
        finding it took. Original gap description, for the record:
        a real gap flagged directly rather than
        left implicit: **M6**'s own `resources/usermod.toml`/
        `usermod/portinfo.py` slice already scoped `rp2` in (its
        `build-system = "cmake"`/`default-manifest = "boards/manifest.py"`
        pins exist, target selection is ready), but no `build_rp2()` ever
        got written — no Pico SDK resolver, no live verification, not
        attempted this session. Caught only when the README's own
        "Target support" table was checked against a real count of
        upstream's ports (20, not the 6 this project scopes to) and it
        turned out the table itself had silently dropped the one port
        that was scoped in but never driven — worth recording as a
        reminder that a summary table can go stale exactly the same way
        code does, not just be written once and trusted.
- **M9** — toolchain provisioning: ESP-IDF fetch + caching, `docker`
  strategy revisit for it (**D19**). MSYS2's own D18 role (windows
  provisioning) ended up superseded entirely — see the `windows` bullet
  above and **D18**'s own addenda.
  - [x] ESP-IDF side: `usermod/espidf.py` (`fetch_esp_idf()`,
        `resolve_esp_idf()`, `ResolvedEspIdf.env()`) + `usermod/build.py`'s
        `build_esp32()`, driving `ports/esp32` the same way the other
        three ports already do. `docker` revisited and dropped for real
        reasons, not left unexamined — see **D19**'s own addendum for the
        live verification (Docker does not run in this project's dev
        sandbox at all; the official clone+install recipe works there
        directly) and the `libusb`/`openocd-esp32` finding that looked
        like a Docker argument on first read and was not one. Both the
        clone and the toolchain+Python-env install are now cached, the
        real gap D19 flagged. 12 hermetic cases across
        `tests/test_espidf.py` and `tests/test_usermod_build.py`, plus a
        full live build: real `v5.5.1` ESP-IDF, `make -C ports/esp32
        BOARD=ESP32_GENERIC`, a genuine `micropython.bin` — through the
        official recipe run by hand first, then again through the actual
        `espidf.py`/`build_esp32()` code path.
  - [x] `windows` toolchain provisioning (**D18**), final state:
        `usermod/llvmmingw.py` (`resolve_llvm_mingw()`, pinned in
        `resources/usermod.toml`'s own `[llvm-mingw]` table, same
        `cached_dir`/`download_file`/`verify_sha256` shape `emsdk.py`
        already uses) for `arm64`; `x64`/`x86` need no dedicated resolver
        at all, just a `shutil.which()` PATH probe for an apt-installed
        `<prefix>gcc` (`build.py`'s own `_resolve_windows_toolchain`
        logic, inlined into `build_windows()`). MSYS2 (`usermod/msys2.py`)
        did real, credited work before being fully superseded: its own
        `usermod-dev.yml` `windows` job (a plain on-push scratch workflow,
        no PR — MSYS2 could not be verified in a Linux sandbox at all)
        caught and fixed four real bugs across its runs before this
        supersession — `usermod/build.py`'s `Path` handling used bare
        `str()`, which is backslash-separated on Windows and breaks any
        GNU Make invocation (fixed to `.as_posix()` everywhere, still the
        rule for every port here); two of `test_emsdk.py`'s own tests
        were silently coupled to the CI host actually being linux-x64;
        `tests/test_build.py`'s own
        `test_pre_build_command_runs_in_module_root` used `touch`, which
        `cmd.exe` has no equivalent for (fixed to `echo hi > marker`);
        and `ResolvedMsys2.to_posix_path()`'s own first-login-shell
        skeleton-banner bug (**D18**'s own addendum has the detail). None
        of these were "not this work's problem" — a bug found while doing
        this work got fixed as part of it, whoever's line it originally
        was. 13 hermetic cases across `tests/test_usermod_build.py` for
        the final `windows`/`x64`/`x86`/`arm64` shape, plus the live
        proofs **D18**'s own addendum records for all three arches.
- **M9b — CLI/config wiring (D23): the five usermod build drivers
  (unix/windows/qemu/webassembly/esp32) are reachable from the actual
  `cibuildmp` CLI now, not just from Python.** Not anticipated when the
  M9-M12 sequence above was first written (README's own "no `--mode
  usermod` entrypoint yet" caveat was still true at the start of this
  slice) -- inserted here rather than renumbering M10-M12, since those
  three describe later work this one is a real prerequisite for, not
  work this one replaces.
  - [x] `usermod/targets.py`: `UsermodTarget` (`{port}` or
        `{port}-{arch}`, no `.mpy` ABI axis at all -- **D23** explains
        why that axis doesn't apply here), a `port -> (axis config key,
        default axis values)` registry, `usermod_targets()`/`select()`.
  - [x] `usermod/options.py`: `[usermod]` config table (+ per-port
        `[usermod.<port>]` sub-tables for the real axis, `archs` or
        `boards` depending on the port) -- **D5**'s own "config scoped
        by build mode" precedent, genuinely followed a second time
        rather than just cited.
  - [x] `usermod/orchestrate.py`: resolves a target's `UsermodBuildOptions`
        into the port-specific `*BuildOptions` `usermod/build.py` already
        has (`user_c_modules` via `portinfo.resolve_user_c_modules()`,
        a combined manifest via `manifests.combined_manifest()` written
        to a real file, a per-identifier `build_dir`), calls the
        matching `build_<port>()`, collects the result into
        `output-dir/<identifier>/` -- no `package.json` (**D23**).
  - [x] `cli.py`: `detect_mode()` auto-picks `natmod`/`usermod` from
        which top-level table the config has, `--platform` becomes its
        explicit override (only needed when a config genuinely defines
        both) rather than the natmod-only stub it was before. No
        config and no table at all still defaults to `natmod`,
        unchanged, so every existing consumer's behaviour is untouched.
  - [x] `usermod/cli.py`: the usermod half of `main()`'s own dispatch --
        `--dry-run`/`--only`/`--print-build-identifiers`/
        `--print-build-matrix`/`--allow-empty`, all working the same
        way they already do for natmod.
  - [x] Verified live, end to end, not just against the hermetic suite:
        a real `[usermod]` config (`ports = ["unix"]`), a real custom
        `mymod` C module, run through the actual `cibuildmp` CLI (no
        mocking) -- fetched v1.28.0 for real, ran the real `make`,
        produced a genuine linked `unix-x64` binary, collected it into
        `mpyhouse/unix-x64/`, and running it directly confirmed the
        custom module actually works: `import mymod; mymod.hello()` ->
        `42`.
  - Deliberately not done in this slice, flagged rather than silently
    skipped: no `[[overrides]]` glob mechanism for usermod yet (the
    per-port option shapes are not uniform enough to reuse natmod's own
    unmodified), no `extra-files`/`pre-build-command` equivalents, no
    `CIBMP_*` environment overrides for `[usermod]`'s own keys beyond
    the genuinely shared `micropython`/`output-dir`, and `--archs`/
    `--toolchain` stay natmod-only (a usermod target's axis is
    config-only; toolchain resolution always goes through whatever each
    `build_<port>()` already does internally).
