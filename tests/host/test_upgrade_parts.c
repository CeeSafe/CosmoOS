/*
 * test_upgrade_parts.c - cosmo-upgrade's pure CeeSafe parts on the host:
 * userland/system/upgrade_parts.cee, the C generated from it built for the
 * host. The boot archive's header fields (a ustar number, a ".." name) and
 * the rewrite of the project's old address in a text (docs/development.md,
 * "The project's addresses"). The files around that rewrite are
 * upgrade_conf.cee's, built for CosmoOS only (its open flags are the
 * system's).
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* upgrade_parts.cee's exports, as cosmo-upgrade.c declares them too. */
uint64_t upgrade_ustar_octal(const uint8_t *f, size_t n, int32_t *ok);
bool upgrade_has_dotdot(const char *name);
uint32_t upgrade_address_move_text(uint8_t *buf, size_t n);

static int g_fail;
#define CHECK(c)                                                              \
    do {                                                                      \
        if (!(c)) {                                                           \
            fprintf(stderr, "test_upgrade_parts: FAIL %s (line %d)\n", #c, __LINE__); \
            g_fail++;                                                         \
        }                                                                     \
    } while (0)

static uint64_t oct(const char *f, size_t n, int32_t *ok)
{
    *ok = 1;
    return upgrade_ustar_octal((const uint8_t *)f, n, ok);
}

#define OLD "https://vkuttyp.github.io/CosmoOS/"
#define NEW "https://ceesafe.github.io/CosmoOS/"

int main(void)
{
    int32_t ok;
    /* ustar numbers: digits after spaces, then NULs or spaces. */
    CHECK(oct("0000644\0", 8, &ok) == 0644 && ok == 1);
    CHECK(oct("  17 \0\0\0", 8, &ok) == 017 && ok == 1);
    CHECK(oct("00000001000\0", 12, &ok) == 01000 && ok == 1);
    CHECK(oct("\0\0\0\0\0\0\0\0", 8, &ok) == 0 && ok == 1);
    CHECK((oct("0000648\0", 8, &ok), ok == 0));      /* an 8 */
    CHECK((oct("12 3\0\0\0\0", 8, &ok), ok == 0));   /* a digit after the field's end */
    CHECK((oct("12x\0\0\0\0\0", 8, &ok), ok == 0));
    /* an already failed field stays failed */
    ok = 0;
    CHECK((upgrade_ustar_octal((const uint8_t *)"0644\0\0\0\0", 8, &ok), ok == 0));

    /* ".." as a whole component only */
    CHECK(upgrade_has_dotdot(".."));
    CHECK(upgrade_has_dotdot("../etc/passwd"));
    CHECK(upgrade_has_dotdot("etc/../passwd"));
    CHECK(upgrade_has_dotdot("etc//..//x"));
    CHECK(upgrade_has_dotdot("etc/.."));
    CHECK(!upgrade_has_dotdot("etc/..x"));
    CHECK(!upgrade_has_dotdot("etc/x.."));
    CHECK(!upgrade_has_dotdot("etc/.../x"));
    CHECK(!upgrade_has_dotdot("etc/./x"));
    CHECK(!upgrade_has_dotdot(""));

    /* the address in a buffer: every occurrence, in place, nothing else changed */
    char text[] = "local file:///var/lib/pkg/repo\ncosmoos " OLD "repo/aarch64\n# " OLD "\nother https://example.com/\n";
    char want[] = "local file:///var/lib/pkg/repo\ncosmoos " NEW "repo/aarch64\n# " NEW "\nother https://example.com/\n";
    CHECK(upgrade_address_move_text((uint8_t *)text, strlen(text)) == 2 && strcmp(text, want) == 0);
    CHECK(upgrade_address_move_text((uint8_t *)text, strlen(text)) == 0);   /* already moved */
    char cut[] = OLD;
    CHECK(upgrade_address_move_text((uint8_t *)cut, strlen(cut) - 1) == 0);   /* a prefix cut short is not one */
    CHECK(upgrade_address_move_text((uint8_t *)"", 0) == 0);

    if (g_fail) {
        fprintf(stderr, "test_upgrade_parts: %d failed\n", g_fail);
        return 1;
    }
    printf("test_upgrade_parts: ok\n");
    return 0;
}
