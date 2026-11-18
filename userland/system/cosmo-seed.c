/*
 * cosmo-seed - first boot without a console: the SSH key, the host name and
 * the network from a cloud-init NoCloud seed (roadmap 1.3 R2;
 * docs/userland/design.md, "First boot without a console").
 *
 *   cosmo-seed
 *
 * /etc/rc runs it before `svc boot` (dropbear must find the key when it
 * starts) and before `hostname -F`. It reads every block device /dev/blkctl
 * lists that is not mounted and not the boot device, by sectors, for one
 * seed: an ISO 9660 volume or a FAT volume labelled `cidata`
 * (seed_read.c). No seed: nothing is printed and the boot is as before.
 * More than one: none is used, and a line says which.
 *
 * meta-data (instance-id, local-hostname), user-data when its first line is
 * `#cloud-config` (hostname, ssh_authorized_keys) and network-config
 * version 2 (ethernets: dhcp4, one IPv4 address, the default gateway, name
 * servers) are read with seed_yaml.c's subset; a key outside it is named in
 * one line and ignored, a file that does not parse is skipped with a line.
 *
 * The host name and the keys apply once per instance: when the seed's
 * instance-id differs from /var/lib/cloud/instance-id (or there is none).
 * The network applies at every boot that has the seed (the kernel keeps no
 * address across a boot): IPV4_SET on /dev/net/tapctl for an interface
 * with an address, which stops its DHCP client; /etc/resolv.conf from the
 * name servers. Exit 0, or 1 when a seed was found and something in it
 * could not be applied (each said in its own line).
 */

#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include <uapi/cosmo/blkctl.h>
#include <uapi/cosmo/netctl.h>

#include "blkdevs.h"
#include "seed_read.h"
#include "seed_yaml.h"

#define CLOUD_DIR "/var/lib/cloud"

static int g_status;

static void problem(void) { g_status = 1; }

/* ---- reading a device in 512-byte sectors --------------------------------------------------------------------- */

static uint8_t g_sec[4096];

static int dev_read(void *ctx, uint64_t lba, uint32_t count, void *buf)
{
    const struct cosmo_blkctl_dev *d = ctx;
    uint32_t ss = d->sector_size;
    if (ss == SEED_SECTOR)
        return blkdevs_read(d, lba, count, buf);
    if (ss < SEED_SECTOR || ss > sizeof(g_sec) || ss % SEED_SECTOR != 0)
        return -1;
    uint32_t per = ss / SEED_SECTOR;
    for (uint32_t i = 0; i < count; i++) {
        uint64_t s = lba + i;
        if (blkdevs_read(d, s / per, 1, g_sec) != 0)
            return -1;
        memcpy((uint8_t *)buf + (size_t)i * SEED_SECTOR, g_sec + (s % per) * SEED_SECTOR, SEED_SECTOR);
    }
    return 0;
}

/* ---- files ------------------------------------------------------------------------------------------------------ */

/* `text` into `path` through a file beside it, renamed over it: a reader never sees half of it. */
static int write_whole(const char *path, const char *text, size_t len, unsigned mode)
{
    char tmp[256];
    if ((size_t)snprintf(tmp, sizeof(tmp), "%s.cosmo-seed", path) >= sizeof(tmp))
        return -1;
    int fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, mode);
    if (fd < 0 || write(fd, text, len) != (ssize_t)len || close(fd) < 0 || rename(tmp, path) < 0) {
        printf("cosmo-seed: writing %s: %s\n", path, strerror(errno));
        if (fd >= 0)
            unlink(tmp);
        return -1;
    }
    return 0;
}

/* A small file's contents, NUL-terminated, at most n - 1 bytes; its length or -1. */
static long read_small(const char *path, char *out, size_t n)
{
    int fd = open(path, O_RDONLY);
    if (fd < 0)
        return -1;
    size_t got = 0;
    for (;;) {
        ssize_t r = read(fd, out + got, n - 1 - got);
        if (r <= 0)
            break;
        got += (size_t)r;
        if (got == n - 1)
            break;
    }
    close(fd);
    out[got] = 0;
    return (long)got;
}

