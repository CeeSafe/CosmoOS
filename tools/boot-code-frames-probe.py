#!/usr/bin/env python3
"""Prove pmm writes every frame where boot-time code ran before the kernel uses it (M52, TEST-28).

--old reverses the fix commit's kernel/memory/pmm.c: the LOADER_RECLAIMABLE
frames (the loader's image, the firmware's boot services) went to bootmem
and the buddy unwritten, so under QEMU's translator a frame keeping the
firmware's old translations kept every later store to it on the slow path.
pmm-boot-code then finds none of the memory map's frames written.
"""
import sys
import fixprobe

sys.exit(fixprobe.run(
    "boot-code-frames-probe", __doc__,
    "pmm writes in place the frames where boot-time code ran (M52, TEST-28)",
    ["kernel/memory/pmm.c"],
    ["pmm-boot-code"],
    [],
    [" written in place at boot", ", 0 written in place at boot"],
    [" written in place at boot", "KiB where boot-time code ran written in place"]))
