#!/usr/bin/env python3
"""Prove the statfs fix (roadmap 1.3 R2; docs/audit/2026-11-18-r2-fs-grow-report.md).

    statfs-span-probe.py [--old] [--base REV] [--arch ARCH]

cosmofs's statfs reported the pool's linear span -- each member rounded up
to whole bitmap chunks of 32512 blocks -- as its size, so df counted up to
127 MiB of padding that does not exist (a 48891-block root showed 65024).
tests/host/test_cfscore.c now checks that statfs's blocks are the members'
blocks. Without --old the test must pass on this tree. With --old, this
tree's test runs against cosmofs_core.cee as it is at REV (default: where
this branch left origin/main), in a throwaway worktree: it must fail at
that check. Runs `make ARCH=ARCH host-test` for test_cfscore alone; give
CEESAFEC (the pinned ceesafec) in the environment. Exit 0 when the mode
shows what it should.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/host/test_cfscore.c"
CHECK = "rc != 0 || st.blocks == real"


def run(tree, arch):
    make = shutil.which("gmake") or "make"
    r = subprocess.run([make, f"ARCH={arch}", "host-test", "HOST_TESTS=$(HOST_OUT)/test_cfscore"], cwd=tree,
                       capture_output=True, text=True, env=os.environ)
    return r.returncode, r.stdout + r.stderr


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", action="store_true")
    ap.add_argument("--base", help="the tree whose cosmofs --old runs (default: the merge base with origin/main)")
    ap.add_argument("--arch", default="x86_64")
    a = ap.parse_args()
    if not a.old:
        rc, out = run(ROOT, a.arch)
        ok = rc == 0 and "host-test: PASS" in out
        print(f"PROBE: {'PASS' if ok else 'FAIL'} mode=fixed arch={a.arch}: test_cfscore "
              f"{'passed' if ok else 'failed'}")
        return 0 if ok else 1
    base = a.base or subprocess.check_output(
        ["git", "-C", str(ROOT), "merge-base", "HEAD", "origin/main"], text=True).strip()
    tree = Path(tempfile.mkdtemp(prefix="ssp-"))
    tree.rmdir()
    subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(tree), base], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        shutil.copy(ROOT / TEST, tree / TEST)
        rc, out = run(tree, a.arch)
        fails = [line.strip() for line in out.splitlines() if line.strip().startswith("FAIL ")]
        ok = rc != 0 and bool(fails) and fails[0].endswith(CHECK)
        print(f"PROBE: {'PASS' if ok else 'FAIL'} mode=old arch={a.arch} base={base[:12]}: "
              + (f"`{fails[0]}`" if ok else f"not that failure (exit {rc}, first {fails[:1]})"))
        return 0 if ok else 1
    finally:
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(tree)])


if __name__ == "__main__":
    sys.exit(main())
