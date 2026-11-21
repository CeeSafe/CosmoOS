# The project's addresses after the move to CeeSafe (2026-11-21)

The repository moved from `vkuttyp/CosmoOS` to `CeeSafe/CosmoOS` on
2026-11-21, at the owner's request, and its Pages site from
`https://vkuttyp.github.io/CosmoOS/` to `https://ceesafe.github.io/CosmoOS/`.
The old site is kept as a mirror (#543; `docs/development.md`, "The
project's addresses"). This change names the new address everywhere current
and moves the old one out of an installed system's configuration when it
upgrades.

## Scope and baseline

Branch `ceesafe-addresses` from main at `6721eab0` (#543's merge), rebased
on `231d7d2f` (#544, the README). Not a roadmap unit: the owner's move.

## What changed

- **`cosmo-upgrade`** moves the old prefix to the new one in
  `/etc/pkg/repos.conf` and `/etc/cosmo-release.conf`, after bringing the
  root to the release.
  - An upgrade keeps `repos.conf`'s `cosmoos` line, which `cosmo-install`
    wrote, as a file changed on the machine, so a release alone could not
    reach it.
  - The prefixes are the same length, so the text is rewritten in place.
    The file is written beside the old one, synced and renamed over it.
  - It is CeeSafe, as new user code is:
    - `userland/system/upgrade_conf.cee` handles the files, built for
      CosmoOS only: its open flags are the system's, which differ from
      macOS's;
    - `userland/system/upgrade_parts.cee` rewrites the text.
  - `upgrade_parts.cee` also takes the boot archive's ustar number and
    `..`-name check from `cosmo-upgrade.c`, so the program's C shrinks by
    9 lines and `cee-share` passes.
- **`tests/host/test_upgrade_parts.c`** tests the ustar fields, the `..`
  check and the text's rewrite (every occurrence, nothing else changed,
  idempotent, a cut-short prefix left alone).
- **`tests/boot/upgrade_test.py`**, the v1.0.3 path, which upgrades with
  this build's `cosmo-upgrade`:
  - before the upgrade it appends a commented line naming the old address
    to `repos.conf`;
  - the upgrade must say `/etc/pkg/repos.conf: the project's address
    moved to https://ceesafe.github.io/CosmoOS/`;
  - the upgraded system's `repos.conf` must have the new line and no old
    one.
- **The new address** in `cosmo-release.conf`, `cosmo-install`'s
  `repos.conf` line, `cosmo-upgrade`'s default, the CI image's name, the
  scripts, the boot tests and the guides. Only records name the old
  address now: audits, history, past release notes, the mirror's step and
  `development.md`'s account of the move.

## Validation

`make matrix` on `217bf71a` (this branch before the rebase; the rebase
changes only `README.md`, which nothing builds or reads), on the other
machine, in the CI image with the pinned ceesafec 0.57.1:

| step | x86-64 | AArch64 |
|---|---|---|
| builds (debug, release, chaos, hbreak), `cee-check` | PASS | PASS |
| `host-test` (with `test_upgrade_parts`), `fuzz` | PASS | PASS |
| `analyze` | clean, 15 baselined | clean, 15 baselined |
| debug `test`, `QEMU_SMP=1` / `2` / `4` | 229.8 / 244.0 / 247.2 s | 274.8 / 286.0 / 306.5 s |
| `test-smp2`, `test-chaos`, `test-harness-retry` | 245.6 / 247.2 / 246.5 s | 288.2 / 312.3 / 303.8 s |
| release `test` | 18.8 s | 23.3 s |

`make test-upgrade` could not run there: fetching v1.0.3 needs a GitHub
token, which that container does not have. The CI job `upgrade` runs it
on this pull request, on both architectures.

## Limits

- Only the two files are rewritten. A system that names the old address
  anywhere else, by hand, keeps it; the mirror serves it until it is
  retired.
- The mirror's retirement is a later decision: after systems have
  upgraded past the release that carries this.
