# ceesafec 0.48.1 to 0.57.1, 2026-11-16

The owner asked for the pin to move to 0.57.1 (published 2026-11-16 11:20
UTC), the release the Mac's `~/.ceesafe/bin/ceesafec` had become.

## Scope and baseline

Branch `ceesafec-0.57.1` from main at `48474fff` (#528's merge). In
scope: the pin and the places that name it. No `.cee` source changed: the
tree compiles under 0.57.1 as it stands.

## What changed

The pin, in the six places the last bump (#526) changed:
`scripts/cee-gen.py`'s `CEESAFEC_VERSION`; `ci/Dockerfile`'s version and
the SHA-256 of `ceesafec-linux-x64.tar.gz` (`8508bc45...`, checked against
the release's `SHA256SUMS`, as was the macOS arm64 build's `6857fe8f...`,
the same file as the Mac's installed 0.57.1); the same SHA-256 in
`.github/workflows/ci.yml`; the install lines in `docs/build/ceesafe.md`
and `docs/build/design.md`; and the history line in `docs/roadmap-1.3.md`.
Backlog SEC-15 now says 0.57.1 still emits `native.c`'s `static
CEE_UNUSED char ceeSC_0[] = "native\000"`.

## Proof

| Check | Result |
|---|---|
| `make cee-check` (every `.cee` source, and the negative sources) on the Mac | PASS on `48474fff` with 0.57.1: `1 negative source(s) refused as their annotations say` |
| The same on #528's branch before its merge | PASS |
| x86-64 and AArch64 kernels, release and debug, built with each compiler | every object (341 on x86-64, 342 on AArch64) the same disassembly and `.rodata`/`.data` under both |
| Release kernels' `.text` / `.rodata` / `.data` / `.bss` (bytes) | x86-64 1307104 / 89792 / 40100 / 840176, AArch64 1151920 / 83716 / 40008 / 813544, under both |

The kernels differ in one string: the 0.57.1 builds were made before the
pin was committed, so their build id is `v1.1.1-36-g48474fff-dirty`
(`kernel/core/main.o`, `procfs.o`, `sysctl.o`, `lxsys.o`'s
`.rodata.str1.1`, six bytes each), which made the debug kernels' `.rodata`
16 bytes larger. Nothing the compiler emits for the kernel changed.

Of the 198 generated files, all but three differ only in their first
comment. The three: `kernel/include/ceesafe/rt.h` declares the hosted
runtime's `ceesafe_rt_windowed`, `ceesafe_window_app_start` and
`ceesafe_clock_local_offset`; `kernel/ceesafe/kcore_test.c` emits one
`Result` type earlier in the file; `kernel/ceesafe/ceesafe_rt_async.c`
adds Windows high-resolution timers, a hosted wake fast path under `#if
!defined(CEE_FREESTANDING)` and a counter the kernel's build leaves
unused. The objects above are the check that none reaches the kernel.

## Validation

On the other machine (the CI image, one container of 4 CPUs and 6 GiB,
with 0.57.1's Linux build from the tree and `qemu-utils` installed in the
container: Limits), 2026-11-16, both architectures one after the other,
on `897c2897`: `matrix: PASS` on both. A first run stopped at
`host-test` on both for want of `qemu-img` in that image
(`FAIL: qemu-img on PATH`), before any boot; the run below installed it
in the container, as #528's did.

| Step | x86-64 | AArch64 |
|---|---|---|
| debug, release, chaos and harness-retry builds, `make cee-check` | PASS | PASS |
| `make host-test`, `make fuzz` | PASS | PASS |
| `make analyze` | clean (15 baselined, 0 unexpected, 0 stale) | clean (15 baselined, 0 unexpected, 0 stale) |
| debug `make test`, `QEMU_SMP=1` | PASS in 228.0 s | PASS in 278.9 s |
| debug `make test`, `QEMU_SMP=2` | PASS in 237.7 s | PASS in 289.3 s |
| debug `make test`, `QEMU_SMP=4` | PASS in 245.4 s | PASS in 314.9 s |
| `make test-smp2` | PASS in 242.8 s | PASS in 285.1 s |
| `make test-chaos` | PASS in 241.7 s | PASS in 307.3 s |
| `make test-harness-retry` | PASS in 244.5 s | PASS in 303.5 s |
| `make BUILD=release test` | PASS in 18.9 s | PASS in 23.2 s |

The kernel code being 0.48.1's (Proof), no alternated boots were run. No
budget was changed.

## Limits

- The Linux host's container image has 0.37.0 built in and predates
  `qemu-utils`; the matrix there ran 0.57.1's Linux build from the tree
  (`CEESAFEC=`), checked against the release's SHA-256, and installed
  `qemu-utils` in the throwaway container, rather than an image rebuilt
  from this `ci/Dockerfile`. CI builds the image from the Dockerfile.
- The object comparison was made on the Mac with Apple clang; the matrix
  and CI build with the CI image's clang.
