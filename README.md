# CosmoOS

CosmoOS is a Unix-like operating system written from scratch for x86-64
and AArch64 servers. It boots through UEFI and installs to a disk. It
runs BusyBox, OpenSSH and unmodified Linux programs. Its root file system
is copy-on-write, with snapshots and boot environments, and the boot is
verified.

It is young. Development began in September 2026, 1.0 was released on
2026-10-12, and the current release is **v1.1.2** (2026-11-21). It is
tested on virtual machines only: QEMU on every change, and Parallels
Desktop on Apple Silicon before every release. Try it in a virtual
machine, not on a computer you depend on.

## At a glance

| | |
|---|---|
| Release | [v1.1.2](https://github.com/CeeSafe/CosmoOS/releases/latest), signed, rebuilt bit for bit from its tag |
| Architectures | x86-64 and AArch64 (ARM64), UEFI |
| Tested on | QEMU (`q35`, `virt`) and Parallels Desktop on Apple Silicon |
| Kernel | A hybrid kernel: a small trusted core and modular privileged services |
| Kernel language | C and [CeeSafe](https://ceesafe.github.io/CeeSafe/), a memory-safe language that compiles to C; 52% of ring 0 is CeeSafe |
| Shell and tools | BusyBox 1.37 `ash` and applets, the system's own tools |
| License | [GPL-2.0-only](COPYING) |

## Features

**Installing and booting**
- Images in raw, QCOW2 and VMDK form, an installer ISO, and a cloud
  image that is already installed.
- `cosmo-install` puts the system on a GPT disk: an EFI partition and a
  cosmofs root.
- Verified boot: the UEFI loader checks an Ed25519-signed manifest over
  the kernel, the boot archive and the command line before anything runs.
- First boot without a console: the cloud image grows to fill its disk
  and reads a cloud-init NoCloud seed (host name, SSH keys, static or
  DHCP network).

**Storage: cosmofs**
- Copy-on-write, with checksums, LZ4 compression and crash replay.
- Snapshots and rollback (`cosmo-snap`), and boot environments taken at
  every upgrade.
- Mirrors with resilvering and spares (`cosmo-pool`), `fsck.cosmofs`,
  and online `check` and `scrub` that repair from a good copy.
- An encrypted root (`cosmo-install --encrypt`): a passphrase at boot,
  several key slots.

**Upgrading**
- `cosmo-upgrade --fetch vX.Y.Z` fetches a signed release over HTTPS and
  installs it beside the running one. A reboot runs it, and `--rollback`
  returns to the previous boot environment.
- `pkg` installs signed packages from the project's repository. The
  repository has OpenSSH 10.6, curl 8.23.0, git 2.56.1 and nano 9.3.
- A C compiler on the system: `cc` is TinyCC with musl's headers and
  libraries, and builds static, dynamic and `dlopen` programs there.

**Security**
- Privileges, not an all-powerful uid 0: each process holds a set of
  operation-specific privileges and can drop them, and an ssh session
  holds fewer than the console.
- User-space ASLR, W^X, and `getrandom` that waits until the pool is
  seeded from the CPU, the firmware, virtio-rng or timing jitter.
- Signed, unloadable kernel modules.

**Networking**
- IPv4 and link-local IPv6, TCP and UDP, DHCP or a static address, DNS.
- A firewall, masquerade NAT and port forwarding, and tap interfaces for
  guests.
- `wget` and `curl` over HTTPS. ssh by key, with dropbear, or OpenSSH's
  `sshd` as a package.

**Linux programs**
- A Linux personality runs unmodified static, PIE and dynamically linked
  musl programs for x86-64 and AArch64. It covers threads, signals,
  `poll` and `epoll`, `eventfd`, `timerfd`, `signalfd`, `memfd`, System V
  shared memory and Unix sockets.

**Kernel and devices**
- SMP scheduling with per-CPU run queues and priority inheritance, demand
  paging, copy-on-write `fork`, kernel objects with per-handle rights,
  and lockdep in debug builds.
- PCI with MSI-X, VirtIO (block, network, console, RNG, GPU), NVMe,
  AHCI, Intel e1000e, USB (xHCI, mass storage, hubs, keyboards), and DMA
  remapping (Intel VT-d, ARM SMMUv3).
- `/dev/vmm`, a hypervisor interface: an AArch64 EL2 backend that boots
  Linux guests, and an AMD SVM backend.

**Testing**
- About 530 in-kernel self-tests on both architectures, and host unit
  tests under AddressSanitizer and UBSan.
- Fuzzers, fault injection, and file-system crash replay.
- CI boots both architectures on every change and runs the user guide's
  commands against the release images.

## Not there yet

What a user will meet, in brief. [Known
limitations](docs/guide/limitations.md) has the details, and
[`docs/backlog.md`](docs/backlog.md) the open defects.

- **Physical hardware.** No physical machine is tested. VMware,
  VirtualBox, UTM and clouds have not been tried; the QCOW2, VMDK and ISO
  images exist for them.
- **Desktop and devices.** No graphical desktop: a text console on the
  framebuffer only. No Wi-Fi, Bluetooth, sound or GPU acceleration, and
  no CD-ROM driver.
- **Scale.** No NUMA, no huge pages, no swap, and at most 64 CPUs. No
  CPU or memory hotplug, though PCIe disks can be added and removed.
- **Security.** No KASLR. No UEFI Secure Boot signature. The root file
  system is not verified, there is no TPM measurement, and only one user,
  root, separated by privileges.
- **Networking.** IPv6 is link-local only. No IP fragmentation, no TCP
  window scaling or SACK, and no NTP daemon (the clock is stepped with
  `ntpd -q`).
- **Storage.** No RAID-Z. A mirror holds at most four copies, and a
  rollback takes effect at the next boot.
- **Linux compatibility.** A subset of Linux's system calls: a program
  that needs a missing one gets `ENOSYS`. No containers, no glibc
  programs tried, no inotify.
- **Virtualization.** The Intel VMX backend has never run on hardware.
- **Self-hosting.** CosmoOS is built on Linux or macOS, not on itself.

The work under way is the [1.3 roadmap](docs/roadmap-1.3.md): a release
people can install on the hypervisors and clouds they have, with the
kernel's conversion to CeeSafe finished to a named floor.

## Compared with Linux and FreeBSD

CosmoOS is not a replacement for either. They have decades of work,
hardware support for almost everything and very large software
collections. The table shows where CosmoOS made different choices.

| | CosmoOS | Linux | FreeBSD |
|---|---|---|---|
| Kernel | Hybrid: a trusted core and modular privileged services | Monolithic, with loadable modules | Monolithic, with loadable modules |
| Language | C, with ring 0 moving to CeeSafe (52%) | C, with Rust for some drivers | C |
| Hardware | Virtual machines only, x86-64 and AArch64 | Almost everything, many architectures | Most servers and desktops, several architectures |
| Root's power | No all-powerful root: operation-specific privileges per process | root, refined by capabilities and LSMs (SELinux, AppArmor) | root, refined by Capsicum, jails and the MAC framework |
| Boot integrity | The loader verifies a signed manifest over kernel, boot archive and command line | UEFI Secure Boot through shim; dm-verity and IMA available | UEFI boot; veriexec for signed files |
| File system | cosmofs: copy-on-write, snapshots, mirrors, compression, encryption | ext4 and XFS; Btrfs for copy-on-write | UFS; ZFS for copy-on-write |
| Rollback | Boot environments at every upgrade, built in | Distribution-specific (for example snapper with Btrfs) | Boot environments with ZFS (`bectl`) |
| Linux programs | Native ABI plus a Linux personality (a subset) | Native | The Linux compatibility layer (a subset) |
| Virtualization | `/dev/vmm`: AArch64 EL2 and AMD SVM backends | KVM | bhyve |
| Isolation | Privileges and mount namespaces | Namespaces and cgroups (containers) | Jails |
| Packages | `pkg`: signed, a handful of server packages | apt, dnf and others: tens of thousands | `pkg` and ports: over 30,000 |
| Maturity | Started 2026, a single maintainer | Since 1991 | Since 1993, from BSD |

Its nearest relative in design is FreeBSD with ZFS. Both put
copy-on-write snapshots and boot environments at the centre of
upgrades. CosmoOS differs in its privilege model, which has no
all-powerful root, and in its memory-safe kernel language.

## Installing

Pick the way that matches your machine. Every release on the
[releases page](https://github.com/CeeSafe/CosmoOS/releases/latest)
carries the images for both architectures, the boot files, `SHA256SUMS`
and its signature.

### 1. Download and check

Get the image for your architecture and the checksums. For x86-64:

```sh
curl -LO https://github.com/CeeSafe/CosmoOS/releases/latest/download/cosmoos-x86_64.img
curl -LO https://github.com/CeeSafe/CosmoOS/releases/latest/download/SHA256SUMS
sha256sum --ignore-missing -c SHA256SUMS      # on macOS: shasum -a 256 --ignore-missing -c SHA256SUMS
```

For AArch64, use `cosmoos-aarch64.img`. The other images are named the
same way:

| File | Use it for |
|---|---|
| `cosmoos-ARCH.img` | QEMU: the live system, from which you install |
| `cosmoos-ARCH.qcow2`, `cosmoos-ARCH.vmdk` | The same live system, for hypervisors that take these formats |
| `cosmoos-ARCH.iso` | An installer CD for a UEFI virtual machine |
| `cosmoos-ARCH-cloud.qcow2` | An installed system for a cloud or a KVM host: no install step |

### 2. Install in QEMU (Linux or macOS)

This is the tested path, and the [user guide](docs/guide/installing.md)
gives every command and the output to expect. In short:

1. Install QEMU 9.2 or newer with its UEFI firmware:
   - Debian or Ubuntu: `apt-get install qemu-system-x86 ovmf qemu-system-arm qemu-efi-aarch64`;
   - macOS: `brew install qemu`.
2. Boot a copy of the live image with an empty disk and a virtio-rng
   device attached.
3. At the `cosmo$ ` prompt:
   - run `cosmo-install --list` to find the empty disk;
   - run `cosmo-install DISK` to install on it;
   - type `exit`.
4. Boot the installed disk alone. The first boot asks you to choose
   root's password on the console.

### 3. Parallels Desktop on Apple Silicon

Use the AArch64 image as the VM's first NVMe disk, with a second NVMe disk
to install on, and boot from it. [Tested
platforms](docs/guide/platforms.md) has the VM's settings and what each
release did there.

### 4. Other hypervisors (untested)

Boot `cosmoos-ARCH.iso` in a UEFI virtual machine with an empty disk
attached. Then run `cosmo-install` on that disk, as from the live image.
Use VirtIO, NVMe or AHCI disks and a VirtIO or e1000e network adapter.
These platforms have not been tried yet; a report of what happens is
welcome.

### 5. A cloud or a KVM host

`cosmoos-ARCH-cloud.qcow2` is already installed. At its first boot it
grows to fill its disk. Give it your SSH key with a NoCloud seed: a
small disk labelled `cidata` holding `meta-data` and `user-data` (and
optionally `network-config`). `tools/mkseed.py` in the source tree
writes one:

```sh
printf 'instance-id: my-vm-1\nlocal-hostname: cosmo\n' > meta-data
printf '#cloud-config\nssh_authorized_keys:\n  - %s\n' "$(cat ~/.ssh/id_ed25519.pub)" > user-data
python3 tools/mkseed.py --format iso seed.iso meta-data user-data
```

Attach `seed.iso` as a disk, not a CD-ROM (there is no CD-ROM driver),
then log in with `ssh root@ADDRESS`. Without a seed the machine takes an
address by DHCP and can be reached only from its console.

### After installing

- **Log in over ssh** as root with a key: [ssh](docs/guide/ssh.md).
- **Add software:** `pkg update && pkg install openssh-server curl git
  nano` ([Packages](docs/guide/packages.md)).
- **Upgrade:** `cosmo-upgrade --check`, then `cosmo-upgrade --fetch
  vX.Y.Z` and a reboot ([Upgrading](docs/guide/upgrading.md)).
- **Snapshot before you change things:** `cosmo-snap`
  ([Snapshots and rollback](docs/guide/snapshots.md)).

## Building from source

On a Debian or Ubuntu host, x86-64 or ARM64:

```sh
scripts/setup-dev-linux.sh   # clang, lld, llvm, make, mtools, QEMU and UEFI firmware for both architectures
make check-tools             # check the cross toolchain
make                         # build everything (x86-64, debug)
make test                    # boot under QEMU; PASS or FAIL from the serial console and exit code
make run                     # an interactive boot on the terminal
```

`ARCH=aarch64` builds for AArch64 and `BUILD=release` a release build.
On macOS, run `scripts/setup-dev-macos.sh` and use GNU make (`gmake`).
The kernel's CeeSafe sources need the pinned `ceesafec`.
[docs/development.md](docs/development.md) covers the hosts, the
toolchain, CeeSafe, testing and CI, and `make help` lists every target.

## Documentation

| Where | What |
|---|---|
| [`docs/guide/`](docs/guide/README.md) | The user guide: installing, the shell, networking, ssh, packages, upgrading, snapshots, mirrors, encryption, privileges, limitations |
| [`docs/releases/`](docs/releases/) | Release notes |
| [`docs/development.md`](docs/development.md) | Building, running, testing and releasing |
| [`docs/README.md`](docs/README.md) | The subsystems' design documents |
| [`docs/roadmap-1.3.md`](docs/roadmap-1.3.md) | The current roadmap; the [1.0](docs/roadmap-1.0.md) and [1.1](docs/roadmap-1.1.md) roadmaps are complete |
| [`docs/backlog.md`](docs/backlog.md) | Open defects and gaps, by subsystem |
| [`docs/history/`](docs/history/README.md) | What was built, unit by unit |

## Repository layout

| Path | Owns |
|---|---|
| `boot/` | The UEFI loader and boot protocol |
| `kernel/` | The trusted kernel core; `kernel/arch/` holds what is architecture-specific |
| `kernel-services/` | VFS, networking, storage, file systems, virtualization |
| `drivers/` | PCI, VirtIO, NVMe, network, storage, USB and IOMMU drivers |
| `modules/` | Loadable kernel modules packed into the boot archive |
| `compat/linux/` | The Linux personality |
| `libc/`, `userland/` | The native C library; init, the system tools |
| `pkg/`, `ports/` | The package manager and the recipes for third-party software |
| `tools/`, `scripts/` | Host-side tools and automation |
| `tests/` | Host, boot, integration and fuzz tests |
| `docs/` | Documentation, audits, history |
| `prompts/` | The governing prompts: the project's vision, invariants and rules |

## Contributing

The [governing prompts](prompts/) set the architecture, fifteen
invariants, the coding rules and the workflow. [`AGENTS.md`](AGENTS.md)
summarises the rules a change follows: one unit of the current roadmap
at a time, each defect proven by a test that fails without its fix, and
the full validation matrix before a pull request.

## License

Copyright (C) 2026 Veeran Puthumkara.

CosmoOS is free software, licensed under the [GNU General Public
License, version 2 only](COPYING) (`GPL-2.0-only`).

Third-party software that CosmoOS builds from `ports/` keeps its own
license; each recipe fetches the upstream source. When an image includes
mbedTLS (`Apache-2.0 OR GPL-2.0-or-later`), it is used under its GPL
option, since Apache-2.0 alone is not compatible with GPLv2.
