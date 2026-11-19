# ncurses, built for the architecture in hand (roadmap 1.3 R3;
# ports/ncurses/README.md): the wide-character library nano links. It is not a
# package of its own. Static against the musl sysroot the BusyBox port builds,
# through its cc wrapper. There is no terminfo tree on the system: the
# descriptions of xterm-256color, vt100 and linux are compiled into the
# library (--with-fallbacks), and any other TERM is unknown to it. The source
# archive is pinned by version and SHA-256 (of the archive whose GPG signature,
# by Thomas E. Dickey's key 19882D92DDA4C400C22C0D56CC2AF4472167BE03, checked)
# and fetched once into $(PORTS_CACHE) through scripts/fetch-pinned.py.

NCURSES_VERSION := 6.6
NCURSES_SHA256  := 355b4cbbed880b0381a04c46617b7656e362585d52e9cf84a67e2009b749ff11
NCURSES_URL     := https://ftp.gnu.org/gnu/ncurses/ncurses-$(NCURSES_VERSION).tar.gz
NCURSES_TAR     := $(PORTS_CACHE)/ncurses-$(NCURSES_VERSION).tar.gz
NCURSES_FALLBACKS := xterm-256color,vt100,linux

# One build per architecture beside $(OUT), shared by the build variants as
# BusyBox's is. NCURSES_PREFIX holds include/ and lib/ for the ports that link it.
NC_DIR         ?= $(dir $(OUT))ncurses-$(ARCH)
NCURSES_PREFIX := $(NC_DIR)/prefix
NCURSES_A      := $(NCURSES_PREFIX)/lib/libncursesw.a

$(NCURSES_TAR):
	$(Q)$(PYTHON) $(ROOT)/scripts/fetch-pinned.py $@ $(NCURSES_SHA256) $(NCURSES_URL) \
		$(PINNED_MIRROR)/$(notdir $(NCURSES_TAR))

# A cross build: the tools that generate the fallback descriptions and the
# library's tables run on the build host (BUILD_CC, the host's cc; tic from
# this source, built for the host, compiles the descriptions --with-fallbacks
# names). No programs, tests, C++, Ada, manual pages or shared library; no
# terminfo database (--disable-database). The wide-character library only.
# -ffile-prefix-map keeps the build directory out of the objects (make
# reproducible).
$(NCURSES_A): $(NCURSES_TAR) $(BB_LIBC) $(BB_BUILTINS) $(BB_CC) $(ROOT)/ports/ncurses/ncurses.mk
	$(call log,NCURSES,$(NCURSES_VERSION) $(BB_TARGET))
	$(Q)rm -rf $(NC_DIR)/src $(NC_DIR)/host $(NCURSES_PREFIX)
	$(Q)mkdir -p $(NC_DIR)/src $(NC_DIR)/host
	$(Q)tar -xzf $(NCURSES_TAR) -C $(NC_DIR)/src --strip-components=1
	$(Q)cd $(NC_DIR)/host && $(NC_DIR)/src/configure --without-shared --without-cxx --without-cxx-binding \
		--without-ada --without-tests --without-manpages --without-debug --enable-widec \
		--prefix=$(NC_DIR)/host/install > $(NC_DIR)/host-configure.log 2>&1 \
		|| { tail -40 $(NC_DIR)/host-configure.log; exit 1; }
	$(Q)$(MAKE) -s -C $(NC_DIR)/host/include > $(NC_DIR)/host-build.log 2>&1 \
		&& $(MAKE) -s -C $(NC_DIR)/host/ncurses >> $(NC_DIR)/host-build.log 2>&1 \
		&& $(MAKE) -s -C $(NC_DIR)/host/progs tic infocmp >> $(NC_DIR)/host-build.log 2>&1 \
		|| { tail -40 $(NC_DIR)/host-build.log; exit 1; }
	$(Q)mkdir -p $(NC_DIR)/build
	$(Q)cd $(NC_DIR)/build && PATH=$(NC_DIR)/host/progs:$$PATH $(NC_DIR)/src/configure --host=$(BB_TARGET) \
		--build=$$($(NC_DIR)/src/config.guess) CC=$(BB_CC) BUILD_CC=cc AR="$(AR)" RANLIB="$(AR) s" \
		CFLAGS="-O2 -ffile-prefix-map=$(NC_DIR)=ncurses" --prefix=/usr --without-shared --without-cxx \
		--without-cxx-binding --without-ada --without-progs --without-tests --without-manpages --without-debug \
		--without-pkg-config --enable-widec --disable-database --with-fallbacks=$(NCURSES_FALLBACKS) \
		--with-tic-path=$(NC_DIR)/host/progs/tic --with-infocmp-path=$(NC_DIR)/host/progs/infocmp \
		> $(NC_DIR)/configure.log 2>&1 || { tail -40 $(NC_DIR)/configure.log; exit 1; }
	$(Q)PATH=$(NC_DIR)/host/progs:$$PATH $(MAKE) -s -C $(NC_DIR)/build libs > $(NC_DIR)/build.log 2>&1 \
		|| { tail -40 $(NC_DIR)/build.log; exit 1; }
	$(Q)mkdir -p $(NCURSES_PREFIX)/include/ncursesw $(NCURSES_PREFIX)/lib
	$(Q)for d in $(NCURSES_PREFIX)/include $(NCURSES_PREFIX)/include/ncursesw; do \
		cp $(NC_DIR)/build/include/curses.h $(NC_DIR)/build/include/ncurses_dll.h $(NC_DIR)/build/include/unctrl.h \
			$(NC_DIR)/build/include/term.h $(NC_DIR)/build/include/termcap.h $$d/ || exit 1; \
		ln -sf curses.h $$d/ncurses.h; \
	done
	$(Q)cp $(NC_DIR)/build/lib/libncursesw.a $@

.PHONY: ncurses
ncurses: $(NCURSES_A)
