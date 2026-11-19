#!/usr/bin/env python3
"""Roadmap 1.3 R2's acceptance test: first boot without a console
(docs/userland/design.md, "First boot without a console";
docs/userland/testing.md, "test-cloud").

    cloud_test.py --cloud cosmoos-ARCH-cloud.qcow2 --workdir DIR

The cloud image (scripts/mkcloudimage.py) is converted to a raw disk four
times its size and booted alone, with a NoCloud seed this harness writes
(tools/mkseed.py) attached as a second virtio disk:

  seed    ISO 9660 with Joliet. meta-data names an instance id and a
          local-hostname; user-data (#cloud-config) a hostname, which wins,
          and a key made for the run; network-config gives eth0, matched by
          its MAC, 10.0.2.50/24 via 10.0.2.2 and name server 10.0.2.3.
          QEMU forwards a host port to 10.0.2.50:22, the seed's address,
          not the DHCP one (10.0.2.15). The kernel says the disk grew,
          cosmo-grow moves the table, the pool grows; cosmo-seed names the
          seed, the host name, one key added, eth0's address and the
          instance applied. The host's OpenSSH logs in with the seed's key:
          `hostname` is the seed's, `df -k /` is the root partition's whole
          4 KiB blocks, and the partition ends at the disk's last usable
          sector (read on the host after power-off).
  again   The same disk, the same seed written as FAT12: nothing grows,
          `instance ... already applied`, the address is set again (the
          kernel keeps none), and ssh logs in; the key is in
          authorized_keys once and the host name is kept.
  noseed  Another copy of the image, four times its size, no seed:
          cosmo-seed says nothing, eth0 is DHCP's 10.0.2.15, the root grew,
          and the console reaches a shell as an installed system's does.

Exit 0 PASS, 1 FAIL.
"""

import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import install_test  # noqa: E402
import net_login_test  # noqa: E402
from install_test import Boot, Fail, need, no_free_warning, parse_gpt, SS, EXIT_SUCCESS  # noqa: E402
from net_login_test import MAC, free_port, ssh_run, ssh_wait  # noqa: E402

ADDR = "10.0.2.50"
GPT_TAIL = 16384 // SS + 1   # the backup entries and header after the last usable sector


def make_disk(cloud, path):
    """The cloud image as a raw disk four times its size: (old sectors, new sectors)."""
    subprocess.run(["qemu-img", "convert", "-q", "-f", "qcow2", "-O", "raw", cloud, path], check=True)
    old_n = os.path.getsize(path) // SS
    with open(path, "r+b") as f:
        f.truncate(4 * old_n * SS)
    return old_n, 4 * old_n


def make_seed(work, fmt, iid, host, pub):
    d = os.path.join(work, "seed-files")
    os.makedirs(d, exist_ok=True)
    files = {
        "meta-data": f"instance-id: {iid}\nlocal-hostname: not-this-one\n",
        "user-data": f"#cloud-config\nhostname: {host}\nssh_authorized_keys:\n  - {pub}\n",
        "network-config": ("version: 2\n"
                           "ethernets:\n"
                           "  primary:\n"
                           "    match:\n"
                           f"      macaddress: \"{MAC}\"\n"
                           f"    addresses: [{ADDR}/24]\n"
                           "    gateway4: 10.0.2.2\n"
                           "    nameservers:\n"
                           "      addresses: [10.0.2.3]\n"),
    }
    paths = []
    for name, text in files.items():
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write(text)
        paths.append(p)
    out = os.path.join(work, f"seed-{fmt}.img")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mkseed.py"), "--format", fmt, out] + paths,
                   check=True)
    return out


def seed_env(seed, port):
    env = {"QEMU_DISKS": "boot", "QEMU_NET_HOSTFWD": f"tcp:127.0.0.1:{port}-{ADDR}:22"}
    if seed:
        env["QEMU_EXTRA"] = (os.environ.get("QEMU_EXTRA", "") +
                             f" -drive if=none,id=seed,format=raw,file={seed} -device virtio-blk-pci,drive=seed").strip()
    return env