static char *trim(char *s)
{
    while (*s == ' ' || *s == '\t' || *s == '\n' || *s == '\r')
        s++;
    size_t n = strlen(s);
    while (n > 0 && (s[n - 1] == ' ' || s[n - 1] == '\t' || s[n - 1] == '\n' || s[n - 1] == '\r'))
        s[--n] = 0;
    return s;
}

/* ---- the seed's files ------------------------------------------------------------------------------------------- */

static uint8_t g_raw[SEED_FILE_MAX + 1];

/* A seed file into a NUL-terminated copy (static, one per name); NULL when absent or unreadable (said). */
static char *seed_text(const struct seed_dev *d, const char *name, char *out)
{
    size_t len;
    int rc = seed_file(d, name, g_raw, SEED_FILE_MAX, &len);
    if (rc == -ENOENT)
        return NULL;
    if (rc != 0) {
        printf("cosmo-seed: %s: %s\n", name, rc == -EFBIG ? "longer than 64 KiB; not read" : strerror(-rc));
        problem();
        return NULL;
    }
    memcpy(out, g_raw, len);
    out[len] = 0;
    if (strlen(out) != len) {
        printf("cosmo-seed: %s: holds a NUL byte; not read\n", name);
        problem();
        return NULL;
    }
    return out;
}

static char g_meta[SEED_FILE_MAX + 1], g_user[SEED_FILE_MAX + 1], g_net[SEED_FILE_MAX + 1];
static struct yaml_doc g_meta_doc, g_user_doc, g_net_doc;

static bool parse(struct yaml_doc *doc, char *text, const char *name)
{
    if (yaml_parse(doc, text) == 0)
        return true;
    printf("cosmo-seed: %s: line %d: %s; the file is skipped\n", name, doc->error_line, doc->error);
    problem();
    return false;
}

/* Name in one line the keys of map `at` outside `known` (NULL-terminated). */
static void unknown_keys(const struct yaml_doc *doc, int at, const char *const *known, const char *where)
{
    const struct yaml_node *m = yaml_at(doc, at);
    if (m == NULL || m->type != YAML_MAP)
        return;
    char line[512];
    size_t n = 0;
    line[0] = 0;
    for (int e = m->child; e >= 0; e = doc->node[e].next) {
        bool ok = false;
        for (const char *const *k = known; *k; k++)
            ok |= strcmp(*k, doc->node[e].key) == 0;
        if (!ok && n < sizeof(line))
            n += (size_t)snprintf(line + n, sizeof(line) - n, "%s%s", n ? ", " : "", doc->node[e].key);
    }
    if (n > 0)
        printf("cosmo-seed: %s: ignoring %s\n", where, line);
}

static bool truthy(const char *s)
{
    return s != NULL && (strcmp(s, "true") == 0 || strcmp(s, "True") == 0 || strcmp(s, "yes") == 0 ||
                         strcmp(s, "on") == 0);
}

/* ---- once per instance: the host name and the keys ------------------------------------------------------------- */

