/* seed_read.c - a NoCloud seed read from sectors (seed_read.h). */
#include "seed_read.h"

#include <errno.h>
#include <stdbool.h>
#include <string.h>

static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t le32(const uint8_t *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }

static int lower(int c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }

static bool same_ci(const char *a, size_t alen, const char *b)
{
    size_t blen = strlen(b);
    if (alen != blen)
        return false;
    for (size_t i = 0; i < alen; i++)
        if (lower((unsigned char)a[i]) != lower((unsigned char)b[i]))
            return false;
    return true;
}

/* `n` bytes at byte `off` of the device: -EIO past its end or on a failed read. */
static int rd(const struct seed_dev *d, uint64_t off, void *out, size_t n)
{
    uint8_t sec[SEED_SECTOR];
    uint8_t *o = out;
    if (off > d->sectors * SEED_SECTOR || n > d->sectors * SEED_SECTOR - off)
        return -EIO;
    while (n > 0) {
        uint64_t lba = off / SEED_SECTOR;
        size_t at = (size_t)(off % SEED_SECTOR);
        size_t take = SEED_SECTOR - at < n ? SEED_SECTOR - at : n;
        if (d->read(d->ctx, lba, 1, sec) != 0)
            return -EIO;
        memcpy(o, sec + at, take);
        o += take;
        off += take;
        n -= take;
    }
    return 0;
}

/* Whether `len` bytes at byte `off` lie on the device. */
static bool on_device(const struct seed_dev *d, uint64_t off, uint64_t len)
{
    uint64_t size = d->sectors * SEED_SECTOR;
    return off <= size && len <= size - off;
}

/* An 11- or 32-byte label padded with spaces (or NULs) is `cidata`. */
static bool is_cidata(const uint8_t *p, size_t n)
{
    while (n > 0 && (p[n - 1] == ' ' || p[n - 1] == 0))
        n--;
    return same_ci((const char *)p, n, "cidata");
}

/* ---- ISO 9660 (ECMA-119), with Joliet and Rock Ridge names ---------------------------------------------------- */

#define ISO_BLOCK 2048u
#define ISO_DIR_MAX (1024u * 1024u)   /* the largest root directory read */

/* A directory record's extent and length, checked to lie on the device. */
static bool iso_extent(const struct seed_dev *d, const uint8_t *rec, uint64_t *off, uint32_t *len)
{
    uint64_t extent = le32(rec + 2);
    *len = le32(rec + 10);
    *off = extent * ISO_BLOCK;
    return on_device(d, *off, *len);
}

static int probe_iso(struct seed_dev *d)
{
    uint8_t vd[ISO_BLOCK];
    bool seed = false, joliet = false;
    uint8_t root[34], jroot[34];
    for (unsigned i = 0; i < 32; i++) {
        int rc = rd(d, (16u + i) * (uint64_t)ISO_BLOCK, vd, sizeof(vd));
        if (rc != 0)
            return i == 0 ? SEED_NONE : -1;   /* a device too small for a descriptor is not an ISO */
        if (memcmp(vd + 1, "CD001", 5) != 0 || vd[6] != 1)
            break;
        if (vd[0] == 255)
            break;
        if (vd[0] == 1 && !seed && is_cidata(vd + 40, 32)) {
            seed = true;
            memcpy(root, vd + 156, sizeof(root));
        } else if (vd[0] == 2 && vd[88] == '%' && vd[89] == '/' && (vd[90] == '@' || vd[90] == 'C' || vd[90] == 'E')) {
            joliet = true;
            memcpy(jroot, vd + 156, sizeof(jroot));
        }
    }
    if (!seed)
        return SEED_NONE;
    const uint8_t *use = joliet ? jroot : root;
    uint64_t off;
    uint32_t len;
    if (use[0] < 34 || !iso_extent(d, use, &off, &len) || len == 0 || len > ISO_DIR_MAX || off % SEED_SECTOR != 0)
        return SEED_NONE;
    d->kind = SEED_ISO;
    d->iso_root_lba = off / SEED_SECTOR;
    d->iso_root_len = len;
    d->iso_joliet = joliet;
    return SEED_ISO;
}

/* A record's name into `out` (at most 255 bytes): Joliet's UCS-2, else a Rock Ridge NM, else the ISO name; a version
 * (";1") and an ISO name's trailing '.' are dropped. Its length, or -1 when the record is inconsistent. */
