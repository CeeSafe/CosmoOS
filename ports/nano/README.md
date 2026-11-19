# ports/nano

GNU nano, the `nano` package (roadmap 1.3 R3; `docs/pkg/design.md`,
"Cross-built ports"): `pkg install nano` on an installed system.

| Source | Version | SHA-256 |
|---|---|---|
| GNU nano | 9.3 (`nano-9.3.tar.xz`) | `a9affc52c9596ee0682bcdd4ceb3c0b235eb221d83d733dfd9b0dff45897cb0d` (of the archive whose detached signature, `nano-9.3.tar.xz.asc`, verified with Benno Schulenberg's key `168E6F4297BFD7A79AFD4496514BBE2EB8E1961F`, 2026-11-19) |

`scripts/fetch-pinned.py` fetches it once into `$(PORTS_CACHE)` from
nano-editor.org, then the copy in this repository's `pinned-sources`
release, checking the digest whichever served it
(`ports/busybox/README.md`).

## The build (`nano.mk`)

`configure --host=<arch>-linux-musl --disable-nls --disable-libmagic
--enable-utf8` through BusyBox's `cc` wrapper (a static link), with
ncurses (`ports/ncurses/`) given by its flags rather than found by
pkg-config. Then `make`, and `make install` of the program and the syntax
files into a stage, `out/nano-ARCH/stage/`. The program is stripped.
`-ffile-prefix-map` keeps the build directory out of the binary (`make
reproducible`).

nano includes `<sys/vt.h>` on Linux to ask whether its output is a
virtual console (`VT_GETSTATE`). musl's `<sys/vt.h>` includes
`<linux/vt.h>`, and the BusyBox port's sysroot carries no Linux kernel
headers. `include/linux/vt.h` here supplies the one constant and the one
structure nano uses, with Linux's user-space values. CosmoOS has no
virtual consoles, so the ioctl fails and nano treats its terminal as an
ordinary terminal.

## The package (`package`)

- `/usr/bin/nano`, mode 0755. `rnano`, a symbolic link in the stage, is
  not packaged: packages carry regular files only.
- `/usr/share/nano/` (the syntax files), mode 0644.
- `/etc/nanorc`, mode 0644 (this directory's `nanorc`): it includes the
  syntax files. The package owns it and an upgrade replaces it. `pkg` has
  no notion of a configuration file, so your own settings go in
  `~/.nanorc`.

The terminal must be one of the three ncurses knows (`ports/ncurses/`):
`xterm-256color`, `vt100` or `linux`. With any other `TERM`, nano says
`Error opening terminal` and exits.
