#!/usr/bin/env python3
"""Roadmap 1.3 R1's CI test: the release's images for other hypervisors
boot (docs/userland/testing.md, "test-images").

    images_test.py --image cosmoos.img --qcow2 cosmoos-ARCH.qcow2 --vmdk cosmoos-ARCH.vmdk --workdir DIR

For each of the QCOW2 and the VMDK (scripts/mkvmimages.py), on the host:
`qemu-img check` finds it consistent and `qemu-img compare` finds its
contents the raw image's, byte for byte. Then a copy of it is booted as
the boot disk in that format (scripts/qemu-run.sh, QEMU_IMAGE_FORMAT), the
only disk attached: the loader and kernel come from it, the kernel finds
the disk the loader was read from and stays on the live root
(root=boot-disk: no CosmoOS root partition on it), the live shell runs
`uname -v` and lists the disk with `cosmo-install --list`, and `exit` ends
the boot.

Every boot's serial log is kept in the work directory. Exit 0 PASS, 1 FAIL.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from install_test import Boot, Fail, need, EXIT_SUCCESS  # noqa: E402

SS = 512


def host_checks(raw, path, fmt):
    for cmd in (["qemu-img", "check", "-q", "-f", fmt, path],
                ["qemu-img", "compare", "-q", "-f", "raw", "-F", fmt, raw, path]):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise Fail(f"{fmt}: `{' '.join(cmd[:2])}` exit {r.returncode}: {(r.stdout + r.stderr).strip()}")


def boot(args, path, fmt):
    d = os.path.join(args.workdir, fmt)
    os.makedirs(d)
    image = os.path.join(d, os.path.basename(path))
    shutil.copyfile(path, image)   # a boot may write its disk (x86 firmware's \NvVars); the release's file stays
    sectors = os.path.getsize(args.image) // SS
    b = Boot(fmt, image, args.workdir, {"QEMU_IMAGE_FORMAT": fmt, "QEMU_DISKS": "boot"}, args.timeout)
    try:
        b.wait_prompt("the first prompt")
        log = b.text()
        need(log, r"root: root=boot-disk: the boot disk has no CosmoOS root partition; the live root stays",
             f"{fmt}: the kernel on the live root of the disk it was read from")
        out = b.run("uname -v")
        m = need(out, r"^CosmoOS \S+ (\S+)$", f"{fmt}: uname -v")
        build = m.group(1)
        out = b.run("cosmo-install --list")
        m = need(out, rf"^(\S+)\s+-\s+{sectors}\s+{SS}\s", f"{fmt}: the boot disk in cosmo-install --list")
        dev = m.group(1)
        rc = b.finish()
        if rc != EXIT_SUCCESS:
            raise Fail(f"{fmt}: QEMU exit code {rc}, expected {EXIT_SUCCESS}")
    except Exception:
        b.kill()
        raise
    return f"{fmt}: PASS in {b.elapsed():.1f}s (build {build}, boot disk {dev}, {sectors} sectors)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="the raw live image the others were made from")
    ap.add_argument("--qcow2", required=True)
    ap.add_argument("--vmdk", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--timeout", type=float, default=240.0, help="per boot")
    args = ap.parse_args()
    shutil.rmtree(args.workdir, ignore_errors=True)
    os.makedirs(args.workdir)
    results = []
    t0 = time.monotonic()
    try:
        for fmt, path in (("qcow2", args.qcow2), ("vmdk", args.vmdk)):
            host_checks(args.image, path, fmt)
            results.append(f"{fmt}: qemu-img check clean, contents equal to {os.path.basename(args.image)}")
            results.append(boot(args, path, fmt))
    except Fail as e:
        for r in results:
            print(f"test-images: {r}")
        print(f"test-images: FAIL: {e} (logs in {args.workdir})")
        return 1
    for r in results:
        print(f"test-images: {r}")
    print(f"test-images: PASS in {time.monotonic() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
