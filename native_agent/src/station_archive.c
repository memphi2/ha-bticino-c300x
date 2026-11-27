#include "station_archive.h"

#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "file_io.h"
#include "string_util.h"

#define ARCHIVE_MAX_BYTES (128 * 1024)
#define CONF_MAX_BYTES (128 * 1024)
#define OUTDOOR_UNITS_CID "10050"

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

/* The tag <name ...> or <name/> at or after from; NULL when there is none. */
static const char *find_tag(const char *from, const char *name)
{
    size_t name_len = strlen(name);

    for (const char *p = strchr(from, '<'); p != NULL; p = strchr(p + 1, '<')) {
        char next = p[1 + name_len];
        if (strncmp(p + 1, name, name_len) == 0 && (isspace((unsigned char)next) || next == '/' || next == '>')) {
            return p;
        }
    }
    return NULL;
}

/* Cuts text to fit out_len without splitting a UTF-8 character. */
static void fit_utf8(char *text, size_t used)
{
    size_t end = used;

    while (end > 0 && ((unsigned char)text[end - 1] & 0xC0) == 0x80) {
        end--;
    }
    if (end > 0 && ((unsigned char)text[end - 1] & 0x80) != 0) {
        /* A lead byte: keep it only with all of its continuation bytes. */
        unsigned char lead = (unsigned char)text[end - 1];
        size_t want = lead >= 0xF0 ? 4 : lead >= 0xE0 ? 3 : 2;
        if (used - (end - 1) < want) {
            used = end - 1;
        }
    }
    text[used] = '\0';
}

/* The value of attribute name inside the tag [start, end), entities
 * decoded: 1 found, 0 absent, -1 longer than out_len (a name is cut). */
