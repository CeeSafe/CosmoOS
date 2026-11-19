# git, built for the architecture in hand (roadmap 1.3 R3; ports/git/README.md):
# the `git` package. Static against the musl sysroot the BusyBox port builds,
# through its cc wrapper, with libcurl (ports/curl/: HTTPS by mbedTLS) and
# zlib (ports/zlib/) linked in. The source archive is pinned by version and
# SHA-256 (kernel.org's sha256sums.asc, and the archive's signature by Junio C
# Hamano's key 96E07AF25771955980DAD10020D04E5A713660A7, checked) and fetched
# once into $(PORTS_CACHE) through scripts/fetch-pinned.py.

GIT_VERSION := 2.56.1
GIT_SHA256  := f0b0bf89264b9bd2e1c640363e7529643989da76281600473c50745cd34a607f
GIT_URL     := https://www.kernel.org/pub/software/scm/git/git-$(GIT_VERSION).tar.xz
GIT_TAR     := $(PORTS_CACHE)/git-$(GIT_VERSION).tar.xz

# One build per architecture beside $(OUT), shared by the build variants as
# BusyBox's is. GIT_STAGE is the install (DESTDIR) the package takes its
# files from (ports/git/package).
GIT_DIR_    ?= $(dir $(OUT))git-$(ARCH)
GIT_STAGE   := $(GIT_DIR_)/stage
GIT_ELF     := $(GIT_STAGE)/usr/bin/git

$(GIT_TAR):
	$(Q)$(PYTHON) $(ROOT)/scripts/fetch-pinned.py $@ $(GIT_SHA256) $(GIT_URL) $(PINNED_MIRROR)/$(notdir $(GIT_TAR))

# git's own Makefile, no configure: the target named by uname_S and uname_M
# (a Linux system), the compiler BusyBox's wrapper (a static link). HTTP(S)
# through libcurl, given by its flags rather than curl-config; zlib by its
# prefix. No Rust (its parts have C versions), gettext, Perl, Python, Tcl/Tk
# or expat (the last is for pushing over HTTP with WebDAV, which nothing
# uses). git-remote-https, a symbolic link install makes, becomes a copy of
# git-remote-http. The built-in commands are not
# installed under their dashed names (SKIP_DASHED_BUILT_INS) and nothing is a
# hard link (packages carry regular files). No file-system monitor daemon:
# Linux's is inotify, which CosmoOS lacks. -ffile-prefix-map keeps the build
# directory out of the binaries (make reproducible).
GIT_MAKE_FLAGS = CC=$(BB_CC) AR="$(AR)" RANLIB="$(AR) s" uname_S=Linux uname_M=$(ARCH) uname_O=GNU/Linux \
	uname_R=6.0 uname_P=unknown uname_V=1 HOST_CPU=$(ARCH) \
	CFLAGS="-O2 -ffile-prefix-map=$(GIT_DIR_)=git" prefix=/usr gitexecdir=/usr/libexec/git-core \
	CURLDIR=$(CURL_PREFIX) CURL_CFLAGS="-I$(CURL_PREFIX)/include" CURL_LDFLAGS="$(CURL_LINK_LIBS)" \
	ZLIB_PATH=$(ZLIB_PREFIX) NO_GETTEXT=YesPlease NO_PERL=YesPlease NO_PYTHON=YesPlease NO_TCLTK=YesPlease \
	NO_EXPAT=YesPlease NO_INSTALL_HARDLINKS=YesPlease SKIP_DASHED_BUILT_INS=YesPlease INSTALL_SYMLINKS= \
	NO_REGEX=NeedsStartEnd USE_LIBPCRE= NO_OPENSSL=YesPlease NO_RUST=YesPlease FSMONITOR_DAEMON_BACKEND= FSMONITOR_OS_SETTINGS= V=

$(GIT_ELF): $(GIT_TAR) $(LIBCURL_A) $(CURL_ENTROPY_A) $(MBEDTLS_LIBS) $(ZLIB_A) $(BB_LIBC) $(BB_BUILTINS) $(BB_CC) \
		$(ROOT)/ports/git/git.mk
	$(call log,GIT,$(GIT_VERSION) $(BB_TARGET))
	$(Q)rm -rf $(GIT_DIR_)/src $(GIT_STAGE)
	$(Q)mkdir -p $(GIT_DIR_)/src
	$(Q)tar -xJf $(GIT_TAR) -C $(GIT_DIR_)/src --strip-components=1
	$(Q)$(MAKE) -s -C $(GIT_DIR_)/src $(GIT_MAKE_FLAGS) all > $(GIT_DIR_)/build.log 2>&1 \
		|| { tail -40 $(GIT_DIR_)/build.log; exit 1; }
	$(Q)$(MAKE) -s -C $(GIT_DIR_)/src $(GIT_MAKE_FLAGS) install DESTDIR=$(GIT_STAGE) > $(GIT_DIR_)/install.log 2>&1 \
		|| { tail -40 $(GIT_DIR_)/install.log; exit 1; }
	$(Q)cp $(GIT_STAGE)/usr/libexec/git-core/git-remote-http $(GIT_STAGE)/usr/libexec/git-core/git-remote-https.new \
		&& mv -f $(GIT_STAGE)/usr/libexec/git-core/git-remote-https.new $(GIT_STAGE)/usr/libexec/git-core/git-remote-https
	$(Q)for f in $$(find $(GIT_STAGE)/usr/bin $(GIT_STAGE)/usr/libexec/git-core -type f); do \
		if head -c 4 $$f | grep -q 'ELF'; then $(OBJCOPY) --strip-all --remove-section=.note \
			--remove-section=.comment $$f || exit 1; fi; \
	done

.PHONY: git
git: $(GIT_ELF)

# The package (pkg/pkg.mk's server-ports): its file and the stage it reads.
SERVER_PACKAGES     += $(ROOT)/ports/git/package=$(GIT_STAGE)
SERVER_PACKAGE_DEPS += $(GIT_ELF) $(ROOT)/ports/git/package
