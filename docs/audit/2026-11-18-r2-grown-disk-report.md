# R2, first PR: a disk that grew keeps its partitions and its root grows, 2026-11-18

Roadmap 1.3 R2 ("First boot without a console"), started by the owner
2026-11-18 while R1 waits for its hypervisor report. R2's acceptance is
`make test-cloud` on both architectures: the image copied to a disk four
times its size and booted with a seed; the harness logs in over SSH with
the seed's key and sees the host name and a root file system of the disk's
size; without a seed the boot is as today. The owner chose the shape that
day: a prebuilt installed image that grows, and a seed read from ISO 9660
or FAT. The design note is `docs/userland/design.md`, "First boot without a
console" (this PR's first commit). This PR is the partition table half of
"grows": the partition table and the root's pool. The static address,
the seed and the cloud image with `test-cloud` follow in their own PRs.
The pool's growth was planned as a second PR and joined this one when the
CeeSafe rule's gate made each PR offset its own C (below).

## Scope and baseline

Branch `r2-first-boot` from main at `a22afe4e` (#530's merge). In scope:
the kernel's GPT parser and partition scan, a new user program, init's
root mount, `test-install`. A new feature: proven by its test, not a probe.

Before this PR an image copied to a larger disk lost every partition: the
primary header's alternate LBA still names the old last sector, and
`gpt.cee` refused any table whose backup is not on the disk's last sector
(`backup header is not on the last sector`), so `part.cee` registered
nothing and `root=boot-disk` found no root.

## What changed

- **`kernel/block/gpt.cee`** (CeeSafe): the backup header is read where the
  primary's alternate LBA says, which may be before the last sector but
  must be past the usable range; every check a backup on the last sector
  passes still applies to it. Refused with new reasons: a backup past the
  last sector (a disk that shrank: `backup header is past the last
  sector`) or inside the usable range (`backup header is inside the usable
  range`). `struct gpt_table` (gpt.h) gains `backup_lba`, last, so the
  callers that declare part of it are unchanged.
- **`kernel/block/part.cee`** (CeeSafe): a table that registered and is
  short of the disk logs `part: DISK: the disk grew after its partition
  table was written (backup header at sector N of M)`.
- **`userland/system/cosmo-grow.cee`**, new, `--table DEVICE`, a whole
  user program in CeeSafe: reads the table of DEVICE's disk with the same
  parser; nothing to do and nothing said when it fits. Otherwise it
  rebuilds the table with `gpt_build` for its old size and compares head
  and tail with the disk byte for byte, refusing (exit 3) a table
  `gpt_build` did not write, so nothing a rebuild drops is lost; builds it
  for the disk's real size with DEVICE, when it is the CosmoOS root and the
  last partition, ending at the new last usable sector; parses that from
  memory; writes the backup, flushes, writes the primary, flushes, clears
  the old backup header and `RESCAN`s, through its own `/dev/blkctl`
  channel.
- **User programs in CeeSafe** (`docs/build/ceesafe.md`, "User programs"):
  the first version of `cosmo-grow` was C, and #531's first CI run failed
  the CeeSafe rule's gate (`cee-share`: `userland/` +280, `kernel/` +4
  lines of C to convert). The build now takes `userland/**/*.cee`
  (`build/cee.mk`), compiles CeeSafe's runtime for user mode apart from the
  kernel's object, links the programs' panic hook
  (`userland/lib/ceesafe_panic.c`, named in FLOOR as the kernel's
  `ceesafe_panic.c` is), and names an exported `cosmo_program_main` `main`
  at the link, freestanding CeeSafe having none. `install_gpt.c` is the GPT
  code alone; `cosmo-install` and `blkid` link the shared runtime.
