# GNU nano, built for the architecture in hand (roadmap 1.3 R3;
# ports/nano/README.md): the `nano` package. Static against the musl sysroot the
# BusyBox port builds, through its cc wrapper, with ncurses
# (ports/ncurses/ncurses.mk) linked in. The source archive is pinned by version
# and SHA-256 (of the archive whose GPG signature, by Benno Schulenberg's key
# 168E6F4297BFD7A79AFD4496514BBE2EB8E1961F, checked) and fetched once into
# $(PORTS_CACHE) through scripts/fetch-pinned.py.

NANO_VERSION := 9.3
NANO_SHA256  := a9affc52c9596ee0682bcdd4ceb3c0b235eb221d83d733dfd9b0dff45897cb0d
NANO_URL     := https://www.nano-editor.org/dist/v9/nano-$(NANO_VERSION).tar.xz
NANO_TAR     := $(PORTS_CACHE)/nano-$(NANO_VERSION).tar.xz

# One build per architecture beside $(OUT), shared by the build variants as
# BusyBox's is. NANO_STAGE is the install (DESTDIR) the package takes its
# files from (ports/nano/package).
NANO_DIR   ?= $(dir $(OUT))nano-$(ARCH)
NANO_STAGE := $(NANO_DIR)/stage
NANO_ELF   := $(NANO_STAGE)/usr/bin/nano

$(NANO_TAR):
	$(Q)$(PYTHON) $(ROOT)/scripts/fetch-pinned.py $@ $(NANO_SHA256) $(NANO_URL) $(PINNED_MIRROR)/$(notdir $(NANO_TAR))

# configure for the musl target with BusyBox's compiler wrapper (a static
# link). No native language support (no gettext on the system), no libmagic.
# ncurses is found by the flags given, not by pkg-config. The syntax files
# (share/nano/*.nanorc) are installed; /etc/nanorc is the package's
# (ports/nano/nanorc), which includes them. -ffile-prefix-map keeps the build
# directory out of the binary (make reproducible).
$(NANO_ELF): $(NANO_TAR) $(NCURSES_A) $(ROOT)/ports/nano/include/linux/vt.h $(ROOT)/ports/nano/nanorc $(BB_LIBC) $(BB_BUILTINS) $(BB_CC) $(ROOT)/ports/nano/nano.mk
	$(call log,NANO,$(NANO_VERSION) $(BB_TARGET))
	$(Q)rm -rf $(NANO_DIR)/src $(NANO_STAGE)
	$(Q)mkdir -p $(NANO_DIR)/src
	$(Q)tar -xJf $(NANO_TAR) -C $(NANO_DIR)/src --strip-components=1
	$(Q)cd $(NANO_DIR)/src && ./configure --host=$(BB_TARGET) --build=$$(./config.guess) \
		CC=$(BB_CC) AR="$(AR)" RANLIB="$(AR) s" CFLAGS="-O2 -ffile-prefix-map=$(NANO_DIR)=nano" \
		NCURSESW_CFLAGS="-I$(NCURSES_PREFIX)/include/ncursesw" NCURSESW_LIBS="$(NCURSES_A)" \
		CPPFLAGS="-I$(NCURSES_PREFIX)/include -I$(ROOT)/ports/nano/include" LDFLAGS="-L$(NCURSES_PREFIX)/lib" PKG_CONFIG=false \
		--prefix=/usr --sysconfdir=/etc --disable-nls --disable-libmagic --enable-utf8 \
		> $(NANO_DIR)/configure.log 2>&1 || { tail -40 $(NANO_DIR)/configure.log; exit 1; }
	$(Q)$(MAKE) -s -C $(NANO_DIR)/src > $(NANO_DIR)/build.log 2>&1 || { tail -40 $(NANO_DIR)/build.log; exit 1; }
	$(Q)$(MAKE) -s -C $(NANO_DIR)/src/src install-exec DESTDIR=$(NANO_STAGE) > /dev/null
	$(Q)$(MAKE) -s -C $(NANO_DIR)/src/syntax install DESTDIR=$(NANO_STAGE) > /dev/null
	$(Q)mkdir -p $(NANO_STAGE)/etc
	$(Q)cp $(ROOT)/ports/nano/nanorc $(NANO_STAGE)/etc/nanorc
	$(Q)$(OBJCOPY) --strip-all --remove-section=.note --remove-section=.comment $@

.PHONY: nano
nano: $(NANO_ELF)

# The package (pkg/pkg.mk's server-ports): its file and the stage it reads.
SERVER_PACKAGES     += $(ROOT)/ports/nano/package=$(NANO_STAGE)
SERVER_PACKAGE_DEPS += $(NANO_ELF) $(ROOT)/ports/nano/package