static int iso_name(const uint8_t *rec, size_t reclen, bool joliet, char *out)
{
    size_t nl = rec[32];
    if (33 + nl > reclen)
        return -1;
    const uint8_t *nm = rec + 33;
    size_t n = 0;
    if (joliet) {
        if (nl % 2 != 0)
            return -1;
        for (size_t i = 0; i + 1 < nl && n < 255; i += 2)
            out[n++] = nm[i] == 0 && nm[i + 1] < 128 ? (char)nm[i + 1] : '?';
    } else {
        /* System use: after the name and a pad byte when its length is even. */
        size_t su = 33 + nl + (nl % 2 == 0 ? 1 : 0);
        bool rr = false;
        while (su + 4 <= reclen) {
            size_t elen = rec[su + 2];
            if (elen < 4 || su + elen > reclen)
                break;
            if (rec[su] == 'N' && rec[su + 1] == 'M' && elen >= 5 && (rec[su + 4] & 0x6) == 0) {
                for (size_t i = 5; i < elen && n < 255; i++)
                    out[n++] = (char)rec[su + i];
                rr = true;
            }
            su += elen;
        }
        if (rr)
            return (int)n;
        /* An ISO name cannot hold '-' (d-characters): mkisofs-style tools write '_' for it. */
        for (size_t i = 0; i < nl && n < 255; i++)
            out[n++] = nm[i] == '_' ? '-' : (char)nm[i];
    }
    for (size_t i = 0; i < n; i++)
        if (out[i] == ';') {
            n = i;
            break;
        }
    if (!joliet && n > 0 && out[n - 1] == '.')
        n--;
    return (int)n;
}

static int iso_file(const struct seed_dev *d, const char *name, uint8_t *buf, size_t max, size_t *len)
{
    uint8_t blk[ISO_BLOCK];
    uint64_t base = d->iso_root_lba * SEED_SECTOR;
    for (uint32_t at = 0; at < d->iso_root_len; at += ISO_BLOCK) {
        uint32_t span = d->iso_root_len - at < ISO_BLOCK ? d->iso_root_len - at : ISO_BLOCK;
        if (rd(d, base + at, blk, span) != 0)
            return -EIO;
        uint32_t pos = 0;
        while (pos < span) {
            size_t rl = blk[pos];
            if (rl == 0)
                break;   /* the rest of this block is padding */
            if (rl < 34 || pos + rl > span)
                return -EINVAL;
            const uint8_t *rec = blk + pos;
            pos += (uint32_t)rl;
            if (rec[25] & 0x2)
                continue;   /* a directory: ".", ".." or a subdirectory */
            char got[256];
            int gl = iso_name(rec, rl, d->iso_joliet, got);
            if (gl < 0)
                return -EINVAL;
            if (!same_ci(got, (size_t)gl, name))
                continue;
            if (rec[25] & 0x80)
                return -EINVAL;   /* a file in several extents: not something a seed needs */
            uint64_t off;
            uint32_t flen;
            if (!iso_extent(d, rec, &off, &flen))
                return -EINVAL;
            if (flen > max)
                return -EFBIG;
            if (rd(d, off, buf, flen) != 0)
                return -EIO;
            *len = flen;
            return 0;
        }
    }
    return -ENOENT;
}

/* ---- FAT12, FAT16, FAT32 --------------------------------------------------------------------------------------- */

static int probe_fat(struct seed_dev *d)
{
    uint8_t b[SEED_SECTOR];
    if (d->sectors < 1 || d->read(d->ctx, 0, 1, b) != 0)
        return -1;
    if (b[510] != 0x55 || b[511] != 0xAA || le16(b + 11) != SEED_SECTOR)
        return SEED_NONE;
    uint32_t spc = b[13], rsvd = le16(b + 14), nfats = b[16], rootent = le16(b + 17);
    if (spc == 0 || (spc & (spc - 1)) != 0 || spc > 128 || rsvd == 0 || nfats == 0 || nfats > 4)
        return SEED_NONE;
    uint32_t total = le16(b + 19) ? le16(b + 19) : le32(b + 32);
    uint32_t fatsz = le16(b + 22) ? le16(b + 22) : le32(b + 36);
    uint32_t rootsecs = (rootent * 32u + SEED_SECTOR - 1) / SEED_SECTOR;
    uint64_t first = (uint64_t)rsvd + (uint64_t)nfats * fatsz + rootsecs;
    if (fatsz == 0 || total > d->sectors || first >= total)
        return SEED_NONE;
    uint32_t clusters = (uint32_t)((total - first) / spc);
    int bits = clusters < 4085 ? 12 : clusters < 65525 ? 16 : 32;
    if (bits == 32 && (rootent != 0 || le16(b + 22) != 0))
        return SEED_NONE;
    if (bits != 32 && rootent == 0)
        return SEED_NONE;
    /* The FAT must hold an entry for every cluster. */
    if ((uint64_t)fatsz * SEED_SECTOR * 8 / (uint64_t)bits < (uint64_t)clusters + 2)
        return SEED_NONE;
    d->fat_bits = bits;
    d->spc = spc;
    d->fat_lba = rsvd;
    d->fat_sectors = fatsz;
    d->root_lba = (uint64_t)rsvd + (uint64_t)nfats * fatsz;
    d->root_entries = rootent;
    d->root_cluster = bits == 32 ? le32(b + 44) : 0;
    d->data_lba = first;
    d->clusters = clusters;
    if (bits == 32 && (d->root_cluster < 2 || d->root_cluster > clusters + 1))
        return SEED_NONE;
    const uint8_t *label = bits == 32 ? (b[66] == 0x29 ? b + 71 : NULL) : (b[38] == 0x29 ? b + 43 : NULL);
    d->kind = SEED_FAT;
    if (label != NULL && is_cidata(label, 11))
        return SEED_FAT;
    /* Or the root directory's volume label entry; seed_file finds it under this name. */
    size_t len;
    int rc = seed_file(d, "\001label", NULL, 0, &len);
    if (rc == 0)
        return SEED_FAT;
    d->kind = SEED_NONE;
    return rc == -EIO ? -1 : SEED_NONE;
}

