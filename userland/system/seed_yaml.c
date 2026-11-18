/* seed_yaml.c - the YAML subset a NoCloud seed needs (seed_yaml.h). */
#include "seed_yaml.h"

#include <stdbool.h>
#include <string.h>

#define LINES_MAX 1024

struct line {
    int indent;
    char *s;   /* the content: indentation, comment and trailing blanks removed */
    int no;    /* from 1 */
};

struct parser {
    struct yaml_doc *doc;
    struct line line[LINES_MAX];
    int n, i;
};

static int fail(struct parser *p, int no, const char *why)
{
    if (p->doc->error == NULL) {
        p->doc->error = why;
        p->doc->error_line = no;
    }
    return -1;
}

static int new_node(struct parser *p, enum yaml_type t, int no)
{
    if (p->doc->count >= YAML_NODES_MAX)
        return fail(p, no, "too many nodes");
    int k = p->doc->count++;
    struct yaml_node *nd = &p->doc->node[k];
    memset(nd, 0, sizeof(*nd));
    nd->type = t;
    nd->child = nd->next = -1;
    nd->text = "";
    return k;
}

static void append(struct parser *p, int parent, int last, int k)
{
    if (last < 0)
        p->doc->node[parent].child = k;
    else
        p->doc->node[last].next = k;
}

static char *trim(char *s)
{
    while (*s == ' ')
        s++;
    size_t n = strlen(s);
    while (n > 0 && s[n - 1] == ' ')
        s[--n] = 0;
    return s;
}

/* The end of a quoted scalar starting at s (on the quote): the closing quote, or NULL. */
static char *quote_end(char *s)
{
    char q = *s;
    for (char *t = s + 1; *t; t++) {
        if (q == '"' && *t == '\\' && t[1])
            t++;
        else if (*t == q) {
            if (q == '\'' && t[1] == '\'')
                t++;
            else
                return t;
        }
    }
    return NULL;
}

/* A scalar in place: quotes removed and escapes resolved. NULL with an error. */
static const char *scalar(struct parser *p, char *s, int no)
{
    s = trim(s);
    if (*s == '\'' || *s == '"') {
        char *end = quote_end(s);
        if (end == NULL || *trim(end + 1) != 0)
            return fail(p, no, "an unterminated quoted scalar or text after it"), NULL;
        char q = *s, *w = s, *r = s + 1;
        for (; r < end; r++) {
            if (q == '\'' && *r == '\'')
                r++;   /* '' is one quote */
            else if (q == '"' && *r == '\\') {
                r++;
                char c = *r == 'n' ? '\n' : *r == 't' ? '\t' : *r;
                if (c != '\n' && c != '\t' && c != '\\' && c != '"' && c != '/')
                    return fail(p, no, "an escape outside \\n \\t \\\\ \\\" \\/"), NULL;
                *w++ = c;
                continue;
            }
            *w++ = *r;
        }
        *w = 0;
        return s;
    }
    if (strchr("{&*!|>%@`", *s) && *s)
        return fail(p, no, "a flow map, anchor, alias, tag or block scalar (not in the subset)"), NULL;
    for (char *t = s; *t; t++)
        if (*t == ':' && (t[1] == ' ' || t[1] == 0))
            return fail(p, no, "a map inside a value on one line (not in the subset)"), NULL;
    return s;
}

static int scalar_node(struct parser *p, char *s, int no)
{
    const char *t = scalar(p, s, no);
    if (t == NULL)
        return -1;
    int k = new_node(p, YAML_SCALAR, no);
    if (k >= 0)
        p->doc->node[k].text = t;
    return k;
}

