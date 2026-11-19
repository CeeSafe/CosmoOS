# R2, second PR: a static IPv4 address from user space (2026-11-19)

Roadmap 1.3 R2 ("First boot without a console"), the second of four PRs.
The design note is `docs/userland/design.md`, "First boot without a
console"; this PR adds what its section "The network, every boot" needs
from the kernel.

## Scope and baseline

A seed's `network-config` may give an interface a static address. Before
this PR the kernel set an address only from DHCP or from fw_cfg at boot
(`opt/cosmo/ipv4`, a test seam); user space could not set one. The base
is the first PR's head (`528b53ad`, #531), merged into main as
`f408cdb9`.

## What changed

- `kernel/include/uapi/cosmo/netctl.h`: `COSMO_NETCTL_IPV4_SET` (6) and
  `struct cosmo_netctl_ipv4` (version, op, the interface's name, address,
  gateway, prefix, three reserved bytes). The snapshot version stays 8:
  no record changed, and an older kernel refuses op 6 with `-EINVAL`.
- `kernel-services/network/tap.cee`, `ctlIpv4`: exactly one record; the
  reserved bytes zero, a nonzero address, a prefix of 1 to 32, a name
  terminated within its field. The interface is found by name
  (`netif_find`, `-ENOENT`); loopback and a guest's tap (`NODEFAULT`) are
  refused. Its DHCP client stops first (`dhcp_client_stop`, which waits
  for the client's work), so no lease replaces the address, then
  `netif_set_ipv4` sets address, mask and gateway (the default route's,
  as fw_cfg's path sets it).
- `tests/host/test_tap.c`, `test_ipv4_set`: a good record stops the
  client and sets the address, the mask of its prefix (`/24`, `/32`, `/1`)
  and the gateway; loopback, an unknown interface (`-ENOENT`), prefixes 0
  and 33, a zero address, a nonzero reserved byte, an unterminated name
  and a record one byte short are each refused and change nothing (no
  address, no client stopped), and every interface found is put back
  (refcounts). The `NODEFAULT` refusal is the loopback one's branch; no
  case of its own.
- `docs/kernel-services/network/design.md`, "A static address from user
  space".

### The CeeSafe rule's offset

`netctl.h`'s new struct and op are C in `kernel/`. `pipe_floor.c` (54
lines), which held a pipe end's two `kobject_io_type` tables and the
constant checks, is folded into `kernel/ipc/pipe.cee`: the tables are
read-only statics of the imported C type (ADR 0091) whose members are the
pipe-end functions, now `@callback`, and the constants are `@cvalue`
checked. `kernel/kernel.mk` loses its line. `socket.cee`'s comment no
longer names `pipe_floor.c`. The gate: no tree has more C to convert than
the base.

## Validation

`make matrix` on `a986037d`, both architectures on the other machine, in
the CI image with the pinned ceesafec 0.57.1 and a fresh `out/`:

| step | x86-64 | AArch64 |
|---|---|---|
| builds (debug, release, chaos, hbreak), `cee-check` | PASS | PASS |
| `host-test`, `fuzz` | PASS | PASS |
| `analyze` | clean, 15 baselined | clean, 15 baselined |
| debug `test`, `QEMU_SMP=1` / `2` / `4` | 230.0 / 239.0 / 244.9 s | 277.3 / 286.5 / 299.4 s |
| `test-smp2`, `test-chaos`, `test-harness-retry` | 238.1 / 239.1 / 244.0 s | 290.7 / 303.8 / 303.7 s |
| release `test` | 19.0 s | 23.0 s |

Branch CI: see the pull request.

## Limits

- One IPv4 address per interface, as the kernel keeps; IPv6 is not set.
- An address set by `IPV4_SET` lasts until the boot ends: the kernel keeps
  none across a boot, so `cosmo-seed` sets it at every boot (the next PR).
