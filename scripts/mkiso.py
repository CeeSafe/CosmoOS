#!/usr/bin/env python3
"""mkiso.py: the installer ISO (roadmap 1.3 R1; docs/boot/design.md, "The installer ISO").

    mkiso.py bootvol IMAGE DIR    the live image's ESP as the ISO's boot archive carries it:
                                  DIR/esp.img, its bytes up to the last sector that is not zero,
                                  and DIR/sectors, its length in 512-byte sectors (decimal)
    mkiso.py iso DISK OUT.iso     an ISO 9660 image whose one El Torito entry boots UEFI from
                                  partition 1 of DISK (a GPT image made by mkimage.sh)

The ISO boots from a CD, which the kernel has no driver for; what the
firmware reads off it is all the system gets. Its boot partition holds a
boot archive with the installed system's boot partition in it (the
`bootvol` files), which the kernel registers as a read-only block device
(kernel/block/bootvol.cee) for cosmo-install to copy.

The El Torito catalog: a validation entry for platform 0xEF (UEFI) and a
bootable, no-emulation default entry pointing at the boot partition, which
is the last thing on the disc. Its sector count is 1. The count is 16 bits
of 512-byte sectors, so no value describes a boot image over 32 MiB, and
FAT32's smallest is 64 MiB; EDK2 reads a count below 2 as "to the end of
the volume", which is the boot image exactly. The rest is the least ISO
9660 asks: a primary volume descriptor, the boot record, the terminator,
an empty root directory and its path tables. Every date is ISO 9660's
"not specified", so the image is a function of its input.
"""
import os
import struct
import sys

SS = 512
CD = 2048


def gpt_partition1(data):
    """Partition 1 of a GPT image, as bytes."""
    hdr = data[SS:2 * SS]
    if hdr[:8] != b"EFI PART":
        sys.exit("mkiso: no GPT header at LBA 1")
    entries_lba, = struct.unpack_from("<Q", hdr, 72)
    entry_size, = struct.unpack_from("<I", hdr, 84)
    e = data[entries_lba * SS:entries_lba * SS + entry_size]
    first, last = struct.unpack_from("<QQ", e, 32)
    if first == 0 or last < first:
        sys.exit("mkiso: partition 1 is empty")
    return data[first * SS:(last + 1) * SS]


def bootvol(image, out):
    esp = gpt_partition1(open(image, "rb").read())
    end = len(esp)
    while end > 0 and not any(esp[end - SS:end]):
        end -= SS
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "esp.img"), "wb") as f:
        f.write(esp[:end])
    with open(os.path.join(out, "sectors"), "w") as f:
        f.write(f"{len(esp) // SS}\n")
    print(f"mkiso: {out}: the boot partition, {len(esp) // SS} sectors, {end} bytes stored")


def both16(v):
    return struct.pack("<H", v) + struct.pack(">H", v)


def both32(v):
    return struct.pack("<I", v) + struct.pack(">I", v)


def dirrec(lba, size, name):
    """A directory's record (flags 2), with ISO 9660's even length."""
    body = (bytes(1) + both32(lba) + both32(size) + bytes(7) + bytes([2, 0, 0]) + both16(1) + bytes([len(name)]) +
            name)
    if (1 + len(body)) % 2:
        body += b"\0"
    return bytes([1 + len(body)]) + body


def sector(b):
    assert len(b) <= CD
    return b + bytes(CD - len(b))


def iso(disk, out):
    esp = gpt_partition1(open(disk, "rb").read())
    pvd_lba, br_lba, term_lba, cat_lba, root_lba, ptl_lba, ptm_lba, esp_lba = range(16, 24)
    total = esp_lba + (len(esp) + CD - 1) // CD
    unspecified = b"0" * 16 + b"\0"   # ISO 9660 8.4.26.1: a date not specified

    pvd = (b"\x01CD001\x01\0" + b" " * 32 + b"COSMOOS".ljust(32) + bytes(8) + both32(total) + bytes(32) +
           both16(1) + both16(1) + both16(CD) + both32(10) + struct.pack("<I", ptl_lba) + bytes(4) +
           struct.pack(">I", ptm_lba) + bytes(4) + dirrec(root_lba, CD, b"\0") +
           b" " * (128 * 4 + 37 * 3) + unspecified * 4 + b"\x01\0")
    br = b"\0CD001\x01" + b"EL TORITO SPECIFICATION".ljust(32, b"\0") + bytes(32) + struct.pack("<I", cat_lba)
    term = b"\xffCD001\x01"

    validation = bytearray(struct.pack("<BBH", 1, 0xEF, 0) + bytes(24) + b"\0\0\x55\xaa")
    struct.pack_into("<H", validation, 28, -sum(struct.unpack("<16H", bytes(validation))) & 0xFFFF)
    default = struct.pack("<BBHBBHI", 0x88, 0, 0, 0, 0, 1, esp_lba) + bytes(20)

    root = dirrec(root_lba, CD, b"\0") + dirrec(root_lba, CD, b"\1")
    ptl = struct.pack("<BBIH", 1, 0, root_lba, 1) + b"\0\0"
    ptm = struct.pack(">BBIH", 1, 0, root_lba, 1) + b"\0\0"

    tmp = out + ".tmp"
    with open(tmp, "wb") as f:
        f.write(bytes(16 * CD))
        for b in (pvd, br, term, bytes(validation) + default, root, ptl, ptm):
            f.write(sector(b))
        f.write(esp)
        f.write(bytes(total * CD - f.tell()))
    os.replace(tmp, out)
    print(f"mkiso: {out}: {total} sectors of 2048 bytes, the boot partition ({len(esp)} bytes) at {esp_lba}")


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ("bootvol", "iso"):
        sys.exit(__doc__)
    (bootvol if sys.argv[1] == "bootvol" else iso)(sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    main()
