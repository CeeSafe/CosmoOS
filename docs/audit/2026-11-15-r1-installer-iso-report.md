# R1, second PR: the installer ISO, 2026-11-15

Roadmap 1.3 R1 asks for the release in the forms other hypervisors take.
The first PR (#525) added the QCOW2 and the VMDK; this one adds
`cosmoos-<arch>.iso`, a UEFI CD that boots the live system and installs
it onto a disk. The CeeSafe pin moved to 0.48.1 first (#526), as the
owner asked, since the ISO's kernel code is CeeSafe.

## Scope and baseline

Branch `r1-iso`, made on `r1-images` (#525) and `ceesafec-0.47.1` (#526,
the 0.48.1 pin) and merged with main after both (`af5a8b66`).
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

**Found by the matrix: two host tests that did not link.** The first
matrix of this branch (the other machine, 2026-11-15) failed `make
host-test` on both architectures, so it booted nothing: `test_blkctl`
links `blkctl.c`, which now calls `bootvol_is`, and `test_part` links
`part.c`, which now calls `bootvol_register`, and neither test defined
them. Both are digest tests recorded from the C before the CeeSafe
port, which had no boot volume. Each now defines the function without
noting it in the digest, so the digests are still the C's
(`0xa8eae3202115e31f` for `blkctl`), and checks it directly:
`blkctl_bootvol` names each of six devices the boot volume in turn, then
none, and requires `LIST` to mark that one with `COSMO_BLKCTL_BOOT` and
no other, partitions and the read-only flag as before; `test_part`
requires one `bootvol_register` per `blk_part_scan_all`. With
`blkctl.cee` setting no flag for the boot volume, `blkctl_bootvol` failed
(`((d.flags & COSMO_BLKCTL_BOOT) != 0) == (i == which)`); with
`part.cee` not calling `bootvol_register`, `test_part` failed
(`g_bootvol_calls == g_scan_alls`); both sources restored, `make
host-test` passed on the Mac. `uapi/cosmo/blkctl.h`'s comment on the boot
flag names the boot volume.

**Found by CI and review on the PR (#527, run 43683617004).**
- *A debug ISO did not fit.* `make reproducible`, which builds the
  release set in a debug build, failed on both architectures with
  mtools' `Disk full` writing the ISO's disk: its ESP holds the kernel,
  the archive and, inside the archive, the installed ESP (35 MB stored in
  a debug build), over the 64 MiB `mkimage.sh` makes. Every proof above
  was of release builds. `mkimage.sh` now takes `MKIMAGE_ESP=fit`, which
  the ISO's disk alone uses: the files, a sixteenth more and 4 MiB, 64 MiB
  at least. The debug ISOs are 84,981,760 bytes (x86-64) and 86,030,336
  (AArch64); the release ISOs stay 67,155,968; the live image's ESP, the
  one installed, stays 64 MiB. `make ARCH=aarch64 reproducible` on the
  Mac: `reproducible: yes`, 28 files the same, the release set's
  `SHA256SUMS` (the ISO's line among them) among them.
- *`cee-share` failed* on the boot flag's comment, two more lines of C
  in `kernel/`; it is one line again, and the gate passes.
- *Greptile: the image path lost its quotes.* Moving the boot drive into
  variables for `QEMU_BOOT_MEDIA` made `qemu-run.sh` split a path with a
  space. The variables now hold the drive's options and devices only, and
  the path is quoted in `-drive` as on main. Through a `QEMU_WRAP` that
  prints each argument, a path with spaces is one argument in all four
  cases (two machines, disk and CD); in the default disk mode, main's
  `qemu-run.sh` and this one give QEMU the same arguments, 64 on x86-64
  and 68 on AArch64, so the matrix's boots are unchanged by it.
- `make BUILD=release test-images` passed again on both architectures.
  The `x86_64, boots` job's `test-guard` boot failed in TEST-28's slow
  mode (`cosmofs-replay` 40605 ms; flakes.md).

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

On the other machine (the CI image, one container of 4 CPUs and 6 GiB,
ceesafec 0.48.1's Linux build from the tree; `qemu-utils`, which the
image predates and `test_mkvmimages.py` needs, installed in each
container as this branch's `ci/Dockerfile` installs it), 2026-11-15,
both architectures one after the other, on `f95da85b` (main's merge
since adds one paragraph to flakes.md). The first run, on `1d4fc791`,
failed `make host-test` on both and booted nothing (Proof, "Found by the
matrix"). AArch64: `matrix: PASS`. x86-64: `matrix: FAIL` on two
two-CPU boots, below.

| Step | x86-64 | AArch64 |
|---|---|---|
| debug, release, chaos and harness-retry builds, `make cee-check` | PASS | PASS |
| `make host-test`, `make fuzz` | PASS | PASS |
| `make analyze` | clean (15 baselined, 0 unexpected, 0 stale) | clean (15 baselined, 0 unexpected, 0 stale) |
| debug `make test`, `QEMU_SMP=1` | PASS in 246.5 s | PASS in 275.5 s |
| debug `make test`, `QEMU_SMP=2` | FAIL after 242.2 s (`blk-irq-budget`); alternated with the base, below: 2 of 2 PASS | PASS in 285.6 s |
| debug `make test`, `QEMU_SMP=4` | PASS in 260.1 s | PASS in 310.6 s |
| `make test-smp2` | FAIL after 304.0 s (timed out); alternated with the base, below: 3 of 3 PASS | PASS in 285.4 s |
| `make test-chaos` | PASS in 254.5 s | PASS in 305.4 s |
| `make test-harness-retry` | PASS in 257.6 s | PASS in 302.8 s |
| `make BUILD=release test` | PASS in 20.1 s | PASS in 23.8 s |

**The two failures.** The `QEMU_SMP=2` boot failed one self-test of 528,
`blk-irq-budget`: `the device had the next completion ready under 90% of
the time`, ready 2944 times of 3301 (89%), its longest tick gap 165 ms
and a bystander's wait 222 ms, under their 250 ms bounds. The storm
formed and stalled for part of its second: the host holding a vCPU, the
check flakes.md's 2026-10-13 entry describes. `test-smp2` timed out with
`self-test cosmofs-replay took 46379 ms (budget 40000 ms)` and the
watchdog's line, `blk-irq-budget` passing (tick gap 9 ms): TEST-28's slow
mode, seen at two CPUs for the first time; every other x86-64 boot of
the matrix took 30.2 to 36.0 s for `cosmofs-replay`. The branch's kernel
change is the boot volume, which registers nothing on these boots (their
archive has no `bootvol/`), so the branch and its base (`e63ac6c0`,
main's tree since #526) were booted alternately on the same machine:

| boot | base: `cosmofs-replay`, verdict | branch |
|---|---|---|
| `test-smp2` 1 | 28488 ms, PASS in 237.6 s | 28792 ms, PASS in 238.2 s |
| `test-smp2` 2 | 29504 ms, PASS in 239.7 s | 28945 ms, PASS in 240.5 s |
| `test-smp2` 3 | 28687 ms, PASS in 240.4 s | 29222 ms, PASS in 236.1 s |
| `QEMU_SMP=2` 1 | 29780 ms, PASS in 237.9 s | 29515 ms, PASS in 239.4 s |
| `QEMU_SMP=2` 2 | 29535 ms, PASS in 240.2 s | 29861 ms, PASS in 241.3 s |

The self-tests' totals agree within 2% (179.7 to 183.7 s). Recorded in
flakes.md under both entries, and backlog TEST-28. No budget was changed.

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
