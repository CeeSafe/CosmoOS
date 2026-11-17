#!/usr/bin/env python3
"""Host test of scripts/mkvmimages.py (make host-test; roadmap 1.3 R1).

qemu-img prints a VMDK's random content id unpadded (`CID=%x`), so one
conversion in sixteen has a CID of seven digits or fewer; the first
version of mkvmimages.py looked for exactly eight and failed those (two
jobs of #525's CI run 43650889097). On synthetic sparse VMDKs:
- descriptors that differ only in qemu-img's CID, eight digits and seven
  and one, come out byte for byte the same, with the CID given and the
  text padded with zeros to the region's end;
- qemu-img draws the CID twice and rewrites the second over the first in
  place (`vmdk_write_cid`), so a second CID k digits shorter leaves the
  first text's last k - 1 bytes after the second's NUL; the second
  version refused those as "bytes after its text" (the AArch64 release
  set of #528's CI run 43827130336). Eight digits redrawn as six or as
  one give the same file as the rest;
- a descriptor with no CID line, or two, is refused, and so is one whose
  extent line names another file, and a region with bytes after its text
  other than up to six of its text's last bytes right after its NUL.

With qemu-img (check-tools requires it): mkvmimages.py makes a VMDK that
`qemu-img check` finds clean and `qemu-img compare` finds equal to the raw
image, and the same raw image converted twice gives the same QCOW2 and the
same VMDK; and through a qemu-img that forces the CID it draws to eight,
seven or one digits, the VMDK is the same each time (the first version
failed the last two with "no CID line in the embedded descriptor", as CI
did), and so it is when it redraws eight digits as one in place.
"""
import hashlib
import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "scripts", "mkvmimages.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import mkvmimages  # noqa: E402

failed = 0


def check(cond, what):
    global failed
    print(("ok: " if cond else "FAIL: ") + what)
    if not cond:
        failed += 1


def synthetic(cid, name="disk.vmdk", extra=b"", tail=b"", cids=1):
    """A sparse VMDK's header and descriptor region (20 sectors at sector 1), as qemu-img lays them out."""
    head = struct.pack("<4sIIQQQQ", b"KDMV", 1, 3, 8192, 128, 1, 20).ljust(512, b"\0")
    text = (b"# Disk DescriptorFile\nversion=1\n" + b"".join(b"CID=" + cid + b"\n" for _ in range(cids)) +
            b"parentCID=ffffffff\ncreateType=\"monolithicSparse\"\n\n# Extent description\nRW 8192 SPARSE \"" +
            name.encode() + b"\"\n" + extra)
    region = (text + b"\0" * (20 * 512 - len(text) - len(tail)) + tail)
    return head + region + b"\0" * 512


def redrawn(data, cid):
    """`data` after qemu-img's second draw, as `vmdk_write_cid` (block/vmdk.c) makes it: the region read whole,
    the CID printed unpadded after the first "CID" with a newline and a NUL, the text from "parentCID" on appended
    after it, and the whole region written back, so a shorter CID leaves the old text's end after the new NUL."""
    region = bytearray(data[512:512 + 20 * 512])
    rest = bytes(region[region.index(b"parentCID"):region.index(b"\0")])
    at = region.index(b"CID") + len(b"CID=")
    new = cid + b"\n" + rest + b"\0"
    region[at:at + len(new)] = new
    return data[:512] + bytes(region) + data[512 + 20 * 512:]


def patched(data, name="disk.vmdk"):
    f = io.BytesIO(data)
    mkvmimages.set_cid(f, b"0123abcd", name)
    return f.getvalue()


def refused(data, name="disk.vmdk"):
    try:
        patched(data, name)
    except SystemExit as e:
        return str(e)
    return None


def synthetic_cases():
    long_, short, one = (patched(synthetic(c)) for c in (b"fedcba98", b"edcba98", b"7"))
    check(long_ == short == one, "a CID of eight, seven and one digits gives the same file")
    region = long_[512:512 + 20 * 512]
    check(b"\nCID=0123abcd\n" in region, "the CID is the one given")
    text = region.split(b"\0", 1)[0]
    check(not any(region[len(text):]), "the text is padded with zeros to the region's end")
    check(long_[:512] == synthetic(b"fedcba98")[:512] and long_[-512:] == bytes(512),
          "the header and what follows the region are untouched")
    check("no single CID line" in (refused(synthetic(b"1", cids=0)) or ""), "a descriptor with no CID is refused")
    check("no single CID line" in (refused(synthetic(b"1", cids=2)) or ""), "a descriptor with two CIDs is refused")
    check("does not name the file" in (refused(synthetic(b"1"), "other.vmdk") or ""),
          "an extent line naming another file is refused")
    for first, second in ((b"fedcba98", b"edcba9"), (b"fedcba98", b"1")):
        data = redrawn(synthetic(first), second)
        region = data[512:512 + 20 * 512]
        left = region[region.index(b"\0") + 1:].split(b"\0", 1)[0]
        why = refused(data)
        check(len(left) == len(first) - len(second) - 1 and why is None and patched(data) == long_,
              f"qemu-img's CID {first.decode()} redrawn as {second.decode()}, {len(left)} bytes of the first text "
              f"left after the second's end, gives the same file ({why or 'no message'})")
    check("bytes after its text" in (refused(synthetic(b"1", tail=b"x")) or ""),
          "a region with bytes after its text is refused")
    text = synthetic(b"1")[512:].split(b"\0", 1)[0]
    for left, what in ((b"x\"\n", "that are not its text's end"), (text[-7:], "seven bytes of its text's end")):
        data = bytearray(synthetic(b"1"))
        data[512 + len(text) + 1:512 + len(text) + 1 + len(left)] = left
        check("bytes after its text" in (refused(bytes(data)) or ""),
              f"a region with bytes after its text's NUL {what} is refused")
    check("not a sparse VMDK" in (refused(b"\0" * 4096) or ""), "a file with no sparse header is refused")


