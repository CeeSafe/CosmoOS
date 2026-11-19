# ports/openssh

OpenSSH's `sftp-server` in the base system (the scp-sftp unit,
2026-10-14), and OpenSSH's clients and `sshd` as two packages (roadmap
1.3 R3, "The packages" below).

The base system's ssh server is dropbear (`ports/dropbear/`). It runs
an external program for the `sftp` subsystem and ships none of its own,
and current OpenSSH `scp` clients use that subsystem too. The program is
OpenSSH's because that is the implementation every `sftp` and `scp`
client is written against.

| Source | Version | SHA-256 |
|---|---|---|
| OpenSSH portable | 10.6p1 (`openssh-10.6p1.tar.gz`, released 2026-10-06) | `a9dc9565dffe8640f64d863cd29a32bc4a3dbdec0566a7fc44c5d6ee767d5f39` (the release notes' `SHA256 (openssh-10.6p1.tar.gz) = qdyVZd/+hkD2TYY80poyvEo9vewFZqf8RMXW7nZ9Xzk=`, base64 there) |

`scripts/fetch-pinned.py` fetches it once into `$(PORTS_CACHE)` from
`cdn.openbsd.org`, then the copy in this repository's `pinned-sources`
release, checking the digest whichever served it (`ports/busybox/README.md`).

## The build (`openssh.mk`)

Against the BusyBox port's musl sysroot and compiler-rt builtins, through
its `cc` wrapper (a static link), as dropbear is: `configure
--host=<arch>-linux-musl --without-openssl --without-zlib --without-pam
--without-pie --without-hardening --without-stackprotect`, no login
records, then `make sftp-server` alone, stripped with `llvm-objcopy`.
`sftp-server` needs neither OpenSSL nor zlib; PIE and the hardening
flags are off for the reason dropbear's are (the wrapper's fixed image
base rules out a static-pie). `-ffile-prefix-map` keeps the build
directory out of the binary (`make reproducible`, which builds it in both
trees through `OSSH_DIR`).

## On the system

`/usr/libexec/sftp-server` (mode 0755: the boot archive's `usr/libexec/`
entries keep their path, `kernel-services/vfs/ramfs.c`), copied to the
installed root with the rest of `/usr`. dropbear runs it as the `sftp`
subsystem (`SFTPSERVER_PATH`), through root's shell, in the session's
privileges (`net cred`: see `docs/guide/privileges.md`).

It makes itself undumpable at start (`prctl(PR_SET_DUMPABLE, 0)`) and
refuses to run when it cannot; the Linux door has had that one `prctl`
option since this port (`compat/linux/syscalls.c`, `lx_prctl`).

## The packages (roadmap 1.3 R3)

`openssh-client` and `openssh-server`, from the same source archive, are
built a second time in a directory of their own
(`out/openssh-pkg-ARCH/`), so the base system's `sftp-server` above is
unchanged. `docs/pkg/design.md`, "Cross-built ports", has the design; the
owner chose that `openssh-server` takes port 22 over from dropbear.

**The build.** `configure` with the flags above, plus:
- zlib (`ports/zlib/`) for compression;
- `--with-privsep-user=sshd` and `--with-privsep-path=/var/empty`;
- `/etc/ssh` for the configuration, `/usr/libexec` for `sshd`'s helpers.

It is still `--without-openssl`. OpenSSH's own code provides Ed25519,
ChaCha20-Poly1305, AES-CTR and AES-GCM, and the Curve25519 and ML-KEM
key exchanges. RSA and ECDSA keys are not available, for logins or as
host keys. `make` builds the programs listed below, each stripped into a
stage.

**`openssh-client`:** `/usr/bin/ssh`, `scp`, `sftp`, `ssh-keygen`,
`ssh-keyscan`, `ssh-agent` and `ssh-add`. This `scp` uses the sftp
protocol, as OpenSSH's does by default.

dropbear's `scp` stays at `/bin/scp`, as the classic protocol's remote
end. `/bin` comes before `/usr/bin` in the PATH, so a bare `scp` is
still that one. Run as a client, it fails for want of dropbear's
`dbclient` (backlog USR-12), so run OpenSSH's as `/usr/bin/scp`.

`ssh` and `sshd` print `setsockopt socket N IP_TOS ...: Protocol not
available` (and `scp`'s `ssh`, `SO_KEEPALIVE`) and carry on: the Linux
personality refuses every socket option (backlog LX-8). `scp` between
two ends on the same system, over loopback, stalls (backlog NET-25).

**`openssh-server`** depends on `openssh-client` of the same version, for
`ssh-keygen`. It holds:
- `/usr/sbin/sshd`, `/usr/libexec/sshd-session` and `sshd-auth`;
- `/etc/ssh/sshd_config` (this directory's `sshd_config`): keys only,
  root by key, no forwarding of any kind (as dropbear), no login records,
  and the `sftp` subsystem the base
  system's `/usr/libexec/sftp-server`;
- `/etc/svc/sshd` (`sshd.svc`) and its start script `/etc/ssh/start`
  (`start`).

`pkg` runs no scripts. What an install would do, the start script does
the first time the service starts:
- it adds the `sshd` user and group (74) to `/etc/passwd` and
  `/etc/group` if they are not there, and makes `/var/empty`;
- it makes the Ed25519 host key, `/etc/ssh/ssh_host_ed25519_key`, once,
  as dropbear's start script makes its own.

It then stops dropbear (`svc stop dropbear`) and execs `sshd -D -e`,
which logs to standard error, kept in `/var/log/svc/sshd`.

**Switching.**
- After `pkg install openssh-server`, run `svc start sshd`, or reboot.
  At boot dropbear starts first (`after dropbear`) and sshd then takes
  port 22 from it.
- `pkg remove openssh-server` removes `/etc/svc/sshd`, and dropbear
  serves again from the next boot or `svc start dropbear`. The host key,
  and the `sshd` user, stay.
- The new server has its own host key, so a client that knew dropbear's
  will say the key changed.

**Limits.**
- The service keeps the supervisor's privileges. It has no `privileges`
  line, as dropbear's has: sshd needs `chroot` for its privilege
  separation, and the start script writes `/etc/passwd` the first time.
- `sshd_config` belongs to the package, and an upgrade replaces it.
- Because the service is `after dropbear`, `svc boot` does not start it
  on a system without dropbear's service (the live system).
