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
and it carries a content id (CID) qemu-img draws at random, which this
script replaces with the first eight hex digits of the raw image's SHA-256
(the same length: nothing moves).
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

# The descriptor is text in the sectors after the sparse header (QEMU's
# vmdk.c writes it at sector 1); 64 KiB is far more than it takes.
DESC_SPAN = 64 * 1024


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
        head = f.read(DESC_SPAN)
        m = re.search(rb"\nCID=([0-9a-f]{8})\n", head)
        if not m:
            sys.exit(f"mkvmimages: {vmdk}: no CID line in the embedded descriptor")
        if b'"' + os.path.basename(vmdk).encode() + b'"' not in head:
            sys.exit(f"mkvmimages: {vmdk}: the extent line does not name the file")
        f.seek(m.start(1))
        f.write(cid)
    os.replace(tmp, vmdk)
    shutil.rmtree(os.path.dirname(tmp))


if __name__ == "__main__":
    main()
