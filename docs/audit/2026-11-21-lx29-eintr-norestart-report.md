# LX-29: SA_RESTART restarted the calls Linux never restarts, 2026-11-21

Found on v1.1.2-rc1 (`9d91c489`), on the owner's Parallels VM, during the
rc's check of what the release adds. `pkg install openssh-server` from the
rc's own ports and `svc start sshd` left the machine with no ssh server:

```
Bind to port 22 on 0.0.0.0 failed: Address in use.
Cannot bind any address.
svc: sshd: exited with status 255
svc: sshd: giving up after 5 restarts
```

dropbear still held port 22. A defect found on an rc is fixed through the
ordinary workflow and a new rc (AGENTS.md, "Releases"), so v1.1.2 waits
for rc2 on this fix.

## Scope and baseline

Branch `lx-eintr-norestart` from main at `9d91c489` (#539's merge, the
rc's commit; CI run 44804214534 passed). The Linux personality's
`lxpoll.cee`, `lxfd.cee`, `lxtime.cee` and `sigcalls.cee`; a check in
`tests/linux/lxtest.c`; a probe. No C is added (CI's `cee-share`).

## The mechanism

What the VM showed:

- `/etc/ssh/start` runs `svc stop dropbear` and then `exec sshd`.
  `svc stop` sends SIGTERM to dropbear and returns.
- dropbear was still running 200 s after `svc stop dropbear` (the
  console polled `ps` once a second). It exited the moment a connection
  reached port 22: `Early exit: Terminated by signal` at 06:07:49, the
  second the Mac connected.
- A direct `kill -TERM` did the same, so `svc` is not the cause.

dropbear is a static musl program (the Linux personality). Its listener
loop blocks in `select` (`pselect6` on AArch64) with no timeout, and
checks its exit flag when `select` returns. musl's `signal()` installs
the SIGTERM handler with `SA_RESTART`.

The kernel's delivery (`kernel/process/signal.c`, `signal_deliver`)
restarts any system call that returned `-EINTR` when the handler has
`SA_RESTART`, unless the call cleared its number (`SIGNAL_NO_RESTART`).
Linux never restarts some calls after a handler, whatever `SA_RESTART`
says, and does restart them after a stop (signal(7); the kernel's
`ERESTARTNOHAND`): `poll`, `ppoll`, `select`, `pselect6`, `epoll_wait`,
`epoll_pwait`, `nanosleep`, `clock_nanosleep`, `rt_sigsuspend` and
`pause` are the ones this personality implements. So dropbear's handler
ran and set the flag, and its `select` was restarted and blocked again.

`make test-ports` did not show it: its step s connects to port 22 until
OpenSSH's banner answers, and the first connection woke dropbear.

The calls signal(7) lists that this personality does not implement
(`epoll_pwait2`, `rt_sigtimedwait`, `io_getevents`, `msgrcv`, `msgsnd`,
`semop`, `semtimedop`) cannot return `-EINTR` here. `futex`'s
`FUTEX_WAIT` is restarted under `SA_RESTART` on Linux too, and is left
as it is.

## The fix

Each of the ten calls passes its result through `noRestart`, which sets
`SIGNAL_RESTART_NOHAND` (bit 62) in the thread's `syscall_nr` when the
result is `-EINTR`. `signal.c` then restarts it after a stop, with the
bit masked off, and not after a handler. Two lines change in `signal.c`
and the comment and define in `signal.h` take the old four lines, so no
C line is added.

The first version cleared the number (`SIGNAL_NO_RESTART`), as the
`rt_sigreturn` paths do. That also stopped the restart after a stop, and
every boot the matrix ran failed (x86-64's seven, release included,
and AArch64's first two before it was stopped):
- the shell harness's `sleep 30 | cat` ended at once on `^Z` and `fg`,
  since `sleep`'s `nanosleep` returned;
- `signal-stop-threads` failed its check 14.

The probe then judged lxtest's lines only, so it passed. Its fixed mode
now also needs the boot test to pass.

One helper per module: the modules share a function through a
prototype in `linux_internal.h` (as `lx_ns_from_timespec`), which is C.
- `lxpoll.cee`: `poll`, `ppoll`, `pselect6`, `select`.
- `lxfd.cee`: `epoll_wait`, `epoll_pwait`.
- `lxtime.cee`: `nanosleep` and `clock_nanosleep`, through
  `sleepReportingRest`, their one return.
- `sigcalls.cee`: `rt_sigsuspend`, `pause`.

`docs/compat/linux/invariants.md` (L5) names the exception.

## The proof

`lxtest`'s new block, "the calls Linux never restarts". For each call:
- A thread blocks in it for up to two seconds, on an empty pipe, an
  epoll set holding the pipe, a two-second sleep, or `rt_sigsuspend`
  with no signal blocked.
- The main thread sends it SIGUSR1, whose handler has `SA_RESTART`, and
  100 ms later reads the thread's result.
- It must be `-EINTR`. If the thread has not returned, a SIGUSR2 without
  `SA_RESTART` ends the call, so a restarted call cannot hang the test.
  The check's value is the call's index times 1000 plus 99, "not
  returned".

AArch64 has six of the calls; x86-64 also has `poll`, `select`,
`epoll_wait` and `pause`.

`tools/eintr-norestart-probe.py` boots the debug `make test` and judges
lxtest's lines. `--old` reverse-applies the fix commit (`compat/linux: a
handler with SA_RESTART ends poll, select, epoll_wait, the sleeps and
sigsuspend with EINTR (LX-29)`) in a throwaway worktree. It was run on
the other machine in the CI image, on `5fb30c86`:

| | x86-64 | AArch64 |
|---|---|---|
| fixed | PASS: `LINUXTEST: PASS` | PASS: `LINUXTEST: PASS` |
| `--old` | PASS: `LINUXTEST: FAIL (10 checks)`, exactly `nr_seen == -4` with 99, 1099, ... 9099 | PASS: `LINUXTEST: FAIL (6 checks)`, exactly 99, 1099, ... 5099 |

Every call was still blocked 100 ms after the restarting signal without
the fix, and none was with it.

## Validation

MATRIX_TABLE

## Limits

- `svc stop` still returns before the service has exited, and
  `/etc/ssh/start` starts sshd right after it. dropbear now exits as soon
  as its handler runs, and sshd's start retries under `svc`'s backoff.
  The rc2 VM check is the end-to-end proof.
- The native personality's `SA_RESTART` rule is unchanged: CosmoOS's own
  ABI restarts any `-EINTR` under it (`kernel/include/uapi/cosmo/syscall.h`).
