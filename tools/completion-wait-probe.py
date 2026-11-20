#!/usr/bin/env python3
"""Prove completion's self-test times the wait from before the completer exists (TEST-31).

--old reverses the fix commit's kernel/scheduler/schedtest.c: t0 is read
after thread_create, as on main. The test's adversary has the waiter sleep
9 ms after thread_create, as a waiter preempted there would, and the
completer sleeps 30 ms; the old order then measures what is left of the
sleep, and `completion` fails at `clock_since_ns(t0) >= MS(30)` on every
boot, at any CPU count. The fixed order reads t0 before the completer
exists, and the wait still blocks: it begins about 20 ms before the
completion.
"""
import sys
import fixprobe

sys.exit(fixprobe.run(
    "completion-wait-probe", __doc__,
    "completion's self-test times the wait from before the completer exists (TEST-31)",
    ["kernel/scheduler/schedtest.c"],
    ["completion"],
    [],
    ["check failed: clock_since_ns(t0) >= MS(30)"],
    ["SELFTEST: completion "]))