static int tag_attribute(const char *start, const char *end, const char *name, char *out, size_t out_len,
                         int may_cut)
{
    static const char *const entities[][2] = {
        {"&amp;", "&"}, {"&lt;", "<"}, {"&gt;", ">"}, {"&quot;", "\""}, {"&apos;", "'"},
    };
    size_t name_len = strlen(name);

    out[0] = '\0';
    for (const char *p = start + 1; p + name_len + 2 < end; p++) {
        if (!isspace((unsigned char)p[-1]) || strncmp(p, name, name_len) != 0) {
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
        while (q < end && *q != quote) {
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
            if (used + 1 >= out_len) {
                if (!may_cut) {
                    out[0] = '\0';
                    return -1;
                }
                fit_utf8(out, used);
                return 1;
            }
            out[used++] = c;
        }
        out[used] = '\0';
        return 1;
    }
    return 0;
}

struct place {
    char cid[16];
    char dev[8];
    char where[C300X_UNIT_WHERE_LEN];
    char name[C300X_UNIT_NAME_LEN];
    int has_cid;
    int valid;
};

/* The attributes of one tag; an attribute it lacks keeps the value in place
 * (its <obj>'s). The tag's cid is its own. */
static void read_place(const char *start, const char *end, struct place *place)
{
    place->has_cid = tag_attribute(start, end, "cid", place->cid, sizeof(place->cid), 0) == 1;
    char value[C300X_UNIT_NAME_LEN];
    int found = tag_attribute(start, end, "dev", value, sizeof(place->dev), 0);
    if (found != 0) {
        place->valid &= found > 0;
        c300x_copy_string(place->dev, sizeof(place->dev), value);
    }
    found = tag_attribute(start, end, "where", value, sizeof(place->where), 0);
    if (found != 0) {
        place->valid &= found > 0;
        c300x_copy_string(place->where, sizeof(place->where), value);
    }
    if (tag_attribute(start, end, "descr", value, sizeof(value), 1) > 0) {
        c300x_copy_string(place->name, sizeof(place->name), value);
    }
}

/* The bus address: dev (2 when the archive has none) followed by where. */
static int place_address(const struct place *place, char *out, size_t out_len)
{
    const char *dev = place->dev[0] != '\0' ? place->dev : "2";

    return place->valid && snprintf(out, out_len, "%s%s", dev, place->where) < (int)out_len
        && c300x_unit_where_valid(out);
}

static void add_entry(struct c300x_archive_entry *entries, int *count, const char *where, const char *name)
{
    for (int index = 0; index < *count; index++) {
        if (strcmp(entries[index].where, where) == 0) {
            return;
        }
    }
    if (*count < C300X_ARCHIVE_MAX_ENTRIES) {
        c300x_copy_string(entries[*count].where, sizeof(entries[0].where), where);
        c300x_copy_string(entries[*count].name, sizeof(entries[0].name), name);
        (*count)++;
    }
}

static void parse_object(struct c300x_station_archive *archive, const struct place *object,
                         const char *body, const char *close)
{
    for (const char *ist = find_tag(body, "ist"); ist != NULL && ist < close; ist = find_tag(ist + 1, "ist")) {
        const char *ist_end = strchr(ist, '>');
        struct place place = *object;
        char address[C300X_UNIT_WHERE_LEN];

        if (ist_end == NULL || ist_end > close) {
            return;
        }
        read_place(ist, ist_end, &place);
        if (!place.has_cid && place_address(&place, address, sizeof(address))) {
            add_entry(archive->units, &archive->unit_count, address, place.name);
        }
    }
}

static void parse_archive(struct c300x_station_archive *archive, const char *xml)
{
    for (const char *obj = find_tag(xml, "obj"); obj != NULL;) {
        const char *obj_end = strchr(obj, '>');
        struct place object;

        if (obj_end == NULL) {
            return;
        }
        const char *close = obj_end[-1] == '/' ? obj_end : strstr(obj_end, "</obj>");
        if (close == NULL) {
            close = obj_end + strlen(obj_end);
        }
        memset(&object, 0, sizeof(object));
        object.valid = 1;
        read_place(obj, obj_end, &object);
        /* Other objects (cameras, intercoms, actuators, ...) are no outdoor units. */
        if (object.has_cid && strcmp(object.cid, OUTDOOR_UNITS_CID) == 0) {
            parse_object(archive, &object, obj_end + 1, close);
        }
        obj = find_tag(close, "obj");
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

static int join_address(char *out, size_t out_len, const char *dev, const char *where)
{
    return snprintf(out, out_len, "%s%s", dev, where) < (int)out_len && c300x_unit_where_valid(out);
}

/* setup/vdes/communication/p_default: dev + address (2, 0 -> 20). */
static void parse_conf(struct c300x_station_archive *archive, const char *xml)
{
    char dev[8], address[16];
    const char *block = strstr(xml, "<p_default>");
    const char *block_end = block != NULL ? strstr(block, "</p_default>") : NULL;

    if (block_end != NULL
        && element_text(block, block_end, "dev", dev, sizeof(dev))
        && element_text(block, block_end, "address", address, sizeof(address))
        && !join_address(archive->default_where, sizeof(archive->default_where), dev, address)) {
        archive->default_where[0] = '\0';
    }
}

void c300x_station_archive_parse(struct c300x_station_archive *archive, const char *archive_xml,
                                 const char *conf_xml)
{
    memset(archive, 0, sizeof(*archive));
    if (archive_xml != NULL) {
        parse_archive(archive, archive_xml);
    }
    if (conf_xml != NULL) {
        parse_conf(archive, conf_xml);
    }
}

/* No stat(): the device's old libc does not export it. */
char *c300x_station_file_read(const char *path, size_t limit, const char **state)
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

void c300x_station_archive_load(struct c300x_station_archive *archive, const char *archive_path,
                                const char *conf_path, const char **archive_state)
{
    const char *conf_state = "missing";
    char *archive_xml = c300x_station_file_read(archive_path, ARCHIVE_MAX_BYTES, archive_state);
    char *conf_xml = c300x_station_file_read(conf_path, CONF_MAX_BYTES, &conf_state);

    c300x_station_archive_parse(archive, archive_xml, conf_xml);
    free(archive_xml);
    free(conf_xml);
}
