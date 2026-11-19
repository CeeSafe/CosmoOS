/*
 * test_seed.c - cosmo-seed's readers on the host (roadmap 1.3 R2):
 * userland/system/seed.cee's ISO 9660 and FAT readers and its YAML subset,
 * the C generated from it built for the host.
 *
 *   test_seed                  the YAML subset's own checks (make host-test)
 *   test_seed probe IMAGE      "iso", "fat", "none" or "error"
 *   test_seed cat IMAGE NAME   the file's bytes, or "error: ..." and exit 1
 *   test_seed yaml FILE        every scalar as "path=value", or "error: line N: ..." and exit 3
 *
 * tests/host/test_seed.py drives the last three over images
 * tools/mkseed.py writes.
 */
#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* seed.cee's exports, as cosmo-seed.cee declares them too. */
int32_t seed_probe(int32_t (*read)(void *, uint64_t, uint32_t, void *), void *ctx, uint64_t sectors);
int32_t seed_file(const char *name, uint8_t *buf, size_t max, size_t *len);
int32_t yaml_parse(uint32_t slot, char *text);
int32_t yaml_error_line(uint32_t slot);
const char *yaml_error(uint32_t slot);
int32_t yaml_root(uint32_t slot);
int32_t yaml_type(uint32_t slot, int32_t i);
int32_t yaml_child(uint32_t slot, int32_t i);
int32_t yaml_next(uint32_t slot, int32_t i);
const char *yaml_key(uint32_t slot, int32_t i);
const char *yaml_text(uint32_t slot, int32_t i);
int32_t yaml_get(uint32_t slot, int32_t from, const char *path);
const char *yaml_str(uint32_t slot, int32_t from, const char *path);

enum { SEED_NONE = 0, SEED_ISO = 1, SEED_FAT = 2 };
enum { YAML_SCALAR = 1, YAML_MAP = 2, YAML_LIST = 3 };
#define SEED_SECTOR 512u
#define SEED_FILE_MAX (64u * 1024u)

static FILE *g_img;
static unsigned g_fails;
static unsigned long g_reads;   /* the reader's calls, which `cat` prints to stderr */

static int32_t file_read(void *ctx, uint64_t lba, uint32_t count, void *buf)
{
    (void)ctx;
    g_reads++;
    /* fseek, not fseeko: glibc hides fseeko under strict C, and a seed is small. */
    if (lba > (uint64_t)LONG_MAX / SEED_SECTOR || fseek(g_img, (long)(lba * SEED_SECTOR), SEEK_SET) != 0)
        return -1;
    return fread(buf, SEED_SECTOR, count, g_img) == count ? 0 : -1;
}

static int open_seed(const char *path)
{
    g_img = fopen(path, "rb");
    if (g_img == NULL)
        return -2;
    long size = fseek(g_img, 0, SEEK_END) == 0 ? ftell(g_img) : -1;
    if (size < 0)
        return -2;
    return seed_probe(file_read, NULL, (uint64_t)size / SEED_SECTOR);
}

static void dump(int at, char *path, size_t plen)
{
    int type = yaml_type(0, at);
    if (type == 0)
        return;
    if (type == YAML_SCALAR) {
        printf("%.*s=%s\n", (int)plen, path, yaml_text(0, at));
        return;
    }
    unsigned i = 0;
    for (int c = yaml_child(0, at); c >= 0; c = yaml_next(0, c), i++) {
        int add = type == YAML_MAP ? snprintf(path + plen, 1024 - plen, "%s%s", plen ? "." : "", yaml_key(0, c))
                                   : snprintf(path + plen, 1024 - plen, "[%u]", i);
        dump(c, path, plen + (size_t)add);
    }
    if (yaml_child(0, at) < 0)
        printf("%.*s=%s\n", (int)plen, path, type == YAML_MAP ? "{}" : "[]");
}

#define CHECK(c)                                                         \
    do {                                                                 \
        if (!(c)) {                                                      \
            printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);        \
            g_fails++;                                                   \
        }                                                                \
    } while (0)

static int parse(const char *text)
{
    static char buf[8192];
    snprintf(buf, sizeof(buf), "%s", text);
    return yaml_parse(0, buf);
}

static int same(const char *a, const char *b) { return a != NULL && b != NULL && strcmp(a, b) == 0; }

