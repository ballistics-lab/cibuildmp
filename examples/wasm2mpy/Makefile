# Author:    Volodymyr Shymanskyy
# Created:   24.08.2024
#
# Vendored from github.com/vshymanskyy/wasm2mpy @ 0bf025cdcfa90acc9f808bd5681c1881e2fe0974
# (MIT, see NOTICE in this directory) -- cibuildmp's own integration test for
# a natmod project that is not natmod's own C, WASM compiled through it via
# wasm2c. Two additions below, everything else unchanged: BUILD scoped by
# $(ARCH) and a `dist` target, both because cibuildmp needs them (see
# examples/template/natmod/Makefile's own comments for why), not because
# upstream wasm2mpy does.

# Location of top-level MicroPython directory
MPY_DIR ?= /opt/micropython
APP ?= wat

# Added for cibuildmp (see examples/template/natmod/Makefile's comment):
# must be set before the `BUILD ?= build` below, which only applies with no
# prior value, so this line has to come first, not just be present.
BUILD = .obj/$(ARCH)

BUILD ?= build

# x86, x64, armv6m, armv7m, armv7emsp, armv7emdp, xtensa, xtensawin
ARCH ?= armv6m
MOD ?= $(APP)
SRC += runtime/runtime.c        \
  runtime/libc.c                \
  runtime/wasm-rt-mem-impl.c    \
  runtime/wasm-rt-impl.c
  #runtime/wasm-rt-exceptions-impl.c

SRC += $(BUILD)/wasm.c

ifeq ($(ARCH),xtensa)
  SRC += runtime/esp8266-rom.S
endif

LINK_RUNTIME = 1

# Wasm module to build
WASM ?= test/$(APP).wasm

include $(MPY_DIR)/py/dynruntime.mk

#-DWASM_RT_OPTIMIZE -Ofast
CFLAGS += -Os -Iruntime -I$(BUILD) -Wno-unused-value -Wno-unused-function \
          -Wno-unused-variable -Wno-unused-but-set-variable

#MPY_LD_FLAGS += -v

$(BUILD)/wasm.c: $(WASM)
	$(Q)$(MKDIR) -p $(BUILD)
	$(ECHO) "W2C $<"
	$(Q)wasm2c -o $@ --no-debug-names --module-name="wasm" $<
	$(Q)sed -i 's/#if defined(__GNUC__) || defined(__clang__)/#if 0/' $@
	# Remove memchecks, assuming we trust the module
	#$(Q)sed -i 's/MEMCHECK(mem, addr, t1);//' $@

# Added for cibuildmp: the convention every cibuildmp-built natmod Makefile
# follows (see README.md's "Conventions this repo assumes") -- drops the
# built .mpy under build/<arch>*/, which build.collect_output() globs for.
.PHONY: dist
dist: all
	mkdir -p build/$(ARCH)
	cp $(MOD).mpy build/$(ARCH)/