/* As the kernel keeps a DHCP server's name: letters, digits, '-' and '.', 1 to 64 of them. */
static bool hostname_ok(const char *s)
{
    size_t n = strlen(s);
    if (n == 0 || n > 64)
        return false;
    for (size_t i = 0; i < n; i++) {
        char c = s[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' || c == '.'))
            return false;
    }
    return true;
}

static void apply_hostname(const char *name)
{
    if (!hostname_ok(name)) {
        printf("cosmo-seed: host name '%.64s' is not letters, digits, '-' and '.' (at most 64); not set\n", name);
        problem();
        return;
    }
    char text[80];
    size_t len = (size_t)snprintf(text, sizeof(text), "%s\n", name);
    if (write_whole("/etc/hostname", text, len, 0644) < 0 || write_whole(CLOUD_DIR "/hostname", text, len, 0644) < 0) {
        problem();
        return;
    }
    if (sethostname(name, strlen(name)) < 0) {
        printf("cosmo-seed: sethostname %s: %s\n", name, strerror(errno));
        problem();
        return;
    }
    printf("cosmo-seed: host name %s\n", name);
}

static char g_keys[SEED_FILE_MAX + 1];

static bool has_line(const char *text, const char *line)
{
    size_t n = strlen(line);
    for (const char *s = text; *s;) {
        const char *e = strchr(s, '\n');
        size_t len = e ? (size_t)(e - s) : strlen(s);
        while (len > 0 && (s[len - 1] == '\r' || s[len - 1] == ' '))
            len--;
        if (len == n && memcmp(s, line, n) == 0)
            return true;
        s = e ? e + 1 : s + strlen(s);
    }
    return false;
}

static void apply_keys(const struct yaml_doc *doc, int list)
{
    const struct yaml_node *l = yaml_at(doc, list);
    if (l == NULL)
        return;
    if (l->type != YAML_LIST) {
        printf("cosmo-seed: user-data: ssh_authorized_keys is not a list; no key added\n");
        problem();
        return;
    }
    if (mkdir("/root/.ssh", 0700) < 0 && errno != EEXIST) {
        printf("cosmo-seed: /root/.ssh: %s\n", strerror(errno));
        problem();
        return;
    }
    chmod("/root/.ssh", 0700);
    const char *path = "/root/.ssh/authorized_keys";
    long have = read_small(path, g_keys, sizeof(g_keys));
    if (have < 0)
        have = 0, g_keys[0] = 0;
    unsigned added = 0, kept = 0;
    for (int k = l->child; k >= 0; k = doc->node[k].next) {
        const struct yaml_node *key = &doc->node[k];
        if (key->type != YAML_SCALAR || key->text[0] == 0 || strchr(key->text, '\n')) {
            printf("cosmo-seed: user-data: an ssh_authorized_keys entry that is not one line; skipped\n");
            problem();
            continue;
        }
        if (has_line(g_keys, key->text)) {
            kept++;
            continue;
        }
        size_t len = strlen(g_keys), need = strlen(key->text) + 2;
        if (len + need >= sizeof(g_keys)) {
            printf("cosmo-seed: %s would pass 64 KiB; a key is not added\n", path);
            problem();
            break;
        }
        if (len > 0 && g_keys[len - 1] != '\n')
            g_keys[len++] = '\n';
        snprintf(g_keys + len, sizeof(g_keys) - len, "%s\n", key->text);
        added++;
    }
    if (added > 0 && write_whole(path, g_keys, strlen(g_keys), 0600) < 0) {
        problem();
        return;
    }
    chmod(path, 0600);
    printf("cosmo-seed: %u SSH key(s) added to %s%s\n", added, path, kept ? " (others already there)" : "");
}

/* ---- every boot: the network ----------------------------------------------------------------------------------- */

static unsigned char g_snap[COSMO_NETCTL_SNAPSHOT_MAX];
static const struct cosmo_netctl_if *g_ifs;
static unsigned g_nifs;

/* The interface section of /dev/net/tapctl's snapshot (as ip.c walks it). 0 or -1. */
static int load_ifs(void)
{
    int fd = open("/dev/net/tapctl", O_RDONLY);
    if (fd < 0)
        return -1;
    ssize_t n = read(fd, g_snap, sizeof(g_snap));
    close(fd);
    if (n < 0)
        return -1;
    size_t len = (size_t)n, off = 0;
#define TAKE(hdr_t, hdr)                  \
    hdr_t hdr;                            \
    if (len < off + sizeof(hdr))          \
        return -1;                        \
    memcpy(&hdr, g_snap + off, sizeof(hdr)); \
    off += sizeof(hdr);
    TAKE(struct cosmo_netctl_list, ph)
    if (ph.version != COSMO_NETCTL_VERSION)
        return -1;
    off += (size_t)ph.count * sizeof(struct cosmo_netctl_rule);
    TAKE(struct cosmo_netctl_filter_list, fh)
    off += (size_t)fh.guest_count * sizeof(struct cosmo_netctl_filter_guest) +
           (size_t)fh.rule_count * sizeof(struct cosmo_netctl_filter_rule);
    TAKE(struct cosmo_netctl_flow_list, wh)
    off += (size_t)wh.count * sizeof(struct cosmo_netctl_flow);
    TAKE(struct cosmo_netctl_lease_list, lh)
    off += (size_t)lh.count * sizeof(struct cosmo_netctl_lease);
    TAKE(struct cosmo_netctl_if_list, ih)
#undef TAKE
    if (len < off + (size_t)ih.count * sizeof(struct cosmo_netctl_if))
        return -1;
    g_ifs = (const struct cosmo_netctl_if *)(g_snap + off);
    g_nifs = ih.count;
    return 0;
}

/* "a.b.c.d" into network byte order; the text after it in *end. */
static bool ipv4(const char *s, uint32_t *out, const char **end)
{
    uint32_t v = 0;
    for (int part = 0; part < 4; part++) {
        if (*s < '0' || *s > '9')
            return false;
        unsigned n = 0, digits = 0;
        while (*s >= '0' && *s <= '9' && digits < 4) {
            n = n * 10 + (unsigned)(*s++ - '0');
            digits++;
        }
        if (n > 255 || (*s >= '0' && *s <= '9'))
            return false;
        v = (v << 8) | n;
        if (part < 3 && *s++ != '.')
            return false;
    }
    *out = ((v & 0xff) << 24) | ((v & 0xff00) << 8) | ((v >> 8) & 0xff00) | (v >> 24);
    *end = s;
    return true;
}

static bool ipv4_only(const char *s, uint32_t *out)
{
    const char *end;
    return s != NULL && ipv4(s, out, &end) && *end == 0;
}

static bool mac_of(const char *s, uint8_t mac[6])
{
    for (int i = 0; i < 6; i++) {
        unsigned v = 0;
        for (int j = 0; j < 2; j++) {
            char c = *s++;
            v = v * 16 + (unsigned)(c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 :
                                    c >= 'A' && c <= 'F' ? c - 'A' + 10 : 99);
            if (v > 255)
                return false;
        }
        mac[i] = (uint8_t)v;
        if (i < 5 && *s++ != ':')
            return false;
    }
    return *s == 0;
}

static const struct cosmo_netctl_if *if_for(const struct yaml_doc *doc, int eth, const char *id)
{
    const char *mac_text = yaml_str(doc, eth, "match.macaddress");
    uint8_t mac[6];
    if (mac_text != NULL && !mac_of(mac_text, mac))
        return NULL;
    for (unsigned i = 0; i < g_nifs; i++) {
        const struct cosmo_netctl_if *f = &g_ifs[i];
        if (f->flags & (COSMO_NETCTL_IF_LOOPBACK | COSMO_NETCTL_IF_TAP))
            continue;
        if (mac_text != NULL ? memcmp(f->mac, mac, 6) == 0 : strncmp(f->name, id, sizeof(f->name)) == 0)
            return f;
    }
    return NULL;
}

static void apply_network(const struct yaml_doc *doc)
{
    static const char *const top[] = { "version", "ethernets", NULL };
    static const char *const per[] = { "match", "dhcp4", "addresses", "gateway4", "routes", "nameservers", "set-name",
                                       NULL };
    unknown_keys(doc, doc->root, top, "network-config");
    const char *version = yaml_str(doc, -1, "version");
    if (version == NULL || strcmp(version, "2") != 0) {
        printf("cosmo-seed: network-config: version %s is not 2; the network stays as DHCP sets it\n",
               version ? version : "(none)");
        problem();
        return;
    }
    const struct yaml_node *eths = yaml_at(doc, yaml_get(doc, -1, "ethernets"));
    if (eths == NULL || eths->type != YAML_MAP)
        return;
    if (load_ifs() < 0) {
        printf("cosmo-seed: network-config: cannot read the interfaces from /dev/net/tapctl\n");
        problem();
        return;
    }
    uint32_t dns[3];
    unsigned ndns = 0;
    for (int e = eths->child; e >= 0; e = doc->node[e].next) {
        const char *id = doc->node[e].key;
        char where[96];
        snprintf(where, sizeof(where), "network-config: ethernets.%.40s", id);
        unknown_keys(doc, e, per, where);
        const struct yaml_node *ns = yaml_at(doc, yaml_get(doc, e, "nameservers.addresses"));
        for (int k = ns && ns->type == YAML_LIST ? ns->child : -1; k >= 0; k = doc->node[k].next) {
            uint32_t a;
            if (doc->node[k].type == YAML_SCALAR && ipv4_only(doc->node[k].text, &a) && ndns < 3)
                dns[ndns++] = a;
        }
        const struct yaml_node *addrs = yaml_at(doc, yaml_get(doc, e, "addresses"));
        const char *cidr = NULL;
        for (int k = addrs && addrs->type == YAML_LIST ? addrs->child : -1; k >= 0; k = doc->node[k].next)
            if (doc->node[k].type == YAML_SCALAR && strchr(doc->node[k].text, ':') == NULL) {
                if (cidr == NULL)
                    cidr = doc->node[k].text;
                else
                    printf("cosmo-seed: %s: only the first IPv4 address is set (%s)\n", where, cidr);
            }
        const struct cosmo_netctl_if *f = if_for(doc, e, id);
        if (cidr == NULL) {
            if (!truthy(yaml_str(doc, e, "dhcp4")) && f != NULL)
                printf("cosmo-seed: %s: no IPv4 address; %.8s keeps DHCP\n", where, f->name);
            continue;
        }
        if (f == NULL) {
            printf("cosmo-seed: %s: no such interface\n", where);
            problem();
            continue;
        }
        uint32_t addr, gw = 0;
        const char *end;
        unsigned prefix = 0;
        bool ok = ipv4(cidr, &addr, &end) && *end == '/';
        if (ok) {
            char *pe;
            unsigned long p = strtoul(end + 1, &pe, 10);
            ok = *pe == 0 && p >= 1 && p <= 32 && end[1] >= '0' && end[1] <= '9';
            prefix = (unsigned)p;
        }
        const char *gtext = yaml_str(doc, e, "gateway4");
        const struct yaml_node *routes = yaml_at(doc, yaml_get(doc, e, "routes"));
        for (int k = routes && routes->type == YAML_LIST ? routes->child : -1; k >= 0 && !gtext; k = doc->node[k].next) {
            const char *to = yaml_str(doc, k, "to");
            if (to && (strcmp(to, "default") == 0 || strcmp(to, "0.0.0.0/0") == 0))
                gtext = yaml_str(doc, k, "via");
        }
        if (ok && gtext != NULL)
            ok = ipv4_only(gtext, &gw);
        if (!ok) {
            printf("cosmo-seed: %s: '%s'%s%s is not an IPv4 address/prefix and gateway; not set\n", where, cidr,
                   gtext ? " via " : "", gtext ? gtext : "");
            problem();
            continue;
        }
        struct cosmo_netctl_ipv4 c;
        memset(&c, 0, sizeof(c));
        c.version = COSMO_NETCTL_VERSION;
        c.op = COSMO_NETCTL_IPV4_SET;
        memcpy(c.ifname, f->name, sizeof(f->name) < sizeof(c.ifname) ? sizeof(f->name) : sizeof(c.ifname));
        c.ifname[sizeof(c.ifname) - 1] = 0;
        c.addr = addr;
        c.gateway = gw;
        c.prefix = (uint8_t)prefix;
        int fd = open("/dev/net/tapctl", O_WRONLY);
        if (fd < 0 || write(fd, &c, sizeof(c)) != (ssize_t)sizeof(c)) {
            printf("cosmo-seed: %s: setting %s on %s: %s\n", where, cidr, c.ifname, strerror(errno));
            problem();
        } else {
            printf("cosmo-seed: %s %s%s%s\n", c.ifname, cidr, gtext ? " via " : "", gtext ? gtext : "");
        }
        if (fd >= 0)
            close(fd);
    }
    if (ndns > 0) {
        char text[256];
        size_t len = (size_t)snprintf(text, sizeof(text), "# written by cosmo-seed from the seed's network-config\n");
        for (unsigned i = 0; i < ndns; i++) {
            const uint8_t *b = (const uint8_t *)&dns[i];
            len += (size_t)snprintf(text + len, sizeof(text) - len, "nameserver %u.%u.%u.%u\n", b[0], b[1], b[2], b[3]);
        }
        if (write_whole("/etc/resolv.conf", text, len, 0644) == 0)
            printf("cosmo-seed: /etc/resolv.conf: %u name server(s)\n", ndns);
        else
            problem();
    }
}

/* ---- main ------------------------------------------------------------------------------------------------------- */

int main(void)
{
    if (blkdevs_list() < 0)
        return 0;   /* no block devices to look at: nothing to do */
    static struct cosmo_blkctl_dev devs[BLKDEVS_MAX];
    unsigned ndevs = g_nblkdevs;
    memcpy(devs, g_blkdevs, ndevs * sizeof(devs[0]));
    struct seed_dev found[2];
    const char *names[2];
    unsigned nfound = 0, seen = 0;
    for (unsigned i = 0; i < ndevs; i++) {
        struct cosmo_blkctl_dev *d = &devs[i];
        if (d->flags & (COSMO_BLKCTL_MOUNTED | COSMO_BLKCTL_BOOT))
            continue;
        struct seed_dev s;
        memset(&s, 0, sizeof(s));
        s.read = dev_read;
        s.ctx = d;
        s.sectors = d->sectors * (d->sector_size / SEED_SECTOR);
        if (seed_probe(&s) <= 0)
            continue;
        if (nfound < 2) {
            found[nfound] = s;
            names[nfound] = d->name;
            nfound++;
        }
        seen++;
    }
    if (seen == 0)
        return 0;
    if (seen > 1) {
        printf("cosmo-seed: %u seeds (%s, %s%s); none is used\n", seen, names[0], names[1], seen > 2 ? ", ..." : "");
        return 1;
    }
    const struct seed_dev *d = &found[0];
    printf("cosmo-seed: seed on %s (%s)\n", names[0], d->kind == SEED_ISO ? "ISO 9660" : "FAT");

    char *meta = seed_text(d, "meta-data", g_meta);
    if (meta == NULL || !parse(&g_meta_doc, meta, "meta-data")) {
        if (meta == NULL)
            printf("cosmo-seed: the seed has no meta-data; nothing is applied\n");
        return 1;
    }
    static const char *const meta_keys[] = { "instance-id", "local-hostname", NULL };
    unknown_keys(&g_meta_doc, g_meta_doc.root, meta_keys, "meta-data");
    const char *iid = yaml_str(&g_meta_doc, -1, "instance-id");
    if (iid == NULL || iid[0] == 0 || strchr(iid, '\n')) {
        printf("cosmo-seed: meta-data has no instance-id; nothing is applied\n");
        return 1;
    }

    char *user = seed_text(d, "user-data", g_user);
    bool user_ok = false;
    if (user != NULL) {
        if (strncmp(user, "#cloud-config", 13) == 0 && (user[13] == '\n' || user[13] == '\r' || user[13] == 0 ||
                                                         user[13] == ' '))
            user_ok = parse(&g_user_doc, user, "user-data");
        else
            printf("cosmo-seed: user-data is not #cloud-config; it is ignored\n");
    }
    if (user_ok) {
        static const char *const user_keys[] = { "hostname", "ssh_authorized_keys", NULL };
        unknown_keys(&g_user_doc, g_user_doc.root, user_keys, "user-data");
    }

    static char last[256];
    long n = read_small(CLOUD_DIR "/instance-id", last, sizeof(last));
    if (n >= 0 && strcmp(trim(last), iid) == 0) {
        printf("cosmo-seed: instance %s already applied\n", iid);
    } else {
        if (mkdir("/var/lib", 0755) < 0 && errno != EEXIST)
            problem();
        if (mkdir(CLOUD_DIR, 0755) < 0 && errno != EEXIST) {
            printf("cosmo-seed: %s: %s\n", CLOUD_DIR, strerror(errno));
            return 1;
        }
        const char *host = user_ok ? yaml_str(&g_user_doc, -1, "hostname") : NULL;
        if (host == NULL)
            host = yaml_str(&g_meta_doc, -1, "local-hostname");
        if (host != NULL && host[0] != 0)
            apply_hostname(host);
        if (user_ok)
            apply_keys(&g_user_doc, yaml_get(&g_user_doc, -1, "ssh_authorized_keys"));
        char text[300];
        size_t len = (size_t)snprintf(text, sizeof(text), "%.250s\n", iid);
        if (write_whole(CLOUD_DIR "/instance-id", text, len, 0644) == 0)
            printf("cosmo-seed: instance %s applied\n", iid);
        else
            problem();
    }

    char *net = seed_text(d, "network-config", g_net);
    if (net != NULL && parse(&g_net_doc, net, "network-config"))
        apply_network(&g_net_doc);
    return g_status;
}
