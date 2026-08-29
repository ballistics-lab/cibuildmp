# 0021. Execution, not just linking, is central to usermod's value

- Status: Accepted
- Related: [0006], [0039]

<!-- migrated verbatim from docs/BACKLOG.md lines 1143-1163 -->

**D21 — execution, not just linking, is central to usermod's value, and
is already real infrastructure — this does not fit under D6's blanket
"no test runners" deferral without saying so explicitly.** Every port in
`mp-usermod.yml` except `esp32` (build-only by design — there is no esp32
emulator to hand a firmware image to, stated directly in that job's own
header) already runs something after building: Node for `webassembly`,
the built interpreter directly for `unix`/`windows`, and two bespoke
Python harnesses (`micropython/ci/run_qemu.py`,
`micropython/ci/run_rp2040py.py`) for the bare-metal/emulated targets —
both of which shadow `open()` to inline the test fixture, since neither
target has a writable filesystem to copy one onto (`ports/qemu` links
`-nostdlib` with no VFS at all; the rp2040py path pushes a script over the
raw REPL instead of a real file). A natmod really is closer to a wheel — a
binary artifact whose job ends at "loads and the symbols resolve." A
usermod *is* the runtime; "compiles" proves much less about it than
"boots and imports" does, and the qemu/rp2040 jobs exist specifically
because a usermod that links cleanly but fails to boot is a real, observed
failure class, not a hypothetical one. This does not overturn **D6** for
natmod. It does mean usermod's own eventual phase should decide this
question on purpose rather than inherit D6's answer by default.
