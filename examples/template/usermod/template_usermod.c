// The usermod-shape twin of natmod/template.c: same "template" module
// name (facade.py's own `from template import add` works unmodified
// against either build), same underlying add() (../src/template_core.c),
// wrapped here in usermod's own statically-linked MP_REGISTER_MODULE
// binding instead of dynruntime's relocatable one -- proof the shared
// core, not just the Python-level facade, builds through both paths.

#include "py/runtime.h"
#include "../src/template_core.h"

static mp_obj_t add(mp_obj_t a_obj, mp_obj_t b_obj) {
    mp_int_t a = mp_obj_get_int(a_obj);
    mp_int_t b = mp_obj_get_int(b_obj);
    return mp_obj_new_int(template_add(a, b));
}
static MP_DEFINE_CONST_FUN_OBJ_2(add_obj, add);

static const mp_rom_map_elem_t template_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_template) },
    { MP_ROM_QSTR(MP_QSTR_add), MP_ROM_PTR(&add_obj) },
};
static MP_DEFINE_CONST_DICT(template_globals, template_globals_table);

const mp_obj_module_t template_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&template_globals,
};

MP_REGISTER_MODULE(MP_QSTR_template, template_user_cmodule);
