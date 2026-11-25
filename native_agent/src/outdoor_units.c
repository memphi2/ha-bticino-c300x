#include "outdoor_units.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#include "file_io.h"
#include "json_util.h"
#include "string_util.h"

#define ARCHIVE_MAX_BYTES (128 * 1024)
#define CONF_MAX_BYTES (128 * 1024)

int c300x_unit_where_valid(const char *where)
{
    size_t length = where != NULL ? strlen(where) : 0;
    int digits = 0;

    if (length == 0 || length >= C300X_UNIT_WHERE_LEN) {
        return 0;
    }
    for (const char *p = where; *p != '\0'; p++) {
        if (isdigit((unsigned char)*p)) {
            digits++;
        } else if (*p != '#' || digits == 0) {
            return 0;
        } else {
            digits = 0;
        }
    }
    return digits > 0;
}

void c300x_unit_id_from_where(const char *where, char *out, size_t out_len)
{
    c300x_copy_string(out, out_len, where);
    for (char *p = out; *p != '\0'; p++) {
        if (*p == '#') {
            *p = '_';
        }
    }
}

void c300x_unit_action_where(const char *where, char *out, size_t out_len)
{
    c300x_copy_string(out, out_len, where);
    char *hash = strchr(out, '#');
    if (hash != NULL) {
        *hash = '\0';
    }
}

/* The value of attribute name inside one tag [start, end), entities decoded. */
static int tag_attribute(const char *start, const char *end, const char *name, char *out, size_t out_len)
{
    size_t name_len = strlen(name);

    out[0] = '\0';
    for (const char *p = start; p + name_len + 2 < end; p++) {
        if (strncmp(p, name, name_len) != 0 || !isspace((unsigned char)p[-1])) {
            continue;
        }
        const char *q = p + name_len;
        while (q < end && isspace((unsigned char)*q)) q++;
        if (q >= end || *q != '=') continue;
        q++;
        while (q < end && isspace((unsigned char)*q)) q++;
        if (q >= end || (*q != '"' && *q != '\'')) continue;
        char quote = *q++;
        size_t used = 0;
        while (q < end && *q != quote && used + 1 < out_len) {
            static const char *const entities[][2] = {
                {"&amp;", "&"}, {"&lt;", "<"}, {"&gt;", ">"}, {"&quot;", "\""}, {"&apos;", "'"},
            };
            char c = *q++;
            if (c == '&') {
                for (size_t e = 0; e < sizeof(entities) / sizeof(entities[0]); e++) {
                    size_t entity_len = strlen(entities[e][0]);
                    if ((size_t)(end - (q - 1)) >= entity_len && strncmp(q - 1, entities[e][0], entity_len) == 0) {
                        c = entities[e][1][0];
                        q += entity_len - 1;
                        break;
                    }
                }
            }
            out[used++] = c;
        }
        out[used] = '\0';
        return 1;
    }
    return 0;
}

static int add_unit(struct c300x_outdoor_units *units, const char *where, const char *name, const char *source)
{
    struct c300x_outdoor_unit *unit;

    if (units->count >= C300X_MAX_OUTDOOR_UNITS || !c300x_unit_where_valid(where)) {
        return -1;
    }
    unit = &units->items[units->count];
    memset(unit, 0, sizeof(*unit));
    c300x_copy_string(unit->where, sizeof(unit->where), where);
    c300x_unit_id_from_where(where, unit->id, sizeof(unit->id));
    c300x_unit_action_where(where, unit->action_where, sizeof(unit->action_where));
    c300x_copy_string(unit->lock_where, sizeof(unit->lock_where), unit->action_where);
    c300x_copy_string(unit->name, sizeof(unit->name), name != NULL ? name : "");
    c300x_copy_string(unit->source, sizeof(unit->source), source);
    return units->count++;
}

static int join_address(char *out, size_t out_len, const char *dev, const char *where)
{
    return snprintf(out, out_len, "%s%s", dev, where) < (int)out_len && c300x_unit_where_valid(out);
}

/* Outdoor units are the <ist> without cid of an <obj> (locks have cid 10060
 * and the address of their unit, so a unit's lock is its action_where); the
 * bus address is the obj's dev followed by the ist's where. */
