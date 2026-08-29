# 0016. USER_C_MODULES is a directory on Make-driven ports, a single .cmake file on CMake-driven ones

- Status: Accepted
- Related: [0007], [0039]

<!-- migrated verbatim from docs/BACKLOG.md lines 902-940 -->

**D16 — `USER_C_MODULES` is a directory on Make-driven ports, a single
`.cmake` file on CMake-driven ones — same variable name, two incompatible
shapes.** `unix`/`windows`/`webassembly`/`qemu` glob a directory (`make`'s
own `USER_C_MODULES` convention, `py/py.mk`); `esp32`/`rp2040` are
CMake-driven ports and take one `.cmake` entry point to `include()` —
stated directly in `build-usermod-rp2040`'s own input doc ("unlike
build-usermod-unix/build-usermod-webassembly's own user_c_modules, this
one is a *file*... CMake's USER_C_MODULES takes a single .cmake entry
point to include, not a directory to glob") and mirrored in
`build-usermod-esp32`'s. A consumer therefore needs *two* files for one
module tree (`usermod/` for the directory form, `usermod/micropython.cmake`
for the CMake form) — a7p's own tree carries both. `cibuildmp` should
resolve this itself once it already knows which port it's driving (the
same D7 board-database lookup that already knows Make vs. CMake per port),
not leave a consumer to notice the split by reading a composite action's
own doc comment the way today's three consumers had to.

Corrected after reading `py/usermod.cmake` directly rather than trusting
`build-usermod-rp2040`'s own doc comment: the "a file, not a directory to
glob" framing above is the action author's own convention, not what CMake
actually enforces. `USER_C_MODULES` on the CMake side is a *list* of
paths, and `usermod.cmake`'s own loop accepts a directory too — it just
appends `/micropython.cmake` to it (`if (IS_DIRECTORY ...)`) rather than
globbing every subdirectory the way `py/py.mk`'s `$(wildcard
$(USER_C_MODULES)/*/micropython.mk)` does on the make side. So the real
difference is not file-vs-directory, it's *how many modules one entry can
resolve to*: one `make`-side directory can hold several modules side by
side (one per subdirectory with its own `micropython.mk`), one `cmake`-side
entry always resolves to exactly one `micropython.cmake`, whether given as
a direct path or as a directory. Verified against a real `v1.28.0`
checkout, not transcribed from a doc comment: `unix`/`webassembly`/
`windows`/`qemu` all `include $(TOP)/py/py.mk`; `esp32`/`rp2040` both
forward `-DUSER_C_MODULES=` from their own `Makefile` into `cmake`, which
then includes the single, shared `py/usermod.cmake` — not a per-port CMake
file each writes its own copy of. `build-system` per port is now pinned
data (**D10**'s own pattern) in `resources/usermod.toml`, read through
`usermod/portinfo.py`, scoped to the same six ports **D16–D21** already
has a reference for.
