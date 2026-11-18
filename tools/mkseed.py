#!/usr/bin/env python3
"""Write a cloud-init NoCloud seed image with no host tools (roadmap 1.3 R2).

    mkseed.py --format iso|fat [--fat-bits 12|16] [--names joliet|rock|plain] OUTPUT FILE...

Each FILE is stored in the volume's root directory under its base name
(meta-data, user-data, network-config). The volume is labelled `cidata`,
which is what cosmo-seed (userland/system/seed_read.c) and cloud-init look
for.

  iso   ISO 9660, 2048-byte blocks. --names joliet (default) adds a Joliet
        volume whose names are the files' own; rock gives the primary
        volume Rock Ridge NM names instead; plain gives it only ISO names
        (the base name upper-cased, '-' written '_', with ";1"), as
        `genisoimage` without -J or -r would.
  fat   FAT12 (1 MiB) or FAT16 (16 MiB) with VFAT long names, one sector
        per cluster, label CIDATA.

Deterministic: the same files give the same image.
"""
import argparse
import os
import struct
import sys

BLOCK = 2048


def both16(v):
    return struct.pack("<H", v) + struct.pack(">H", v)


def both32(v):
    return struct.pack("<I", v) + struct.pack(">I", v)


def dir_record(extent, size, flags, name, su=b""):
    pad = b"\0" if len(name) % 2 == 0 else b""
    length = 33 + len(name) + len(pad) + len(su)
    length += length % 2
    rec = (bytes([length, 0]) + both32(extent) + both32(size) + bytes([126, 1, 1, 0, 0, 0, 0]) +
           bytes([flags, 0, 0]) + both16(1) + bytes([len(name)]) + name + pad + su)
    return rec + b"\0" * (length - len(rec))


def directory(records):
    """Records packed so that none crosses a block; the whole length."""
    out = b""
    for r in records:
        if len(out) // BLOCK != (len(out) + len(r) - 1) // BLOCK:
            out += b"\0" * (BLOCK - len(out) % BLOCK)
        out += r
    return out + b"\0" * (-len(out) % BLOCK)