def qemu_cases():
    if not shutil.which("qemu-img"):
        check(False, "qemu-img on PATH (make check-tools requires it)")
        return
    with tempfile.TemporaryDirectory() as d:
        raw = os.path.join(d, "raw.img")
        with open(raw, "wb") as f:
            for i in range(64):
                f.write(hashlib.sha256(bytes([i])).digest() * 2048)   # 64 KiB per step: 4 MiB, no zero cluster
        outs = []
        for run in ("a", "b"):
            os.mkdir(os.path.join(d, run))
            q, v = os.path.join(d, run, "x.qcow2"), os.path.join(d, run, "x.vmdk")
            r = subprocess.run([sys.executable, SCRIPT, raw, q, v], capture_output=True, text=True)
            check(r.returncode == 0, f"mkvmimages.py, run {run} ({r.stderr.strip() or 'no message'})")
            if r.returncode:
                return
            outs.append((open(q, "rb").read(), open(v, "rb").read()))
            c = subprocess.run(["qemu-img", "check", "-q", "-f", "vmdk", v], capture_output=True, text=True)
            check(c.returncode == 0, f"qemu-img check finds run {run}'s VMDK clean")
            c = subprocess.run(["qemu-img", "compare", "-q", "-f", "raw", "-F", "vmdk", raw, v])
            check(c.returncode == 0, f"qemu-img compare finds run {run}'s VMDK equal to the raw image")
        check(outs[0][0] == outs[1][0], "two conversions give the same QCOW2")
        check(outs[0][1] == outs[1][1], "two conversions give the same VMDK")

        # The draws themselves, forced: a qemu-img that converts, then sets the CID it drew to FORCE_CID, unpadded
        # as qemu-img prints it (the text one byte shorter for seven digits, the region's zeros one longer); and
        # with FIRST>SECOND, sets FIRST so and then SECOND as vmdk_write_cid does, over it in place.
        wrap = os.path.join(d, "bin")
        os.mkdir(wrap)
        with open(os.path.join(wrap, "qemu-img"), "w") as f:
            f.write(f"""#!{sys.executable}
import os, re, subprocess, sys
r = subprocess.run([{shutil.which("qemu-img")!r}] + sys.argv[1:]).returncode
if r == 0 and sys.argv[1] == "convert" and "vmdk" in sys.argv:
    first, _, second = os.environ["FORCE_CID"].partition(">")
    with open(sys.argv[-1], "r+b") as f:
        f.seek(512)
        region = f.read(20 * 512)
        text = region.split(b"\\0", 1)[0]
        text = re.sub(rb"(?m)^CID=[0-9a-f]+$", b"CID=" + first.encode(), text)
        region = bytearray(text + bytes(len(region) - len(text)))
        if second:
            at = region.index(b"CID") + 4
            new = second.encode() + b"\\n" + bytes(region[region.index(b"parentCID"):len(text)]) + b"\\0"
            region[at:at + len(new)] = new
        f.seek(512)
        f.write(region)
sys.exit(r)
""")
        os.chmod(os.path.join(wrap, "qemu-img"), 0o755)
        forced = {}
        for c in ("fedcba98", "edcba98", "1", "fedcba98>1"):
            out = os.path.join(d, "forced-" + c)
            os.mkdir(out)
            env = dict(os.environ, PATH=wrap + os.pathsep + os.environ["PATH"], FORCE_CID=c)
            v = os.path.join(out, "x.vmdk")
            r = subprocess.run([sys.executable, SCRIPT, raw, os.path.join(out, "x.qcow2"), v], env=env,
                               capture_output=True, text=True)
            check(r.returncode == 0, f"mkvmimages.py with qemu-img's CID {c} ({r.stderr.strip() or 'no message'})")
            forced[c] = open(v, "rb").read() if r.returncode == 0 else None
        check(forced["fedcba98"] is not None and forced["fedcba98"] == forced["edcba98"] == forced["1"] == outs[0][1],
              "qemu-img's CID of eight, seven or one digits gives the same VMDK")
        check(forced["fedcba98>1"] is not None and forced["fedcba98>1"] == outs[0][1],
              "qemu-img's CID of eight digits redrawn as one, in place, gives the same VMDK")


synthetic_cases()
qemu_cases()
sys.exit(1 if failed else 0)