/* The FAT's entry for cluster `c`, or -1 when it cannot be read. */
static int64_t fat_next(const struct seed_dev *d, uint32_t c)
{
    uint64_t off = d->fat_bits == 12 ? c + c / 2 : d->fat_bits == 16 ? 2ull * c : 4ull * c;
    uint8_t v[4] = { 0 };
    size_t n = d->fat_bits == 32 ? 4 : 2;
    if (off + n > (uint64_t)d->fat_sectors * SEED_SECTOR || rd(d, d->fat_lba * SEED_SECTOR + off, v, n) != 0)
        return -1;
    if (d->fat_bits == 12)
        return c & 1 ? le16(v) >> 4 : le16(v) & 0xFFF;
    if (d->fat_bits == 16)
        return le16(v);
    return le32(v) & 0x0FFFFFFF;
}

static bool fat_eoc(const struct seed_dev *d, int64_t v)
{
    return d->fat_bits == 12 ? v >= 0xFF8 : d->fat_bits == 16 ? v >= 0xFFF8 : v >= 0x0FFFFFF8;
}

static bool fat_cluster_ok(const struct seed_dev *d, int64_t c) { return c >= 2 && c <= (int64_t)d->clusters + 1; }

static uint64_t cluster_off(const struct seed_dev *d, uint32_t c)
{
    return (d->data_lba + (uint64_t)(c - 2) * d->spc) * SEED_SECTOR;
}

/* A long name being gathered from its entries, which come before the short entry, last part first. */
struct lfn {
    char name[256];
    unsigned parts, next;   /* parts in the set; the sequence number expected next (counting down) */
    uint8_t sum;
    bool ok;
};

static uint8_t short_sum(const uint8_t *e)
{
    uint8_t s = 0;
    for (int i = 0; i < 11; i++)
        s = (uint8_t)(((s & 1) << 7) + (s >> 1) + e[i]);
    return s;
}

static void lfn_take(struct lfn *l, const uint8_t *e)
{
    unsigned seq = e[0] & 0x1F;
    if (e[0] & 0x40) {
        memset(l, 0, sizeof(*l));
        if (seq == 0 || seq > 19)
            return;
        l->parts = seq;
        l->next = seq;
        l->sum = e[13];
        l->ok = true;
    }
    if (!l->ok || seq != l->next || e[13] != l->sum) {
        l->ok = false;
        return;
    }
    static const uint8_t at[13] = { 1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30 };
    for (unsigned i = 0; i < 13; i++) {
        uint16_t ch = le16(e + at[i]);
        size_t pos = (seq - 1) * 13 + i;
        if (pos >= 255)
            break;
        l->name[pos] = ch == 0 || ch == 0xFFFF ? 0 : ch < 128 ? (char)ch : '?';
    }
    l->next--;
}

/* One 32-byte directory entry against `name`: 1 matched (its first cluster and size out), 0 not, -1 the end. The
 * name "\001label" matches the volume label entry when it reads `cidata`. */
