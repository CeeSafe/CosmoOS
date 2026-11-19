# R3, first PR: cross-built ports as packages; nano, curl and git (2026-11-19)

Roadmap 1.3 R3 ("The software a server needs, as packages"), the first
of three PRs. The design note is `docs/pkg/design.md`, "Cross-built
ports". The owner chose two things before it was written:
- the ports are a repository of their own, outside the boot archive;
- the openssh-server package takes port 22 over from dropbear (the
  second PR).

## Scope and baseline

Before this PR the only programs in the package repository were the
recipes compiled with the native toolchain (`hello`, `fortune`, the
resolver's demos) and `busybox-dyn`. Everything cross-built from upstream
source (BusyBox, dropbear, `sftp-server`, mbedTLS's two programs, tcc)
went into the boot archive. There was no nano, curl, git, zlib or
ncurses. The base is main at `31f25fc6` (#534).

The plan is three PRs:
1. this one: the pipeline, and nano, curl and git;
2. OpenSSH (`ssh`, `scp`, `sftp`, `ssh-keygen`, and `sshd` in dropbear's
   place);
3. publication (the release set and the Pages repository), the report
   and the tick.

## What changed

- **The packaging path.** `tools/pkgbuild.py pack --package FILE --root
  STAGE` reads a cross-built port's `package` file:
  - `name`, `version`, `summary`, and `depends` (repeatable);
  - `file: PATH MODE`, where `PATH` ending in `/` takes every regular file
    under it.

  It packs those paths from the port's staged install, and with `--out`
  a directory it names the file `NAME-VERSION.cpk`. The archive is the
  one `build` writes. `pack`'s command-line form is unchanged.
- **The ports repository.** `make server-ports` packs every
  `SERVER_PACKAGES` entry into `$(OUT)/pkg/server` and indexes it, signed
  with the package key. It is not in the boot archive.
- **The ports.** Each is built statically against the BusyBox port's musl
  sysroot through its `cc` wrapper, from an archive pinned by SHA-256.
  Each digest was checked against upstream's own: zlib.net's published
  value; GPG signatures for ncurses, nano and curl; kernel.org's list and
  Junio C Hamano's signature for git. The READMEs name the keys.

  | Port | Version | Package | Notes |
  |---|---|---|---|
  | zlib | 1.4 | none (linked in) | |
  | ncurses | 6.6 | none (linked in) | `xterm-256color`, `vt100` and `linux` compiled in; no terminfo tree |
  | nano | 9.3 | `nano`, 46 files | `ports/nano/include/linux/vt.h`: the one constant and struct nano's `<sys/vt.h>` needs |
  | curl | 8.23.0 | `curl` | mbedTLS with the system's configuration and CA bundle; zlib |
  | git | 2.56.1 | `git`, about 15 MiB | libcurl; no Rust, Perl, Python, gettext or file-system monitor; `git-remote-https` a copy |

- **mbedTLS's entropy source.** `mbedtls_hardware_poll` moved from
  `tls_common.c` to `ports/mbedtls/entropy.c`. It is linked by
  `ssl_client`, `cosmo-fetch`, the host test's `cosmo-fetch`, and curl
  (as `libcosmo_entropy.a`). The function itself is unchanged.
- **The Linux personality's line for a missing call** now names the
  process: `linux: pid N (NAME): unimplemented system call NR`
  (`compat/linux/lxhooks.cee`, still DEBUG). Raising it to INFO was
  tried and reverted: the base system already makes two such calls, and
  at INFO their lines would land on every serial console in the middle of
  other tests' output.
- **`build/config.mk`.** A build whose `SELFTEST` is not its `BUILD`'s
  default gets its own tree (`out/ARCH-debug-noselftest`,
  `out/ARCH-release-selftest`). The objects do not record the flag, so
  the two variants would otherwise share stale objects.
- **`make test-ports`** (`tests/boot/ports_test.py`; CI job `ports`,
  both architectures, `SELFTEST=0`). Its steps are in
  `docs/pkg/testing.md`, "test-ports".

## Found

Step z lists unimplemented calls the base system's programs make on
both architectures. None of the ports' programs made one.

| Process | Call | x86-64 | AArch64 | Backlog |
|---|---|---|---|---|
| `cat` | `sendfile` | 40 | 71 | LX-26 |
| `dropbear` | `execveat` | 322 | 281 | LX-27 |

Neither breaks its program. git is built without its inotify monitor,
and nothing else asked for inotify (LX-28). `setsockopt` refuses every
option (LX-8): curl and git set `TCP_NODELAY` and keep-alive and carry
on without them.

## The harness's own fixes along the way

- **nano's Enter.** A host pty's line ends in LF, which nano reads as ^J
  (Justify), so the save prompt never got its Enter. `pty_keys` types
  raw keys, with Enter as CR.
- **A lost command.** In one run the command typed after ^X was lost,
  because nano had not given the terminal back yet. Each step now waits
  only for output that arrives after its keys, and ^X waits for the
  shell's prompt.
- **One deadline per command.** The boot's single deadline would not
  cover its commands. On a loaded host `pkg install git` took 146 s on
  x86-64, and on a quiet one 54 s on AArch64, so each command has 360 s
  of its own (`Boot.per_command`).
- **Step z cannot pass vacuously.** A probe compiled on the target by
  `tcc` calls `inotify_init1`, and its line must be in the log. On a
  release kernel the line is never logged, and the probe makes the test
  fail with that reason.

## Validation

`make SELFTEST=0 test-ports` on this machine, on `46d2918c`:

| | x86-64 | AArch64 |
|---|---|---|
| a. nano installed | 46 files | 46 files |
| c. curl | the served file byte for byte; another CA's certificate exit 60, no request | the same |
| g. git | clone (2 commits), a third commit, fsck clean | the same |
| b. nano under ssh -tt | the title bar; `Wrote 2 lines`; the file read back | the same |
| z. missing calls | the probe's only, from the ports | the same |
| verdict | PASS | PASS |

`make matrix` on `46d2918c` (the code of this PR; the report and history
entry came after), on the other machine, in the CI image with the pinned
ceesafec 0.57.1 and a fresh `out/`, one architecture after the other:

| step | x86-64 | AArch64 |
|---|---|---|
| builds (debug, release, chaos, hbreak), `cee-check` | PASS | PASS |
| `host-test`, `fuzz` | PASS | PASS |
| `analyze` | clean, 15 baselined | clean, 15 baselined |
| debug `test`, `QEMU_SMP=1` / `2` / `4` | 227.9 / 243.0 / 246.3 s | 273.8 / 282.4 / 302.6 s |
| `test-smp2`, `test-chaos`, `test-harness-retry` | 244.3 / 241.6 / 246.0 s | 289.2 / 308.9 / 300.3 s |
| release `test` | 18.9 s | 23.4 s |

Branch CI: PENDING.

## Limits

- The repository is built (`make server-ports`), but no release carries
  it and the published Pages repository does not hold its packages yet.
  That is the third PR, which is why the roadmap box is not ticked.
- Packages carry regular files only. nano's `rnano`, a symbolic link,
  is left out, and git's `git-remote-https` is a 4 MiB copy.
- `pkg` has no configuration files: an upgrade of nano replaces
  `/etc/nanorc`.
- ncurses knows three terminals. With any other `TERM`, nano says
  `Error opening terminal`.
