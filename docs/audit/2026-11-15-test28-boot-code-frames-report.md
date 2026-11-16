# TEST-28: frames where boot-time code ran, written before use, 2026-11-15

Backlog TEST-28: a four-CPU x86-64 debug boot ran in one of two modes,
`cosmofs-replay` at about 30 s or at about 53 s against its 40 s bound,
and the slow mode ran out of the boot's 300 s. It turned main red on
`24421af8`, `af5a8b66` and `d2392534`, and failed boots in the matrices
of #520, #525, #526 and #527. The owner asked first whether CeeSafe's
newer compilers caused it, then for the root cause.

## Scope and baseline

Branch `test28-boot-frames` from main at `d2392534` (ceesafec 0.48.1).
In scope: the cause, the physical memory manager's boot path
(`kernel/memory/pmm.c`), its documents, its test and the record of
TEST-28. Out of scope: QEMU itself, AArch64's `process-user` sighting
of the same day (flakes.md), which this does not explain, and AArch64's
own slow mode of `cosmofs-replay`, found while validating this and on
main as well: a different mechanism, recorded as backlog TEST-29
(Validation).

## The compiler is not the cause

On the other machine (the CI image, one container of 4 CPUs), main's
sources built with ceesafec 0.37.0 and with 0.49.0, x86-64 debug, four
CPUs, booted in ABBA order: 0.37.0 nine of nine fast (`cosmofs-replay`
29.2 to 31.1 s); 0.49.0 four slow (49 to 56 s), two between (37 s),
three fast. But the kernel C of 0.50.0 is 0.49.0's and 0.48.1's byte
for byte but for each file's banner, and 0.48.1's is 0.47.1's after
preprocessing; all that changed since 0.37.0 is 218 fewer overflow and
index checks (of about 7,700; ten sampled, each provably unneeded) and
renumbered types. The same 0.49.0 tree with one 24 KiB file added to the
boot archive booted fast four times of four. So the compiler changed
which boots met the slow mode, not the code that runs in it.

## The mechanism

Three candidates fell first: the kernel's physical base (the padded
archive loaded at the same addresses and ran fast), storms of
translation invalidations or TLB flushes (QEMU's own counters, sampled
every 2 s over QMP with `info jit`, were no higher in slow boots: 0 TB
flushes, 0 full TLB flushes in every boot), and conflicts in QEMU's
direct-mapped software TLB (the slots of every page on the path,
computed for each table size from 64 to 512, are all distinct).

`irqrestore-bench`'s per-CPU probes showed the slow mode belonged to one
thread: in slow boots the self-test runner's save/restore pair took 2.2
to 2.4 us, the same loop on a fresh thread on the same CPU 0.45 to 0.53.
Run on the runner itself, the probe's own loop was slow too, so the
thread's data, not the code's place, was slow. The runner is the boot
thread `kmain`, and debug `arch_irq_save`/`arch_irq_restore` (lockdep's
pairing, `kernel/core/lockdep.c`) write its `struct thread` on every
call. One access at a time, a million each, interrupts masked:

| boot | `kmain`'s `struct thread` | store to it | load | store to its stack | store to the heap |
|---|---|---|---|---|---|
| fast (two) | phys `0xfc8c040` | 4.4 ns | 4.4 ns | 2.3 ns | 2.2 ns |
| slow | phys `0xfec4040` | 371.9 ns | 4.4 ns | 2.3 ns | 2.2 ns |

`0xfec4040` is in a LOADER_RECLAIMABLE entry of the boot memory map
(`0xfe98000`-`0xfedc000`, just below the firmware's runtime services):
EfiBootServicesCode, EfiBootServicesData, EfiLoaderCode or -Data
(`boot/uefi/main.c`, `translate_type`). QEMU 10.0's
`accel/tcg/tb-maint.c`: a store to a page that holds translated code
invalidates the translation blocks the store overlaps, and the page
returns to the fast store path only `if (!p->first_tb)`. The firmware's
code, translated while it ran, sits at offsets no kernel store reaches;
its blocks stay, and every store to the page takes `notdirty_write`.
`pmm.c` released these frames to bootmem and the buddy without writing
them, and page poisoning writes only frames freed later.

**Cause, not correlation.** The same instrumented kernel, rewriting
every 8-byte word of `kmain`'s page in place (a compare-exchange of each
word with itself) after the first measurement: in the two slow boots of
four, stores to `struct thread` went from 404.5 and 368.3 ns to 4.4 ns at
once, and the rest of each boot ran at the fast mode's pace
(`completion-race` 1125 and 1082 ms against about 2100 slow,
`lockdep-bench` 704 and 706 against 1766); both passed, where every
earlier slow boot timed out. Their `cosmofs-replay`, 36.4 and 35.4 s, is
the 37 s middle mode: the same effect on other objects, which only the
runner's page was rewritten for.

