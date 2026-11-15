#!/usr/bin/env python3
"""mkvmimages.py RAW QCOW2 VMDK

The live image in the formats hypervisors take (roadmap 1.3 R1;
docs/development.md, "Releases"): QCOW2 for QEMU, UTM and the KVM clouds,
VMDK (monolithicSparse, one file) for VMware and VirtualBox. Each holds the
raw image's bytes and nothing else: `qemu-img compare` finds them equal
(make test-images).

Both are made by `qemu-img convert` and are as reproducible as the image,
which the release requires of every file of its set (`make reproducible`,
the release workflow's two builds): QCOW2 is a pure function of its input.
A VMDK's embedded descriptor names the file itself in its extent line, so
it is converted under its final name, in a directory of its own beside it;
and it carries a content id (CID) qemu-img draws at random and prints
unpadded (`CID=%x`: one draw in sixteen has seven digits or fewer). This
script rewrites the descriptor's whole region, the sectors the sparse
header names, with the CID set to the first eight hex digits of the raw
image's SHA-256 and the text padded with zeros to the region's end, so
nothing qemu-img drew is left in the file.
"""
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

SECTOR = 512


def set_cid(f, cid, name):
    """Rewrite the embedded descriptor of the monolithicSparse VMDK open as
    `f` with CID `cid` (8 hex digits); `name` is the file's, for messages
    and the extent line's check."""
    head = f.read(SECTOR)
    magic, _version, _flags, _capacity, _grain, desc_offset, desc_size = struct.unpack_from("<4sIIQQQQ", head)
    if magic != b"KDMV" or desc_offset == 0 or desc_size == 0:
        sys.exit(f"mkvmimages: {name}: not a sparse VMDK with an embedded descriptor")
    f.seek(desc_offset * SECTOR)
    region = f.read(desc_size * SECTOR)
    text = region.split(b"\0", 1)[0]
    if any(region[len(text):]):
        sys.exit(f"mkvmimages: {name}: the descriptor region holds bytes after its text")
    new, n = re.subn(rb"(?m)^CID=[0-9a-f]{1,8}$", b"CID=" + cid, text)
    if n != 1:
        sys.exit(f"mkvmimages: {name}: no single CID line in the embedded descriptor")
    if b'"' + os.path.basename(name).encode() + b'"' not in new:
        sys.exit(f"mkvmimages: {name}: the extent line does not name the file")
    if len(new) >= len(region):
        sys.exit(f"mkvmimages: {name}: the descriptor does not fit its region")
    f.seek(desc_offset * SECTOR)
    f.write(new + bytes(len(region) - len(new)))


def convert(raw, out, fmt, opts):
    """Convert `raw` to `out` through a file of the same name in a fresh
    directory beside it; return that file's path."""
    d = tempfile.mkdtemp(prefix=".mkvmimages-", dir=os.path.dirname(os.path.abspath(out)))
    tmp = os.path.join(d, os.path.basename(out))
    subprocess.run(["qemu-img", "convert", "-q", "-f", "raw", "-O", fmt, "-o", opts, raw, tmp], check=True)
    return tmp


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    raw, qcow2, vmdk = sys.argv[1:]
    with open(raw, "rb") as f:
        cid = hashlib.sha256(f.read()).hexdigest()[:8].encode()

    tmp = convert(raw, qcow2, "qcow2", "compat=1.1,cluster_size=65536")
    os.replace(tmp, qcow2)
    shutil.rmtree(os.path.dirname(tmp))

    tmp = convert(raw, vmdk, "vmdk", "subformat=monolithicSparse")
    with open(tmp, "r+b") as f:
        set_cid(f, cid, vmdk)
    os.replace(tmp, vmdk)
    shutil.rmtree(os.path.dirname(tmp))


if __name__ == "__main__":
    main()
