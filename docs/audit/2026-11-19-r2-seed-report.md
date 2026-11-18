# R2, third PR: the NoCloud seed (2026-11-19)

Roadmap 1.3 R2 ("First boot without a console"), the third of four PRs.
The design is `docs/userland/design.md`, "The seed"; the owner chose, on
2026-11-18, a seed read from ISO 9660 or FAT.

## Scope and baseline

The SSH key, the host name and the network come from a cloud-init NoCloud
seed (`cidata`) attached as a disk. Before this PR nothing read one. The
base is the second PR's head (`a986037d`), the address a seed's
`network-config` sets going through its `IPV4_SET`.

## What changed

- `userland/system/seed.cee` (CeeSafe): the readers and the YAML subset.
  ISO 9660 (the primary volume labelled `cidata`; Joliet names, else Rock
  Ridge `NM`, else ISO names) and FAT12/16/32 (the label `cidata`; VFAT
  long names, else 8.3), by sectors through a caller's reader, every
  offset, length, count and cluster checked against the device and the
  buffers. The YAML subset of the design's table; anything else is a parse
  error with its line. Exported to C (`seed_probe`, `seed_file`,
  `yaml_*`) for the program and the host test.
- `userland/system/cosmo-seed.cee` (CeeSafe): every block device neither
  mounted nor the boot device is probed through `/dev/blkctl`; none, and
  it says nothing; two, and it uses none. `meta-data`'s `instance-id`
  gates the host name and the keys, applied once per instance
  (`/var/lib/cloud/instance-id`); the network (`IPV4_SET`, the name
  servers into `/etc/resolv.conf`) at every boot with a seed.
- `userland/etc/rc` runs `cosmo-seed` after `mount -a` and before `svc
  boot` and `hostname -F`; `netcfg.c` does not apply a DHCP server's host
  name while `/var/lib/cloud/hostname` exists.
- `tools/mkseed.py`: a seed as ISO 9660 (Joliet, Rock Ridge or plain
  names) or FAT12/16 (long names), with no host tools; deterministic.
- `tests/host/test_seed.c` and `test_seed.py` (`make host-test`): the
  generated C of `seed.cee` built for the host, over every layout
  `mkseed.py` writes (each file read back byte for byte, a missing one
  `ENOENT`), what is not a seed, damaged volumes (an extent past the end,
  a FAT chain that loops or ends early, an oversized file), and the YAML
  subset (a network-config, an unknown key, parse errors).
- Documents: the design note's seed section, `docs/userland/testing.md`,
  `docs/build/ceesafe.md`.

### The CeeSafe rule's offset

The new programs are CeeSafe. `netcfg.c`'s check (+4 lines) is offset by
porting `userland/coreutils/sync.c` (9 lines) whole, as `sync.cee`. The
gate: no tree has more C to convert than the base.

## Proof

The seed code's first run on a booted system is the next PR's `make
test-cloud`, which this tree passes with that PR on top (x86-64 and
AArch64, release, on the developer's Mac): an ISO seed sets the host name,
the key and `10.0.2.50/24`, a FAT seed of the same instance applies
nothing again and sets the address again, and no seed says nothing.

## Validation

PENDING: the matrix on `9b198db6`, both architectures.

## Limits

- The kernel has no CD-ROM driver: a seed a hypervisor presents as a CD is
  not seen; it must be a disk (virtio, AHCI, NVMe or USB).
- The YAML subset of the design's table; a file outside it is skipped
  with its line, and the boot goes on.
- One IPv4 address per interface; IPv6 entries are skipped.
- Lines that come with a system error go to standard error through
  `perror` (CeeSafe does not import libc's errno).