def iso(files, names):
    n = len(files)
    # Blocks: 0-15 system area, 16 PVD, 17 Joliet SVD (or terminator), then terminator, path tables, directories,
    # files.
    joliet = names == "joliet"
    vds = 3 if joliet else 2
    lpath, mpath = 16 + vds, 16 + vds + 1
    jlpath, jmpath = mpath + 1, mpath + 2
    root = jmpath + 1 if joliet else mpath + 1
    # One block per directory is enough for three files.
    jroot = root + 1
    data = (jroot + 1) if joliet else (root + 1)
    extents = []
    at = data
    for _, body in files:
        extents.append(at)
        at += max(1, -(-len(body) // BLOCK))
    total = at

    def records(jol):
        here = jroot if jol else root
        su_dot = b"SP\x07\x01\xbe\xef\x00" if names == "rock" and not jol else b""
        recs = [dir_record(here, BLOCK, 2, b"\0", su_dot), dir_record(here, BLOCK, 2, b"\1")]
        for (name, body), ext in zip(files, extents):
            if jol:
                nm = (name + ";1").encode("utf-16-be")
                su = b""
            else:
                nm = (name.upper().replace("-", "_") + ";1").encode()
                su = b""
                if names == "rock":
                    raw = name.encode()
                    su = b"NM" + bytes([5 + len(raw), 1, 0]) + raw
            recs.append(dir_record(ext, len(body), 0, nm, su))
        return directory(recs)

    def vd(kind, jol):
        v = bytearray(BLOCK)
        v[0] = kind
        v[1:6] = b"CD001"
        v[6] = 1
        if jol:
            v[8:40] = "".ljust(16).encode("utf-16-be")
            v[40:72] = "cidata".ljust(16).encode("utf-16-be")
            v[88:91] = b"%/E"
        else:
            v[8:40] = b" " * 32
            v[40:72] = b"cidata".ljust(32)
        v[80:88] = both32(total)
        v[120:124] = both16(1)
        v[124:128] = both16(1)
        v[128:132] = both16(BLOCK)
        v[132:140] = both32(10)
        v[140:144] = struct.pack("<I", jlpath if jol else lpath)
        v[148:152] = struct.pack(">I", jmpath if jol else mpath)
        here = jroot if jol else root
        v[156:190] = dir_record(here, BLOCK, 2, b"\0")
        for i in range(190, 813):
            if v[i] == 0 and 190 <= i < 813:
                v[i] = 0x20 if i < 813 else 0
        for off in (813, 830, 847, 864):
            v[off:off + 17] = b"0" * 16 + b"\0"
        v[881] = 1
        return bytes(v)

    def path_table(here, big):
        fmt = ">I" if big else "<I"
        parent = ">H" if big else "<H"
        return bytes([1, 0]) + struct.pack(fmt, here) + struct.pack(parent, 1) + b"\0\0"

    img = bytearray(total * BLOCK)

    def put(block, data):
        img[block * BLOCK:block * BLOCK + len(data)] = data

    put(16, vd(1, False))
    if joliet:
        put(17, vd(2, True))
    term = bytearray(BLOCK)
    term[0] = 255
    term[1:6] = b"CD001"
    term[6] = 1
    put(16 + vds - 1, bytes(term))
    put(lpath, path_table(root, False))
    put(mpath, path_table(root, True))
    if joliet:
        put(jlpath, path_table(jroot, False))
        put(jmpath, path_table(jroot, True))
    put(root, records(False))
    if joliet:
        put(jroot, records(True))
    for (_, body), ext in zip(files, extents):
        put(ext, body)
    return bytes(img)


def lfn_entries(name, short):
    s = 0
    for c in short:
        s = (((s & 1) << 7) + (s >> 1) + c) & 0xFF
    units = [ord(c) for c in name] + [0]
    units += [0xFFFF] * (-len(units) % 13)
    parts = [units[i:i + 13] for i in range(0, len(units), 13)]
    out = []
    for seq in range(len(parts), 0, -1):
        u = parts[seq - 1]
        e = bytearray(32)
        e[0] = seq | (0x40 if seq == len(parts) else 0)
        for i, off in enumerate((1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30)):
            e[off:off + 2] = struct.pack("<H", u[i])
        e[11] = 0x0F
        e[13] = s
        out.append(bytes(e))
    return out


def fat(files, bits):
    sectors = 2048 if bits == 12 else 32768
    rsvd, nfats, rootent, spc = 1, 2, 512, 1
    rootsecs = rootent * 32 // 512
    clusters_guess = sectors
    fatsz = -(-((clusters_guess + 2) * bits // 8 + 1) // 512)
    first = rsvd + nfats * fatsz + rootsecs
    clusters = (sectors - first) // spc
    assert (clusters < 4085) == (bits == 12) and (bits == 12 or clusters < 65525)
    img = bytearray(sectors * 512)
    bs = bytearray(512)
    bs[0:3] = b"\xEB\x3C\x90"
    bs[3:11] = b"MSWIN4.1"
    struct.pack_into("<HBHBHHBHHHII", bs, 11, 512, spc, rsvd, nfats, rootent, sectors, 0xF8, fatsz, 32, 64, 0, 0)
    bs[36] = 0x80
    bs[38] = 0x29
    bs[39:43] = b"\x43\x49\x44\x41"
    bs[43:54] = b"CIDATA     "
    bs[54:62] = (b"FAT12   " if bits == 12 else b"FAT16   ")
    bs[510:512] = b"\x55\xAA"
    img[0:512] = bs
    entries = []
    label = bytearray(32)
    label[0:11] = b"CIDATA     "
    label[11] = 0x08
    entries.append(bytes(label))
    table = {0: 0xFF8 if bits == 12 else 0xFFF8, 1: 0xFFF if bits == 12 else 0xFFFF}
    eoc = 0xFFF if bits == 12 else 0xFFFF
    nxt = 2
    for i, (name, body) in enumerate(files):
        base = name.upper().replace(".", "")[:6] or "F"
        short = (base + "~" + str(i + 1)).ljust(8)[:8].encode() + b"   "
        entries.extend(lfn_entries(name, short))
        e = bytearray(32)
        e[0:11] = short
        e[11] = 0x20
        need = max(1, -(-len(body) // 512)) if body else 0
        start = nxt if need else 0
        for k in range(need):
            c = nxt + k
            table[c] = c + 1 if k + 1 < need else eoc
            off = (first + (c - 2) * spc) * 512
            chunk = body[k * 512:(k + 1) * 512]
            img[off:off + len(chunk)] = chunk
        nxt += need
        struct.pack_into("<H", e, 26, start)
        struct.pack_into("<I", e, 28, len(body))
        entries.append(bytes(e))
    assert len(entries) <= rootent and nxt - 2 <= clusters
    root = (rsvd + nfats * fatsz) * 512
    blob = b"".join(entries)
    img[root:root + len(blob)] = blob
    fatbytes = bytearray(fatsz * 512)
    for c, v in table.items():
        if bits == 16:
            struct.pack_into("<H", fatbytes, 2 * c, v)
        else:
            off = c + c // 2
            cur = struct.unpack_from("<H", fatbytes, off)[0]
            cur = (cur & 0x000F) | (v << 4) if c & 1 else (cur & 0xF000) | v
            struct.pack_into("<H", fatbytes, off, cur & 0xFFFF)
    for k in range(nfats):
        at = (rsvd + k * fatsz) * 512
        img[at:at + len(fatbytes)] = fatbytes
    return bytes(img)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--format", choices=("iso", "fat"), required=True)
    ap.add_argument("--fat-bits", type=int, choices=(12, 16), default=12)
    ap.add_argument("--names", choices=("joliet", "rock", "plain"), default="joliet")
    ap.add_argument("output")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    files = [(os.path.basename(f), open(f, "rb").read()) for f in a.files]
    data = iso(files, a.names) if a.format == "iso" else fat(files, a.fat_bits)
    with open(a.output, "wb") as f:
        f.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
