# R3, third PR: the ports repository in the release set and the published repository (2026-11-20)

Roadmap 1.3 R3 ("The software a server needs, as packages"), the third
of three PRs. The design note is `docs/pkg/design.md`, "Cross-built
ports".

## Scope and baseline

The first two PRs (#535, #536) built nano, curl, git and OpenSSH's two
packages into a signed repository of their own, `$(OUT)/pkg/server`, which
`make test-ports` serves to an installed system. A release did not
carry it, so `pkg install` from the published repository could not find
them. The base is main at `26334c83` (#536's merge), whose CI passed
(run 44655419063).

## What changed

- **`scripts/mkrelease.py`** takes the ports repository's directory and
  writes `cosmoos-ARCH-ports.tar`: its INDEX and each package the INDEX
  lists, as `pkgbuild.tar_archive` members (no owner, no time). A package
  file the INDEX does not list, or the reverse, stops the set. The tar is
  in `SHA256SUMS`. `make release-set` builds the ports repository first.
- **`scripts/publish-repo.py`**, for a release whose `SHA256SUMS` lists
  the tar:
  - checks the tar's digest with the rest of the set;
  - checks its INDEX's signature against the release key, and each
    package's size and SHA-512 against its stanza;
  - refuses a package name or a file that boot.tar's repository already
    has, and a file the INDEX does not list;
  - publishes one INDEX of both, signed, in (name, version) order.

  A release without the tar is published as before. The weekly re-sign
  works from the site's files, so it keeps the ports.
- **`.github/workflows/repository.yml`** downloads the tar with the set.
- **`scripts/check-release-version.py`** expects the tar in a set.
- **`scripts/check-reproducible.sh`** builds the ports in each of its
  two trees (`ZLIB_DIR`, `NC_DIR`, `NANO_DIR`, `CURL_DIR`, `GIT_DIR_`,
  `OSSH_PKG_DIR`) and compares `pkg/server/INDEX`, which names each
  package's SHA-512.
- **`.github/workflows/ci.yml`**, the release-set job:
  - Its limit is 60 minutes, up from 40, from the times below.
  - Its cache key is the ports test's, every `ports/*/*.mk`, so the new
    archives are cached.
- **`.github/workflows/ci.yml`**, the "build, boot, analyze" job: its
  limit is 60 minutes, up from 45. Its debug `make reproducible` builds the
  ports in each tree too. The build part took 1579 s (x86-64) and 1587 s
  (AArch64) on main (run 44655419063). On this branch it took 2399 s, and
  ran past 2700 s, cancelled in that check (run 44677881609). The ports do
  not depend on BUILD, but sharing one build between the two trees saves
  nothing: their rules depend on each tree's BusyBox libc and mbedTLS.
- **Documents.** `docs/development.md` (the set, the repository's step 6)
  and `docs/guide/packages.md` (`pkg install openssh-server` from a
  release after v1.1.1).

## Validation

`tests/host/test_publish_repo.py` builds signed sets in a temporary
directory, one with a ports tar of nano.
- Passing with the change:
  - the published repository holds hello and nano in one INDEX, signed;
  - nano's digest is the tar's;
  - the release directory has no tar;
  - the weekly re-sign keeps nano.
- Refused:
  - a package whose digest differs from its stanza;
  - an INDEX signed by another key (`ports.tar: INDEX: unknown signing
    key`);
  - a package name boot.tar's repository has;
  - a file the INDEX does not list (`stray.cpk not in its INDEX`);
  - a set whose `SHA256SUMS` names a tar that is not there.
- On main's `publish-repo.py` the test fails 9 checks.

`make BUILD=release reproducible` and then `make release`, as the CI job
runs them, on the other machine in the CI image at four CPUs, with a
git checkout of `5c53f811` and `COSMO_KEYDIR=/tmp/cosmo-ci-keys`:

| | x86-64 | AArch64 |
|---|---|---|
| `reproducible` | yes, `pkg/server/INDEX` the same | the same |
| `cosmoos-ARCH-ports.tar` in `SHA256SUMS` | `c2d88b58…` | `d005c9b0…` |
| both steps | 2499 s | 2575 s |

On CI on main (run 44655419063) the same two steps took 673 s and
830 s without the ports.
- A ports build there is about 7-10 minutes: the ports test's build
  step took 629 s and 416 s, kernel included.
- Three more builds bring the job near its old 40-minute limit.
- release.yml's build jobs make one set each: 261-335 s for v1.1.1, plus
  one ports build, inside their 40 minutes.

`make matrix` on `5c53f811`, on the other machine, in the CI image with
the pinned ceesafec 0.57.1, one architecture after the other. The second
commit changes only `ci.yml` and documents.

| step | x86-64 | AArch64 |
|---|---|---|
| builds (debug, release, chaos, hbreak), `cee-check` | PASS | PASS |
| `host-test`, `fuzz` | PASS | PASS |
| `analyze` | clean, 15 baselined | clean, 15 baselined |
| debug `test`, `QEMU_SMP=1` / `2` / `4` | 227.1 / 240.6 / 245.1 s | 277.6 / 284.8 / 303.7 s |
| `test-smp2`, `test-chaos`, `test-harness-retry` | 236.1 / 241.2 / 244.9 s | 284.9 / 307.7 / 304.4 s |
| release `test` | 18.7 s | 23.3 s |

Each Linux call a port needed and CosmoOS lacked: none. Step z of
`make test-ports` found no unimplemented call from a port in #535 and
#536, on both architectures. LX-26 and LX-27 (`sendfile`, `execveat`)
are made by the base system's BusyBox and dropbear. LX-28 (no inotify)
is the backend git's file-system monitor is built without.
R3's acceptance, `make test-ports`, passes on main (run 44655419063,
"ports test", both architectures), and R3 is ticked.

Branch CI:
- `574e94a8` (run 44677881609): "build, boot, analyze (aarch64, build)"
  was cancelled at its 45-minute limit in the reproducible check, above;
  every other job passed. The release-set jobs took 1426 s and 1490 s.
- `e30af109` (run 44684284236): PASS. The build parts took 2257 s
  (x86-64) and 2132 s (AArch64), and the release-set jobs 2207 s and
  1482 s.

## Limits

- The ports reach the published repository with the next release
  (v1.1.2). v1.1.1's set has no tar.
- A package name in both repositories stops the publish rather than
  choosing one.
