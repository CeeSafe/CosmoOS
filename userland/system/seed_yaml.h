/*
 * seed_yaml.h - the YAML a NoCloud seed needs, and nothing else (roadmap
 * 1.3 R2; docs/userland/design.md, "First boot without a console").
 *
 * Block maps, block lists (a list item may itself be a map: "- to: x" with
 * "  via: y" under it), flow lists of scalars ("[a, b]"), plain, single-
 * and double-quoted scalars, and comments. Anything else -- anchors, tags,
 * block scalars ("|", ">"), flow maps, tabs for indentation, a second
 * document -- is a parse error, and the caller skips the file. The parser
 * works in the caller's buffer (scalars are NUL-terminated in place) and a
 * fixed arena: no allocation.
 */
#ifndef USERLAND_SEED_YAML_H
#define USERLAND_SEED_YAML_H

#include <stddef.h>

enum yaml_type { YAML_SCALAR = 1, YAML_MAP = 2, YAML_LIST = 3 };

struct yaml_node {
    enum yaml_type type;
    const char *key;     /* an entry of a map: its key; else NULL */
    const char *text;    /* a scalar's text */
    int child, next;     /* indices into the arena, -1 for none: a map's entries or a list's items, in order */
};

#define YAML_NODES_MAX 512

struct yaml_doc {
    struct yaml_node node[YAML_NODES_MAX];
    int count;
    int root;            /* -1: an empty document */
    int error_line;      /* from 1, when the parse failed */
    const char *error;
};

/* Parse `text` (NUL-terminated, modified in place). 0, or -1 with
 * doc->error and doc->error_line set. */
int yaml_parse(struct yaml_doc *doc, char *text);

/* The node at `path` from `from` (-1: the root): map keys separated by
 * '.', e.g. "nameservers.addresses". -1 when there is none. */
int yaml_get(const struct yaml_doc *doc, int from, const char *path);
/* The scalar's text at `path`, or NULL (absent, or not a scalar). */
const char *yaml_str(const struct yaml_doc *doc, int from, const char *path);

static inline const struct yaml_node *yaml_at(const struct yaml_doc *doc, int i)
{
    return i >= 0 && i < doc->count ? &doc->node[i] : NULL;
}

#endif /* USERLAND_SEED_YAML_H */
