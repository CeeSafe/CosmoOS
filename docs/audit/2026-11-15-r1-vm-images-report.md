# R1, first PR: the release's QCOW2 and VMDK, 2026-11-15

Roadmap 1.3 R1 ("Images for the hypervisors people have"), chosen by the
owner 2026-11-15 after v1.1.1. R1's acceptance is a CI job that boots the
QCOW2 image and boots the ISO, installs from it and boots the result, on
both architectures, and a dated report of the release on VMware,
VirtualBox and UTM. This PR is the QCOW2 and VMDK half; the installer ISO
and the report on the three hypervisors follow in their own PRs.

## Scope and baseline

Branch `r1-images` from main at `9f466e70` (v1.1.1's record). In scope:
the release set, `qemu-run.sh`'s boot disk, a new image test, the CI
image's packages. No compiled code changes.

R1's text says `make dist` writes the images. Since the roadmap was written
`make dist` is the source tarball that builds without ceesafec
(`scripts/dist.py`), so the images are made by their own target,
`make vm-images`, and carried by `make release`'s set, which is what the
release publishes.

## What changed

- **`scripts/mkvmimages.py`** makes `cosmoos-<arch>.qcow2` and
  `cosmoos-<arch>.vmdk` (one-file `monolithicSparse`) from the live image
  with `qemu-img convert`. The release requires every file of its set to be
  the same in two builds (`make reproducible`, the release workflow's
  `two builds compared`). QCOW2 is: two conversions of one image are equal.
  A VMDK is not: its embedded descriptor carries a content id
  (`CID=`) that qemu-img draws at random, and its extent line names the
  file it was written as. The script converts under the final name (in a
  fresh directory beside it) and replaces the CID with the first eight hex
  digits of the image's SHA-256, the same length, so no byte moves.
- **`make vm-images`**, and the release set (`scripts/mkrelease.py`,
  `make release-set`) carries both; `scripts/check-release-version.py`'s
  list of a set's names and its host test know them.
- **`QEMU_IMAGE_FORMAT`** in `scripts/qemu-run.sh` (default `raw`): the
  boot disk's format on both machines.
- **`make test-images`** (`tests/boot/images_test.py`): for each image,
  `qemu-img check` and `qemu-img compare` against the raw image on the
  host, then a boot of a copy as the only disk in its format, which must
  show the kernel finding the disk the loader was read from
  (`root: root=boot-disk: the boot disk has no CosmoOS root partition; the
  live root stays`), answer `uname -v` and `cosmo-install --list` with the
  disk at the image's size, and end with the kernel's success code. CI runs
  it in the `install` job (release builds, both architectures).
- **The CI image gains `qemu-utils`** (qemu-img; Debian installs QEMU
  without it under `--no-install-recommends`), and `make check-tools`
  asks for `qemu-img`.
- Documents: `docs/development.md` (the targets, the set, the variable),
  `docs/userland/testing.md` ("test-images"), the guide's download
  paragraph (`docs/guide/installing.md`).

## Proof

On the developer's Mac (QEMU 11.1.3, `qemu-img` from Homebrew):

| Check | x86-64 | AArch64 |
|---|---|---|
| `make BUILD=release test-images` | PASS in 14.1 s: QCOW2 7 s, VMDK 7 s, boot disk `ahci0p0` | PASS in 19.1 s: QCOW2 9 s, VMDK 10 s, boot disk `vda` |
| `scripts/mkvmimages.py` twice on v1.1.1's published AArch64 image | | both files identical; `qemu-img compare` equal |
| the QCOW2 booted as raw (`qemu-run.sh`'s format pinned to `raw` by hand) | | FAIL: `the firmware did not hand over within 30s, twice (no loader banner)` |
| `python3 tests/host/test_release_version.py` | ok | |
| `make release-set` | | 12 files, the QCOW2 and VMDK among them; `check-release-version.py` names no file |

## Ahead of the ISO: a prototype on Parallels

The owner asked for the ISO on Parallels Desktop before it exists. The
ISO's open question is the firmware's: a UEFI El Torito boot image over
32 MiB has no sector count the specification allows (the field counts
512-byte sectors in 16 bits), and the boot partition is 64 MiB, FAT32's
least. A throwaway ISO 9660 writer (not in this PR) put v1.1.1's
published AArch64 boot partition last on the disc, its catalog entry
platform 0xEF, no emulation, sector count 1 (which EDK2 reads as "the rest
of the volume").

| Where | Result |
|---|---|
| QEMU 11.1.3, EDK2, the ISO on a virtio-SCSI CD, no other disk | `boot volume: no GPT partition`, `build v1.1.1`, the live root, `CosmoOS userland ready`, the shell |
| Parallels Desktop, a new VM "CosmoOS ISO test" (2 CPUs, 2 GiB, the ISO on its SATA CD, a blank 512 MiB NVMe disk) | the same: the firmware read the 64 MiB boot image off the CD; the live system, the welcome screen in colour on the window, `cosmo-install --list` naming only `nvme0n1` |

Parallels' AArch64 SATA controller is reached through ACPI's AML only
(backlog DRV-4), so the kernel never sees the CD drive. The installer
lists no source to copy, as expected: the ISO's install path is the next
PR's.

Found on that VM, on the live image and so in v1.1.1 itself, and added to
the backlog: `clear` erases nothing on the window (the framebuffer console
ignores `ESC [ J`; DRV-19), and `cosmo-welcome` typed at the live image's
shell fails `Exec format error`, `cosmo-sh` running no `#!` script
(USR-11).

## Validation

On the other machine (`docs/development.md`, "Running the matrix": the CI
image, one container of 4 CPUs and 6 GiB), 2026-11-15, both architectures
one after the other, on `b8f36309` (this PR's code; the later commits are
documents). AArch64: `matrix: PASS`. x86-64: `matrix: FAIL` on
`test-chaos` alone, out of time in the four-CPU slow mode (below).

| Step | x86-64 | AArch64 |
|---|---|---|
| debug, release, chaos and harness-retry builds, `make cee-check` | PASS | PASS |
| `make host-test`, `make fuzz` | PASS | PASS |
| `make analyze` | clean (15 baselined, 0 unexpected, 0 stale) | clean (15 baselined, 0 unexpected, 0 stale) |
| debug `make test`, `QEMU_SMP=1` | PASS in 242.6 s | PASS in 279.0 s |
| debug `make test`, `QEMU_SMP=2` | PASS in 238.6 s | PASS in 288.0 s |
| debug `make test`, `QEMU_SMP=4` | PASS in 243.9 s | PASS in 303.2 s |
| `make test-smp2` | PASS in 241.0 s | PASS in 289.5 s |
| `make test-chaos` | FAIL after 304.5 s (timed out); run again: PASS in 246.1 s | PASS in 305.4 s |
| `make test-harness-retry` | PASS in 244.2 s | PASS in 299.8 s |
| `make BUILD=release test` | PASS in 20.2 s | PASS in 24.2 s |

**The timed-out boot.** `timed out after 300s`, with `self-test
cosmofs-replay took 54117 ms (budget 40000 ms)` and `cosmofs-snap-reserved
took 8905 ms (budget 8000 ms)`; no self-test failed. That is the slow mode
of four-CPU x86-64 debug boots on that machine (`docs/testing/flakes.md`,
2026-11-14; backlog TEST-28): `cosmofs-replay` at 53 to 56 s instead of 30
to 36. The step run again took the fast mode (`cosmofs-replay` 29.6 s).
This PR compiles nothing new into a kernel or a program. No budget was
changed.

## Limits

- The images are the live image in other containers: what each hypervisor
  presents to the image (its disk controller, its network card) is R1's
  report, not this PR's.
- The VMDK says `ddb.adapterType = "ide"`, qemu-img's default. VMware
  attaches a disk it imports to the controller the virtual machine has;
  CosmoOS has no IDE driver, so on VMware the disk belongs on SATA or
  NVMe. The report will say what each hypervisor did.
