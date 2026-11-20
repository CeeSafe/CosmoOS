# OpenSSH's sftp-server, built from OpenSSH portable for the architecture in
# hand (the scp-sftp unit; ports/openssh/README.md): dropbear runs it for the
# "sftp" subsystem (ports/dropbear/localoptions.h, SFTPSERVER_PATH), and
# provides none of its own. Only sftp-server is built: no ssh, sshd or
# keys. Static against the musl sysroot and compiler-rt builtins the BusyBox
# port builds, with the project's clang, as dropbear is. The source archive
# is pinned by version and SHA-256 (the release notes' value, base64 there)
# and fetched once into $(PORTS_CACHE) through scripts/fetch-pinned.py.

OPENSSH_VERSION := 10.6p1
OPENSSH_SHA256  := a9dc9565dffe8640f64d863cd29a32bc4a3dbdec0566a7fc44c5d6ee767d5f39
OPENSSH_URL     := https://cdn.openbsd.org/pub/OpenBSD/OpenSSH/portable/openssh-$(OPENSSH_VERSION).tar.gz
OPENSSH_TAR     := $(PORTS_CACHE)/openssh-$(OPENSSH_VERSION).tar.gz

# One build per architecture beside $(OUT), shared by the build variants as
# BusyBox's and dropbear's are.
OSSH_DIR        ?= $(dir $(OUT))openssh-$(ARCH)
SFTP_SERVER_ELF := $(OSSH_DIR)/sftp-server

$(OPENSSH_TAR):
	$(Q)$(PYTHON) $(ROOT)/scripts/fetch-pinned.py $@ $(OPENSSH_SHA256) $(OPENSSH_URL) \
		$(PINNED_MIRROR)/$(notdir $(OPENSSH_TAR))

# configure for the musl target with BusyBox's compiler wrapper (a static
# link with musl's start files). No OpenSSL and no zlib: sftp-server uses
# neither. No PIE and no hardening flags: the wrapper's fixed image base
# rules out a static-pie, as for dropbear. No PAM, no login records.
# -ffile-prefix-map keeps the build directory out of the binary (make
# reproducible).
$(SFTP_SERVER_ELF): $(OPENSSH_TAR) $(BB_LIBC) $(BB_BUILTINS) $(BB_CC) $(ROOT)/ports/openssh/openssh.mk
	$(call log,OPENSSH,sftp-server $(OPENSSH_VERSION) $(BB_TARGET))
	$(Q)rm -rf $(OSSH_DIR)/src
	$(Q)mkdir -p $(OSSH_DIR)/src
	$(Q)tar -xzf $(OPENSSH_TAR) -C $(OSSH_DIR)/src --strip-components=1
	$(Q)cd $(OSSH_DIR)/src && ./configure --host=$(BB_TARGET) \
		CC=$(BB_CC) AR="$(AR)" RANLIB="$(AR) s" CFLAGS="-O2 -ffile-prefix-map=$(OSSH_DIR)=openssh" \
		--without-openssl --without-zlib --without-pam --without-pie --without-hardening \
		--without-stackprotect --disable-lastlog --disable-utmp --disable-utmpx --disable-wtmp \
		--disable-wtmpx --disable-libutil --disable-pututline --disable-pututxline \
		--with-privsep-path=/var/empty --sysconfdir=/etc/ssh > $(OSSH_DIR)/configure.log 2>&1 \
		|| { tail -40 $(OSSH_DIR)/configure.log; exit 1; }
	$(Q)$(MAKE) -s -C $(OSSH_DIR)/src sftp-server > $(OSSH_DIR)/build.log 2>&1 \
		|| { tail -40 $(OSSH_DIR)/build.log; exit 1; }
	$(Q)$(OBJCOPY) --strip-all --remove-section=.note --remove-section=.comment $(OSSH_DIR)/src/sftp-server \
		$(SFTP_SERVER_ELF)

.PHONY: sftp-server
sftp-server: $(SFTP_SERVER_ELF)

# /usr/libexec/sftp-server, where dropbear looks for it.
OPENSSH_ARCHIVE_ENTRIES := usr/libexec/sftp-server=$(SFTP_SERVER_ELF)
OPENSSH_ARCHIVE_DEPS := $(SFTP_SERVER_ELF)

