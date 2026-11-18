/*
 * ceesafe_panic.c - CeeSafe's panic hook for the user programs written in or
 * linking CeeSafe (the runtime shim, as kernel/ceesafe/ceesafe_panic.c is
 * the kernel's: scripts/cee-share.py's FLOOR). A failed CeeSafe check is a
 * bug in the program: it prints the reason and the CeeSafe line and aborts.
 */

#include <stdio.h>
#include <stdlib.h>

#include "ceesafe/rt.h"

_Noreturn void ceesafe_panic(cee_panic_kind kind, cee_loc loc)
{
    fprintf(stderr, "ceesafe panic: %s at %s:%u:%u\n", ceesafe_panic_reason(kind), loc.file, (unsigned)loc.line,
            (unsigned)loc.column);
    abort();
}
