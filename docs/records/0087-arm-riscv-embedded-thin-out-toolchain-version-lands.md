# 0087 — `arm_embedded`/`riscv_embedded` lose their baked cross toolchain; `toolchain_version` becomes a real, read field

Status: Implemented for `rp2` — the one of the six ports this record names that has a real
`build_<port>()` driver today ([0053]'s own gap: `nrf`/`cc3200`/`renesas-ra`/`stm32`/`samd` have
verified rows and no build code at all, so there is nothing for this record to wire for them yet).
See its own addendum below for what landed, two real corrections to this record's own text, and
what is still open.
Related: [0025], [0031], [0053], [0058], [0068], [0082], [0084], [0085], [0086], [0091]

## What this is

The main body of [0085] actually landing, for the six ports that share the ordinary case:
`nrf`, `cc3200`, `renesas-ra`, `stm32`, `samd`, `rp2` (`mimxrt`'s own disjoint `>= 13` ceiling is
[0088], not here). `arm_embedded.Dockerfile`/`riscv_embedded.Dockerfile` drop their `ARG
TOOLCHAIN_URL`/`ARG TOOLCHAIN_SHA256` and the `RUN` that curls/verifies/extracts them, keeping only
the base image plus the apt set every build already needs (`build-essential git python3
python3-pyelftools`, `cmake` for `rp2` only, per `arm_embedded.Dockerfile`'s own existing comment
— nothing here changes that set, since [0086]'s fetch needs `curl`/`ca-certificates`/`xz-utils`
already present, not new). `toolchain_version` — already a real field on every `[usermod.alif]`
row and read by nothing — becomes the value [0086]'s mechanism resolves for these six ports' own
rows too, replacing the shared, baked xpack pin.

## The one assumption this record corrects before writing any code

**There is no root-then-drop-to-uid step here, and no `HOME` relocation, unlike [0084]'s own
`unix`/pypa work.** Read directly from `dockerrun.py`: `run()` passes `--user
{os.getuid()}:{os.getgid()}` unconditionally on *every* invocation (lines 693-694) — every
container this project starts already runs at the host's own uid from the first instruction, for
every port, today. [0084]'s root/non-root saga (`build_esp32.py`'s own `export HOME=...`, the
apt-needs-root-but-the-build-must-not-run-as-root problem) was specific to that record's own
decision to `apt-get install` at *every invocation* against a bare `ubuntu:26.04` — packages
writing into `/var/lib/dpkg` and other root-owned system paths. This record does neither: the
toolchain arrives as a tarball into an already-writable, host-mounted, uid-owned cache directory,
using tools already baked into the (still Dockerfile-built, still published) image at build time.
That whole class of problem does not arise, and this record should not import it by analogy.

## What stays exactly as it is

- **The image itself is still built and published**, unlike `unix`'s move to a bare upstream
  base — `arm_embedded`/`riscv_embedded` are not adopting [0084]'s "no image of our own" answer,
  only its "the cache is populated from inside the container" rule. The apt layer (native
  compiler, `cmake`, `git`, `python3`, `pyelftools`) stays baked in at image-build time, so no
  per-invocation apt cost is introduced here.
- **`container_mpy_cross()` is untouched.** It resolves whatever `gcc` the image's own `PATH`
  finds — the image's native `build-essential` compiler, unaffected by moving the *cross* xpack
  compiler out. This record does **not** make old tags buildable on its own: `arm_embedded`'s
  own native gcc is the same `ubuntu:26.04` `build-essential` [0084] measured as gcc 15.2.0 for
  `natmod_host`, which [0082] already ties to nine failing pre-`v1.26.0` tags — and `mpy-cross`
  fails on that native compiler *before* the row's own cross toolchain is ever invoked, the same
  order [0084] found for `unix`. Closing that is [0091], entirely separate from and not
  presupposed by this record's own boundary-sample verification.
- **`riscv_embedded`'s own `riscv-none-elf-*` → `riscv64-unknown-elf-*` symlink step** stays,
  unaffected by where the tarball it symlinks now comes from.

## What changes

- The two Dockerfiles thin out as described above.
- `PATH` for the cross toolchain moves from a baked `ENV` line to a per-run value `dockerrun.run()`
  passes as `env=`, resolved from the row's own `toolchain_version` via [0086]'s cache path —
  the same shape `rp2_make_command()` and friends already build up their environment with, not a
  new mechanism for passing env into a container.
- `alif`'s existing `toolchain_version` rows become a second real consumer of the same [0086]
  mechanism, on the same image family, closing the exact gap [0085] named ("nothing reads it").

