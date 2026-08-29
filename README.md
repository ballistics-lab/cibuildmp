# cibuildmp

Build MicroPython native C extensions for every target they support, from
one declarative config — on CI and on your own machine. `cibuildwheel`, for
MicroPython.

Covers **natmod** (dynamically loadable native `.mpy` modules, built against
`py/dynruntime.mk`) and **usermod** (`USER_C_MODULES`, compiled straight
into a port's own firmware build) C extensions.

## Why

MicroPython gives a native C extension two standard, unrelated build paths:

- **natmod** — `natmod/Makefile` includes MicroPython's own
  `py/dynruntime.mk`, parameterised by `ARCH=`. Produces a runtime-loadable
  `.mpy` per target architecture. See MicroPython's own `examples/natmod/`.
- **usermod** — `usermod/micropython.cmake` + `usermod/micropython.mk`,
  pointed at via `USER_C_MODULES=` on a port's own build. Compiled straight
  into the firmware image. See MicroPython's
  [`docs/develop/cmodules.rst`](https://docs.micropython.org/en/latest/develop/cmodules.html).

[`ballistics-lab/micropython-bclibc`](https://github.com/ballistics-lab/micropython-bclibc),
[`o-murphy/micropython-wasm3`](https://github.com/o-murphy/micropython-wasm3)
and [`o-murphy/a7p`](https://github.com/o-murphy/a7p) each already follow
that layout — that part was never the problem. What diverged was the CI
*around* it: each repo's own GitHub Actions workflow was hand-copied into
the next and then evolved independently, so the same ~10-architecture
build matrix and the same toolchain-install steps ended up as three
separate, slowly drifting copies. `cibuildmp` is the shared home for the
parts that are genuinely identical across all three, resolving each
target's cross-toolchain itself instead of leaving it hand-written per
repo, the same way locally and on CI.

## Quick start

Install it from PyPI and point it at a module with a `cibuildmp.toml`:

```console
$ uv tool install cibuildmp
$ cibuildmp --build "mpy6.3-*" --dry-run
cibuildmp: 10 target(s) against MicroPython v1.29.0
  [ 1/10] mpy6.3-v1.29.0-x86           make -C natmod ARCH=x86 dist
  [ 2/10] mpy6.3-v1.29.0-x64           make -C natmod ARCH=x64 dist
  ...
```

An unconfigured `build` matches nothing at all, from any platform — see
[Identifiers and selectors](#identifiers-and-selectors) below for the full
identifier list and glob syntax. Drop `--dry-run` and it builds for real:
each target lands in its own `output-dir/<identifier>/` directory
(`mpyhouse/mpy6.3-x64/`, …), with a `package.json` mip can install from
once `version` is set.

**`cibuildmp` needs a reachable Docker daemon on whatever host runs it.**
It never builds an image itself — it pulls pre-built, pinned images
(`ghcr.io/ballistics-lab/<target>`) and launches sibling containers, one
per target, the same way cibuildwheel's own container runtime does. That
covers natmod (a single `docker/natmod.Dockerfile` for all ten arches) and
every usermod port, `esp32` included — only the ESP-IDF `git clone` itself
stays on the host (source, not a binary, the same reasoning `mpy_dir`
mounts straight in everywhere else); installing ESP-IDF's own tools and
building both run inside `esp_idf_base`. There is no
"run `cibuildmp` itself inside Docker" story any more — a previous root
`Dockerfile` offered that and was deleted once usermod needed to launch
sibling containers of its own (Docker-in-Docker was ruled out); `uv tool
install cibuildmp`/`pip install cibuildmp` directly is the one supported
way to run it outside CI.

A non-native target (anything other than your own machine's architecture)
also needs an emulator registered: `docker/setup-qemu-action@v4` on CI, or
once per machine locally, `docker run --privileged --rm tonistiigi/binfmt
--install all`. `cibuildmp` names the missing emulator up front rather
than letting the build fail with `exec format error`.

On CI, use the action instead of installing the CLI yourself — it already
runs on a bare runner with the runner's own Docker daemon reachable:

```yaml
- uses: ballistics-lab/cibuildmp@v0.3.0
  with:
    build: "mpy6.3-* v1.29.0-manylinux_2_28_x86_64"
```

See [`examples/template`](examples/template) for a minimal natmod module
and its `cibuildmp.toml`, and [`examples/wasm2mpy`](examples/wasm2mpy) for
one whose native source is WebAssembly, compiled through `wasm2c` — the
natmod contract doesn't care what produced the C. `cibuildmp --help` lists
every flag; `CIBMP_*` environment variables and a `[tool.cibuildmp]` table
in `pyproject.toml` both work as config overrides too.

## Identifiers and selectors

Every buildable thing — one natmod arch, one usermod port/board/arch cell —
has a real, stable **identifier**, read straight from
`resources/build-platforms.toml` (never guessed or reconstructed from a
format string). `build`/`skip` (config, `CIBMP_BUILD`/`CIBMP_SKIP` env
vars, or `--build`/`--skip` on the CLI) are space-separated glob patterns
matched against these identifiers, `skip` applied after `build`; an
`[override."<glob>"]` table applies option overrides to whichever
identifiers match its own glob. There's no other selection mechanism — no
per-platform table, no `--platform`/`--only` flag, no `auto`/`native`/`all`
keyword vocabulary. **An unconfigured `build` selects nothing, from any
platform.**

Identifier shapes, one per platform:

| Platform              | Shape                   | Example                         |
| --------------------- | ----------------------- | ------------------------------- |
| natmod                | `mpy{abi}-{tag}-{arch}` | `mpy6.3-v1.29.0-armv7emsp`      |
| usermod `unix`        | `{tag}-{arch}`          | `v1.29.0-manylinux_2_28_x86_64` |
| usermod `windows`     | `{tag}-{arch}`          | `v1.29.0-win_amd64`             |
| usermod `webassembly` | `{tag}-{arch}`          | `v1.29.0-wasm32`                |
| usermod `qemu`        | `{tag}-qemu-{board}`    | `v1.24.0-qemu-MICROBIT`         |
| usermod `esp32`       | `{tag}-esp32-{board}`   | `v1.29.0-esp32-ESP32_GENERIC`   |
| usermod `rp2`         | `{tag}-rp2-{board}`     | `v1.29.0-rp2-RPI_PICO`          |

The shape genuinely differs per usermod port — `unix`/`windows`/
`webassembly` carry no port name at all in the identifier, only `qemu`/
`esp32`/`rp2` do. `--print-build-identifiers --json` against a broad `build`
glob is the fastest way to see the real list for yourself rather than
guessing one by hand:

```console
$ cibuildmp --build "mpy6.3-* v1.29.0-manylinux* v1.29.0-esp32-*" \
    --print-build-identifiers
```

```toml
build = "mpy6.3-*"                        # every arch, one natmod ABI, newest verified tag
build = "mpy6.2-* mpy6.3-*"                # two ABIs in one invocation
build = "v1.29.0-manylinux*"               # every native unix cell, one tag
skip  = "*_ppc64le *_s390x *_riscv64"      # drop the emulated-everywhere cells
build = "v1.29.0-esp32-ESP32_GENERIC"      # exactly one board

[override."*-armv7emsp"]
extra-make-args = ["MP_BCLIBC_PRECISION=single"]
```

`{...,...}` brace expansion works inside a pattern (`build =
"*-{x64,armv6m}"`), matching shell glob syntax. A `build`/`skip` pattern
that can never match any real identifier is a load-time error, not a
silent no-op.

When a `build` glob names no specific MicroPython tag, natmod narrows the
match to the newest tag this project has verified as *stable* for that
ABI — name one explicitly (`mpy6.3-v1.29.0-*`) to pin it yourself. Usermod
has no equivalent narrowing: every real `(port, tag, arch/board)` row
already carries its own explicit tag.

### `--keep-going` and the JSON build report

The default is fail-fast: the first target to fail stops the whole
invocation, and nothing selected after it is even attempted — the same
behaviour `cibuildwheel` itself has, unconditionally, with no keep-going
concept of its own. `--keep-going` (record [0063]) is a deliberate cibuildmp
divergence for the opposite case — a `--build` glob wide enough to span a
real coverage sweep, where the point is to find out *every* target's own
outcome rather than stop at the first one that fails.

Every attempted target — success or failure, `--keep-going` or not — is
written to a JSON report, one file per invocation, under
`~/.cache/cibuildmp/reports/` by default (`CIBMP_REPORT_PATH` to redirect
it). Each entry carries the identifier, how long it took, and either the
built artifact's directory/size/file listing or the error that stopped it:

```json
{
  "generated_at": "2026-08-29T12:00:00+00:00",
  "total_duration": 12.4,
  "built": 1,
  "failed": 1,
  "results": [
    {
      "identifier": "v1.29.0-manylinux_2_28_x86_64",
      "duration": 9.1,
      "error": null,
      "output_dir": "mpyhouse/v1.29.0-manylinux_2_28_x86_64",
      "size": 1048576,
      "files": ["micropython-v1.29.0-manylinux_2_28_x86_64"]
    },
    {
      "identifier": "v1.29.0-qemu-POWERNV9",
      "duration": 3.3,
      "error": "make: *** [firmware.elf] Error 1",
      "output_dir": null,
      "size": null,
      "files": []
    }
  ]
}
```

## Target support

### Natmod, per arch

All ten `ARCH=` values `py/dynruntime.mk` accepts, all baked into one
`docker/natmod.Dockerfile` image (`linux/amd64`, pulled from
`ghcr.io/ballistics-lab/natmod`) — natmod builds no bare-host toolchain of
any kind any more, `x86`'s 32-bit multilib included, which is exactly what
makes it buildable on an arm64 runner too. Adopted in all three consuming
repos and verified on real CI, arch by arch, not just `--dry-run`.

<table>
<thead>
<tr>
  <th>Arch</th>
  <th>Toolchain</th>
  <th>Status</th>
</tr>
</thead>
<tbody>
<tr>
  <td>
    <code>x64</code><br>
  </td>
  <td>host gcc</td>
  <td>✅</td>
</tr>
<tr>
  <td>
    <code>x86</code><br>
  </td>
  <td>host gcc (<code>-m32</code>)</td>
  <td>✅</td>
</tr>
<tr>
  <td>
    <code>armv6m</code><br>
    <code>armv7m</code><br>
    <code>armv7emsp</code><br>
    <code>armv7emdp</code><br>
  </td>
  <td>
    <code>arm-none-eabi-</code><br>
  </td>
  <td>✅</td>
</tr>
<tr>
  <td>
    <code>xtensa</code><br>
  </td>
  <td>
    <code>xtensa-lx106-elf-</code><br>
  </td>
  <td>✅</td>
</tr>
<tr>
  <td>
    <code>xtensawin</code><br>
  </td>
  <td>
    <code>xtensa-esp32-elf-</code><br>
  </td>
  <td>✅</td>
</tr>
<tr>
  <td>
    <code>rv32imc</code><br>
    <code>rv64imc</code><br>
  </td>
  <td>
    <code>riscv64-unknown-elf-</code><br>
  </td>
  <td>✅</td>
</tr>
</tbody>
</table>

### Usermod, per port/arch

Upstream MicroPython has 20 ports (`ports/*` in a real checkout); every one
is listed below for orientation, not just the ones this project covers.
`resources/build-platforms.toml` carries independently-verified
`(tag, arch/board)` rows for 15 of them; only 6 (`unix`, `windows`, `qemu`,
`webassembly`, `esp32`, `rp2`) have a real build driver wired into the CLI
at all — the other 9 have verified facts a config can already *name*, but
nothing yet to actually build them. Every ✅ row below is live-verified
against a real MicroPython checkout, including a real custom
`USER_C_MODULES` module — `unix`, `windows`, `webassembly` and `qemu` are
additionally exercised end to end through the real `action.yml` on every
push (`build-examples.yml`), producing genuine linked binaries with their
executable bit intact, Docker-only (`unix`: one native image per
arch/libc; `windows`/`webassembly`/`qemu`: one image each — `qemu`'s own
`v1.29.0-qemu-MPS2_AN385` runs in its own matrix leg rather than sharing
a job with already-proven cells, since it was the first build ever run
through that path). `esp32` and `rp2` are the two ports not wired into
this project's own `action.yml` yet; `esp32`'s own composite action
remains the supported, verified production path for it, and `rp2`'s
driver was only just live-verified directly against `examples/template`
(record 0060) -- not yet exercised through `action.yml`.

<table>
<thead>
<tr>
  <th>Port</th>
  <th>Target</th>
  <th>Provisioning</th>
  <th>Status</th>
</tr>
</thead>
<tbody>
<tr>
  <td><code>unix / manylinux</code></td>
  <td>
    <code>manylinux_2_28_x86_64</code><br>
    <code>manylinux_2_28_i686</code><br>
    <code>manylinux_2_28_aarch64</code><br>
    <code>manylinux_2_31_armv7l</code><br>
    <code>manylinux_2_39_mipsel</code>
  </td>
  <td>

  native image[^native]<br>
  native image[^native]<br>
  native image[^native]<br>
  native image[^native]<br>
  cross image[^cross]

  </td>
  <td>✅</td>
</tr>
<tr>
  <td><code>unix / musllinux</code></td>
  <td>
    <code>musllinux_1_2_x86_64</code><br>
    <code>musllinux_1_2_i686</code><br>
    <code>musllinux_1_2_aarch64</code><br>
    <code>musllinux_1_2_armv7l</code>
  </td>
  <td>

  native image[^native]

  </td>
  <td>✅</td>
</tr>
<tr>
  <td><code>unix / manylinux</code></td>
  <td>
    <code>manylinux_2_28_ppc64le</code><br>
    <code>manylinux_2_28_s390x</code><br>
    <code>manylinux_2_39_riscv64</code>
  </td>
  <td>

  native image[^native]

  </td>
  <td>

  ⚠️[^emulated]

  </td>
</tr>
<tr>
  <td><code>unix / musllinux</code></td>
  <td>
    <code>musllinux_1_2_ppc64le</code><br>
    <code>musllinux_1_2_s390x</code><br>
    <code>musllinux_1_2_riscv64</code>
  </td>
  <td>

  native image[^native]

  </td>
  <td>

  ⚠️[^emulated]

  </td>
</tr>
<tr>
  <td><code>qemu</code></td>
  <td>
    <code>MPS2_AN385</code><br>
    <code>MICROBIT</code><br>
    <code>MPS2_AN500</code><br>
    <code>MPS3_AN547</code><br>
    <code>NETDUINO2</code><br>
    <code>SABRELITE</code>
  </td>
  <td>
    <code>arm-none-eabi-</code></td>
  <td>✅</td>
</tr>
<tr>
  <td><code>qemu</code></td>
  <td>
    <code>VIRT_RV32</code><br>
    <code>VIRT_RV64</code><br>
  </td>
  <td>
    <code>riscv64-unknown-elf-</code></td>
  <td>✅</td>
</tr>
<tr>
  <td><code>qemu</code></td>
  <td>
    <code>POWERNV9</code> (PowerPC)
  </td>
  <td><code>powerpc64le-linux-gnu-</code></td>
  <td>✅</td>
</tr>
<tr>
  <td><code>webassembly</code></td>
  <td>
    <code>pyscript</code> variant
  </td>
  <td><code>emsdk</code> (Linux x64 host only)</td>
  <td>✅</td>
</tr>
<tr>
  <td><code>esp32</code></td>
  <td>
    every board across <code>v1.28.0</code>/<code>v1.29.0</code>[^esp32ci]
  </td>
  <td><code>esp_idf_base</code> (Docker) -- ESP-IDF cloned on the host, installed in-container, per-board <code>idf_target</code>/<code>idf_version</code></td>
  <td>✅</td>
</tr>
<tr>
  <td><code>windows</code></td>
  <td>
    <code>x64</code><br>
    <code>x86</code><br>
    <code>arm64</code>
  </td>
  <td>
    <code>apt install gcc-mingw-w64-x86-64</code><br>
    <code>apt install gcc-mingw-w64-i686</code><br>
    <code>llvm-mingw</code> (Linux x64 host only)
  </td>
  <td>✅</td>
</tr>
<tr>
  <td><code>rp2</code></td>
  <td>
    every board across <code>v1.20.0</code>-<code>v1.30.0-preview</code>
  </td>
  <td><code>arm_embedded</code> (Docker) -- Pico SDK + every <code>lib/</code> it needs are vendored by the MicroPython release tarball itself[^rp2ci]</td>
  <td>✅</td>
</tr>
<tr>
  <td>
    <code>mimxrt</code><br>
    <code>samd</code><br>
    <code>stm32</code><br>
    <code>psoc-edge</code><br>
    <code>alif</code><br>
    <code>esp8266</code><br>
    <code>cc3200</code><br>
    <code>renesas-ra</code><br>
    <code>nrf</code>
  </td>
  <td>

  verified `(tag, board)` rows exist[^nodriver]

  </td>
  <td>—</td>
  <td>❌ no build driver yet</td>
</tr>
<tr>
  <td>
    <code>zephyr</code>
  </td>
  <td>Zephyr RTOS (any board)</td>
  <td>—</td>
  <td>❌ no build driver yet</td>
</tr>
<tr>
  <td>
    <code>pic16bit</code><br>
    <code>powerpc</code> (as a standalone port)<br>
    <code>bare-arm</code><br>
    <code>minimal</code><br>
    <code>embed</code>
  </td>
  <td>no verified rows at all — reference builds or CPU families with no matching natmod/usermod facts</td>
  <td>—</td>
  <td>❌ out of scope</td>
</tr>
</tbody>
</table>

[^native]: Nothing to provision. The image is `ghcr.io/ballistics-lab/<target>`, a thin layer over pypa's own `quay.io/pypa/<target>` (the same images cibuildwheel builds wheels in), carrying a native compiler for that architecture. Non-native targets run emulated. The binary is checked against its target's real platform tag after every build.

[^cross]: The one target that still cross-compiles: pypa publishes no mipsel image and there's no Docker official image for 32-bit mipsel, so there's nothing to be native to.

[^emulated]: `ppc64le`/`s390x`/`riscv64`, both libcs — published (`resources/pinned_docker_images.toml` has a real digest for each) and reachable by naming them in `build`, but native to no runner GitHub offers, so no real build has ever run through one: the six-cell equivalent of `qemu`'s own gap before it got a dedicated CI leg. Point `CIBMP_UNIX_<TARGET>_DOCKER_IMAGE` at a locally-built image, or an emulated one, to work on one of these.

[^nodriver]: `resources/build-platforms.toml` has real, independently-verified rows for each of these ports (walked against a real MicroPython checkout the same way every ✅ row above was); a config can name their identifiers today. What's missing is a `build_<port>()` driver (`platforms/usermod/build_<port>.py`) to actually run one — not a scope decision, just not built yet.
[^rp2ci]: `build_rp2()` runs no provisioning step inside the container at all — the Pico SDK and everything it needs (`lib/pico-sdk`/`lib/tinyusb`/`lib/lwip`/`lib/btstack`/`lib/cyw43-driver`) are plain git submodules of the MicroPython checkout, already vendored as real files by the release tarball this project prefers. Running the port's own `make ... submodules` target was tried first and failed live against a real tarball checkout ("fatal: not a git repository", since a release tarball is not a git checkout at all); those submodules are threaded into `sources.fetch_micropython()` instead, reached only on its clone path (a preview tag with no tarball). Live-verified: a real `examples/template` build against `v1.29.0-rp2-RPI_PICO` producing a genuine 681984-byte `firmware.uf2` with the project's own C module linked in. Record 0060.

[^esp32ci]: `build_esp32()` went Docker 2026-08-28 (`esp_idf_base`, [0058]), closing the venv conflict that made every real esp32 build fail on the bare host; `idf_version`/`idf_target` are threaded from each board's own real row rather than a fixed default, and `HOME` is exported explicitly for the same reason `esp32`'s own `ports/esp32` needs a real per-user cache dir that `dockerrun.run()`'s `--user <uid>:<gid>` doesn't otherwise give it (unmapped on GitHub's own runners specifically, live-caught on real CI). `test-platforms.yml`'s own broad sweep is what actually proves this across the whole board matrix, not a spot check — Xtensa and RISC-V both, both MicroPython tags this project currently tracks.

No Windows or macOS host is needed for any of the ✅/⚠️ usermod targets
above, `windows`'s own three arches included — every toolchain there is
either already on a Linux host or downloads/apt-installs onto one.

## Conventions this repo assumes

A module following the natmod/usermod layout looks like:

```
natmod/
  Makefile              # includes py/dynruntime.mk, dispatches on ARCH=
usermod/
  micropython.cmake
  micropython.mk
  manifest.py
```

`build-natmod` only assumes `natmod/Makefile` (or whatever `natmod_dir`
points at) accepts `ARCH=` and `MPY_DIR=` and has a `dist` target that
drops the built `.mpy` under `build/<arch>*/`. Nothing here assumes a
specific module name, precision scheme, or test framework — those stay in
the consuming repo.

**One more requirement for the `cibuildmp` CLI specifically:** scope
`dynruntime.mk`'s `BUILD` variable by `$(ARCH)` — `BUILD = .obj/$(ARCH)`
before the `include`, kept outside `build/` so it does not collide with
the `dist` output the CLI globs for (see
`examples/template/natmod/Makefile`). `cibuildmp` runs every selected
target sequentially in one `natmod/` tree, and `dynruntime.mk` defaults
`BUILD ?= build` unscoped, so without this a second `ARCH=` in the same
invocation finds the previous arch's own object files "up to date" and
skips rebuilding — the merged `.mpy` silently stays the *first* arch's
binary. `cibuildmp` catches this itself (a header-arch verification step
fails loudly instead), but scoping `BUILD` avoids paying for the failed
build at all.

If the module also builds `rv32imc` with more than one `arch-flags` value
in the same invocation, `BUILD` needs `$(ARCH_FLAGS)` folded in too —
`BUILD = .obj/$(ARCH)$(if $(ARCH_FLAGS),+$(ARCH_FLAGS))`, for the same
reason on that second axis.

None of this cares what produced the `.c` files `SRC` lists —
[`examples/wasm2mpy`](examples/wasm2mpy) compiles WebAssembly to C via
`wasm2c` in a Makefile rule before the same `dynruntime.mk` flow takes
over.

## Roadmap

[`docs/0000-TRACKER.md`](docs/0000-TRACKER.md) is the plan of record: the
decisions taken and why (in [`docs/records/`](docs/records/)), what's
implemented, what's deliberately deferred. `docs/BACKLOG.md` is now just a
short redirect into that scheme, not itself the plan.

Natmod is done end to end — target selection, MicroPython/`mpy-cross`
provisioning, and the build itself, all ten arches now running inside one
pulled `docker/natmod.Dockerfile` image rather than a host-side
toolchain resolver (that resolver, and its own `--toolchain` flag, are
deleted) — verified on real CI in all three consuming repos, not just
`--dry-run`. Usermod's
own build drivers are wired into the CLI too (see
[Target support](#target-support) above): `unix`/`windows`/`webassembly`
run live through the real `action.yml`, all three in one invocation. What's
still open is the third consuming-repo step: none of
`micropython-bclibc`/`a7p`/`micropython-wasm3` has repinned its own usermod
workflow to the `cibuildmp` CLI yet. Until one does, the composite actions
stay the supported path for it.

## Composite actions

The pre-CLI building blocks — one GitHub Action per build step
(`fetch-micropython`, `build-natmod`, `build-usermod-unix`/`-windows`/
`-webassembly`/`-rp2040`/`-armv7m`/`-esp32`, …). Still fully supported for
CI, but no longer where new work starts — new usermod ports and arches
land in the CLI's own `usermod/build_<port>.py` first. Full input/output
reference and a usage example: [`docs/ACTIONS.md`](docs/ACTIONS.md).

## Versioning

Pin consumers to a tag, not `@main` and not a commit SHA — bumping the tag
a consumer references is a deliberate, visible edit in that repo, same as
bumping any other CI dependency.

The `cibuildmp` package and the actions share one version. `v0.3.0` is the
first tag where the CLI actually builds a module, not just plans it; it
continues `micropython-native-ci`'s version line rather than restarting
it, since this repo absorbed that one (its consumers have since repinned;
the old repo is now archived). See [`CHANGELOG.md`](CHANGELOG.md) for the
full history.

The root `action.yml` installs `cibuildmp` from its own checkout rather
than from PyPI (`uv tool install "$GITHUB_ACTION_PATH"`, already the
pinned ref's own source, checked out by GitHub Actions before any step
runs), so the tool that runs on CI is always exactly the ref you pinned,
with no index to keep in sync. Running it yourself with `uv tool install
cibuildmp`/`pip install cibuildmp` instead pulls whatever's newest on
PyPI unless you pin a version there too.
