#!/usr/bin/env python3
"""cosmo-seed's readers against seeds tools/mkseed.py writes (roadmap 1.3 R2).

    test_seed.py TEST_SEED

TEST_SEED is tests/host/test_seed.c built for the host (make host-test). For
each of ISO 9660 with Joliet, Rock Ridge and plain names and FAT12 and FAT16
with long names: the seed is found and each file reads back byte for byte;
a missing file is ENOENT. Then what is not a seed (zeros, an ISO labelled
otherwise), damaged volumes (an ISO file extent past the end, a FAT chain
that loops or ends early, an oversized file) and the YAML subset: a
network-config, an unknown key, and parse errors. Exit 0 when every check
passes.
"""
import os
import re
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MKSEED = os.path.join(ROOT, "tools", "mkseed.py")
FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


def tool(*args):
    r = subprocess.run([sys.argv[1], *args], capture_output=True)
    return r.returncode, r.stdout


META = b"instance-id: iid-host-1\nlocal-hostname: seeded\n"
USER = b"#cloud-config\nhostname: seeded-host\nssh_authorized_keys:\n  - ssh-ed25519 AAAAC3Nza test@host\n"
NET = (b"version: 2\nethernets:\n  eth0:\n    match:\n      macaddress: '52:54:00:12:34:56'\n"
       b"    addresses: [10.0.2.50/24]\n    gateway4: 10.0.2.2\n    nameservers:\n      addresses: [10.0.2.3]\n")


def make(work, fmt, extra, files):
    paths = []
    for name, body in files:
        p = os.path.join(work, name)
        with open(p, "wb") as f:
            f.write(body)
        paths.append(p)
    img = os.path.join(work, f"seed-{fmt}-{'-'.join(extra) or 'default'}.img")
    subprocess.run([sys.executable, MKSEED, "--format", fmt, *extra, img, *paths], check=True)
    return img


