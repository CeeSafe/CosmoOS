# R1, second PR: the installer ISO, 2026-11-15

Roadmap 1.3 R1 asks for the release in the forms other hypervisors take.
The first PR (#525) added the QCOW2 and the VMDK; this one adds
`cosmoos-<arch>.iso`, a UEFI CD that boots the live system and installs
it onto a disk. The CeeSafe pin moved to 0.48.1 first (#526), as the
owner asked, since the ISO's kernel code is CeeSafe.

## Scope and baseline

Branch `r1-iso`, stacked on `r1-images` (#525) and `ceesafec-0.47.1`
(#526, the 0.48.1 pin).
In scope: the ISO's writer, the kernel's view of the boot volume, the
test, the release set and their documents. Out of scope: a CD driver
(ATAPI or SCSI MMC), and what VMware, VirtualBox and UTM make of the
images (R1's report).

The constraint that shaped it: `scripts/cee-share.py --gate` refuses any
growth in C, the loader's and the installer's included, so neither could
learn about CDs. And the kernel has no CD driver, so what the firmware
reads off the disc is all the system gets.

## What changed

- **`scripts/mkiso.py`.** `bootvol IMAGE DIR` writes partition 1 of the
  live image (the ESP `cosmo-install` copies from a disk boot) as
  `esp.img`, up to its last sector that is not zero, and its length in
  sectors as `sectors`. `iso DISK OUT.iso` writes the least ISO 9660 a
  UEFI firmware boots: a primary volume descriptor, an El Torito boot
  record, the terminator, a catalog (validation entry for platform 0xEF,
  one bootable no-emulation entry), an empty root directory and its path
  tables, and partition 1 of DISK last. The entry's sector count is 1:
  16 bits of 512-byte sectors cannot describe a 64 MiB FAT32 image, and
  EDK2 reads a count below 2 as the rest of the volume. Every date is
  "not specified", so the ISO is a function of its inputs.
- **The Makefile's ISO chain** (`make iso`): the live image's boot volume;
  an archive that is the live one plus `bootvol/esp.img` and
  `bootvol/sectors`; a manifest signing the kernel, that archive and the
  command line; a GPT image from `mkimage.sh` with those; the ISO from its
  partition 1. The release set carries `cosmoos-<arch>.iso`
  (`scripts/mkrelease.py`, `scripts/check-release-version.py` and its
  host test).
- **`kernel/block/bootvol.cee`** (CeeSafe, new): `bootvol_register`,
  called first in the boot-time partition scan (`part.cee`), registers the
  two archive files as `bootvol`, a read-only device of `sectors`
  512-byte sectors that reads zeros past the stored bytes and completes a
  write with `-EROFS`. Nothing is registered when the archive has no
  `bootvol/` files; files that disagree are logged and refused.
  `bootvol_is` names it.
- **`kernel-services/vfs/blkctl.cee`** sets the boot flag on `bootvol`, so
  `cosmo-install` treats it as the boot partition and copies it; the
  installer is unchanged. **`ramfs.cee`** skips `bootvol/` entries, so the
  image is not unpacked a second time into the live root.
- **`scripts/qemu-run.sh`**: `QEMU_BOOT_MEDIA=cdrom` attaches the boot
  image as a read-only CD (q35's default CD drive; a SCSI CD on `virt`).
- **`make test-images`** gains the ISO stage (`tests/boot/images_test.py`;
  docs/userland/testing.md): the ISO boots as a CD beside a blank disk and
  installs onto it; on the host, partition 1 of the result must be the
  live ESP byte for byte; then the disk boots alone, asks for the first
  password, logs in and answers `uname -v`. CI's `install` job runs it,
  both architectures, release builds.
- Documents: docs/boot/design.md ("The installer ISO"),
  docs/kernel/device/design.md (the boot volume, under "Partitions"),
  docs/userland/testing.md, docs/development.md (`iso`, `QEMU_BOOT_MEDIA`,
  the release set), the guide's download paragraph.

## Proof

On the developer's Mac (QEMU 11.1.3), release builds, ceesafec 0.48.1,
on `1d4fc791` (this branch with #525's and #526's heads merged in):

| Check | x86-64 | AArch64 |
|---|---|---|
| `make cee-check` | PASS: every source, `bootvol.cee` among them; `1 negative source(s) refused as their annotations say` | |
| `make BUILD=release test-images` | PASS in 30.7 s; the ISO stage live and installed in 9.4 s, the disk alone booted to `ahci0p0p2` and logged in in 9.3 s | PASS in 43.0 s; the ISO stage live and installed in 13.5 s, the disk alone booted to `vda2` and logged in in 11.6 s |
| the kernel's line on the CD | `bootvol: ... 131072 sectors, 23517184 bytes stored` | `bootvol: ... 131072 sectors, 23865856 bytes stored` |
| `cosmoos-<arch>.iso` | 67,155,968 bytes | 67,155,968 bytes |
| the ISO rebuilt from nothing (`out/.../iso` and the ISO removed) | | the same SHA-256 (`782b4108...`) |
| `make release-set` | | 13 files, the ISO among them, in `SHA256SUMS` |
| `python3 tests/host/test_release_version.py` | 20 ok | |
| `python3 tests/host/test_mkvmimages.py` (#525's) | 21 ok | |
| `scripts/cee-share.py --gate origin/main` | PASS: no tree's C grew | |

The same checks under 0.47.1, before the pin moved, gave the same kernel
lines and sizes.

**The test is not vacuous.** With `bootvol.cee` storing no bytes (every
read zeros: `d.stored = 0`), the AArch64 ISO stage failed with
`test-images: FAIL: iso: the installed disk's partition 1 is not the
live image's ESP byte for byte`; the source restored, it passed. (Run
under 0.47.1, before the pin moved; the 0.48.1 pass is the table's.)

**On Parallels Desktop** (the owner's Mac, a new AArch64 VM "CosmoOS ISO
test" with the ISO on its SATA CD and a blank 512 MiB NVMe disk), an
earlier build of this branch: the firmware booted the CD to the live
system; the kernel registered `bootvol` (64 MiB, 23.9 MB stored);
`cosmo-install --list` showed it read-only with the boot flag;
`cosmo-install nvme0n1` installed (325 files, both partitions); booted
from the disk, the system switched to its root on `nvme0n1p2`, asked
for root's first password, and the login took it. The welcome drew in
colour on the VM's window.

## Validation

VALIDATION

## Limits

- The ISO boots on firmware that reads a sector count below 2 as the rest
  of the volume, as EDK2 does (QEMU's OVMF and AAVMF, Parallels). A
  firmware that reads exactly one sector gets no boot image; which
  firmwares those are is R1's report.
- The live system cannot read the disc after the firmware is done with
  it: no CD driver. The boot volume is copied from memory. Parallels'
  AArch64 machine does not show the kernel its CD at all; x86-64's AHCI
  driver logs `an ATAPI device ... is not driven`.
- The ISO carries the kernel and the live archive twice: in the disc's
  own boot partition, and again inside `bootvol/esp.img`, the installed
  system's boot partition, which that partition's archive holds.
- `cee-share.py --gate` passes: the change adds no C.