def grown_root(disk_path, n):
    """After power-off: the root partition's last sector is the disk's last usable one. Its size in 4 KiB blocks."""
    _, parts = parse_gpt(open(disk_path, "rb").read())
    if len(parts) != 2 or parts[1][4] != n - GPT_TAIL - 1:
        raise Fail(f"{os.path.basename(disk_path)}: partitions {parts}, expected the root to end at {n - GPT_TAIL - 1}")
    return (parts[1][4] - parts[1][3] + 1) * SS // 4096


def check_grew(log, old_n, n, what):
    need(log, rf"^\[ INFO\] part: \S+: the disk grew after its partition table was written \(backup header "
              rf"at sector {old_n - 1} of {n}\)$", f"{what}: the kernel's line for a disk that grew")
    need(log, rf"^cosmo-grow: \S+: the partition table now covers {n} sectors \(it covered {old_n}\)$",
         f"{what}: cosmo-grow moving the table")
    return int(need(log, r"^\[ INFO\] cosmofs: member 0 grows from \d+ to (\d+) blocks$",
                    f"{what}: the root's pool growing").group(1))


def ssh_facts(work, port):
    rc, out = ssh_run(work, port, True, "hostname; df -k / | tail -n 1; grep -c . /root/.ssh/authorized_keys; "
                                        "ip -4 addr show eth0; echo facts-ok")
    if rc != 0 or "facts-ok" not in out:
        raise Fail(f"ssh: the facts: status {rc}, output {out!r}")
    return out


def stage_seed(args, results, cloud, key_pub, iid, host):
    work = args.workdir
    disk = os.path.join(work, "cloud.img")
    old_n, n = make_disk(cloud, disk)
    seed = make_seed(work, "iso", iid, host, key_pub)
    port = free_port()
    b = Boot("seed", disk, work, seed_env(seed, port), args.timeout)
    try:
        b.wait_prompt("the first prompt")
        log = b.text()
        need(log, r"^init: switched to the disk root \S+ \(root=boot-disk\)$", "the cloud image's boot")
        blocks = check_grew(log, old_n, n, "the seeded boot")
        no_free_warning(log, "the grown root's mount")
        need(log, r"^cosmo-seed: seed on \S+ \(ISO 9660\)$", "cosmo-seed finding the seed")
        need(log, rf"^cosmo-seed: host name {host}$", "cosmo-seed setting the host name")
        need(log, r"^cosmo-seed: 1 SSH key\(s\) added to /root/\.ssh/authorized_keys$", "cosmo-seed adding the key")
        need(log, rf"^cosmo-seed: eth0 {re.escape(ADDR)}/24 via 10\.0\.2\.2", "cosmo-seed setting eth0's address")
        need(log, rf"^cosmo-seed: instance {iid} applied$", "cosmo-seed recording the instance")
        need(log, r"^svc: dropbear started$", "the ssh server")
        waited = ssh_wait(work, port, strict=False)
        out = ssh_facts(work, port)
        need(out, rf"^{host}$", "hostname over ssh")
        df_kib = int(need(out, r"^\S+\s+(\d+)\s+\d+\s+\d+\s+\d+%\s+/$", "df -k / over ssh").group(1))
        need(out, r"^1$", "the key once in authorized_keys")
        need(out, rf"^\s+inet {re.escape(ADDR)}/24 ", "eth0's static address (ip addr)")
        rc = b.finish()
        if rc != EXIT_SUCCESS:
            raise Fail(f"seeded boot: QEMU exit code {rc}")
    except Exception:
        b.kill()
        raise
    root_blocks = grown_root(disk, n)
    if blocks != root_blocks or df_kib != 4 * root_blocks:
        raise Fail(f"the pool grew to {blocks} blocks and df says {df_kib} KiB; the root partition holds "
                   f"{root_blocks} blocks ({4 * root_blocks} KiB)")
    results.append(f"seed: PASS in {b.elapsed():.1f}s ({old_n} -> {n} sectors, the pool to {blocks} blocks, df "
                   f"{df_kib} KiB = the root partition; ISO seed: host name {host}, eth0 {ADDR}/24; ssh with the "
                   f"seed's key {waited:.1f}s after the prompt)")
    return disk, port, df_kib


