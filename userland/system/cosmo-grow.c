/*
 * cosmo-grow - fit a copied disk image to the disk it is on (roadmap 1.3
 * R2; docs/userland/design.md, "First boot without a console").
 *
 *   cosmo-grow --table DEVICE   DEVICE a partition (init passes the root)
 *                               or a whole disk
 *
 * An image copied to a larger disk keeps its GPT where it was: the kernel
 * accepts it, with the backup header short of the last sector (gpt.h's
 * backup_lba). --table moves the table to the disk's real size: the usable
 * range ends where a table for this disk ends, the backup entries and
 * header move to the last sectors, and the partition DEVICE names, when it
 * is the CosmoOS root and the last partition on the disk, grows to the new
 * end of the usable range. Then RESCAN.
 *
 * Only a table exactly as gpt_build writes it (cosmo-install's, and so the
 * cloud image's) is rewritten: the table is rebuilt for its old size and
 * compared byte for byte with the disk first, so nothing it holds -- an
 * attribute, a name, a third-party layout -- is lost by the rebuild. The
 * new backup is written first and the primary last: until the primary
 * lands the old table, which the kernel still accepts, is the disk's.
 *
 * Quiet when there is nothing to do, which is every boot but the first on
 * a larger disk. Exit 0 done or nothing to do, 1 failed (the old table
 * still the disk's, or the new one whole), 2 usage, 3 refused (a table
 * gpt_build did not write).
 */

#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <kernel/gpt.h>
#include <uapi/cosmo/blkctl.h>

#include "blkdevs.h"

#define HEAD_MAX (GPT_BUILD_HEAD_SECTORS(512) * 512 > GPT_BUILD_HEAD_SECTORS(4096) * 4096 \
                      ? GPT_BUILD_HEAD_SECTORS(512) * 512 : GPT_BUILD_HEAD_SECTORS(4096) * 4096)

static uint8_t g_head[HEAD_MAX], g_tail[HEAD_MAX];   /* the table being written */
static uint8_t g_disk[HEAD_MAX];                     /* what the disk holds, to compare */
static uint8_t g_scratch[GPT_SCRATCH_BYTES];
static struct gpt_table g_table;

static int disk_read(void *ctx, uint64_t lba, uint32_t count, void *buf)
{
    return blkdevs_read(ctx, lba, count, buf) == 0 ? 0 : -1;
}

/* A disk of `n` sectors holding only g_head and g_tail: the new table, parsed before it is written. */
struct mem_disk {
    uint32_t ss;
    uint64_t n;
};

static int mem_read(void *ctx, uint64_t lba, uint32_t count, void *buf)
{
    const struct mem_disk *d = ctx;
    uint64_t head = GPT_BUILD_HEAD_SECTORS(d->ss), tail0 = d->n - GPT_BUILD_TAIL_SECTORS(d->ss);
    for (uint32_t i = 0; i < count; i++) {
        uint8_t *out = (uint8_t *)buf + (size_t)i * d->ss;
        uint64_t s = lba + i;
        if (s < head)
            memcpy(out, g_head + s * d->ss, d->ss);
        else if (s >= tail0 && s < d->n)
            memcpy(out, g_tail + (s - tail0) * d->ss, d->ss);
        else
            memset(out, 0, d->ss);
    }
    return 0;
}

/* The table's partitions as gpt_build takes them. */
static unsigned build_parts(const struct gpt_table *t, struct gpt_build_part *out)
{
    for (unsigned i = 0; i < t->nparts; i++) {
        memset(&out[i], 0, sizeof(out[i]));
        out[i].index = t->parts[i].index;
        out[i].first_lba = t->parts[i].first_lba;
        out[i].last_lba = t->parts[i].last_lba;
        memcpy(out[i].type, t->parts[i].type, 16);
        memcpy(out[i].uuid, t->parts[i].uuid, 16);
    }
    return t->nparts;
}

/* Whether the disk's table is gpt_build's for a disk of `n0` sectors: rebuilt, and equal byte for byte. */
static bool is_built(const struct cosmo_blkctl_dev *disk, const struct gpt_table *t, uint64_t n0)
{
    uint32_t ss = disk->sector_size;
    struct gpt_build_part parts[GPT_MAX_PARTS];
    unsigned np = build_parts(t, parts);
    if (t->nr_entries != GPT_BUILD_ENTRIES || t->entry_size != GPT_BUILD_ENTRY_SIZE ||
        t->first_usable != gpt_build_first_usable(ss) || t->last_usable != gpt_build_last_usable(ss, n0))
        return false;
    for (unsigned i = 0; i < t->nparts; i++)
        if (t->parts[i].attrs != 0)
            return false;
    if (!gpt_build(ss, n0, t->disk_guid, parts, np, g_head, g_tail))
        return false;
    size_t hb = (size_t)GPT_BUILD_HEAD_SECTORS(ss) * ss, tb = (size_t)GPT_BUILD_TAIL_SECTORS(ss) * ss;
    if (blkdevs_read(disk, 0, GPT_BUILD_HEAD_SECTORS(ss), g_disk) != 0 || memcmp(g_disk, g_head, hb) != 0)
        return false;
    if (blkdevs_read(disk, n0 - GPT_BUILD_TAIL_SECTORS(ss), GPT_BUILD_TAIL_SECTORS(ss), g_disk) != 0 ||
        memcmp(g_disk, g_tail, tb) != 0)
        return false;
    return true;
}