static void parse_archive(struct c300x_outdoor_units *units, const char *xml)
{
    const char *obj = xml;

    while ((obj = strstr(obj, "<obj")) != NULL) {
        const char *obj_end = strchr(obj, '>');
        char dev[8];
        if (obj_end == NULL) break;
        if (!tag_attribute(obj, obj_end, "dev", dev, sizeof(dev)) || dev[0] == '\0') {
            c300x_copy_string(dev, sizeof(dev), "2");
        }
        const char *close = obj_end[-1] == '/' ? obj_end : strstr(obj_end, "</obj>");
        if (close == NULL) close = obj_end + strlen(obj_end);
        for (const char *ist = strstr(obj_end, "<ist"); ist != NULL && ist < close; ist = strstr(ist + 4, "<ist")) {
            const char *ist_end = strchr(ist, '>');
            char where[C300X_UNIT_WHERE_LEN], cid[16], name[C300X_UNIT_NAME_LEN], address[C300X_UNIT_WHERE_LEN];
            if (ist_end == NULL) break;
            if (!tag_attribute(ist, ist_end, "where", where, sizeof(where))
                || !join_address(address, sizeof(address), dev, where)) {
                continue;
            }
            if (tag_attribute(ist, ist_end, "cid", cid, sizeof(cid))) {
                continue;
            }
            (void)tag_attribute(ist, ist_end, "descr", name, sizeof(name));
            for (int index = 0; index < units->count; index++) {
                if (strcmp(units->items[index].where, address) == 0) {
                    address[0] = '\0';
                }
            }
            if (address[0] != '\0') {
                add_unit(units, address, name, "archive");
            }
        }
        obj = close;
    }
}

static int element_text(const char *start, const char *end, const char *name, char *out, size_t out_len)
{
    char open[32], close[32];
    snprintf(open, sizeof(open), "<%s>", name);
    snprintf(close, sizeof(close), "</%s>", name);
    const char *value = strstr(start, open);
    if (value == NULL || value >= end) return 0;
    value += strlen(open);
    const char *value_end = strstr(value, close);
    if (value_end == NULL || value_end > end) return 0;
    while (value < value_end && isspace((unsigned char)*value)) value++;
    while (value_end > value && isspace((unsigned char)value_end[-1])) value_end--;
    if ((size_t)(value_end - value) >= out_len) return 0;
    memcpy(out, value, (size_t)(value_end - value));
    out[value_end - value] = '\0';
    return 1;
}

/* setup/vdes/communication/p_default: dev + address (2, 0 -> 20). */
static int default_from_conf(const char *xml, char *out, size_t out_len)
{
    char dev[8], address[16];
    const char *block = xml != NULL ? strstr(xml, "<p_default>") : NULL;
    const char *block_end = block != NULL ? strstr(block, "</p_default>") : NULL;

    return block_end != NULL
        && element_text(block, block_end, "dev", dev, sizeof(dev))
        && element_text(block, block_end, "address", address, sizeof(address))
        && join_address(out, out_len, dev, address);
}

void c300x_outdoor_units_build(struct c300x_outdoor_units *units, const char *archive_xml,
                               const char *archive_state, const char *conf_xml,
                               const char *fallback_devaddr, const char *default_lock)
{
    struct c300x_outdoor_unit seen[C300X_MAX_OUTDOOR_UNITS];
    int seen_count = 0;
    char default_where[C300X_UNIT_WHERE_LEN];
    char learned[C300X_UNIT_WHERE_LEN] = "";
    const struct c300x_outdoor_unit *previous = units->loaded ? c300x_outdoor_units_default(units) : NULL;

    if (previous != NULL && strcmp(previous->source, "default") == 0) {
        c300x_copy_string(learned, sizeof(learned), previous->where);
    }

    for (int index = 0; units->loaded && index < units->count; index++) {
        if (strcmp(units->items[index].source, "seen") == 0) {
            seen[seen_count++] = units->items[index];
        }
    }
    units->count = 0;
    units->default_index = -1;
    units->loaded = 1;
    c300x_copy_string(units->archive, sizeof(units->archive), archive_state);
    if (archive_xml != NULL) {
        parse_archive(units, archive_xml);
        if (units->count == 0 && strcmp(archive_state, "ok") == 0) {
            c300x_copy_string(units->archive, sizeof(units->archive), "empty");
        }
    }
    if (!default_from_conf(conf_xml, default_where, sizeof(default_where))) {
        c300x_copy_string(default_where, sizeof(default_where),
            c300x_unit_where_valid(fallback_devaddr) ? fallback_devaddr : "20");
    }
    for (int index = 0; index < units->count && units->default_index < 0; index++) {
        if (strcmp(units->items[index].action_where, default_where) == 0
            || strcmp(units->items[index].where, default_where) == 0) {
            units->default_index = index;
        }
    }
    if (units->default_index < 0) {
        char action[C300X_UNIT_WHERE_LEN];
        c300x_unit_action_where(learned, action, sizeof(action));
        /* A qualifier the default unit learned from a caller frame stays. */
        units->default_index = add_unit(units, strcmp(action, default_where) == 0 ? learned : default_where,
                                        "", "default");
        if (units->default_index >= 0) {
            c300x_unit_id_from_where(default_where, units->items[units->default_index].id,
                                     sizeof(units->items[0].id));
        }
    }
    if (units->default_index >= 0 && c300x_unit_where_valid(default_lock)) {
        c300x_copy_string(units->items[units->default_index].lock_where,
            sizeof(units->items[0].lock_where), default_lock);
    }
    for (int index = 0; index < seen_count && units->count < C300X_MAX_OUTDOOR_UNITS; index++) {
        if (c300x_outdoor_units_find_id(units, seen[index].id) < 0) {
            units->items[units->count++] = seen[index];
        }
    }
}

