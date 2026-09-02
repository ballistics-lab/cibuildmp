# 0087 — `arm_embedded`/`riscv_embedded` lose their baked cross toolchain; `toolchain_version` becomes a real, read field

Status: Proposed — blocked on [0086]; not implemented.
Related: [0025], [0031], [0058], [0068], [0082], [0084], [0085], [0086]

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
  compiler out. Any gcc-15-vs-old-tags breakage this may still hit for these ports' own
  `mpy-cross` builds is the same class [0082] already named and [0084] already scoped as its own
  follow-up ("carry `TAG_CFLAGS` into every port's `mpy-cross`") — explicitly out of scope here,
  not silently absorbed into this record.
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