/* A value on a line: a flow list or a scalar. */
static int inline_value(struct parser *p, char *s, int no)
{
    s = trim(s);
    if (*s != '[')
        return scalar_node(p, s, no);
    size_t n = strlen(s);
    if (s[n - 1] != ']')
        return fail(p, no, "a flow list without its ']'");
    s[n - 1] = 0;
    int list = new_node(p, YAML_LIST, no), last = -1;
    if (list < 0)
        return -1;
    char *e = trim(s + 1);
    if (*e == 0)
        return list;
    for (;;) {
        char *comma;
        if (*e == '\'' || *e == '"') {
            char *q = quote_end(e);
            if (q == NULL)
                return fail(p, no, "an unterminated quoted scalar");
            comma = strchr(q, ',');
        } else {
            if (*e == '[')
                return fail(p, no, "a nested flow list (not in the subset)");
            comma = strchr(e, ',');
        }
        if (comma)
            *comma = 0;
        int k = scalar_node(p, e, no);
        if (k < 0)
            return -1;
        append(p, list, last, k);
        last = k;
        if (!comma)
            return list;
        e = trim(comma + 1);
    }
}

static bool is_dash(const char *s) { return s[0] == '-' && (s[1] == ' ' || s[1] == 0); }

/* Where a "key:" ends (the colon), or NULL: a colon followed by a blank or the line's end, after a plain or quoted
 * key. */
static char *key_colon(char *s)
{
    char *t = s;
    if (*t == '\'' || *t == '"') {
        t = quote_end(t);
        if (t == NULL)
            return NULL;
        t++;
        while (*t == ' ')
            t++;
        return *t == ':' && (t[1] == ' ' || t[1] == 0) ? t : NULL;
    }
    if (*t == '[' || *t == '{')
        return NULL;
    for (; *t; t++)
        if (*t == ':' && (t[1] == ' ' || t[1] == 0))
            return t;
    return NULL;
}

static int node(struct parser *p, int ind);

static int list(struct parser *p, int ind)
{
    int k = new_node(p, YAML_LIST, p->line[p->i].no), last = -1;
    if (k < 0)
        return -1;
    while (p->i < p->n && p->line[p->i].indent == ind && is_dash(p->line[p->i].s)) {
        struct line *l = &p->line[p->i];
        char *content = l->s + 1;
        while (*content == ' ')
            content++;
        int item;
        if (*content == 0) {
            p->i++;
            if (p->i < p->n && p->line[p->i].indent > ind)
                item = node(p, p->line[p->i].indent);
            else
                item = scalar_node(p, content, l->no);
        } else {
            /* The item's content starts a node at its own column: "- to: x" then "  via: y". */
            l->indent += (int)(content - l->s);
            l->s = content;
            item = node(p, l->indent);
        }
        if (item < 0)
            return -1;
        append(p, k, last, item);
        last = item;
    }
    if (p->i < p->n && p->line[p->i].indent > ind)
        return fail(p, p->line[p->i].no, "indentation that belongs to nothing");
    return k;
}

static int map(struct parser *p, int ind)
{
    int k = new_node(p, YAML_MAP, p->line[p->i].no), last = -1;
    if (k < 0)
        return -1;
    while (p->i < p->n && p->line[p->i].indent == ind) {
        struct line *l = &p->line[p->i];
        if (is_dash(l->s))
            return fail(p, l->no, "a list item where a map entry was expected");
        char *colon = key_colon(l->s);
        if (colon == NULL)
            return fail(p, l->no, "a line that is not a map entry");
        *colon = 0;
        const char *key = scalar(p, l->s, l->no);
        if (key == NULL)
            return -1;
        for (int e = p->doc->node[k].child; e >= 0; e = p->doc->node[e].next)
            if (strcmp(p->doc->node[e].key, key) == 0)
                return fail(p, l->no, "a key given twice");
        char *rest = trim(colon + 1);
        p->i++;
        int value;
        if (*rest != 0)
            value = inline_value(p, rest, l->no);
        else if (p->i < p->n && p->line[p->i].indent > ind)
            value = node(p, p->line[p->i].indent);
        else if (p->i < p->n && p->line[p->i].indent == ind && is_dash(p->line[p->i].s))
            value = list(p, ind);   /* "key:" then "- a" at the key's own column */
        else
            value = scalar_node(p, rest, l->no);   /* empty: null */
        if (value < 0)
            return -1;
        p->doc->node[value].key = key;
        append(p, k, last, value);
        last = value;
    }
    if (p->i < p->n && p->line[p->i].indent > ind)
        return fail(p, p->line[p->i].no, "indentation that belongs to nothing");
    return k;
}