# ---- The openssh-client and openssh-server packages (roadmap 1.3 R3;
# ports/openssh/README.md, "The packages"; docs/pkg/design.md, "Cross-built
# ports") ----
#
# A second build of the same source in a directory of its own, so the base
# system's sftp-server above is unchanged. zlib (ports/zlib/) for
# compression; OpenSSH's own crypto, still without OpenSSL (Ed25519,
# ChaCha20-Poly1305, AES-CTR and GCM, the Curve25519 and ML-KEM key
# exchanges). The privilege separation user is `sshd`, its directory
# /var/empty (ports/openssh/start makes both). Installed into a stage the
# two package files read.
OSSH_PKG_DIR   ?= $(dir $(OUT))openssh-pkg-$(ARCH)
OSSH_STAGE     := $(OSSH_PKG_DIR)/stage
OSSH_SSH_ELF   := $(OSSH_STAGE)/usr/bin/ssh
OSSH_CLIENTS   := ssh scp sftp ssh-keygen ssh-keyscan ssh-agent ssh-add
OSSH_SERVERS   := sshd sshd-session sshd-auth

$(OSSH_SSH_ELF): $(OPENSSH_TAR) $(ZLIB_A) $(BB_LIBC) $(BB_BUILTINS) $(BB_CC) $(ROOT)/ports/openssh/openssh.mk \
		$(ROOT)/ports/openssh/sshd_config $(ROOT)/ports/openssh/start $(ROOT)/ports/openssh/sshd.svc
	$(call log,OPENSSH,$(OPENSSH_VERSION) $(BB_TARGET) clients and sshd)
	$(Q)rm -rf $(OSSH_PKG_DIR)/src $(OSSH_STAGE)
	$(Q)mkdir -p $(OSSH_PKG_DIR)/src
	$(Q)tar -xzf $(OPENSSH_TAR) -C $(OSSH_PKG_DIR)/src --strip-components=1
	$(Q)cd $(OSSH_PKG_DIR)/src && ./configure --host=$(BB_TARGET) \
		CC=$(BB_CC) AR="$(AR)" RANLIB="$(AR) s" CFLAGS="-O2 -ffile-prefix-map=$(OSSH_PKG_DIR)=openssh" \
		--prefix=/usr --sysconfdir=/etc/ssh --libexecdir=/usr/libexec --with-privsep-path=/var/empty \
		--with-privsep-user=sshd --with-zlib=$(ZLIB_PREFIX) --without-openssl --without-pam --without-pie \
		--without-hardening --without-stackprotect --disable-lastlog --disable-utmp --disable-utmpx \
		--disable-wtmp --disable-wtmpx --disable-libutil --disable-pututline --disable-pututxline \
		--with-default-path=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin \
		--with-superuser-path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
		> $(OSSH_PKG_DIR)/configure.log 2>&1 || { tail -40 $(OSSH_PKG_DIR)/configure.log; exit 1; }
	$(Q)$(MAKE) -s -C $(OSSH_PKG_DIR)/src $(OSSH_CLIENTS) $(OSSH_SERVERS) > $(OSSH_PKG_DIR)/build.log 2>&1 \
		|| { tail -40 $(OSSH_PKG_DIR)/build.log; exit 1; }
	$(Q)mkdir -p $(OSSH_STAGE)/usr/bin $(OSSH_STAGE)/usr/sbin $(OSSH_STAGE)/usr/libexec $(OSSH_STAGE)/etc/ssh \
		$(OSSH_STAGE)/etc/svc
	$(Q)for p in $(OSSH_CLIENTS); do $(OBJCOPY) --strip-all --remove-section=.note --remove-section=.comment \
		$(OSSH_PKG_DIR)/src/$$p $(OSSH_STAGE)/usr/bin/$$p || exit 1; done
	$(Q)$(OBJCOPY) --strip-all --remove-section=.note --remove-section=.comment $(OSSH_PKG_DIR)/src/sshd \
		$(OSSH_STAGE)/usr/sbin/sshd
	$(Q)for p in sshd-session sshd-auth; do $(OBJCOPY) --strip-all --remove-section=.note --remove-section=.comment \
		$(OSSH_PKG_DIR)/src/$$p $(OSSH_STAGE)/usr/libexec/$$p || exit 1; done
	$(Q)cp $(ROOT)/ports/openssh/sshd_config $(OSSH_STAGE)/etc/ssh/sshd_config
	$(Q)cp $(ROOT)/ports/openssh/start $(OSSH_STAGE)/etc/ssh/start
	$(Q)cp $(ROOT)/ports/openssh/sshd.svc $(OSSH_STAGE)/etc/svc/sshd

.PHONY: openssh-pkg
openssh-pkg: $(OSSH_SSH_ELF)

# The packages (pkg/pkg.mk's server-ports): their files and the stage they read.
SERVER_PACKAGES     += $(ROOT)/ports/openssh/package-client=$(OSSH_STAGE) $(ROOT)/ports/openssh/package-server=$(OSSH_STAGE)
SERVER_PACKAGE_DEPS += $(OSSH_SSH_ELF) $(ROOT)/ports/openssh/package-client $(ROOT)/ports/openssh/package-server
