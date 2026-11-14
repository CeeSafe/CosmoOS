# ceesafec 0.37.0 to 0.47.1, 2026-11-15

The owner asked for the pin to move to CeeSafe's current release after R1's
first PR (#525) and before R1's ISO PR, whose new kernel code is CeeSafe.
0.47.1 was the latest published release (2026-11-14 22:50 UTC); 352
CeeSafe commits and fifteen releases separate it from 0.37.0.

## Scope and baseline

Branch `ceesafec-0.47.1` from main at `9f466e70`. In scope: the pin and
the places that name it. No `.cee` source changed: the tree compiles
under 0.47.1 as it stands.

## What changed

The pin, in the six places the last bump (`cbbfebb8`, 0.33.0 to 0.37.0)
changed: `scripts/cee-gen.py`'s `CEESAFEC_VERSION`, `ci/Dockerfile`'s
version and the SHA-256 of `ceesafec-linux-x64.tar.gz`
(`74a60d94...`, checked against the release's `SHA256SUMS`), the same
SHA-256 in `.github/workflows/ci.yml`, the install lines in
`docs/build/ceesafe.md` and `docs/build/design.md`, and the history line
in `docs/roadmap-1.3.md`. Backlog SEC-15 says 0.47.1 still emits a C
string a static points to as a writable array (`native.c`'s `static char
ceeSC_0[] = "native\000"`).

## Proof

| Check | Result |
|---|---|
| `make cee-check` (every `.cee` source, and the negative sources) with 0.47.1 on the Mac | PASS: every source compiles; `1 negative source(s) refused as their annotations say` |
| x86-64 release kernel, `.text` / `.rodata` / `.data` / `.bss` (bytes), 0.37.0 against 0.47.1 | 1304592 / 89200 / 40052 / 840176 against 1303184 / 89216 / 40052 / 840176 |

## Validation

FILLED IN WHEN THE MATRIX ENDS.

## Limits

- The Linux host's container image has 0.37.0 built in; the matrix there
  ran 0.47.1's Linux build from the tree (`CEESAFEC=`), checked against
  the release's SHA-256, rather than an image rebuilt from this
  `ci/Dockerfile`. CI builds the image from the Dockerfile.
