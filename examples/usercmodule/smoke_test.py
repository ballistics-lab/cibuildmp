# Run under the built `unix` binary itself (`micropython smoke_test.py`) --
# not part of the cibuildmp build, a separate step after it in
# .github/workflows/test-upstream-usermodule.yml. A binary that merely
# links is not the same claim as one whose modules actually run: this
# exercises the real, documented API each of upstream's three
# examples/usercmodule/ modules exports (read from a real v1.29.0
# checkout), not just that cibuildmp's own build reported success.
#
# rp2 has no equivalent step (docs/records/0069) -- `firmware.uf2` needs
# real hardware or a board-specific emulator neither this fixture nor
# cibuildmp itself provides; `unix` is the one port here whose own output
# is a binary this runner can simply execute.

import cexample

assert cexample.add_ints(2, 3) == 5

timer = cexample.Timer()
assert timer.time() >= 0

advanced_timer = cexample.AdvancedTimer()
assert advanced_timer.seconds >= 0

import cppexample

# example.cpp's own cppfunc(): (a + b, "hellocpp") -- also proves the
# lambda/auto it uses compiled as real C++11, not just that -lstdc++ linked.
assert cppexample.cppfunc(2, 3) == (5, "hellocpp")

# subpackage/modexamplepackage.c registers itself as `example_package`, not
# `subpackage` -- the directory name and the Python package name are not
# the same thing here, confirmed against the real source rather than
# guessed from the directory's own name.
import example_package

example_package.f()
example_package.foo.f()
example_package.foo.bar.f()

print("smoke test OK: cexample, cppexample, example_package all import and run")
