# 0012. pyelftools and ar are cibuildmp's own dependencies, not something it installs at build time

- Status: Accepted
- Related: [0002]

<!-- migrated verbatim from docs/BACKLOG.md lines 206-232 -->

**D12 — `pyelftools` and `ar` are `cibuildmp`'s own dependencies, not
something it installs at build time.**
Neither is binutils. `ar` (PyPI `ar`, 1.0.1, "Access ar archive files") is a
pure-Python package that `mpy_ld.py` imports via `from ar import Archive` in
a `try`/`except`; `pyelftools` is imported directly as `elftools.elf`. No
system binary involved for either.

`ar` is formally optional in `mpy_ld.py` (`Archive = None` when the import
fails) but not practically optional for `cibuildmp`: it is needed whenever
`MPY_LD_FLAGS` contains `-l...a`, which is always true under
`LINK_RUNTIME=1` — the case bclibc uses to link `libm.a`. So both are
ordinary dependencies, not an `extra`; both are small and pure-Python, so the
cost is low. `pyelftools` should be pinned wide (`pyelftools>=0.29`), not
exact — the pin is shared across every MicroPython tag a user's config
builds, and the surface `mpy_ld.py` actually uses is narrow and stable, but a
tight pin would let one old tag break the whole tool.

Mechanism is the one already verified for `CROSS=` under M2:
`py/dynruntime.mk` line 10 assigns `PYTHON = python3` with a plain `=`, never
`override`, so a command-line variable wins. `cibuildmp` passes
`PYTHON=<sys.executable>` alongside `CROSS=`, and `make` runs `mpy_ld.py`
under the interpreter that already has both packages — the "isolated
environment" this used to require comes for free, since `uv tool install`
(**D8**) already puts `cibuildmp` in its own venv and the system interpreter
is never touched. This removes the first M3 checkbox as separate work; it is
one more argument on the `make` command line.

## Addendum, 2026-08-28 — `ar` was never a dependency of anything

This record names two packages. Only one of them is real.

Prompted by the user pointing out that both were already declared in `pyproject.toml`,
the list was re-derived from real checkouts rather than from this record's own text.
`grep`ing `tools/` at every tag natmod supports — v1.12, v1.15, v1.18, v1.20.0, v1.21.0,
v1.23.0, v1.25.0, v1.27.0, v1.28.0 — finds **zero** occurrences of `import ar`, and a
grep of the whole v1.28.0 tree finds none either. Read in full, `tools/ar_util.py`
imports `os`, `re`, `hashlib`, `functools`, `pickle`, `collections` and
`elftools.elf.elffile`. `tools/mpy_ld.py` imports `sys`, `os`, `struct`, `re`,
`elftools.elf.elffile` and `ar_util`. Nothing anywhere imports a module named `ar`.

**`ar_util` is needed; `ar` is not, and they are not the same thing** — which is the
whole of the confusion. `tools/ar_util.py` is MicroPython's own 8 KB source file, it
arrives with the checkout like `mpy_ld.py` itself, it is never installed by anything, and
`mpy_ld.py` genuinely depends on it (`import ar_util` at line 33; `ar_util.load_archive`
and `ar_util.resolve` at 1548 and 1552). `ar` is a package on PyPI. Nothing in this
project or in MicroPython ever imported it.

The name is what made the error durable: `ar_util.py` is about `.a` archives, `ar` is a
real PyPI package for reading them, so "`ar_util` needs `ar`" reads as obvious. It is not
true — `ar_util` parses archives with `elftools` and its own code — but the inference was
plausible, was written down here as fact, and was then copied forward three times without
being re-checked against a file that takes seconds to open.

**Where it had spread, all corrected in the same change:**

- `pyproject.toml` declared `"ar"` as a runtime dependency of cibuildmp.
- `docker/natmod.Dockerfile` installed `python3-pip` solely to
  `pip install --break-system-packages ar`, carried a comment explaining why PEP 668
  had to be overridden for it, and asserted `import ar` in its verification line.
  All of that is gone; `python3-pyelftools` is an apt package, so the image now needs
  neither pip nor the override.
- `src/cibuildmp/platforms/natmod/build.py` said "`ar` comes with build-essential",
  which was wrong independently of the above — `dpkg -S` inside the built image finds
  no owning package for `/usr/local/lib/python3.12/dist-packages/ar`, because pip put
  it there. Two comments in this repository asserted different origins for the same
  package, and both were wrong.

`pyelftools` is the whole dependency, and everything this record says about *it* —
pure Python, needed by `mpy_ld.py`, declared rather than pip-installed at build time —
stands unchanged. [0050] later moved the requirement from cibuildmp's own environment
into the image (`PYTHON=python3`, not `PYTHON=<sys.executable>`, since the host
interpreter's path does not exist across the mount), which is why the Dockerfile is one
of the places this had to be fixed.

The image's own digest changes as a result, so `pinned_docker_images.toml` needs a
republish before the smaller layer is what builds actually pull.