def main():
    if len(sys.argv) != 2:
        print("usage: test_seed.py TEST_SEED")
        return 2
    big = bytes((i * 7 + 3) & 0xFF for i in range(3000))   # several clusters, several ISO sectors
    files = [("meta-data", META), ("user-data", USER), ("network-config", NET + b"# " + big.hex().encode()[:2000])]
    with tempfile.TemporaryDirectory() as work:
        kinds = [("iso", ["--names", "joliet"], "iso"), ("iso", ["--names", "rock"], "iso"),
                 ("iso", ["--names", "plain"], "iso"), ("fat", ["--fat-bits", "12"], "fat"),
                 ("fat", ["--fat-bits", "16"], "fat")]
        for fmt, extra, want in kinds:
            img = make(work, fmt, extra, files)
            label = f"{fmt} {' '.join(extra)}"
            rc, out = tool("probe", img)
            check(out.strip() == want.encode(), f"{label}: found as a seed ({out.strip().decode()})")
            for name, body in files:
                rc, out = tool("cat", img, name)
                check(rc == 0 and out == body, f"{label}: {name} reads back ({len(body)} bytes)")
            rc, out = tool("cat", img, "vendor-data")
            check(rc == 1 and out.strip() == b"error: ENOENT", f"{label}: a missing file is ENOENT")

        # Not seeds.
        zeros = os.path.join(work, "zeros.img")
        with open(zeros, "wb") as f:
            f.write(bytes(1 << 20))
        check(tool("probe", zeros)[1].strip() == b"none", "zeros are not a seed")
        iso = make(work, "iso", ["--names", "joliet"], files)
        data = bytearray(open(iso, "rb").read())
        other = bytearray(data)
        other[16 * 2048 + 40:16 * 2048 + 46] = b"OTHERS"
        p = os.path.join(work, "other.iso")
        open(p, "wb").write(other)
        check(tool("probe", p)[1].strip() == b"none", "an ISO labelled otherwise is not a seed")
        tiny = os.path.join(work, "tiny.img")
        open(tiny, "wb").write(bytes(512))
        check(tool("probe", tiny)[1].strip() == b"none", "a one-sector device is not a seed")

        # Damage: an ISO file whose extent lies past the device's end (Joliet's record for meta-data).
        jroot = struct.unpack_from("<I", data, 17 * 2048 + 156 + 2)[0] * 2048
        at = jroot
        found = False
        while at < jroot + 2048 and data[at]:
            nl = data[at + 32]
            if bytes(data[at + 33:at + 33 + nl]).decode("utf-16-be", "replace").startswith("meta-data"):
                struct.pack_into("<I", data, at + 2, 0x7FFFFFFF)
                found = True
            at += data[at]
        p = os.path.join(work, "past-end.iso")
        open(p, "wb").write(data)
        rc, out = tool("cat", p, "meta-data")
        check(found and rc == 1 and out.strip() == b"error: EINVAL", "an ISO extent past the end is EINVAL")
        # A record shorter than a record's fixed part (the first file's, after "." and "..").
        data2 = bytearray(open(iso, "rb").read())
        first = jroot + data2[jroot] + data2[jroot + data2[jroot]]
        data2[first] = 33
        p = os.path.join(work, "bad-record.iso")
        open(p, "wb").write(data2)
        rc, out = tool("cat", p, "network-config")
        check(rc == 1 and out.strip() == b"error: EINVAL", f"a damaged ISO directory record is EINVAL ({out.strip().decode()})")

        # FAT: a chain that loops, and one that ends before the file.
        fat = bytearray(open(make(work, "fat", ["--fat-bits", "16"], files), "rb").read())
        fat_at = 512   # the first FAT, after one reserved sector
        net_first = None
        root = (1 + 2 * struct.unpack_from("<H", fat, 22)[0]) * 512
        for k in range(0, 512 * 32, 32):
            e = fat[root + k:root + k + 32]
            if e[0] == 0:
                break
            if e[11] == 0x20 and e[0:4] == b"NETW":
                net_first = struct.unpack_from("<H", e, 26)[0]
        loop = bytearray(fat)
        struct.pack_into("<H", loop, fat_at + 2 * net_first, net_first)
        p = os.path.join(work, "loop.img")
        open(p, "wb").write(loop)
        rc, out = tool("cat", p, "network-config")
        check(net_first is not None and rc == 1 and out.strip() == b"error: EINVAL", "a FAT chain that loops is EINVAL")
        short = bytearray(fat)
        struct.pack_into("<H", short, fat_at + 2 * net_first, 0xFFFF)
        p = os.path.join(work, "short.img")
        open(p, "wb").write(short)
        rc, out = tool("cat", p, "network-config")
        check(rc == 1 and out.strip() == b"error: EINVAL", "a FAT chain shorter than its file is EINVAL")
        huge = bytearray(fat)
        for k in range(0, 512 * 32, 32):
            if huge[root + k + 11] == 0x20 and huge[root + k:root + k + 4] == b"META":
                struct.pack_into("<I", huge, root + k + 28, 70000)
        p = os.path.join(work, "huge.img")
        open(p, "wb").write(huge)
        rc, out = tool("cat", p, "meta-data")
        check(rc == 1 and out.strip() == b"error: EFBIG", "a file over 64 KiB is EFBIG, not read")

        # FAT32: a root directory whose chain loops (cluster 2 -> 2) on a volume of 70000 clusters, every entry
        # deleted, so no end mark stops the walk. Refused after a directory's 65536 entries (4096 one-sector
        # clusters, two reads each), not after a walk of every cluster.
        clusters32, fatsz32, rsvd32 = 70000, 548, 32
        first32 = rsvd32 + 2 * fatsz32
        total32 = first32 + clusters32
        bs = bytearray(512)
        bs[0:3] = b"\xEB\x58\x90"
        struct.pack_into("<HBHBHHBHHHII", bs, 11, 512, 1, rsvd32, 2, 0, 0, 0xF8, 0, 32, 64, 0, total32)
        struct.pack_into("<IHHI", bs, 36, fatsz32, 0, 0, 2)
        bs[66] = 0x29
        bs[71:82] = b"CIDATA     "
        bs[82:90] = b"FAT32   "
        bs[510:512] = b"\x55\xAA"
        p = os.path.join(work, "root-loop32.img")
        with open(p, "wb") as f:
            f.truncate(total32 * 512)
            f.write(bs)
            for k in range(2):
                f.seek((rsvd32 + k * fatsz32) * 512)
                f.write(struct.pack("<III", 0x0FFFFFF8, 0x0FFFFFFF, 2))
            f.seek(first32 * 512)
            f.write(b"\xE5" + b"\x00" * 31)
            f.write((b"\xE5" + b"\x00" * 31) * 15)
        r = subprocess.run([sys.argv[1], "probe", p], capture_output=True)
        check(r.stdout.strip() == b"fat", f"a FAT32 seed is FAT ({r.stdout.strip().decode()})")
        r = subprocess.run([sys.argv[1], "cat", p, "meta-data"], capture_output=True)
        m = re.search(rb"reads=(\d+)", r.stderr)
        reads = int(m.group(1)) if m else -1
        check(r.returncode == 1 and r.stdout.strip() == b"error: EINVAL" and 0 < reads <= 2 * 4096 + 16,
              f"a FAT32 root chain that loops is EINVAL within a directory's entries ({reads} reads)")

        # The YAML subset, as cosmo-seed reads the three files.
        def yaml(text):
            p = os.path.join(work, "y.yaml")
            open(p, "wb").write(text)
            rc, out = tool("yaml", p)
            return rc, out.decode()

        rc, out = yaml(NET)
        check(rc == 0 and "ethernets.eth0.match.macaddress=52:54:00:12:34:56\n" in out and
              "ethernets.eth0.addresses[0]=10.0.2.50/24\n" in out and
              "ethernets.eth0.nameservers.addresses[0]=10.0.2.3\n" in out, "network-config parses")
        rc, out = yaml(b"version: 2\nethernets:\n  eth0:\n    routes:\n      - to: default\n        via: 10.0.2.2\n")
        check(rc == 0 and "ethernets.eth0.routes[0].to=default\n" in out and
              "ethernets.eth0.routes[0].via=10.0.2.2\n" in out, "a list of maps parses")
        rc, out = yaml(USER + b"runcmd: [ls]\n")
        check(rc == 0 and "runcmd[0]=ls\n" in out and "hostname=seeded-host\n" in out,
              "an unknown key parses (cosmo-seed names it and ignores it)")
        for bad, why in ((b"a: |\n  x\n", "a block scalar"), (b"a:\n\t- 1\n", "a tab"), (b"a: {b: 1}\n", "a flow map"),
                         (b"a: 1\n  b: 2\n", "stray indentation"), (b"- a\nb: 1\n", "a map after a list")):
            rc, out = yaml(bad)
            check(rc == 3 and out.startswith("error: line "), f"{why} is a parse error ({out.strip()})")
    print(f"test_seed: {'FAIL' if FAILS else 'PASS'} ({len(FAILS)} failed)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
