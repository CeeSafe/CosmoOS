#!/usr/bin/env python3
"""mkcloudimage.py --image LIVE.img --out CLOUD.qcow2 [--workdir DIR] [--mib N]

The cloud image (roadmap 1.3 R2; docs/userland/design.md, "The cloud
image"): an installed system, the disk `cosmo-install` writes, as QCOW2.
It is made the way `make test-install` makes one: the live image boots in
QEMU (scripts/qemu-run.sh, through tests/boot/install_test.py's Boot) with
a blank N MiB disk (default 256), `cosmo-install` installs on it, the root
is mounted to check it has at least half as much again free as it holds,
and the boot powers off; `qemu-img convert` writes the disk as QCOW2.

Nothing specific to a machine is in it: dropbear's host key is made at the
first start, there is no /etc/hostname, root has no password and an empty
authorized_keys. The disk and partition GUIDs and the pool's uuid are drawn
by cosmo-install, so the image is not byte-reproducible; it is not part of
`make release`'s set (which two builds must make the same), and the release
workflow makes it from the published live image in a job of its own.

The live image's QEMU, firmware and network are qemu-run.sh's, so the
architecture is the image's: give ARCH in the environment as for `make`.
Exit 0 when the image is written.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests", "boot"))
import install_test  # noqa: E402
from install_test import Boot, Fail, need, SS, EXIT_SUCCESS  # noqa: E402


def install(live, target, mib, work, timeout):
    """Boot `live` with `target` attached; install on it. Returns (dev, used KiB, free KiB)."""
    env = {"QEMU_EXTRA": (os.environ.get("QEMU_EXTRA", "") +
                          f" -drive if=none,id=inst,format=raw,file={target} -device virtio-blk-pci,drive=inst").strip()}
    b = Boot("cloud-install", live, work, env, timeout)
    try:
        b.wait_prompt("the first prompt")
        out = b.run("cosmo-install --list")
        dev = need(out, rf"^(\S+)\s+-\s+{(mib << 20) // SS}\s+{SS}\s", "cosmo-install --list").group(1)
        out = b.status(f"cosmo-install {dev}", "install-status")
        need(out, r"^install-status=0$", "cosmo-install")
        root_dev = need(out, rf"^cosmo-install: installed on {dev}: esp {dev}p?1, root ({dev}p?2), ",
                        "cosmo-install").group(1)
        out = b.run(f"mkdir /mnt/c && mount -t cosmofs /dev/{root_dev} /mnt/c && df -k /mnt/c && "
                    "umount /mnt/c && echo look-ok")
        need(out, r"^look-ok$", "the installed root")
        m = need(out, r"^\S+\s+(\d+)\s+(\d+)\s+(\d+)\s+\d+%\s+/mnt/c$", "df -k of the installed root")
        used, free = int(m.group(2)), int(m.group(3))
        rc = b.finish()
        if rc != EXIT_SUCCESS:
            raise Fail(f"install boot: QEMU exit code {rc}, expected {EXIT_SUCCESS}")
    except Exception:
        b.kill()
        raise
    return dev, used, free


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True, help="the live image (cosmoos-ARCH.img)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir")
    ap.add_argument("--mib", type=int, default=256)
    ap.add_argument("--timeout", type=float, default=240.0)
    a = ap.parse_args()
    work = a.workdir or os.path.splitext(a.out)[0] + "-work"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(os.path.join(work, "live"))
    live = os.path.join(work, "live", "cosmoos.img")
    shutil.copyfile(a.image, live)   # the scratch disks qemu-run.sh makes land beside it
    target = os.path.join(work, "cloud.img")
    with open(target, "wb") as f:
        f.truncate(a.mib << 20)
    try:
        dev, used, free = install(live, target, a.mib, work, a.timeout)
    except Fail as e:
        print(f"mkcloudimage: FAIL: {e} (logs in {work})", file=sys.stderr)
        return 1
    if free * 2 < used:
        print(f"mkcloudimage: the root holds {used} KiB with {free} KiB free on {a.mib} MiB, less than half as "
              f"much again: give a larger --mib", file=sys.stderr)
        return 1
    tmp = a.out + ".tmp"
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    subprocess.run(["qemu-img", "convert", "-q", "-f", "raw", "-O", "qcow2", target, tmp], check=True)
    os.replace(tmp, a.out)
    shutil.rmtree(work, ignore_errors=True)
    print(f"mkcloudimage: {a.out}: {a.mib} MiB, installed on {dev}; the root holds {used} KiB, {free} KiB free")
    return 0


if __name__ == "__main__":
    sys.exit(main())
