#include "py/runtime.h"

static mp_obj_t mymod_hello(void) {
    return mp_obj_new_int(42);
}
static MP_DEFINE_CONST_FUN_OBJ_0(mymod_hello_obj, mymod_hello);

static const mp_rom_map_elem_t mymod_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_mymod) },
    { MP_ROM_QSTR(MP_QSTR_hello), MP_ROM_PTR(&mymod_hello_obj) },
};
static MP_DEFINE_CONST_DICT(mymod_globals, mymod_globals_table);

const mp_obj_module_t mymod_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&mymod_globals,
};

MP_REGISTER_MODULE(MP_QSTR_mymod, mymod_user_cmodule);
