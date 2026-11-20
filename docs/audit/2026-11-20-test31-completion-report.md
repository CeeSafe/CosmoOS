# TEST-31: completion's self-test timed the wait from after the completer existed, 2026-11-20

Main's CI run 44718105032, on the merge of #538 (`f15ea9dc`, v1.1.2's
release notes, a documentation PR), failed "build, boot, analyze
(x86_64, stress)", in the step "Boot test with the harness's first
attempt broken (debug)":

```
SELFTEST: completion       ... FAIL: check failed: clock_since_ns(t0) >= MS(10) at line 1363 (11 ms)
SELFTEST: FAIL (1 of 529)
```

The same code passed every other job of that run, and #537's merge run
(44695692624) before it. Main red, so fixed now rather than recorded.

## Scope and baseline

Branch `test31-completion` from main at `f15ea9dc`. One self-test
(`selftest_completion`, `kernel/scheduler/schedtest.c`) and a probe; no
kernel code outside the self-tests. A self-test is compiled code, so the
matrix ran.

## The mechanism

```c
struct thread *t = thread_create(completer_entry, &c, "completer", SCHED_PRIO_DEFAULT);
CHECK(t != NULL);
CHECK(!completion_done(&c));
uint64_t t0 = clock_now_ns();
wait_for_completion(&c);
CHECK(clock_since_ns(t0) >= MS(10));
```

The completer sleeps 10 ms and then completes. The check expects the
wait to last that sleep, but `t0` was read after `thread_create`, by
which time the completer may already be asleep: it can run at once on
another CPU, or ahead of the test's thread on this one (both at default
priority). Whatever part of its sleep has passed before `t0` is missing
from the measured wait. The sleep ends on a 4 ms tick (CONFIG_HZ 250),
which usually rounds it up past the time lost, so the check almost always
held. In the stress job's boot the test's thread was delayed long
enough between `thread_create` and `t0` that the check failed. That boot
ran the harness's broken first attempt, so the machine was busy. The
function measures how long `wait_for_completion` blocks, not the
completer's sleep, so the bound did not hold.

## The fix

`t0` is read before `thread_create`. The wait then covers the whole
sleep whenever the completer starts. The assertion is unchanged: the
waiter still has to block until the completer completes, at least 10 ms
after the completer could first run.

## The proof

The test now carries its adversary. The completer sets `started` as its
sleep begins, and the test waits for that and then sleeps 9 ms more
before `wait_for_completion`, as a waiter preempted after
`thread_create` would. With `t0` read before the completer exists the
wait still measures at least 10 ms. Read after, as on main, it measures
what is left of the sleep plus the 9 ms: under 10 ms unless the sleep
overran by more than 9 ms, which a quiet boot's 4 ms tick does not do.

`tools/completion-wait-probe.py` builds and boots the debug `make test`.
`--old` reverse-applies the fix commit (`completion's self-test times
the wait from before the completer exists (TEST-31)`) in a throwaway
worktree, keeping the adversary. It was run on the other machine in the
CI image at four CPUs, on `c51df81e`:

| | x86-64 | AArch64 |
|---|---|---|
| fixed | PASS: `completion ... ok (14 ms)`, `SELFTEST: PASS (529 tests)` | PASS: `ok (17 ms)`, 529 tests |
| `--old` | PASS: `completion ... FAIL: check failed: clock_since_ns(t0) >= MS(10) at line 1376 (14 ms)`, `SELFTEST: FAIL (1 of 529)` | PASS: the same check, `(17 ms)`, 1 of 529 |

The test as a whole takes 14-17 ms; the check fails because the measured
wait is under 10 ms.

## Validation

`make matrix` on `c51df81e`, on the other machine, in the CI image with
the pinned ceesafec 0.57.1, one architecture after the other:

| step | x86-64 | AArch64 |
|---|---|---|
| builds (debug, release, chaos, hbreak), `cee-check` | PASS | PASS |
| `host-test`, `fuzz` | PASS | PASS |
| `analyze` | clean, 15 baselined | clean, 15 baselined |
| debug `test`, `QEMU_SMP=1` / `2` / `4` | 227.6 / 252.8 / 246.8 s | 276.2 / 286.1 / 305.0 s |
| `test-smp2`, `test-chaos`, `test-harness-retry` | 238.1 / 244.1 / 246.7 s | 281.6 / 306.7 / 305.2 s |
| release `test` | 18.9 s | 23.3 s |

## Records

- `docs/backlog.md`: TEST-31, struck through as fixed.
- `docs/testing/flakes.md`: the sighting, as a test defect, not a flake.
- The same order elsewhere: every `clock_now_ns` within six lines after
  a `thread_create(` in `kernel/` was read. One more checks a lower
  bound against the created thread's sleep: `io-poll`
  (`kernel/io/polltest.c`, `selftest_io_poll`) reads `t0` after creating
  `late_writer`, which sleeps 20 ms, and checks the poll lasted 10 ms.
  Its margin is 10 ms, not this test's 0, and it has not failed; backlog
  TEST-32. The others bound from above (`devready`, `ttytest.c`), wait
  for a flag with a deadline (`lockdeptest.c`), or measure without a
  bound (`devtest.c`, `epolltest.c`, `preempt`).
