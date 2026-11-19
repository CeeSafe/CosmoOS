# ports/zlib

zlib, the compression library curl, git and OpenSSH link (roadmap 1.3 R3;
`docs/pkg/design.md`, "Cross-built ports"). It is linked into those ports
statically and is not a package of its own.

| Source | Version | SHA-256 |
|---|---|---|
| zlib | 1.4 (`zlib-1.4.tar.gz`) | `02dd159783677a749c04adbdd02b55b8a2bcc7e054f51b76b549199a916ad584` (zlib.net's published value) |

`scripts/fetch-pinned.py` fetches it once into `$(PORTS_CACHE)` from
zlib.net, then the copy in this repository's `pinned-sources` release,
checking the digest whichever served it (`ports/busybox/README.md`).

## The build (`zlib.mk`)

zlib's own `configure` (not autoconf) with `--static` and `CHOST` set to
`<arch>-linux-musl`, through BusyBox's `cc` wrapper (the musl sysroot and
compiler-rt builtins: `ports/busybox/README.md`), then `make libz.a`
alone. `zlib.h`, `zconf.h` and `libz.a` are copied to
`$(ZLIB_PREFIX)` (`out/zlib-ARCH/prefix/`) for the ports that link it.
`-ffile-prefix-map` keeps the build directory out of the objects (`make
reproducible`).