def stage_again(args, results, disk, port, key_pub, iid, host, df_kib):
    """`port` is the first boot's: known_hosts names the host key by it."""
    work = args.workdir
    seed = make_seed(work, "fat", iid, host, key_pub)
    b = Boot("again", disk, work, seed_env(seed, port), args.timeout)
    try:
        b.wait_prompt("the first prompt")
        log = b.text()
        if re.search(r"the disk grew after|^cosmo-grow:|cosmofs: member 0 grows", log, re.M):
            raise Fail("the second boot grew the disk again")
        need(log, r"^cosmo-seed: seed on \S+ \(FAT\)$", "cosmo-seed finding the FAT seed")
        need(log, rf"^cosmo-seed: instance {iid} already applied$", "the instance already applied")
        if re.search(r"^cosmo-seed: (host name |\d+ SSH key)", log, re.M):
            raise Fail("the second boot of the same instance applied the host name or keys again")
        need(log, rf"^cosmo-seed: eth0 {re.escape(ADDR)}/24 via 10\.0\.2\.2", "eth0's address set again")
        ssh_wait(work, port, strict=True)   # the host key was kept
        out = ssh_facts(work, port)
        need(out, rf"^{host}$", "the host name kept")
        need(out, rf"^\S+\s+{df_kib}\s", "df -k / unchanged")
        need(out, r"^1$", "the key still once in authorized_keys")
        rc = b.finish()
        if rc != EXIT_SUCCESS:
            raise Fail(f"second boot: QEMU exit code {rc}")
    except Exception:
        b.kill()
        raise
    results.append(f"again: PASS in {b.elapsed():.1f}s (FAT seed, instance already applied, nothing grown; eth0 "
                   f"{ADDR}/24 again; the same host key, host name and one key)")


def stage_noseed(args, results, cloud):
    work = args.workdir
    disk = os.path.join(work, "noseed.img")
    old_n, n = make_disk(cloud, disk)
    b = Boot("noseed", disk, work, {"QEMU_DISKS": "boot"}, args.timeout)
    try:
        b.wait_prompt("the first prompt")
        log = b.text()
        need(log, r"^init: switched to the disk root \S+ \(root=boot-disk\)$", "the unseeded boot")
        blocks = check_grew(log, old_n, n, "the unseeded boot")
        if re.search(r"^cosmo-seed:", log, re.M):
            raise Fail("cosmo-seed said something with no seed attached")
        need(log, r"^\[ INFO\] dhcp: eth0: bound to 10\.0\.2\.15 ", "eth0 on DHCP")
        out = b.run("df -k / | tail -n 1; ls /var/lib/cloud 2>&1; echo look-ok")
        need(out, r"^look-ok$", "the unseeded console")
        need(out, rf"^\S+\s+{blocks * 4}\s", "df / after the root grew")
        need(out, r"No such file or directory", "no /var/lib/cloud without a seed")
        rc = b.finish()
        if rc != EXIT_SUCCESS:
            raise Fail(f"unseeded boot: QEMU exit code {rc}")
    except Exception:
        b.kill()
        raise
    grown_root(disk, n)
    results.append(f"noseed: PASS in {b.elapsed():.1f}s (no line from cosmo-seed, eth0 by DHCP, the pool to "
                   f"{blocks} blocks)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--timeout", type=float, default=240.0, help="per boot")
    args = ap.parse_args()
    shutil.rmtree(args.workdir, ignore_errors=True)
    os.makedirs(args.workdir)
    key = os.path.join(args.workdir, "id_ed25519")
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "cloud-test", "-f", key], check=True)
    key_pub = open(key + ".pub").read().strip()
    tag = secrets.token_hex(4)
    iid, host = f"iid-cloud-test-{tag}", f"cloudy-{tag}"
    results = []
    t0 = time.monotonic()
    try:
        disk, port, df_kib = stage_seed(args, results, args.cloud, key_pub, iid, host)
        stage_again(args, results, disk, port, key_pub, iid, host, df_kib)
        stage_noseed(args, results, args.cloud)
    except Fail as e:
        for r in results:
            print(f"test-cloud: {r}")
        print(f"test-cloud: FAIL: {e} (logs in {args.workdir})")
        return 1
    for r in results:
        print(f"test-cloud: {r}")
    print(f"test-cloud: PASS in {time.monotonic() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
