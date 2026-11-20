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

`t0` is read before `thread_create`, so the measured wait covers the
whole sleep whenever the completer starts. The assertion is kept: the
waiter must block until the completer completes, no sooner than its
sleep after `t0`.

## The proof

The test now carries its adversary: after `thread_create` the test
sleeps 9 ms before `wait_for_completion`, as a waiter preempted there
would, and the completer sleeps 30 ms (it slept 10). The check is
`clock_since_ns(t0) >= MS(30)`.
- With `t0` read before the completer exists, the wait measures the
  whole sleep, and still blocks: the waiter arrives 9-13 ms in, about
  20 ms before the completion.
- Read after, where main reads it (after the adversary's 9 ms), it
  measures what is left of the sleep: under 30 ms on every boot, at any
  CPU count, since the completer begins its sleep during or before the
  9 ms.

The first version of this branch kept the 10 ms sleep and had the waiter
arrive 9 ms into it. Codex's review pointed out that on one CPU the
waiter's tick-rounded 9 ms could end after the completion, so the test
no longer waited on a pending completion. The 30 ms sleep keeps that
case. Kernel C may not grow (CI's `cee-share`), so the change adds no
lines: the two checks after `thread_create` are one.

`tools/completion-wait-probe.py` builds and boots the debug `make test`
at one CPU. `--old` reverse-applies the fix commit (`completion's
self-test times the wait from before the completer exists (TEST-31)`) in
a throwaway worktree, keeping the adversary. It was run on the other
machine in the CI image (four host CPUs), on `9b4ddcb3`:

| | x86-64 | AArch64 |
|---|---|---|
| fixed | PASS: `completion ... ok (34 ms)`, `SELFTEST: PASS (529 tests)` | PASS: `ok (34 ms)`, 529 tests |
| `--old` | PASS: `completion ... FAIL: check failed: clock_since_ns(t0) >= MS(30) at line 1363 (31 ms)`, `SELFTEST: FAIL (1 of 529)` | PASS: the same check, `(34 ms)`, 1 of 529 |

The time in brackets is the whole test's, not the measured wait.

## Validation

`make matrix` on `9b4ddcb3`, on the other machine, in the CI image with
the pinned ceesafec 0.57.1, one architecture after the other:

(running)

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
