# curl, built for the architecture in hand (roadmap 1.3 R3; ports/curl/README.md):
# the `curl` package, and the static libcurl git links (ports/git/). Static
# against the musl sysroot the BusyBox port builds, through its cc wrapper,
# with mbedTLS (ports/mbedtls/: the same library and configuration wget's
# ssl_client and cosmo-fetch use) and zlib (ports/zlib/) linked in. The source
# archive is pinned by version and SHA-256 (of the archive whose GPG
# signature, by Daniel Stenberg's key 27EDEAF22F3ABCEB50DB9A125CC908FDB71E12C2,
# checked) and fetched once into $(PORTS_CACHE) through scripts/fetch-pinned.py.

CURL_VERSION := 8.23.0
CURL_SHA256  := 8dadd7d2536a314f982ad05a651b713f426bf7d02cc2c76cffb9796f2218e6c5
CURL_URL     := https://curl.se/download/curl-$(CURL_VERSION).tar.xz
CURL_TAR     := $(PORTS_CACHE)/curl-$(CURL_VERSION).tar.xz

# One build per architecture beside $(OUT), shared by the build variants as
# BusyBox's is. CURL_STAGE is the install (DESTDIR) the package takes its
# files from (ports/curl/package); CURL_PREFIX holds libcurl and its headers
# for git.
CURL_DIR    ?= $(dir $(OUT))curl-$(ARCH)
CURL_STAGE  := $(CURL_DIR)/stage
CURL_PREFIX := $(CURL_DIR)/prefix
CURL_ELF    := $(CURL_STAGE)/usr/bin/curl
LIBCURL_A   := $(CURL_PREFIX)/lib/libcurl.a
# mbedTLS's entropy source, mbedtls_hardware_poll (getrandom), is the
# program's to supply (ports/mbedtls/cosmo_config.h): ports/mbedtls/entropy.c,
# the one ssl_client and cosmo-fetch link, as a library of its own.
CURL_ENTROPY_A := $(CURL_DIR)/lib/libcosmo_entropy.a
# What a program linking libcurl links after it.
CURL_LINK_LIBS := $(LIBCURL_A) $(MBEDTLS_LIBS) $(CURL_ENTROPY_A) $(ZLIB_A)

$(CURL_TAR):
	$(Q)$(PYTHON) $(ROOT)/scripts/fetch-pinned.py $@ $(CURL_SHA256) $(CURL_URL) $(PINNED_MIRROR)/$(notdir $(CURL_TAR))

$(CURL_ENTROPY_A): $(ROOT)/ports/mbedtls/entropy.c $(MBEDTLS_LIBS) $(BB_CC)
	$(Q)mkdir -p $(dir $@)
	$(Q)$(BB_CC) $(MBEDTLS_CFLAGS) -Wall -Wextra -Werror -I$(MBEDTLS_DIR)/src/include -c $< -o $(CURL_DIR)/lib/entropy.o
	$(Q)rm -f $@ && $(AR) rcs $@ $(CURL_DIR)/lib/entropy.o

# configure for the musl target with BusyBox's compiler wrapper (a static
# link). curl's --with-mbedtls names a prefix (include/ and lib/); the
# mbedTLS port leaves its archives in src/library, so they are copied into
# one. TLS by mbedTLS, compiled against its headers with this system's
# configuration (MBEDTLS_USER_CONFIG_FILE), so curl and the library agree on
# it; the certificate authorities are the system's bundle. zlib for
# compressed transfers. Everything else that would need another library is
# off (HTTP/2, IDN, the public suffix list, brotli, zstd, libssh, LDAP), and
# so are the protocols a server's curl does not need. -ffile-prefix-map keeps
# the build directory out of the binary (make reproducible).
$(CURL_ELF) $(LIBCURL_A) &: $(CURL_TAR) $(MBEDTLS_LIBS) $(CURL_ENTROPY_A) $(ZLIB_A) $(BB_LIBC) $(BB_BUILTINS) $(BB_CC) \
		$(ROOT)/ports/curl/curl.mk
	$(call log,CURL,$(CURL_VERSION) $(BB_TARGET))
	$(Q)rm -rf $(CURL_DIR)/src $(CURL_STAGE) $(CURL_PREFIX)
	$(Q)mkdir -p $(CURL_DIR)/src
	$(Q)tar -xJf $(CURL_TAR) -C $(CURL_DIR)/src --strip-components=1
	$(Q)rm -rf $(CURL_DIR)/mbedtls && mkdir -p $(CURL_DIR)/mbedtls/lib
	$(Q)cp -R $(MBEDTLS_DIR)/src/include $(CURL_DIR)/mbedtls/include && cp $(MBEDTLS_LIBS) $(CURL_DIR)/mbedtls/lib/
	$(Q)cd $(CURL_DIR)/src && ./configure --host=$(BB_TARGET) --build=$$(./config.guess) \
		CC=$(BB_CC) AR="$(AR)" RANLIB="$(AR) s" CFLAGS="-O2 -ffile-prefix-map=$(CURL_DIR)=curl" \
		CPPFLAGS="-I$(ROOT)/ports/mbedtls -DMBEDTLS_USER_CONFIG_FILE='<cosmo_config.h>'" \
		LDFLAGS="-L$(CURL_DIR)/lib" LIBS="-lcosmo_entropy" PKG_CONFIG=false \
		--prefix=/usr --disable-shared --enable-static --with-mbedtls=$(CURL_DIR)/mbedtls \
		--with-zlib=$(ZLIB_PREFIX) --with-ca-bundle=/etc/ssl/certs/ca-certificates.crt --without-ca-path \
		--without-libpsl --without-libidn2 --without-nghttp2 --without-nghttp3 --without-ngtcp2 \
		--without-brotli --without-zstd --without-libssh --without-libssh2 --without-librtmp \
		--without-gssapi --disable-ldap --disable-ldaps --disable-rtsp --disable-dict --disable-telnet \
		--disable-tftp --disable-pop3 --disable-imap --disable-smtp --disable-gopher --disable-mqtt \
		--disable-smb --disable-docs --disable-manual --enable-ipv6 \
		> $(CURL_DIR)/configure.log 2>&1 || { tail -40 $(CURL_DIR)/configure.log; exit 1; }
	$(Q)$(MAKE) -s -C $(CURL_DIR)/src > $(CURL_DIR)/build.log 2>&1 || { tail -40 $(CURL_DIR)/build.log; exit 1; }
	$(Q)$(MAKE) -s -C $(CURL_DIR)/src/src install-exec DESTDIR=$(CURL_STAGE) > /dev/null
	$(Q)$(OBJCOPY) --strip-all --remove-section=.note --remove-section=.comment $(CURL_ELF)
	$(Q)mkdir -p $(CURL_PREFIX)/lib $(CURL_PREFIX)/include
	$(Q)cp $(CURL_DIR)/src/lib/.libs/libcurl.a $(LIBCURL_A)
	$(Q)cp -R $(CURL_DIR)/src/include/curl $(CURL_PREFIX)/include/

.PHONY: curl
curl: $(CURL_ELF)

# The package (pkg/pkg.mk's server-ports): its file and the stage it reads.
SERVER_PACKAGES     += $(ROOT)/ports/curl/package=$(CURL_STAGE)
SERVER_PACKAGE_DEPS += $(CURL_ELF) $(ROOT)/ports/curl/package
