# ports/ncurses

ncurses, the terminal library nano links (roadmap 1.3 R3;
`docs/pkg/design.md`, "Cross-built ports"). It is linked into nano
statically and is not a package of its own.

| Source | Version | SHA-256 |
|---|---|---|
| ncurses | 6.6 (`ncurses-6.6.tar.gz`, from ftp.gnu.org) | `355b4cbbed880b0381a04c46617b7656e362585d52e9cf84a67e2009b749ff11` (of the archive whose detached signature, `ncurses-6.6.tar.gz.sig`, verified with Thomas E. Dickey's key `19882D92DDA4C400C22C0D56CC2AF4472167BE03`, 2026-11-19) |

`scripts/fetch-pinned.py` fetches it once into `$(PORTS_CACHE)` from
ftp.gnu.org, then the copy in this repository's `pinned-sources` release,
checking the digest whichever served it (`ports/busybox/README.md`).

## The build (`ncurses.mk`)

A cross build in two passes over one source tree:

1. **For the build host**, with the host's compiler: ncurses' `tic` and
   `infocmp`, which the second pass runs. Nothing from this pass is
   installed or shipped.
2. **For the target**, through BusyBox's `cc` wrapper: `configure
   --host=<arch>-linux-musl --enable-widec --disable-database
   --with-fallbacks=xterm-256color,vt100,linux`, with no shared library,
   programs, tests, C++, Ada or manual pages, then `make libs`.

There is no terminfo tree on the system. `--disable-database` with
fallbacks compiles those three descriptions into the library
(`ncurses/fallback.c`, made by the first pass's `tic` and `infocmp`), and
any other `TERM` is unknown to a program linked with it. `xterm-256color`
is what an ssh client from macOS, Linux or Windows Terminal sends,
`vt100` the least any terminal does, and `linux` the Linux console's.

`libncursesw.a` and the public headers (`curses.h`, `term.h`,
`termcap.h`, `unctrl.h`, `ncurses_dll.h`, and `ncurses.h` as a link to
`curses.h`) are copied to `$(NCURSES_PREFIX)` (`out/ncurses-ARCH/prefix/`),
both at `include/` and at `include/ncursesw/`. `-ffile-prefix-map` keeps
the build directory out of the objects (`make reproducible`).
