# ports/curl

curl, the `curl` package (roadmap 1.3 R3; `docs/pkg/design.md`,
"Cross-built ports"): `pkg install curl` on an installed system. Its
static library, libcurl, is also what git's HTTPS transport links
(`ports/git/`).

| Source | Version | SHA-256 |
|---|---|---|
| curl | 8.23.0 (`curl-8.23.0.tar.xz`) | `8dadd7d2536a314f982ad05a651b713f426bf7d02cc2c76cffb9796f2218e6c5` (of the archive whose detached signature, `curl-8.23.0.tar.xz.asc`, verified with Daniel Stenberg's key `27EDEAF22F3ABCEB50DB9A125CC908FDB71E12C2`, the key his own page, daniel.haxx.se/address.html, names; 2026-11-19) |

`scripts/fetch-pinned.py` fetches it once into `$(PORTS_CACHE)` from
curl.se, then the copy in this repository's `pinned-sources` release,
checking the digest whichever served it (`ports/busybox/README.md`).

## The build (`curl.mk`)

`configure --host=<arch>-linux-musl --disable-shared --enable-static`
through BusyBox's `cc` wrapper (a static link):

- **TLS by mbedTLS** (`ports/mbedtls/`): the same library, built with the
  same configuration, that `wget`'s `ssl_client` and `cosmo-fetch` use.
  curl is compiled against its headers with `MBEDTLS_USER_CONFIG_FILE`
  set to `cosmo_config.h`, so curl and the library agree on what is
  configured. `--with-mbedtls` takes a prefix (`include/` and `lib/`),
  so the mbedTLS port's headers and archives are copied into one,
  `out/curl-ARCH/mbedtls/`.
- **Entropy.** That configuration takes its entropy from
  `mbedtls_hardware_poll`, which the program supplies. That function is
  `ports/mbedtls/entropy.c` (getrandom), the one `ssl_client` and
  `cosmo-fetch` link, built here as `libcosmo_entropy.a`.
- **The certificate authorities** are the system's bundle,
  `/etc/ssl/certs/ca-certificates.crt` (`--with-ca-bundle`, no CA path),
  the one `wget` and `pkg` use.
- **zlib** (`ports/zlib/`) for compressed transfers.
- **Off:** everything else that would need another library (HTTP/2 and
  HTTP/3, IDN, the public suffix list, brotli, zstd, libssh, GSS-API),
  and the protocols a server's curl does not need (LDAP, RTSP, DICT,
  TELNET, TFTP, POP3, IMAP, SMTP, GOPHER, MQTT, SMB). HTTP, HTTPS, FTP,
  FTPS and FILE remain. The manual is not built.

`make install` of the program into a stage, `out/curl-ARCH/stage/`; the
program is stripped. `libcurl.a` and `include/curl/` are copied to
`$(CURL_PREFIX)` (`out/curl-ARCH/prefix/`) for git. `-ffile-prefix-map`
keeps the build directory out of the binary (`make reproducible`).

## The package (`package`)

`/usr/bin/curl`, mode 0755.