static int self_test(void)
{
    CHECK(parse("#cloud-config\nhostname: c1  # a comment\nssh_authorized_keys:\n  - ssh-ed25519 AAAA k@h\n"
                "  - 'ssh-rsa B''C'\n") == 0);
    CHECK(same(yaml_str(0, -1, "hostname"), "c1"));
    int keys = yaml_get(0, -1, "ssh_authorized_keys");
    CHECK(keys >= 0 && yaml_type(0, keys) == YAML_LIST);
    int k0 = yaml_child(0, keys), k1 = yaml_next(0, k0);
    CHECK(same(yaml_text(0, k0), "ssh-ed25519 AAAA k@h") && same(yaml_text(0, k1), "ssh-rsa B'C"));
    CHECK(parse("version: 2\nethernets:\n  eth0:\n    match:\n      macaddress: \"52:54:00:12:34:56\"\n"
                "    addresses: [10.0.2.50/24]\n    routes:\n    - to: default\n      via: 10.0.2.2\n"
                "    nameservers:\n      addresses: [10.0.2.3, '8.8.8.8']\n") == 0);
    CHECK(same(yaml_str(0, -1, "ethernets.eth0.match.macaddress"), "52:54:00:12:34:56"));
    int routes = yaml_get(0, -1, "ethernets.eth0.routes");
    CHECK(routes >= 0 && same(yaml_str(0, yaml_child(0, routes), "via"), "10.0.2.2"));
    int ns = yaml_get(0, -1, "ethernets.eth0.nameservers.addresses");
    CHECK(ns >= 0 && same(yaml_text(0, yaml_next(0, yaml_child(0, ns))), "8.8.8.8"));
    CHECK(parse("a: |\n  text\n") == -1 && yaml_error_line(0) == 1);
    CHECK(parse("a: 1\n\tb: 2\n") == -1 && yaml_error_line(0) == 2);
    CHECK(parse("a: 1\n    b: 2\n") == -1);
    CHECK(parse("a: 1\na: 2\n") == -1);
    CHECK(parse("a: {b: 1}\n") == -1);
    CHECK(parse("a: &x 1\n") == -1);
    CHECK(parse("a: \"open\n") == -1);
    CHECK(parse("---\na: 1\n---\nb: 2\n") == -1);
    CHECK(parse("") == 0 && yaml_root(0) == -1);
    CHECK(parse("instance-id: iid-1\nlocal-hostname: c2\n") == 0 && same(yaml_str(0, -1, "instance-id"), "iid-1") &&
          yaml_str(0, -1, "nope") == NULL);
    /* Three documents at once, as cosmo-seed holds meta-data, user-data and network-config. */
    static char a[64], b[64];
    snprintf(a, sizeof(a), "x: 1\n");
    snprintf(b, sizeof(b), "x: 2\n");
    CHECK(yaml_parse(1, a) == 0 && yaml_parse(2, b) == 0 && same(yaml_str(1, -1, "x"), "1") &&
          same(yaml_str(2, -1, "x"), "2"));
    CHECK(yaml_parse(3, a) == -1);   /* no fourth */
    printf("seed yaml subset: %s\n", g_fails ? "FAIL" : "ok");
    return g_fails ? 1 : 0;
}

int main(int argc, char **argv)
{
    if (argc == 1)
        return self_test();
    if (argc == 3 && strcmp(argv[1], "probe") == 0) {
        int rc = open_seed(argv[2]);
        puts(rc == SEED_ISO ? "iso" : rc == SEED_FAT ? "fat" : rc == SEED_NONE ? "none" : "error");
        return 0;
    }
    if (argc == 4 && strcmp(argv[1], "cat") == 0) {
        if (open_seed(argv[2]) <= 0) {
            puts("error: not a seed");
            return 1;
        }
        static uint8_t buf[SEED_FILE_MAX];
        size_t len;
        int rc = seed_file(argv[3], buf, sizeof(buf), &len);
        fprintf(stderr, "reads=%lu\n", g_reads);
        if (rc != 0) {
            printf("error: %s\n", rc == -ENOENT ? "ENOENT" : rc == -EFBIG ? "EFBIG" : rc == -EIO ? "EIO" : "EINVAL");
            return 1;
        }
        fwrite(buf, 1, len, stdout);
        return 0;
    }
    if (argc == 3 && strcmp(argv[1], "yaml") == 0) {
        static char text[SEED_FILE_MAX + 1];
        FILE *f = fopen(argv[2], "rb");
        size_t n = f ? fread(text, 1, SEED_FILE_MAX, f) : 0;
        text[n] = 0;
        if (yaml_parse(0, text) != 0) {
            printf("error: line %d: %s\n", yaml_error_line(0), yaml_error(0));
            return 3;
        }
        char path[1024];
        dump(yaml_root(0), path, 0);
        return 0;
    }
    fprintf(stderr, "usage: test_seed [probe IMAGE | cat IMAGE NAME | yaml FILE]\n");
    return 2;
}
