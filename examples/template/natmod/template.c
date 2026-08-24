// Minimal natmod module. Its only job is to exist: cibuildmp's own CI
// (.github/workflows/build-template.yml) builds it against every arch this
// tool supports, as a real end-to-end check of M3's build path -- not a
// mock, a dry-run, or a unit test.

#include "py/dynruntime.h"

static mp_obj_t add(mp_obj_t a_obj, mp_obj_t b_obj) {
    mp_int_t a = mp_obj_get_int(a_obj);
    mp_int_t b = mp_obj_get_int(b_obj);
    return mp_obj_new_int(a + b);
}
static MP_DEFINE_CONST_FUN_OBJ_2(add_obj, add);

mp_obj_t mpy_init(mp_obj_fun_bc_t *self, size_t n_args, size_t n_kw, mp_obj_t *args) {
    MP_DYNRUNTIME_INIT_ENTRY

    mp_store_global(MP_QSTR_add, MP_OBJ_FROM_PTR(&add_obj));

    MP_DYNRUNTIME_INIT_EXIT
}
