# Run under the built `unix` binary itself, the same convention
# examples/usercmodule/smoke_test.py uses. A binary that merely links is not
# the same claim as one whose LVGL bindings actually run: this registers a
# real (headless) display -- the manylinux_2_28 image this builds against
# has no SDL2, so the module compiles in only `driver/generic`'s own
# hardware drivers plus this script's own manual `lv.display_create()`, the
# supported way to drive LVGL without any physical panel -- builds a real
# widget tree, and renders one frame through it. Live-verified before this
# file existed (record 0097): `lv.obj()` called with no display registered
# at all hangs rather than raising, which is why the display is created
# first, not treated as optional setup.

import lvgl as lv

disp = lv.display_create(240, 240)
buf1 = bytearray(240 * 20 * 4)


def flush_cb(disp, area, color_p):
    disp.flush_ready()


disp.set_flush_cb(flush_cb)
disp.set_buffers(buf1, None, len(buf1), lv.DISPLAY_RENDER_MODE.PARTIAL)

scr = lv.screen_active()
btn = lv.button(scr)
btn.set_size(120, 50)
btn.center()
label = lv.label(btn)
label.set_text("Hello cibuildmp")
label.center()

lv.refr_now(disp)

print("smoke test OK: lvgl display created, widget tree built, frame rendered")
