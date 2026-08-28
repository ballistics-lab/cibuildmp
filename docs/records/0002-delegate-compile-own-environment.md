# 0002. Delegate the compile, own the environment

- Status: Accepted
- Related: [0001]

<!-- migrated verbatim from docs/BACKLOG.md lines 43-55 -->

**D2 — delegate the compile, own the environment.**
Like cibuildwheel, `cibuildmp` does not know how to compile anything. It
invokes the project's own `natmod/Makefile` (which includes
`py/dynruntime.mk` and takes `ARCH=` / `MPY_DIR=`). What `cibuildmp` *does*
own, and what no consuming repo should write again:

- fetching/checking out MicroPython at the configured tag,
- building `mpy-cross`,
- resolving and provisioning the cross toolchain for each target,
- pointing `mpy_ld.py` at its own interpreter (`PYTHON=`) so its host deps
  (`pyelftools`, `ar`) resolve from `cibuildmp`'s own dependencies (**D12**),
- collecting outputs into an output directory with unambiguous names.
