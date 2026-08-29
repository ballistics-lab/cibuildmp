// The actual "business logic" this whole example exists to prove is
// shareable: one pure-C function, no MicroPython API of any kind, so it
// compiles unchanged whether the caller is natmod's own dynruntime.h
// (a restricted, position-independent API surface) or usermod's plain
// py/runtime.h (a normal, statically-linked compile) -- natmod/template.c
// and usermod/template/template.c each wrap this the same function in
// their own mode's own binding shape; neither duplicates the arithmetic.
#ifndef TEMPLATE_CORE_H
#define TEMPLATE_CORE_H

int template_add(int a, int b);

#endif