## The change

New kernel code is CeeSafe and no tree's C may grow
(`scripts/cee-share.py --gate`), so the change is a CeeSafe source,
`kernel/memory/bootframes.cee`, holding the physical memory manager's
two walks of the boot memory map:

- `pmm_write_boot_code_frames(lo, hi)` reads and stores back each word
  of every LOADER_RECLAIMABLE frame in `[lo, hi)` through the direct
  map, with volatile accesses (a store of what was just loaded is one a
  C compiler may otherwise drop), counts them, and logs `pmm: N KiB
  where boot-time code ran written in place`. `pmm_init` calls it over
  the bootstrap direct map before `bootmem_init`, so the page array and
  every later allocation land in written frames; `pmm_release_deferred`
  calls it over each deferred run before releasing it.
- `pmm_mark_deferred(limit)` is `pmm.c`'s `mark_deferred`, the other
  walk, moved beside it; it returns the count `pmm.c` moves from its
  reserved pages to its deferred ones.
- `selftest_pmm_boot_code` is the self-test (Proof).

`pmm.c` is 16 lines shorter. No byte of the frames changes: a firmware
may leave a table in boot-services memory that the kernel reads after
`pmm_init` (ACPI is parsed later), and zeroing would destroy it. Only
LOADER_RECLAIMABLE is written: it is where boot-time code ran, and
writing all RAM would cost real machines a pass over every GiB. A form
that also wrote every USABLE frame in debug builds was tried when
AArch64 boots of the branch went slow, and dropped when those proved to
be TEST-29: it went slow as often. Documents:
docs/kernel/memory/design.md §2.5, invariant M52.

## Proof

`pmm-boot-code` (`kernel/memory/bootframes.cee`) counts the
LOADER_RECLAIMABLE frames the direct map reaches from the boot memory
map, on its own, and requires the count of frames written at boot to
equal it and the count to be above zero (the loader's image is one).
`tools/boot-code-frames-probe.py` boots it with and without the fix
commit's `pmm.c` (`--old` reverses that file of the commit in a
throwaway worktree: main's `pmm.c`, which calls no write;
`tools/fixprobe.py`), on the other machine, debug, one CPU, at
`a2b36824`:

| | x86-64 | AArch64 |
|---|---|---|
| `--old` | `pmm-boot-code: 15546 frames where boot-time code ran, 0 written in place at boot`; `pmm-boot-code ... FAIL: check failed: every LOADER_RECLAIMABLE frame in the direct map written in place at boot`, the boot's one failure of 529: `PROBE: PASS` | `11008 frames ..., 0 written`; the same failure, one of 529: `PROBE: PASS` |
| fixed | `pmm: 62176 KiB where boot-time code ran written in place (loader and boot services)`; `15544 frames ..., 15544 written`; `SELFTEST: PASS (529 tests)`, boot PASS in 226.5 s: `PROBE: PASS` | 44028 KiB; 11007 of 11007; PASS in 277.4 s: `PROBE: PASS` |

The behaviour the invariant stands for was measured on the other
machine, 0.50.0's tree with this change and nothing else (`pmm.c`'s
write over all released frames, the first form of the change, which
the final form narrows to LOADER_RECLAIMABLE): six of six four-CPU
x86-64 debug boots fast, `cosmofs-replay` 29.7 to 32.9 s, every
`completion-race` 1088 to 1230 ms and `cosmofs-snap-reserved` 4148 to
4246 ms, none in the middle mode; the same tree without it, six boots
the same hour: two slow, two between, two fast. The final form's
alternated boots are under Validation.

## Validation

On the other machine (the CI image, one container of 4 CPUs and 6 GiB,
ceesafec 0.48.1's Linux build from the tree; `qemu-utils` installed in
each container, which the image predates), 2026-11-16, on `a2b36824`
(the later commit is documents). `matrix: PASS` on both architectures,
every step:

