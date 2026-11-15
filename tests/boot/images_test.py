#!/usr/bin/env python3
"""Roadmap 1.3 R1's CI test: the release's images for other hypervisors
boot, and the installer ISO installs (docs/userland/testing.md,
"test-images").

    images_test.py --image cosmoos.img --qcow2 cosmoos-ARCH.qcow2 --vmdk cosmoos-ARCH.vmdk
                   --iso cosmoos-ARCH.iso --workdir DIR

For each of the QCOW2 and the VMDK (scripts/mkvmimages.py), on the host:
`qemu-img check` finds it consistent and `qemu-img compare` finds its
contents the raw image's, byte for byte. Then a copy of it is booted as
the boot disk in that format (scripts/qemu-run.sh, QEMU_IMAGE_FORMAT), the
only disk attached: the loader and kernel come from it, the kernel finds
the disk the loader was read from and stays on the live root
(root=boot-disk: no CosmoOS root partition on it), the live shell runs
`uname -v` and lists the disk with `cosmo-install --list`, and `exit` ends
the boot.

The ISO (scripts/mkiso.py) boots as a CD (QEMU_BOOT_MEDIA=cdrom: q35's
AHCI, virt's virtio-SCSI; the kernel reads neither), with a blank disk
beside it: the kernel registers the boot archive's boot volume as
`bootvol`, `cosmo-install --list` names it the boot device, the install
onto the blank disk succeeds, and on the host the disk's partition 1 is
the live image's ESP byte for byte. Then the disk boots alone: it switches
to its root, asks for root's password at its first boot, logs in, and
powers off.

Every boot's serial log is kept in the work directory. Exit 0 PASS, 1 FAIL.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from install_test import Boot, Fail, need, EXIT_SUCCESS, parse_gpt, esp_of, ESP_TYPE, ROOT_TYPE  # noqa: E402

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


def stage_iso(args):
    """Boot the ISO as a CD beside a blank disk, install, check the disk on the host, boot it."""
    d = os.path.join(args.workdir, "iso")
    os.makedirs(d)
    iso = os.path.join(d, os.path.basename(args.iso))
    shutil.copyfile(args.iso, iso)
    target = os.path.join(d, "target.img")
    with open(target, "wb") as f:
        f.truncate(256 << 20)
    esp = esp_of(open(args.image, "rb").read())
    sectors = len(esp) // SS
    extra = f"-drive if=none,id=inst,format=raw,file={target} -device virtio-blk-pci,drive=inst"
    b = Boot("iso", iso, args.workdir, {"QEMU_BOOT_MEDIA": "cdrom", "QEMU_DISKS": "boot", "QEMU_EXTRA": extra},
             args.timeout)
    try:
        b.wait_prompt("the first prompt")
        log = b.text()
        need(log, r"^boot volume: no GPT partition$", "iso: the loader read from the CD")
        need(log, rf"^\[ INFO\] bootvol: the installed system's boot partition, from the boot archive: {sectors} "
             r"sectors, \d+ bytes stored$", "iso: the boot volume")
        need(log, r"root: root=boot-disk: the boot disk has no CosmoOS root partition; the live root stays",
             "iso: the live root")
        out = b.run("cosmo-install --list")
        need(out, rf"^bootvol\s+-\s+{sectors}\s+{SS}\s+ro boot\s*$", "iso: bootvol, the boot device, in cosmo-install --list")
        m = need(out, rf"^(\S+)\s+-\s+{(256 << 20) // SS}\s+{SS}\s", "iso: the blank disk in cosmo-install --list")
        dev = m.group(1)
        out = b.status(f"cosmo-install {dev}", "install-status")
        need(out, r"^install-status=0$", "iso: cosmo-install")
        m = need(out, rf"^cosmo-install: installed on {dev}: esp ({dev}p?1), root ({dev}p?2), "
                      r"partuuid ([0-9a-f-]{36})$", "iso: cosmo-install")
        partuuid = m.group(3)
        rc = b.finish()
        if rc != EXIT_SUCCESS:
            raise Fail(f"iso: QEMU exit code {rc}, expected {EXIT_SUCCESS}")
    except Exception:
        b.kill()
        raise
    install_s = b.elapsed()

    data = open(target, "rb").read()
    _, parts = parse_gpt(data)
    if [(p[0], p[1]) for p in parts] != [(1, ESP_TYPE), (2, ROOT_TYPE)]:
        raise Fail(f"iso: the installed disk's partitions are {parts}")
    (_, _, _, f1, l1), (_, _, u2, _, _) = parts
    if str(u2) != partuuid:
        raise Fail(f"iso: partition 2 is {u2}, the installer said {partuuid}")
    if data[f1 * SS:(l1 + 1) * SS] != esp:
        raise Fail("iso: the installed disk's partition 1 is not the live image's ESP byte for byte")

    b = Boot("iso-installed", target, args.workdir, {"QEMU_DISKS": "boot"}, args.timeout)
    try:
        b.wait_prompt("the installed disk's first prompt")
        log = b.text()
        m = need(log, r"^init: switched to the disk root (\S+) \(root=boot-disk\)$", "iso: the installed boot")
        need(log, r"root has no password yet: choose one now\.$", "iso: the installed boot's first password")
        need(log, r" login: root$", "iso: the installed boot's login")
        out = b.run("uname -v")
        need(out, r"^CosmoOS \S+ \S+$", "iso: uname -v on the installed system")
        rc = b.finish()
        if rc != EXIT_SUCCESS:
            raise Fail(f"iso-installed: QEMU exit code {rc}, expected {EXIT_SUCCESS}")
    except Exception:
        b.kill()
        raise
    return (f"iso: PASS (live from the CD and installed on {dev} in {install_s:.1f}s; partition 1 the image's ESP "
            f"byte for byte; the disk alone booted to root {m.group(1)} and logged in in {b.elapsed():.1f}s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="the raw live image the others were made from")
    ap.add_argument("--qcow2", required=True)
    ap.add_argument("--vmdk", required=True)
    ap.add_argument("--iso", required=True)
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
        results.append(stage_iso(args))
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
