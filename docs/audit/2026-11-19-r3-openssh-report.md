# R3, second PR: OpenSSH's clients and sshd as packages (2026-11-19)

Roadmap 1.3 R3 ("The software a server needs, as packages"), the second
of three PRs. The design note is `docs/pkg/design.md`, "Cross-built
ports", "sshd in place of dropbear". The owner chose that the
openssh-server package takes port 22 over from dropbear, with the base
system unchanged.

## Scope and baseline

The first PR (#535) made cross-built ports into a repository of their own
and packaged nano, curl and git. OpenSSH was in the base system only as
`sftp-server`, the `sftp` subsystem dropbear runs. The base is the first
PR's head; the branch was rebased onto main at `09dc35a1`
(#535's merge) before it opened.

## What changed

- **`ports/openssh/openssh.mk`** gains a second build of the pinned
  OpenSSH 10.6p1 in a directory of its own (`out/openssh-pkg-ARCH/`), so
  the base system's `sftp-server` is unchanged. It is built with zlib and
  still without OpenSSL, with the privilege separation user `sshd` and
  `/var/empty`. The programs are stripped into a stage.
- **`openssh-client`:** `/usr/bin/ssh`, `scp`, `sftp`, `ssh-keygen`,
  `ssh-keyscan`, `ssh-agent`, `ssh-add`.
- **`openssh-server`** depends on `openssh-client = 10.6`. It holds:
  - `/usr/sbin/sshd`, `/usr/libexec/sshd-session`, `sshd-auth`;
  - `/etc/ssh/sshd_config`: keys only, root by key, no forwarding, no login records,
    and the base system's `sftp-server` as the `sftp` subsystem;
  - `/etc/svc/sshd`, which is `after dropbear`, and its start script
    `/etc/ssh/start`.
- **The start script.** pkg runs no scripts, so the script does what an
  install would, once: it adds the `sshd` user and group (74), makes
  `/var/empty`, and makes the Ed25519 host key. Then it runs `svc stop
  dropbear` and execs `sshd -D -e`.
- **`Makefile`.** `ports/zlib/zlib.mk` is included before
  `ports/openssh/openssh.mk`, whose rule names zlib's library (make
  expands a rule's prerequisites as it reads it).
- **`make test-ports`, step s.**
  - Before: port 22 answers with dropbear's banner.
  - `pkg install openssh-server` also installs `openssh-client`, its
    dependency.
  - After `svc start sshd`, port 22 answers with OpenSSH 10.6's banner.
  - From the host: a key login as root, and `scp` of 200000 random bytes
    there and back, byte for byte.
  - On the target: its own `ssh-keygen`, and its own `ssh` to its sshd.
  - The ports' programs, sshd's included, made no unimplemented call.

## Found

- **`/bin/scp`.** It is dropbear's, and `/bin` precedes `/usr/bin` in
  the PATH. As a client it runs `/usr/bin/dbclient`, which the base
  system does not ship, so a bare `scp` on the target fails whether or
  not this package is installed (backlog USR-12). OpenSSH's is
  `/usr/bin/scp`.
- **`scp` over loopback.** OpenSSH's `scp` from the target to its own
  sshd stalls at 0%: `sftp-server` starts and exits with status 0, and
  the client waits on. The same server copied the same file both ways
  with the host (backlog NET-25, not reduced). The test does not run
  `scp` on the target. Its acceptance is the host's `scp` both ways.
- **Socket options.** `ssh` and `sshd` print `setsockopt ... IP_TOS ...:
  Protocol not available`, and scp's `ssh` the same for `SO_KEEPALIVE`.
  The Linux personality refuses every socket option (LX-8), and both
  carry on.

## Validation

`make SELFTEST=0 test-ports` on this machine, on `8eaa62d5` (before the rebase), with nano,
curl and git as in the first PR:

| | x86-64 | AArch64 |
|---|---|---|
| s. banner before / after | `SSH-2.0-dropbear_2026.94` / `SSH-2.0-OpenSSH_10.6` | the same |
| s. key login, scp there and back | 1.6 s to the login; the file byte for byte | 1.0 s; the same |
| s. the target's ssh-keygen and ssh | ran | ran |
| z. missing calls | the probe's only, from the ports | the same |
| verdict | PASS | PASS |

`make matrix` on `ddab15b4` (this PR's code and report before the
rebase, stacked on #535 without its review fix), on the other machine,
in the CI image with the pinned ceesafec 0.57.1 and a fresh `out/`, one
architecture after the other. The rebase brought only #535's change to
`tools/pkgbuild.py` and its host test, which no boot runs.

| step | x86-64 | AArch64 |
|---|---|---|
| builds (debug, release, chaos, hbreak), `cee-check` | PASS | PASS |
| `host-test`, `fuzz` | PASS | PASS |
| `analyze` | clean, 15 baselined | clean, 15 baselined |
| debug `test`, `QEMU_SMP=1` / `2` / `4` | 227.4 / 238.9 / 248.3 s | 277.0 / 284.6 / 307.0 s |
| `test-smp2`, `test-chaos`, `test-harness-retry` | 240.2 / 241.7 / 247.3 s | 285.0 / 306.4 / 302.4 s |
| release `test` | 19.0 s | 23.5 s |

The review's one finding (Codex, P2): `sshd_config` left TCP, agent and
stream-local forwarding at OpenSSH's defaults, which allow them, where
dropbear here is built with none (`ports/dropbear/localoptions.h`). It
now sets `DisableForwarding yes` and `PermitTunnel no`. Step s runs
`ssh -W 127.0.0.1:22` from the host through sshd and expects it refused.
`make SELFTEST=0 test-ports` on the other machine, in the CI image:

| | x86-64 | AArch64 |
|---|---|---|
| the old `sshd_config` | FAIL: the forward stayed open and brought back `SSH-2.0-OpenSSH_10.6` | the same |
| the fix | PASS, `ssh -W refused` | the same |

The change is to a packaged file and to `ports_test.py`, which no matrix
step runs, so the matrix above stands.

Branch CI: PENDING.

## Limits

- The service keeps the supervisor's privileges: sshd needs `chroot` for
  its privilege separation, and the start script writes `/etc/passwd` the
  first time.
- `pkg remove openssh-server` leaves the `sshd` user and the host key.
  dropbear serves again from the next boot or `svc start dropbear`.
- `sshd_config` belongs to the package, and an upgrade replaces it.
- RSA and ECDSA keys cannot be used: the build has no OpenSSL.
