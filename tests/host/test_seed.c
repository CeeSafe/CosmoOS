/*
 * test_seed.c - cosmo-seed's readers on the host (roadmap 1.3 R2):
 * userland/system/seed_read.c and seed_yaml.c, built as they are.
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
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../../userland/system/seed_read.h"
#include "../../userland/system/seed_yaml.h"

static FILE *g_img;
static unsigned g_fails;

static int file_read(void *ctx, uint64_t lba, uint32_t count, void *buf)
{
    (void)ctx;
    if (fseeko(g_img, (off_t)(lba * SEED_SECTOR), SEEK_SET) != 0)
        return -1;
    return fread(buf, SEED_SECTOR, count, g_img) == count ? 0 : -1;
}

static int open_seed(const char *path, struct seed_dev *d)
{
    g_img = fopen(path, "rb");
    if (g_img == NULL)
        return -2;
    fseeko(g_img, 0, SEEK_END);
    memset(d, 0, sizeof(*d));
    d->read = file_read;
    d->sectors = (uint64_t)ftello(g_img) / SEED_SECTOR;
    return seed_probe(d);
}

static void dump(const struct yaml_doc *doc, int at, char *path, size_t plen)
{
    const struct yaml_node *n = yaml_at(doc, at);
    if (n == NULL)
        return;
    if (n->type == YAML_SCALAR) {
        printf("%.*s=%s\n", (int)plen, path, n->text);
        return;
    }
    unsigned i = 0;
    for (int c = n->child; c >= 0; c = doc->node[c].next, i++) {
        int add = n->type == YAML_MAP ? snprintf(path + plen, 1024 - plen, "%s%s", plen ? "." : "", doc->node[c].key)
                                       : snprintf(path + plen, 1024 - plen, "[%u]", i);
        dump(doc, c, path, plen + (size_t)add);
    }
    if (n->child < 0)
        printf("%.*s=%s\n", (int)plen, path, n->type == YAML_MAP ? "{}" : "[]");
}

#define CHECK(c)                                                         \
    do {                                                                 \
        if (!(c)) {                                                      \
            printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);        \
            g_fails++;                                                   \
        }                                                                \
    } while (0)

static struct yaml_doc g_doc;

static int parse(const char *text)
{
    static char buf[8192];
    snprintf(buf, sizeof(buf), "%s", text);
    return yaml_parse(&g_doc, buf);
}

static int self_test(void)
{
    CHECK(parse("#cloud-config\nhostname: c1  # a comment\nssh_authorized_keys:\n  - ssh-ed25519 AAAA k@h\n"
                "  - 'ssh-rsa B''C'\n") == 0);
    CHECK(strcmp(yaml_str(&g_doc, -1, "hostname"), "c1") == 0);
    int keys = yaml_get(&g_doc, -1, "ssh_authorized_keys");
    CHECK(keys >= 0 && g_doc.node[keys].type == YAML_LIST);
    int k0 = g_doc.node[keys].child, k1 = g_doc.node[k0].next;
    CHECK(strcmp(g_doc.node[k0].text, "ssh-ed25519 AAAA k@h") == 0 && strcmp(g_doc.node[k1].text, "ssh-rsa B'C") == 0);
    CHECK(parse("version: 2\nethernets:\n  eth0:\n    match:\n      macaddress: \"52:54:00:12:34:56\"\n"
                "    addresses: [10.0.2.50/24]\n    routes:\n    - to: default\n      via: 10.0.2.2\n"
                "    nameservers:\n      addresses: [10.0.2.3, '8.8.8.8']\n") == 0);
    CHECK(strcmp(yaml_str(&g_doc, -1, "ethernets.eth0.match.macaddress"), "52:54:00:12:34:56") == 0);
    int routes = yaml_get(&g_doc, -1, "ethernets.eth0.routes");
    CHECK(routes >= 0 && strcmp(yaml_str(&g_doc, g_doc.node[routes].child, "via"), "10.0.2.2") == 0);
    int ns = yaml_get(&g_doc, -1, "ethernets.eth0.nameservers.addresses");
    CHECK(ns >= 0 && strcmp(g_doc.node[g_doc.node[g_doc.node[ns].child].next].text, "8.8.8.8") == 0);
    CHECK(parse("a: |\n  text\n") == -1 && g_doc.error_line == 1);
    CHECK(parse("a: 1\n\tb: 2\n") == -1 && g_doc.error_line == 2);
    CHECK(parse("a: 1\n    b: 2\n") == -1);
    CHECK(parse("a: 1\na: 2\n") == -1);
    CHECK(parse("a: {b: 1}\n") == -1);
    CHECK(parse("a: &x 1\n") == -1);
    CHECK(parse("a: \"open\n") == -1);
    CHECK(parse("---\na: 1\n---\nb: 2\n") == -1);
    CHECK(parse("") == 0 && g_doc.root == -1);
    CHECK(parse("instance-id: iid-1\nlocal-hostname: c2\n") == 0 &&
          strcmp(yaml_str(&g_doc, -1, "instance-id"), "iid-1") == 0 && yaml_str(&g_doc, -1, "nope") == NULL);
    printf("seed yaml subset: %s\n", g_fails ? "FAIL" : "ok");
    return g_fails ? 1 : 0;
}

int main(int argc, char **argv)
{
    if (argc == 1)
        return self_test();
    struct seed_dev d;
    if (argc == 3 && strcmp(argv[1], "probe") == 0) {
        int rc = open_seed(argv[2], &d);
        puts(rc == SEED_ISO ? "iso" : rc == SEED_FAT ? "fat" : rc == SEED_NONE ? "none" : "error");
        return 0;
    }
    if (argc == 4 && strcmp(argv[1], "cat") == 0) {
        if (open_seed(argv[2], &d) <= 0) {
            puts("error: not a seed");
            return 1;
        }
        static uint8_t buf[SEED_FILE_MAX];
        size_t len;
        int rc = seed_file(&d, argv[3], buf, sizeof(buf), &len);
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
        if (yaml_parse(&g_doc, text) != 0) {
            printf("error: line %d: %s\n", g_doc.error_line, g_doc.error);
            return 3;
        }
        char path[1024];
        dump(&g_doc, g_doc.root, path, 0);
        return 0;
    }
    fprintf(stderr, "usage: test_seed [probe IMAGE | cat IMAGE NAME | yaml FILE]\n");
    return 2;
}
