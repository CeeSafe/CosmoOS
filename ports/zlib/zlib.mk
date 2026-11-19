# zlib, built for the architecture in hand (roadmap 1.3 R3; ports/zlib/README.md):
# a static library and its headers, linked into the ports that need it (curl,
# git, OpenSSH). It is not a package of its own. Static against the musl sysroot
# the BusyBox port builds, through its cc wrapper, as dropbear is. The source
# archive is pinned by version and SHA-256 (zlib.net's published value) and
# fetched once into $(PORTS_CACHE) through scripts/fetch-pinned.py.

ZLIB_VERSION := 1.4
ZLIB_SHA256  := 02dd159783677a749c04adbdd02b55b8a2bcc7e054f51b76b549199a916ad584
ZLIB_URL     := https://zlib.net/zlib-$(ZLIB_VERSION).tar.gz
ZLIB_TAR     := $(PORTS_CACHE)/zlib-$(ZLIB_VERSION).tar.gz

# One build per architecture beside $(OUT), shared by the build variants as
# BusyBox's is. ZLIB_PREFIX holds include/ and lib/ for the ports that link it.
ZLIB_DIR    ?= $(dir $(OUT))zlib-$(ARCH)
ZLIB_PREFIX := $(ZLIB_DIR)/prefix
ZLIB_A      := $(ZLIB_PREFIX)/lib/libz.a

$(ZLIB_TAR):
	$(Q)$(PYTHON) $(ROOT)/scripts/fetch-pinned.py $@ $(ZLIB_SHA256) $(ZLIB_URL) $(PINNED_MIRROR)/$(notdir $(ZLIB_TAR))

# zlib's own configure (not autoconf): --static builds libz.a alone. CHOST
# names the target so it picks the cross tools it is given.
# -ffile-prefix-map keeps the build directory out of the objects (make
# reproducible).
$(ZLIB_A): $(ZLIB_TAR) $(BB_LIBC) $(BB_BUILTINS) $(BB_CC) $(ROOT)/ports/zlib/zlib.mk
	$(call log,ZLIB,$(ZLIB_VERSION) $(BB_TARGET))
	$(Q)rm -rf $(ZLIB_DIR)/src $(ZLIB_PREFIX)
	$(Q)mkdir -p $(ZLIB_DIR)/src
	$(Q)tar -xzf $(ZLIB_TAR) -C $(ZLIB_DIR)/src --strip-components=1
	$(Q)cd $(ZLIB_DIR)/src && CHOST=$(BB_TARGET) CC=$(BB_CC) AR="$(AR)" RANLIB="$(AR) s" \
		CFLAGS="-O2 -ffile-prefix-map=$(ZLIB_DIR)=zlib" ./configure --static --prefix=$(ZLIB_PREFIX) \
		> $(ZLIB_DIR)/configure.log 2>&1 || { tail -40 $(ZLIB_DIR)/configure.log; exit 1; }
	$(Q)$(MAKE) -s -C $(ZLIB_DIR)/src libz.a AR="$(AR)" ARFLAGS=rcD RANLIB="$(AR) s" > $(ZLIB_DIR)/build.log 2>&1 \
		|| { tail -40 $(ZLIB_DIR)/build.log; exit 1; }
	$(Q)mkdir -p $(ZLIB_PREFIX)/include $(ZLIB_PREFIX)/lib
	$(Q)cp $(ZLIB_DIR)/src/zlib.h $(ZLIB_DIR)/src/zconf.h $(ZLIB_PREFIX)/include/
	$(Q)cp $(ZLIB_DIR)/src/libz.a $@

.PHONY: zlib
zlib: $(ZLIB_A)
