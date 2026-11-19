# R2, fourth PR: the cloud image and `make test-cloud` (2026-11-19)

Roadmap 1.3 R2 ("First boot without a console"), the last of four PRs.
It adds R2's acceptance test and the image it boots, and ticks R2.

## Scope and baseline

The first three PRs made a grown disk keep its partitions and grow its
root (#531), let user space set a static address, and read a NoCloud
seed. What was missing: an image to give a cloud, and the test the roadmap
names. The base is the third PR's head.

## What changed

- `scripts/mkcloudimage.py` (`make cloud-image`,
  `$(OUT)/cosmoos-ARCH-cloud.qcow2`): the live image boots in QEMU with a
  blank 256 MiB disk, `cosmo-install` installs on it, the root is mounted
  to check it has at least half as much again free as it holds, and the
  disk is converted to QCOW2. On this tree the root holds 20144 KiB (x86-64)
  and 20228 KiB (AArch64), with about 169 MiB free.
- `tests/boot/cloud_test.py` (`make test-cloud`): stages `seed`, `again`
  and `noseed` (`docs/userland/testing.md`, "test-cloud").
- CI: `make test-cloud` is a step of the `net-login` job (both
  architectures, release; the job's limit 30 -> 40 minutes, the test
  taking under a minute of boots plus the image's install).
- Release: the image is not byte-reproducible (cosmo-install draws its
  GUIDs), so it stays out of `make release`'s set, which two builds must
  make the same. A `cloud` job per architecture makes it from the
  published live image and runs `cloud_test.py` on it; `publish` waits
  for it and adds both images to `SHA256SUMS` before signing it.
  `scripts/release-notes.py` names the file.
- Documents: the design note's "The cloud image" (the name, the size, the
  release job), `docs/userland/testing.md`, `docs/development.md` (the
  release workflow's jobs), the history entry, and R2 ticked in
  `docs/roadmap-1.3.md`.

The PR changes no compiled code: a harness no matrix step runs, a
host-side script, make targets, workflows and documents. By AGENTS.md it
is exempt from the matrix; its proof is the acceptance test on both
architectures and branch CI.

## Proof

`make BUILD=release test-cloud` on the developer's Mac (QEMU, TCG), on
this tree:

| stage | x86-64 | AArch64 |
|---|---|---|
| seed | PASS, 12.6 s | PASS, 17.3 s |
| again | PASS, 11.0 s | PASS, 12.9 s |
| noseed | PASS, 12.2 s | PASS, 14.4 s |
| all | 36.3 s | 45.0 s |

On both: 524288 -> 2097152 sectors, the pool to 245499 blocks, `df -k /`
981996 KiB, which is the root partition's whole 4 KiB blocks; the ISO
seed's host name and `eth0 10.0.2.50/24`; ssh with the seed's key 0.2 s
after the console's prompt; the FAT seed's `instance ... already applied`
with the same host key, host name and one key; no seed, no `cosmo-seed`
line and eth0 by DHCP.

The first x86-64 run's seed stage (which passed), its lines from
`cosmo-grow`, cosmofs, `cosmo-seed` and svc, in order:

```text
cosmo-grow: ahci0p0: the partition table now covers 2097152 sectors (it covered 524288)
cosmo-grow: ahci0p0p2: 1963999 sectors, was 391135
[ INFO] cosmofs: member 0 grows from 48891 to 245499 blocks
cosmo-seed: seed on vda (ISO 9660)
cosmo-seed: host name cloudy-a02fd614
cosmo-seed: 1 SSH key(s) added to /root/.ssh/authorized_keys
cosmo-seed: instance iid-cloud-test-a02fd614 applied
cosmo-seed: eth0 10.0.2.50/24 via 10.0.2.2
cosmo-seed: /etc/resolv.conf: 1 name server(s)
svc: dropbear started
```

With the second PR's review fixes under it (`IPV4_SET` flushes the
neighbours; a second `dhcp_client_stop` waits; `b1370163`), it passed
again: x86-64 11.9 / 12.7 / 12.0 s (37.0 s), AArch64 16.2 / 16.2 /
16.5 s (49.2 s), with the same facts.

The first run's `again` stage failed in the harness, not the system: the
host key is recorded in `known_hosts` under the forwarded port, and the
second boot forwarded a new one. It now reuses the first boot's port.

## Validation

PENDING: branch CI (`net-login`, both architectures).

## Limits

- The release workflow's `cloud` job runs only on a tag; it has not run
  yet. Its steps are the ones `make cloud-image` and `make test-cloud`
  run, called directly on the published image.
- Every machine made from one image shares its disk and partition GUIDs
  and its pool's uuid.
- A crash during `cosmo-grow`'s primary write at the first boot can leave
  a table the kernel refuses (backlog BLK-11).
