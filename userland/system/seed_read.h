/*
 * seed_read.h - a cloud-init NoCloud seed, read from a block device's
 * sectors with no file system mounted (roadmap 1.3 R2; docs/userland/
 * design.md, "First boot without a console").
 *
 * A seed is an ISO 9660 volume whose primary volume identifier is
 * `cidata`, or a FAT12, FAT16 or FAT32 volume labelled `cidata` (either
 * case). Its files are in the root directory. Everything read from the
 * device is untrusted: every offset, length, count and cluster number is
 * checked against the device and the buffers before it is used, and a
 * volume that fails a check is "not a seed" or a read error, never a
 * read outside a buffer.
 *
 * Sectors are 512 bytes here; the caller's reader converts to the
 * device's own size. No allocation: the caller owns every buffer.
 */
#ifndef USERLAND_SEED_READ_H
#define USERLAND_SEED_READ_H

#include <stddef.h>
#include <stdint.h>

#define SEED_SECTOR 512u
#define SEED_FILE_MAX (64u * 1024u)   /* the largest seed file read */

/* `count` 512-byte sectors from `lba` into `buf`: 0, or nonzero when the
 * device cannot (past its end included). */
typedef int (*seed_read_fn)(void *ctx, uint64_t lba, uint32_t count, void *buf);

enum seed_kind { SEED_NONE = 0, SEED_ISO = 1, SEED_FAT = 2 };

/* What a probe found, for seed_file. */
struct seed_dev {
    seed_read_fn read;
    void *ctx;
    uint64_t sectors;        /* the device's size in 512-byte sectors */
    enum seed_kind kind;
    /* ISO 9660: the root directory to read names from (Joliet's when there
     * is one), and how its names are spelled. */
    uint64_t iso_root_lba;   /* in 512-byte sectors */
    uint32_t iso_root_len;   /* bytes */
    int iso_joliet;
    /* FAT. */
    int fat_bits;            /* 12, 16 or 32 */
    uint32_t spc;            /* sectors per cluster */
    uint64_t fat_lba;        /* the first FAT */
    uint32_t fat_sectors;    /* its length */
    uint64_t root_lba;       /* FAT12/16: the fixed root directory */
    uint32_t root_entries;   /* FAT12/16 */
    uint32_t root_cluster;   /* FAT32 */
    uint64_t data_lba;       /* cluster 2 */
    uint32_t clusters;       /* data clusters: valid numbers are 2 .. clusters + 1 */
};

/* Whether `d` (read, ctx and sectors set) holds a seed: SEED_ISO or
 * SEED_FAT with the rest of `d` filled in, SEED_NONE, or -1 when the
 * device could not be read. */
int seed_probe(struct seed_dev *d);

/* The root directory file `name` (compared ignoring case) of a probed
 * seed into `buf` (at most `max` bytes, max <= SEED_FILE_MAX); its length
 * in *len. 0, -ENOENT (no such file), -EFBIG (longer than max), -EIO (a
 * read failed) or -EINVAL (the volume's structures are inconsistent). */
int seed_file(const struct seed_dev *d, const char *name, uint8_t *buf, size_t max, size_t *len);

#endif /* USERLAND_SEED_READ_H */