- **The C that stays, offset by ports** (the owner's choice, 2026-11-18):
  init's calls (+29 lines) against `hostname` ported whole
  (`userland/system/hostname.cee`, -32); `gpt.h`'s field and comment and
  the two mount flags (+6) against `kernel/core/fwcfg.cee` (-22, the name
  built as `ksnprintf` built it, truncated at 63 characters); `struct
  cfs`'s one field against the dead `cfs_bit_clear`. `cee-share.py --gate`: no tree has more
  C to convert than `a22afe4e`.
- **The pool grows** (`docs/kernel-services/filesystem/cosmofs/design.md`,
  "Growing a member"). init mounts the root with the new
  `COSMO_MOUNT_GROW` (`MOUNT_GROW`, a writable cosmofs mount's alone;
  `sys_mount` refuses it elsewhere with `-EINVAL`). `cfs_members_load`
  reads it from the mount's flags and, for a pool of one plain member
  (no copies, no copy-state record, no spares) on a device larger than the
  member table says, grows the member and the superblock's total to the
  device (at most `CFS_MAX_BLOCKS`) before `layout` sizes the linear space,
  keeping the old count in `struct cfs`'s one new field, `grown_from`. The
  bitmap load reads only the chunks the old size had, frees every grown
  block (the old last chunk's padding included), marks each chunk holding
  one dirty and leaves the grown blocks out of the free-count comparison;
  the mount commits before it returns. Line: `cosmofs: member 0 grows from
  N to M blocks`. No format change.
- **`statfs` counted padding** (a defect found on the way, fixed because
  it blocks R2's acceptance: "a root file system of the disk's size").
  cosmofs reported the pool's linear span, every member rounded up to
  whole bitmap chunks of 32512 blocks, so `df` showed a 48891-block root
  as 65024 blocks and the grown 245499-block root as 260096. It now sums
  the members' blocks. `tests/host/test_cfscore.c` checks it on every
  `statfs` round (its digest moves, the only change in what the rounds
  see); `tools/statfs-span-probe.py --old` runs this test against main's
  `cosmofs_core.cee` in a throwaway worktree and fails at the check, on
  both architectures:

  ```text
  PROBE: PASS mode=old arch=x86_64 base=a22afe4e76fc: `FAIL .../tests/host/test_cfscore.c:940: rc != 0 || st.blocks == real`
  PROBE: PASS mode=fixed arch=x86_64: test_cfscore passed
  PROBE: PASS mode=old arch=aarch64 base=a22afe4e76fc: `FAIL .../tests/host/test_cfscore.c:940: rc != 0 || st.blocks == real`
  PROBE: PASS mode=fixed arch=aarch64: test_cfscore passed
  ```
- `cfs_bit_clear`, a `static inline` in `cosmofs_internal.h` nothing
  called, is removed.
- **`userland/init/init.c`**: `switch_to_disk_root` runs `cosmo-grow
  --table ROOTDEV` before `unlock_root` and `check_root`.
- **`tests/boot/install_test.py`**: stages `grow` and `grow-again`
  (below); the default stage list includes them.
- `docs/backlog.md` BLK-10: what `cosmo-grow` leaves alone.
- Tests: `tests/host/test_gpt.c` (a grown disk accepted with
  `backup_lba`; a damaged backup there refused; a shrunk disk and a backup
  inside the usable range refused with their reasons); `test_part.c`'s
  `gpt_parse` stand-in fills `backup_lba`.
- Documents: `docs/userland/design.md` (the design note), `docs/kernel/
  device/design.md` (the parser's rules), `docs/userland/testing.md`
  (the stages), gpt.h's comment.

## Proof

`make BUILD=release test-install`, on the developer's Mac (QEMU 11.1.3),
both architectures, PASS. The new stages copy the installed 256 MiB disk
to a file four times as long and boot it alone:

| | x86-64 | AArch64 |
|---|---|---|
| disk | `ahci0p0`, 524288 -> 2097152 sectors | `vda`, 524288 -> 2097152 sectors |
| root partition | 391135 -> 1963999 sectors | 391135 -> 1963999 sectors |
| grow boot | 10.5 s | 24.6 s |
| grow-again | 19.4 s, nothing said | 23.3 s, nothing said |

The x86-64 grow boot's lines, in order:

```text
[ INFO] part: ahci0p0: the disk grew after its partition table was written (backup header at sector 524287 of 2097152)
cosmo-grow: ahci0p0: the partition table now covers 2097152 sectors (it covered 524288)
cosmo-grow: ahci0p0p2: 1963999 sectors, was 391135
init: switched to the disk root ahci0p0p2 (root=boot-disk)
```

On the host the grown file's two GPT copies are valid and equal at the new
end, the ESP's entry unchanged and the root's ending at the new last usable
sector, 2097118 (the 32 sectors of backup entries and the backup header
after it).

The cosmofs root on the grown partition still has its old size: its member
table says how many blocks it has, and a member smaller than its device
mounts (design.md, "The member table"). Growing it is the next PR.

## Validation

`make matrix` on `5c97ee3b` (the code; later commits are documents):
AArch64 on the developer's Mac, x86-64 on the other machine in the CI
image with the pinned ceesafec 0.57.1 (the matrix's tree copy had removed
it there, and the image has no `qemu-img`: the first two x86-64 runs failed
every step for those reasons, nothing of the change's; the third installed
`qemu-utils` in its container).

| step | x86-64 | AArch64 |
|---|---|---|
| builds (debug, release, chaos, hbreak), `cee-check` | PASS | PASS |
| `host-test`, `fuzz` | PASS | PASS |
| `analyze` | clean, 15 baselined | clean, 14 baselined |
| debug `test`, `QEMU_SMP=1` / `2` / `4` | 228.2 / 241.4 / 244.0 s | 178.7 / 173.6 s / see below |
| `test-smp2`, `test-chaos`, `test-harness-retry` | 240.7 / 244.4 / 245.3 s | 192.7 / 231.6 / 213.5 s |
| release `test` | 18.6 s | 24.3 s |

AArch64 `QEMU_SMP=4` failed in the matrix with `process-user` at 23090 ms
against its 15 s bound while another session's CeeSafe contract suite and
the Parallels VM loaded the Mac (load average 11.75 / 65.28 / 77.76); run
again alone with the one-minute load at 6.96: PASS in 209.3 s,
`process-user` 6770 ms (`docs/testing/flakes.md`, the entry of this date).
`make BUILD=release test-install`: PASS on both (above).

## Limits

- Only a pool of one plain member grows; a line says why another does not.

- Only a table `gpt_build` wrote is moved; another is reported and left.
- A root that is not the last partition keeps its size.
