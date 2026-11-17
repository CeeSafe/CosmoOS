#!/usr/bin/env python3
"""Prove the VMDK redraw fix (docs/audit/2026-11-16-vmdk-redraw-report.md).

    vmdk-redraw-probe.py [--old] [--base REV]

Runs tests/host/test_mkvmimages.py against scripts/mkvmimages.py. With
--old, against the script as it is at REV (default: where this branch
left origin/main), in a throwaway worktree with this tree's test: the test
must fail at the redraw it models, qemu-img's CID of eight digits redrawn
in place as six, refused as "bytes after its text". Without --old, the
test must pass on this tree. Exit 0 when the mode shows what it should.
The script is host-side and the same for both architectures; the probe
takes no ARCH.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/host/test_mkvmimages.py"
FIRST = ("FAIL: qemu-img's CID fedcba98 redrawn as edcba9, 1 bytes of the first text left after the second's end, "
         "gives the same file (mkvmimages: disk.vmdk: the descriptor region holds bytes after its text)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", action="store_true")
    ap.add_argument("--base", help="the tree whose script --old runs (default: the merge base with origin/main)")
    a = ap.parse_args()
    if not a.old:
        r = subprocess.run([sys.executable, str(ROOT / TEST)], capture_output=True, text=True)
        ok = r.returncode == 0 and "FAIL" not in r.stdout
        print(f"PROBE: {'PASS' if ok else 'FAIL'} mode=fixed: test_mkvmimages {'passed' if ok else 'failed'}")
        return 0 if ok else 1
    base = a.base or subprocess.check_output(
        ["git", "-C", str(ROOT), "merge-base", "HEAD", "origin/main"], text=True).strip()
    tree = Path(tempfile.mkdtemp(prefix="vrp-"))
    tree.rmdir()
    subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(tree), base], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        shutil.copy(ROOT / TEST, tree / TEST)
        r = subprocess.run([sys.executable, str(tree / TEST)], capture_output=True, text=True)
        fails = [line for line in r.stdout.splitlines() if line.startswith("FAIL")]
        ok = r.returncode != 0 and fails[:1] == [FIRST]
        print(f"PROBE: {'PASS' if ok else 'FAIL'} mode=old base={base[:12]}: "
              + (f"`{FIRST}`" if ok else f"not that failure (exit {r.returncode}, first {fails[:1]})"))
        for line in fails[1:]:
            print(f"  also: {line}")
        return 0 if ok else 1
    finally:
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(tree)])


if __name__ == "__main__":
    sys.exit(main())
