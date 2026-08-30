# See ../cexample/micropython.mk's own header comment for why USERMOD_DIR is
# overridden to $(TOP)-relative before including upstream's real file, rather than
# forwarded unchanged.
USERMOD_DIR := $(TOP)/examples/usercmodule/subpackage
include $(USERMOD_DIR)/micropython.mk
