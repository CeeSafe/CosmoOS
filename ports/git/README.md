# ports/git

Git, the `git` package (roadmap 1.3 R3; `docs/pkg/design.md`,
"Cross-built ports"): `pkg install git` on an installed system.

| Source | Version | SHA-256 |
|---|---|---|
| Git | 2.56.1 (`git-2.56.1.tar.xz`, kernel.org) | `f0b0bf89264b9bd2e1c640363e7529643989da76281600473c50745cd34a607f` (kernel.org's `sha256sums.asc` lists it; the release's signature, `git-2.56.1.tar.sign` over the uncompressed archive, verified with a subkey, `E1F036B1FEE7221FC778ECEFB0B5E88696AFE6CB`, of Junio C Hamano's key `96E07AF25771955980DAD10020D04E5A713660A7`; 2026-11-19) |

`scripts/fetch-pinned.py` fetches it once into `$(PORTS_CACHE)` from
kernel.org, then the copy in this repository's `pinned-sources` release,
checking the digest whichever served it (`ports/busybox/README.md`).

## The build (`git.mk`)

Git's own Makefile, with no configure step: `uname_S=Linux` and the
architecture name the target. The compiler is BusyBox's `cc` wrapper,
which links statically.

- **HTTP(S)** is libcurl (`ports/curl/`), with mbedTLS and zlib linked
  after it. Its flags are given directly (`CURL_LDFLAGS`) rather than
  read from `curl-config`. HTTPS checks against the system's bundle,
  `/etc/ssl/certs/ca-certificates.crt`, which is curl's.
- **zlib** comes from `ports/zlib/`.
- **Off:**
  - Rust (`NO_RUST`): the parts written in it have C versions until Git 3.0.
  - gettext, Perl, Python and Tcl/Tk.
  - expat, which only pushing over HTTP with WebDAV uses.
  - PCRE.
  - OpenSSL: SHA-1 is git's collision-detecting implementation, SHA-256
    its own.
  - The file-system monitor daemon: Linux's backend is inotify, which
    CosmoOS lacks (backlog LX-28).
- **No dashed built-ins** (`SKIP_DASHED_BUILT_INS`) and no hard links
  (`NO_INSTALL_HARDLINKS`): packages carry regular files.

`make install` writes into a stage, `out/git-ARCH/stage/`. Every ELF
file in it is stripped. `git-remote-https`, which install makes as a
symbolic link, becomes a copy of `git-remote-http`. `-ffile-prefix-map`
keeps the build directory out of the binaries (`make reproducible`).

## The package (`package`)

About 15 MiB:
- `/usr/bin/git`.
- `/usr/libexec/git-core/git-remote-http` and `git-remote-https`, which
  git runs for an `https://` remote.
- The commands git still keeps as shell scripts, and the libraries they
  include: `git-submodule`, `git-mergetool`, `git-filter-branch` and the
  merge strategies, with `git-sh-setup`, `git-sh-i18n` and its
  `envsubst`.
- `/usr/share/git-core/templates/`, which `git init` copies.

Left out:
- The server-side programs: `git-daemon`, `git-http-backend`,
  `git-shell` and `scalar`.
- `git-imap-send`.
- `git-http-fetch`: git's own transport no longer runs it.
- The commands written in Perl or Python (`send-email`, `svn`, `cvs*`,
  `archimport`, `p4`), which this build replaces with stubs saying so.
- `ftp://` and `ftps://` remotes, the other two links install makes.
- The bash completion script: there is no bash.

Git pages its output through `less` (BusyBox's) when the output is a
terminal, as on Linux; `git --no-pager` or `GIT_PAGER=cat` turns that off.