static int grow_table(const char *name)
{
    if (strncmp(name, "/dev/", 5) == 0)
        name += 5;
    int rc = blkdevs_list();
    if (rc < 0) {
        fprintf(stderr, "cosmo-grow: cannot list the block devices: %s\n", strerror(-rc));
        return 1;
    }
    const struct cosmo_blkctl_dev *dev = blkdevs_find(name);
    if (dev == NULL) {
        fprintf(stderr, "cosmo-grow: %s: no such device\n", name);
        return 2;
    }
    const struct cosmo_blkctl_dev *disk = dev;
    uint32_t grow_index = 0;   /* the partition to grow; 0 for none */
    if (dev->flags & COSMO_BLKCTL_PART) {
        disk = blkdevs_find(dev->disk);
        grow_index = dev->index;
        if (disk == NULL) {
            fprintf(stderr, "cosmo-grow: %s: its disk %s is not listed\n", name, dev->disk);
            return 1;
        }
    }
    char dname[COSMO_BLKCTL_NAME];
    strcpy(dname, disk->name);
    uint32_t ss = disk->sector_size;
    uint64_t n = disk->sectors;
    const char *why = "";
    struct cosmo_blkctl_dev rd = *disk;   /* gpt_parse's context is not const */
    enum gpt_result r = gpt_parse(ss, n, disk_read, &rd, g_scratch, &g_table, &why);
    if (r == GPT_NONE)
        return 0;   /* no table: nothing of ours to fit */
    if (r != GPT_OK) {
        fprintf(stderr, "cosmo-grow: %s: the partition table cannot be read: %s\n", dname,
                r == GPT_IO ? "an I/O error" : why);
        return 1;
    }
    if (g_table.backup_lba == n - 1)
        return 0;   /* the table fits the disk: every boot but the first on a larger one */
    uint64_t n0 = g_table.backup_lba + 1;
    if (!is_built(disk, &g_table, n0)) {
        fprintf(stderr, "cosmo-grow: %s: the disk grew from %llu to %llu sectors, but its partition table is not "
                        "one cosmo-install wrote; it is left as it is\n",
                dname, (unsigned long long)n0, (unsigned long long)n);
        return 3;
    }

    struct gpt_build_part parts[GPT_MAX_PARTS];
    unsigned np = build_parts(&g_table, parts);
    uint64_t last_end = 0;
    for (unsigned i = 0; i < np; i++)
        if (parts[i].last_lba > last_end)
            last_end = parts[i].last_lba;
    int grown = -1;
    uint64_t old_last = 0;
    for (unsigned i = 0; i < np && grow_index != 0; i++) {
        if (parts[i].index != grow_index)
            continue;
        if (memcmp(parts[i].type, gpt_type_cosmo_root, 16) != 0)
            printf("cosmo-grow: %s is not a CosmoOS root partition; it keeps its size\n", name);
        else if (parts[i].last_lba != last_end)
            printf("cosmo-grow: %s is not the last partition on %s; it keeps its size\n", name, dname);
        else {
            grown = (int)i;
            old_last = parts[i].last_lba;
            parts[i].last_lba = gpt_build_last_usable(ss, n);
        }
    }
    if (!gpt_build(ss, n, g_table.disk_guid, parts, np, g_head, g_tail)) {
        fprintf(stderr, "cosmo-grow: %s: cannot lay out a table for %llu sectors\n", dname, (unsigned long long)n);
        return 1;
    }
    static struct gpt_table check;
    struct mem_disk md = { ss, n };
    if (gpt_parse(ss, n, mem_read, &md, g_scratch, &check, &why) != GPT_OK || check.nparts != np ||
        check.backup_lba != n - 1) {
        fprintf(stderr, "cosmo-grow: %s: the table built does not parse: %s\n", dname, why);
        return 1;
    }

    /* The backup first: until the primary is written the old table, whose backup is untouched, is the disk's. */
    rc = blkdevs_write(disk, n - GPT_BUILD_TAIL_SECTORS(ss), GPT_BUILD_TAIL_SECTORS(ss), g_tail);
    if (rc == 0)
        rc = blkdevs_flush(disk);
    if (rc == 0)
        rc = blkdevs_write(disk, 0, GPT_BUILD_HEAD_SECTORS(ss), g_head);
    if (rc == 0)
        rc = blkdevs_flush(disk);
    if (rc < 0) {
        fprintf(stderr, "cosmo-grow: %s: writing the partition table: %s\n", dname, strerror(-rc));
        return 1;
    }
    /* The old backup header is now inside a partition or free space: cleared, so nothing finds a stale table. */
    memset(g_disk, 0, ss);
    if (blkdevs_write(disk, n0 - 1, 1, g_disk) != 0 || blkdevs_flush(disk) != 0)
        printf("cosmo-grow: %s: the old backup header at sector %llu was not cleared\n", dname,
               (unsigned long long)(n0 - 1));

    printf("cosmo-grow: %s: the partition table now covers %llu sectors (it covered %llu)\n", dname,
           (unsigned long long)n, (unsigned long long)n0);
    if (grown >= 0)
        printf("cosmo-grow: %s: %llu sectors, was %llu\n", name,
               (unsigned long long)(parts[grown].last_lba - parts[grown].first_lba + 1),
               (unsigned long long)(old_last - parts[grown].first_lba + 1));
    unsigned nparts = 0;
    rc = blkdevs_rescan(dname, &nparts);
    if (rc == -EBUSY) {
        printf("cosmo-grow: %s: a partition is in use; the new sizes apply from the next boot\n", dname);
        return 0;
    }
    if (rc < 0 || nparts != np) {
        fprintf(stderr, "cosmo-grow: %s: rescanning the partitions: %s\n", dname,
                rc < 0 ? strerror(-rc) : "a different number of partitions appeared");
        return 1;
    }
    fflush(stdout);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 3 && strcmp(argv[1], "--table") == 0)
        return grow_table(argv[2]);
    fprintf(stderr, "usage: cosmo-grow --table DEVICE\n");
    return 2;
}