static int node(struct parser *p, int ind)
{
    struct line *l = &p->line[p->i];
    if (is_dash(l->s))
        return list(p, ind);
    if (key_colon(l->s) != NULL)
        return map(p, ind);
    p->i++;
    return inline_value(p, l->s, l->no);
}

int yaml_parse(struct yaml_doc *doc, char *text)
{
    static struct parser ps;
    struct parser *p = &ps;
    memset(p, 0, sizeof(*p));
    p->doc = doc;
    doc->count = 0;
    doc->root = -1;
    doc->error = NULL;
    doc->error_line = 0;
    int no = 0;
    bool started = false;
    for (char *s = text; s != NULL;) {
        char *nl = strchr(s, '\n');
        if (nl)
            *nl = 0;
        no++;
        size_t len = strlen(s);
        if (len > 0 && s[len - 1] == '\r')
            s[--len] = 0;
        int ind = 0;
        while (s[ind] == ' ')
            ind++;
        if (s[ind] == '\t')
            return fail(p, no, "a tab in the indentation");
        /* The comment: a '#' at the start or after a blank, outside quotes. */
        char *c = s + ind;
        char q = 0;
        for (char *t = c; *t; t++) {
            if (q) {
                if (q == '"' && *t == '\\' && t[1])
                    t++;
                else if (*t == q)
                    q = 0;
            } else if ((*t == '\'' || *t == '"') && (t == c || t[-1] == ' ' || t[-1] == '[' || t[-1] == ',' ||
                                                      t[-1] == ':' || t[-1] == '-')) {
                q = *t;
            } else if (*t == '#' && (t == c || t[-1] == ' ')) {
                *t = 0;
                break;
            }
        }
        c = trim(c);
        if (*c != 0) {
            if (strcmp(c, "---") == 0 || strcmp(c, "...") == 0) {
                if (started || strcmp(c, "...") == 0)
                    return fail(p, no, "a second document (not in the subset)");
            } else {
                if (p->n >= LINES_MAX)
                    return fail(p, no, "too many lines");
                p->line[p->n++] = (struct line){ .indent = ind, .s = c, .no = no };
            }
            started = true;
        }
        s = nl ? nl + 1 : NULL;
    }
    if (p->n == 0)
        return 0;
    int r = node(p, p->line[0].indent);
    if (r < 0)
        return -1;
    if (p->i < p->n)
        return fail(p, p->line[p->i].no, "indentation that belongs to nothing");
    doc->root = r;
    return 0;
}

int yaml_get(const struct yaml_doc *doc, int from, const char *path)
{
    int at = from < 0 ? doc->root : from;
    const char *s = path;
    while (at >= 0 && *s) {
        const char *dot = strchr(s, '.');
        size_t n = dot ? (size_t)(dot - s) : strlen(s);
        if (doc->node[at].type != YAML_MAP)
            return -1;
        int found = -1;
        for (int e = doc->node[at].child; e >= 0; e = doc->node[e].next)
            if (strlen(doc->node[e].key) == n && memcmp(doc->node[e].key, s, n) == 0) {
                found = e;
                break;
            }
        at = found;
        s = dot ? dot + 1 : s + n;
    }
    return at;
}

const char *yaml_str(const struct yaml_doc *doc, int from, const char *path)
{
    int k = yaml_get(doc, from, path);
    return k >= 0 && doc->node[k].type == YAML_SCALAR ? doc->node[k].text : NULL;
}
