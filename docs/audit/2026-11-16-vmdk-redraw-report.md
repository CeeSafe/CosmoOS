# The VMDK's second CID draw, 2026-11-16

A defect of R1's first PR (#525, `scripts/mkvmimages.py`) that turns CI red
at random: the AArch64 release set of #528's run 43827130336 failed with

    mkvmimages: /__w/CosmoOS/CosmoOS/out/repro-a/cosmoos-aarch64.vmdk: the descriptor region holds bytes after its text

in `make ARCH=aarch64 BUILD=release reproducible`. #528 changes no script
or image path, and main's runs since #525 passed. It is fixed here because
it can turn main red (AGENTS.md, scope rules).

## Scope and baseline

Branch `vmdk-redraw` from main at `d2392534`. In scope:
`scripts/mkvmimages.py`, its host test, a probe. No compiled code changes.

## The mechanism

qemu-img draws a VMDK's content id twice. `vmdk_co_do_create`
(QEMU's `block/vmdk.c`, the same in v10.0.0 and master) writes the
embedded descriptor with `CID=%x` of one `g_random_int()`. On the
conversion's first data write, `vmdk_write_cid` draws another and rewrites
the descriptor in place: it reads the whole region (`DESC_SIZE`, 20
sectors), prints the new CID after the first `CID` with `"%x\n"`, appends
the text from `parentCID` on with `pstrcat`, and writes the whole region
back. The new text's NUL lands where it ends; nothing clears what follows.
A second CID k digits shorter than the first ends the text k bytes sooner,
so the first text's last k - 1 bytes stay after the new NUL. They are the
new text's last k - 1 bytes too, since the text after the CID line is
copied unchanged.

`mkvmimages.py` refused any byte after the text's NUL. A one-digit
shrink leaves nothing (the old NUL's place is the only byte uncovered), so
the case needs the second CID two or more digits shorter: about one
conversion in 270 (the first CID eight digits, 15/16; the second six or
fewer, 1/256; the rarer pairs add little).

Measured with Homebrew's `qemu-img` 11.1.3 on the Mac:

- 250 conversions of a 1 MiB random image: 17 ended with a seven-digit
  CID, none left bytes after the text, as a one-digit shrink should not.
- `qemu-img create` then one `qemu-io` write, until the second CID was
  shorter, three times: `3d3fa1ef` -> `37e9887`, `9a690745` -> `d4ca050`,
  `a5c54fa7` -> `35dfa8c`, each text 334 bytes then 333, which shows the
  second draw rewrites the first in place.

The CI image's `qemu-img` could not be tallied on the Linux host: its
local `cosmoos-ci:local` predates #525's `qemu-utils`, and its images are
not rebuilt there.

## The change

`only_stale_tail` in `scripts/mkvmimages.py` accepts after the text's NUL
what the redraw leaves and nothing else: at most six bytes, equal to the
text's last bytes, then zeros to the region's end. The descriptor is still
rewritten whole, the text padded with zeros, so those bytes do not reach
the file and the set stays reproducible.

`tests/host/test_mkvmimages.py` gains:

- `redrawn`, `vmdk_write_cid`'s rewrite step for step on a synthetic
  descriptor: eight digits redrawn as six leaves 1 byte, as one leaves 6,
  and each gives the same file as the other cases;
- refusals of bytes after the NUL that are not the text's end, and of
  seven bytes of the text's end;
- the forcing `qemu-img` wrapper's `FIRST>SECOND`, which sets the first CID
  and then rewrites the second over it as `vmdk_write_cid` does, through
  the real script and `qemu-img`: `fedcba98>1` gives the same VMDK as an
  unforced conversion.

## Proof

`tools/vmdk-redraw-probe.py`; the script is host-side and the same for both
architectures, so the probe takes no ARCH.

- `--old` (main's script at `d2392534`, this tree's test): PASS. The first
  failure is `FAIL: qemu-img's CID fedcba98 redrawn as edcba9, 1 bytes of
  the first text left after the second's end, gives the same file
  (mkvmimages: disk.vmdk: the descriptor region holds bytes after its
  text)`, CI's message; the redraw as one and the `fedcba98>1` conversion
  fail the same way.
- Fixed: PASS, every check of `test_mkvmimages` passes.

## Validation

Exempt from the matrix (AGENTS.md, scope rules): no compiled code, and no
matrix step makes the VMDK. `make host-test` passed on the Mac (114
suites, ceesafec 0.48.1). Branch CI's release-set and install jobs run the
script on both architectures.

## Limits

- The fix accepts what QEMU 10.0 and master's `vmdk_write_cid` leave. A
  qemu-img that left anything else would still be refused.
- The rate is from QEMU's code and the CID's distribution, not a tally of
  CI conversions.