## Verification order, restated from [0085] because it is easy to get backwards

Build a **new** tag (`v1.29.0`/`v1.30.0-preview`) on the **older** toolchain first. Every
incompatibility this project has measured across [0082]/[0084]/[0085] broke in one direction —
newer compiler rejects older code — so the old tags this change exists for are the low-risk case;
the new ones are where a downgrade could plausibly regress, and that is unverified rather than
assumed safe.

## What this does not do

Does not touch `mimxrt` ([0088]), `natmod` ([0089]), `refresh_toolchain_pins.py`, or [0058]'s own
text ([0090]).

## Addendum: what landed, and two things this record's own text got wrong

Both Dockerfiles are thinned exactly as scoped: no `ARG TOOLCHAIN_URL`/`ARG TOOLCHAIN_SHA256`, no
`RUN` that curls/verifies/extracts one, no baked `ENV PATH`. `build_rp2()`
(`usermod/build_rp2.py`) now calls `targets.rp2_toolchain(tag)` — a `tag -> gcc` lookup built from
`build-platforms.toml`'s own rows, the identical shape `esp32_idf_info()` already has for
`idf_version` — then `toolchain_fetch.resolve_toolchain()`, wraps its own make command in one
`bash -c` script (fetch script, then `export PATH=`, then the command), and mounts the fetched
cache directory alongside its existing mounts. `mimxrt`/`alif` are untouched (no build driver
exists to wire either into, whatever their own row already carries).

**Two things this record's own text got wrong, found only by actually writing the code:**

1. **"`riscv_embedded`'s own symlink step stays [at image-build time]" is impossible once the
   tarball itself moves to container-run time** — there is nothing left in the image to symlink
   *from* at build time. `toolchain_fetch.rename_prefix_script()` (new, [0086]'s own module) now
   does the `riscv-none-elf-*` → `riscv64-unknown-elf-*` rename inside the fetched cache directory
   itself, appended into the same `bash -c` script right after the fetch — not `/usr/local/bin`,
   since `dockerrun.run()`'s own unconditional `--user <uid>:<gid>` (this record's own correct
   point about *no* root/uid dance) means nothing can write there at container-run time either.
2. **"`PATH` ... passes as `env=`" is not how it works.** `dockerrun.run()`'s own `env=` only ever
   emits `-e KEY=VALUE` (replace, not append) — there is no way to *prepend* onto the image's own
   existing `$PATH` through it. The toolchain's own `bin/` is exported inside the `bash -c` script
   itself (`export PATH="<dir>/bin:$PATH"`, before the real command), not passed as `env=`.

**Verified for real, not just unit-tested with mocks** — no Docker daemon needed for any of this,
since every toolchain-group image here is plain `ubuntu:26.04` + a tarball, and this host is
x86_64 Linux: fetched the real `arm-none-eabi-gcc-xpack` `15.2.1-1.1` tarball with
`toolchain_fetch.resolve_toolchain()`'s own real generated script (real `https://github.com/...`
URL, real sha256 check), put it on `PATH` exactly as `build_rp2()`'s own new code composes it, and
built a real `ports/rp2` `v1.29.0` `RPI_PICO` firmware end to end — `firmware.uf2`, 681472 bytes,
`FLASH: 51.96%` used, real pico-sdk/tinyusb sources compiled through it.

**What is still open, honestly:**

- `bin/refresh_toolchain_pins.py`'s own `--check` ([0090]'s own scope item 1) is not fixed here.
  Confirmed live: `current_dockerfile_pin("arm_embedded")`/`("riscv_embedded")` now both return
  `None` (the regex they grep for is gone), and `--check`'s own loop already treats `None` as
  "skip" rather than crashing — so nothing is broken, but `--check` now verifies *nothing* at all
  for these two images' own rows. This was a live, checked fact when [0090] was still a
  Proposed prediction; now that this record has actually landed, it is a real, present gap, not a
  hypothetical one.
- `nrf`/`cc3200`/`renesas-ra`/`stm32`/`samd`/`mimxrt`/`alif` have no `build_<port>()` at all
  ([0053]) — `toolchain_version`/`gcc` sits ready on every one of their own rows, but there is no
  code anywhere to read it yet. Wiring them is repeating `rp2`'s own pattern once each one's build
  driver exists, not new design.
- 13 tests added directly to `toolchain_fetch.py`'s own suite plus `tests/test_usermod_build_rp2.py`
  (real fetch/verify/extract/idempotency behaviour, plus `build_rp2()`'s own PATH/mount wiring) —
  all real `bash -c` execution or real docker-command-list assertions, no shell-string matching on
  faith.