/* No stat(): the device's old libc does not export it. */
static char *read_file(const char *path, size_t limit, const char **state)
{
    char *text = malloc(limit);
    int truncated = 0;

    errno = 0;
    if (text == NULL || !read_bounded_text_file(path, text, limit, &truncated) || truncated) {
        *state = text != NULL && errno == ENOENT ? "missing" : "unreadable";
        free(text);
        return NULL;
    }
    *state = "ok";
    return text;
}

void c300x_outdoor_units_load(struct c300x_outdoor_units *units, const char *archive_path,
                              const char *conf_path, const char *fallback_devaddr,
                              const char *default_lock)
{
    const char *archive_state = "missing";
    const char *conf_state = "missing";
    char *archive = read_file(archive_path, ARCHIVE_MAX_BYTES, &archive_state);
    char *conf = read_file(conf_path, CONF_MAX_BYTES, &conf_state);
    c300x_outdoor_units_build(units, archive, archive_state, conf, fallback_devaddr, default_lock);
    free(archive);
    free(conf);
}

int c300x_outdoor_units_find_id(const struct c300x_outdoor_units *units, const char *id)
{
    for (int index = 0; id != NULL && index < units->count; index++) {
        if (strcmp(units->items[index].id, id) == 0) {
            return index;
        }
    }
    return -1;
}

int c300x_outdoor_units_find_lock(const struct c300x_outdoor_units *units, const char *address)
{
    for (int index = 0; address != NULL && index < units->count; index++) {
        if (strcmp(units->items[index].lock_where, address) == 0) {
            return index;
        }
    }
    return -1;
}

int c300x_outdoor_units_note_caller(struct c300x_outdoor_units *units, const char *where, int *changed)
{
    char action[C300X_UNIT_WHERE_LEN];

    *changed = 0;
    if (!c300x_unit_where_valid(where)) {
        return -1;
    }
    for (int index = 0; index < units->count; index++) {
        if (strcmp(units->items[index].where, where) == 0) {
            return index;
        }
    }
    c300x_unit_action_where(where, action, sizeof(action));
    if (units->default_index >= 0) {
        struct c300x_outdoor_unit *unit = &units->items[units->default_index];
        /* The default from conf.xml knows no qualifier: it learns the caller's. */
        if (strcmp(unit->source, "default") == 0 && strcmp(unit->where, unit->action_where) == 0
            && strcmp(unit->action_where, action) == 0) {
            c300x_copy_string(unit->where, sizeof(unit->where), where);
            *changed = 1;
            return units->default_index;
        }
    }
    int index = add_unit(units, where, "", "seen");
    *changed = index >= 0;
    return index;
}

const struct c300x_outdoor_unit *c300x_outdoor_units_default(const struct c300x_outdoor_units *units)
{
    return units->default_index >= 0 && units->default_index < units->count
        ? &units->items[units->default_index] : NULL;
}

int c300x_outdoor_units_json(const struct c300x_outdoor_units *units, char *out, size_t out_len)
{
    size_t used = 0;
    char name[C300X_JSON_QUOTED_LEN(C300X_UNIT_NAME_LEN)];
    const struct c300x_outdoor_unit *fallback = c300x_outdoor_units_default(units);

    if (!c300x_appendf(out, out_len, &used, "{\"ok\":true,\"default_unit\":\"%s\",\"archive\":\"%s\",\"units\":[",
                       fallback != NULL ? fallback->id : "", units->archive)) {
        return 0;
    }
    for (int index = 0; index < units->count; index++) {
        const struct c300x_outdoor_unit *unit = &units->items[index];
        if (!c300x_appendf(out, out_len, &used,
                "%s{\"id\":\"%s\",\"where\":\"%s\",\"action_where\":\"%s\",\"lock_where\":\"%s\","
                "\"name\":%s,\"source\":\"%s\",\"default\":%s}",
                index > 0 ? "," : "", unit->id, unit->where, unit->action_where, unit->lock_where,
                c300x_json_string(unit->name, name, sizeof(name)), unit->source,
                index == units->default_index ? "true" : "false")) {
            return 0;
        }
    }
    return c300x_appendf(out, out_len, &used, "]}\n");
}
