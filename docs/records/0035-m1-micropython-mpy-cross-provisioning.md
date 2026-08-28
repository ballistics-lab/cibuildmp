# 0035. M1 — MicroPython + mpy-cross provisioning

- Status: Implemented (done)
- Related: [0002], [0013]

<!-- migrated verbatim from docs/BACKLOG.md lines 607-642 -->

### M1 — MicroPython + mpy-cross provisioning — **done**

All in `src/cibuildmp/sources.py`, standard library only.

- [x] Fetch MicroPython at the configured tag, from the release **asset**
      tarball (`.../releases/download/<tag>/micropython-<ver>.tar.xz`) — the
      same URL `fetch-micropython` uses, and not GitHub's auto-generated
      archive, because only the release asset vendors the `lib/` submodules.
- [x] Shallow-clone fallback for refs that publish no asset. Verified rather
      than assumed: `v1.28.0`, `v1.25.0` and `v1.22.0` all return 200,
      `v1.29.0-preview` returns 404.
- [x] `micropython-submodules` config option, applying on the clone path
      only. **A natmod can need a submodule** — upstream's own
      `examples/natmod/btree/Makefile` builds against
      `$(MPY_DIR)/lib/berkeley-db-1.xx`, which is one. The tarball path
      needs nothing here; a `--depth 1` clone vendors none.
- [x] `urllib`, no `wget`. `README.md` records `fetch-micropython` being
      unusable on a Windows runner outside MSYS2 for exactly that reason, so
      this removes a real portability limit rather than a hypothetical one.
- [x] Cache under `~/.cache/cibuildmp/micropython/<tag>/`, honouring
      `CIBMP_CACHE_PATH` and `XDG_CACHE_HOME`. Extraction is staged in a temp
      directory and moved into place with `os.replace`, and a completion
      stamp file gates reuse, so an interrupted run cannot leave a partial
      tree that the next one trusts.
- [x] `mpy-cross` built once per checkout, cached alongside it.
- [x] `read_mpy_abi()` reads `MPY_VERSION`/`MPY_SUB_VERSION` from
      `py/persistentcode.h` and is checked against the identifier's ABI
      before any target is built. The checkout is authoritative; the
      `MPY_ABI` table exists only to answer the question with no checkout.
      A disagreement aborts rather than mislabelling output.

Measured on this machine, `CIBMP_BUILD="*-x64" cibuildmp`: **37 s cold**
(104 MiB download + extract + `mpy-cross`), **0.08 s warm**. That gap is the
whole argument for D9 — under a ten-leg matrix the cold path is paid ten
times over.