| Step | x86-64 | AArch64 |
|---|---|---|
| debug, release, chaos and harness-retry builds, `make cee-check` | PASS | PASS |
| `make host-test`, `make fuzz` | PASS | PASS |
| `make analyze` | clean (15 baselined, 0 unexpected, 0 stale) | clean (15 baselined, 0 unexpected, 0 stale) |
| debug `make test`, `QEMU_SMP=1` | PASS in 234.5 s | PASS in 275.3 s |
| debug `make test`, `QEMU_SMP=2` | PASS in 239.0 s | PASS in 295.6 s |
| debug `make test`, `QEMU_SMP=4` | PASS in 244.5 s | PASS in 304.3 s |
| `make test-smp2` | PASS in 238.2 s | PASS in 287.2 s |
| `make test-chaos` | PASS in 240.0 s | PASS in 311.2 s |
| `make test-harness-retry` | PASS in 244.8 s | PASS in 303.6 s |
| `make BUILD=release test` | PASS in 18.9 s | PASS in 23.1 s |

An earlier AArch64 matrix of the same commit failed `test-smp2`
(`cosmofs-replay` 50.7 s) and `test-chaos` (`blk-irq-budget`: a
default-priority bystander waited 282 ms against its 250 ms bound); the
first is TEST-29 (below); the second's log was not kept and it is not
attributed.

**Before and after, alternated.** Main `d2392534` and this branch,
x86-64 debug, four CPUs, the same machine, five each in ABBA order (the
last column is `irqrestore-bench`'s main loop):

| boot | main: `cosmofs-replay`, self-tests, verdict, pair | this branch |
|---|---|---|
| 1 | 55287 ms, 257.7 s, FAIL after 304.5 s (timed out), 2343 ns | 30230 ms, 188.0 s, PASS in 246.0 s, 454 ns |
| 2 | 36014 ms, 199.5 s, PASS in 258.0 s, 466 ns | 29567 ms, 184.8 s, PASS in 243.3 s, 463 ns |
| 3 | 36201 ms, 199.7 s, PASS in 258.3 s, 470 ns | 29936 ms, 187.2 s, PASS in 245.1 s, 453 ns |
| 4 | 35246 ms, 198.9 s, PASS in 257.7 s, 459 ns | 29806 ms, 187.9 s, PASS in 243.7 s, 449 ns |
| 5 | 35674 ms, 199.0 s, PASS in 256.9 s, 512 ns | 29999 ms, 186.8 s, PASS in 244.6 s, 471 ns |

Main: one slow boot and four in the middle mode; this branch: five
fast, `cosmofs-replay` 29.6 to 30.2 s, the self-tests within 3.2 s of
each other. No budget was changed.

**AArch64: TEST-29, not this.** AArch64 `test-smp2` boots of the branch
went slow in its forms that wrote more, less or nothing (`cosmofs-replay`
about 51 s against 35), and so did main: two of three on 2026-11-16.
Sampled every 20 ms over QMP, a slow boot's extra time is in `crc32c`,
whose loop only loads: its table's page and the buffer it checksums
share a slot of QEMU's software TLB while QEMU has sized it at 256
entries or fewer. The branch with `.rodata` one page later, putting the
table in another slot, booted fast eight times of eight. Recorded in
flakes.md and as backlog TEST-29; not changed here.

## Limits

- QEMU's behaviour is the cause's other half. On hardware these frames
  are ordinary memory; the change costs one pass over them (61 MiB on
  the x86-64 test machine, 43 MiB on AArch64's `virt`).
- A frame of another type where firmware code once ran (memory a driver
  freed back to EfiConventionalMemory) is not written. None was found
  slow here.
- Under 0.47.1 and later every x86-64 debug boot, fast or not, pays
  about 20% more per save/restore pair (445 to 552 ns against 357 to
  445 under 0.37.0) on every CPU. Not explained; the fix leaves it.
- No AArch64 boot has shown TEST-28's slow mode; its slow boots are
  TEST-29's. A diagnostic scan (not kept) timing a same-value store to
  the first words of every RAM frame, in three AArch64 boots of the
  dropped wider form just before `cosmofs-replay`, found 27 to 29 slow
  frames of 61,745: LOADER_RECLAIMABLE ones, the listed ones allocated
  and the same in every boot, their contents not identified, and at
  most one USABLE frame.