static int fat_entry(const uint8_t *e, struct lfn *l, const char *name, uint32_t *cluster, uint32_t *size, int bits)
{
    if (e[0] == 0)
        return -1;
    if (e[0] == 0xE5) {
        l->ok = false;
        return 0;
    }
    if (e[11] == 0x0F) {
        lfn_take(l, e);
        return 0;
    }
    bool use_lfn = l->ok && l->next == 0 && l->sum == short_sum(e);
    l->ok = false;
    if (e[11] & 0x08)
        return strcmp(name, "\001label") == 0 && is_cidata(e, 11);
    if (e[11] & 0x10)
        return 0;   /* a directory */
    char got[256];
    size_t n = 0;
    if (use_lfn) {
        memcpy(got, l->name, sizeof(l->name));
        got[255] = 0;
        n = strlen(got);
    } else {
        for (int i = 0; i < 8 && e[i] != ' '; i++)
            got[n++] = (char)(i == 0 && e[0] == 0x05 ? 0xE5 : e[i]);
        if (e[8] != ' ') {
            got[n++] = '.';
            for (int i = 8; i < 11 && e[i] != ' '; i++)
                got[n++] = (char)e[i];
        }
    }
    if (!same_ci(got, n, name))
        return 0;
    *cluster = (bits == 32 ? (uint32_t)le16(e + 20) << 16 : 0) | le16(e + 26);
    *size = le32(e + 28);
    return 1;
}

static int fat_read_chain(const struct seed_dev *d, uint32_t c, uint32_t size, uint8_t *buf)
{
    uint64_t csize = (uint64_t)d->spc * SEED_SECTOR;
    uint32_t done = 0, steps = 0;
    uint32_t seen[SEED_FILE_MAX / SEED_SECTOR];   /* a file of at most 64 KiB has at most this many clusters */
    while (done < size) {
        if (!fat_cluster_ok(d, c) || steps >= sizeof(seen) / sizeof(seen[0]))
            return -EINVAL;
        for (uint32_t k = 0; k < steps; k++)
            if (seen[k] == c)
                return -EINVAL;   /* the chain comes back on itself */
        seen[steps++] = c;
        uint32_t take = size - done < csize ? size - done : (uint32_t)csize;
        if (rd(d, cluster_off(d, c), buf + done, take) != 0)
            return -EIO;
        done += take;
        if (done == size)
            break;
        int64_t nx = fat_next(d, c);
        if (nx < 0)
            return -EIO;
        if (fat_eoc(d, nx))
            return -EINVAL;   /* the chain ends before the file */
        c = (uint32_t)nx;
    }
    return 0;
}

static int fat_file(const struct seed_dev *d, const char *name, uint8_t *buf, size_t max, size_t *len)
{
    uint8_t sec[SEED_SECTOR];
    struct lfn l;
    memset(&l, 0, sizeof(l));
    uint32_t cluster = 0, size = 0;
    int found = 0;
    if (d->fat_bits != 32) {
        for (uint32_t i = 0; i < d->root_entries && found == 0; i++) {
            if (i % 16 == 0 && rd(d, (d->root_lba + i / 16) * SEED_SECTOR, sec, SEED_SECTOR) != 0)
                return -EIO;
            found = fat_entry(sec + (i % 16) * 32, &l, name, &cluster, &size, d->fat_bits);
        }
    } else {
        uint32_t c = d->root_cluster, steps = 0;
        while (found == 0) {
            if (!fat_cluster_ok(d, c) || ++steps > d->clusters)
                return -EINVAL;
            for (uint32_t s = 0; s < d->spc && found == 0; s++) {
                if (rd(d, cluster_off(d, c) + (uint64_t)s * SEED_SECTOR, sec, SEED_SECTOR) != 0)
                    return -EIO;
                for (unsigned k = 0; k < 16 && found == 0; k++)
                    found = fat_entry(sec + k * 32, &l, name, &cluster, &size, 32);
            }
            if (found != 0)
                break;
            int64_t nx = fat_next(d, c);
            if (nx < 0)
                return -EIO;
            if (fat_eoc(d, nx))
                break;
            c = (uint32_t)nx;
        }
    }
    if (found != 1)
        return -ENOENT;
    if (buf == NULL) {   /* the label */
        *len = 0;
        return 0;
    }
    if (size > max)
        return -EFBIG;
    if (size > 0) {
        int rc = fat_read_chain(d, cluster, size, buf);
        if (rc != 0)
            return rc;
    }
    *len = size;
    return 0;
}

/* ---- the API ---------------------------------------------------------------------------------------------------- */

int seed_probe(struct seed_dev *d)
{
    d->kind = SEED_NONE;
    int rc = probe_iso(d);
    if (rc != SEED_NONE)
        return rc;
    return probe_fat(d);
}

int seed_file(const struct seed_dev *d, const char *name, uint8_t *buf, size_t max, size_t *len)
{
    if (max > SEED_FILE_MAX)
        max = SEED_FILE_MAX;
    *len = 0;
    if (d->kind == SEED_ISO)
        return iso_file(d, name, buf, max, len);
    if (d->kind == SEED_FAT)
        return fat_file(d, name, buf, max, len);
    return -EINVAL;
}
