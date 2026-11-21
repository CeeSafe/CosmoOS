#!/usr/bin/env python3
"""Prove the Linux personality ends a never-restarted call with EINTR under SA_RESTART (LX-29).

    eintr-norestart-probe.py [--old] [--arch x86_64|aarch64] [--tree REV] [--fix REV]

Linux never restarts poll, ppoll, select, pselect6, epoll_wait, epoll_pwait,
nanosleep, clock_nanosleep, rt_sigsuspend or pause after a handler, whatever
SA_RESTART says (signal(7)); the kernel's delivery restarted every -EINTR
under SA_RESTART. So dropbear's SIGTERM handler ran and its select carried
on, and `svc stop dropbear` left it holding port 22 (v1.1.2-rc1 on the
Parallels VM). The probe boots a debug build and judges lxtest's block for
these calls (tests/linux/lxtest.c, "the calls Linux never restarts") by its
own lines.

  fixed  `LINUXTEST: PASS`, no failed check, and the boot test passes: each
         call, blocked in a thread for up to two seconds, has returned
         -EINTR 100 ms after a signal whose handler has SA_RESTART, and a
         call cut short by a stop is still restarted (the shell harness's
         `sleep 30 | cat` under ^Z and fg, the `signal-stop-threads`
         self-test).
  --old  the fix commit reverse-applied whole in a throwaway worktree:
         exactly those checks fail, each still blocked (the value is the
         call's number times 1000 plus 99, the thread's "not returned"),
         and nothing else fails. AArch64 has six of the calls, x86-64 ten.

Logs stay under out/eintr-norestart-probe/<arch>-<mode>. Exit 0 when the
mode shows what it should, else 1.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SUBJECT = "compat/linux: a handler with SA_RESTART ends poll, select, epoll_wait, the sleeps and sigsuspend with EINTR (LX-29)"
CALLS = {"aarch64": 6, "x86_64": 10}   # lxtest.c's NR_POLL, and NR_CALLS


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", action="store_true")
    ap.add_argument("--arch", choices=("x86_64", "aarch64"), default="x86_64")
    ap.add_argument("--tree", default="HEAD")
    ap.add_argument("--fix", help="the fix commit (default: found by its subject)")
    a = ap.parse_args()
    mode = "old" if a.old else "fixed"
    work = ROOT / "out" / "eintr-norestart-probe" / f"{a.arch}-{mode}"
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        sys.exit(f"refusing to overwrite nonempty probe output {work}")
    # A short path: the boot's sockets live under its output directory.
    tree = Path(tempfile.mkdtemp(prefix=f"enr-{a.arch[:3]}-{mode}-", dir=ROOT / "out"))
    tree.rmdir()
    subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(tree), a.tree], check=True,
                   stdout=subprocess.DEVNULL)
    try:
        if a.old:
            sha = a.fix or subprocess.check_output(
                ["git", "-C", str(ROOT), "log", "-1", "--format=%H", "--fixed-strings", f"--grep={SUBJECT}", a.tree],
                text=True).strip()
            if not sha:
                sys.exit(f"no commit '{SUBJECT}' reachable from {a.tree}; name it with --fix")
            # The whole commit, not chosen hunks.
            patch = subprocess.check_output(["git", "-C", str(ROOT), "show", "--format=", sha])
            subprocess.run(["git", "-C", str(tree), "apply", "-R", "--index"], input=patch, check=True)
        make = "gmake" if sys.platform == "darwin" else "make"
        dbg = tree / "out" / "d"
        with (work / "make-debug.log").open("w") as log:
            rc = subprocess.run([make, "-C", str(tree), "-j8", f"ARCH={a.arch}", f"OUT={dbg}", "test"],
                           stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=1800,
                           start_new_session=True).returncode
        boot = dbg / "boot-test.log"
        serial = boot.read_text(errors="replace") if boot.exists() else ""
        if boot.exists():
            subprocess.run(["cp", str(boot), str(work)], check=False)
        fails = [ln for ln in serial.splitlines() if ln.startswith("LINUXTEST: FAIL ") and not
                 re.match(r"LINUXTEST: FAIL \(\d+", ln)]
        passed = re.search(r"^LINUXTEST: PASS$", serial, re.M) is not None
        if a.old:
            want = [f"LINUXTEST: FAIL nr_seen == -4 ({c * 1000 + 99})" for c in range(CALLS[a.arch])]
            ok = sorted(fails) == sorted(want) and \
                re.search(rf"^LINUXTEST: FAIL \({len(want)}\b", serial, re.M) is not None
            seen = f"{len(fails)} failed checks" + ("" if ok else f": {fails}")
        else:
            ok = passed and not fails and rc == 0
            seen = "LINUXTEST: PASS, the boot test passed" if ok else \
                f"{len(fails)} failed checks: {fails}; make test exit {rc}"
        print(f"PROBE: {'PASS' if ok else 'FAIL'} arch={a.arch} mode={mode}: {seen} ({work})")
        return 0 if ok else 1
    finally:
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(tree)])


if __name__ == "__main__":
    sys.exit(main())
