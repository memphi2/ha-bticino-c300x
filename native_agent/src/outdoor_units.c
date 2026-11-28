#include "outdoor_units.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "door_contact.h"
#include "json_util.h"
#include "string_util.h"

#define SEEN_MAX_BYTES (4 * 1024)

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

void c300x_outdoor_units_build(struct c300x_outdoor_units *units, const struct c300x_station_archive *station,
                               const char *archive_state, const char *fallback_devaddr, const char *default_lock)
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
    for (int index = 0; index < station->unit_count; index++) {
        add_unit(units, station->units[index].where, station->units[index].name, "archive");
    }
    if (units->count == 0 && strcmp(archive_state, "ok") == 0) {
        c300x_copy_string(units->archive, sizeof(units->archive), "empty");
    }
    c300x_copy_string(default_where, sizeof(default_where), station->default_where[0] != '\0'
        ? station->default_where : c300x_unit_where_valid(fallback_devaddr) ? fallback_devaddr : "20");
    /* The archive's unit at the default address, else the one behind an
     * apartment interface there (20#2 for 20), is the default unit: one
     * unit with the archive's name and where. Its id is the default
     * address's, as without an archive, so the unit keeps its identity. */
    for (int pass = 0; pass < 2 && units->default_index < 0; pass++) {
        for (int index = 0; index < units->count && units->default_index < 0; index++) {
            const struct c300x_outdoor_unit *unit = &units->items[index];
            if (strcmp(pass == 0 ? unit->where : unit->action_where, default_where) == 0) {
                units->default_index = index;
            }
        }
    }
    if (units->default_index >= 0) {
        c300x_unit_id_from_where(default_where, units->items[units->default_index].id, sizeof(units->items[0].id));
    } else {
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

void c300x_outdoor_units_load(struct c300x_outdoor_units *units, const char *archive_path,
                              const char *conf_path, const char *fallback_devaddr,
                              const char *default_lock)
{
    static const struct c300x_station_archive nothing;
    const char *archive_state = "unreadable";
    struct c300x_station_archive *station = malloc(sizeof(*station));

    if (station == NULL) {
        if (!units->loaded) {
            c300x_outdoor_units_build(units, &nothing, archive_state, fallback_devaddr, default_lock);
        }
        return;
    }
    c300x_station_archive_load(station, archive_path, conf_path, &archive_state);
    c300x_outdoor_units_build(units, station, archive_state, fallback_devaddr, default_lock);
    free(station);
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

/* The unit with this plain action address whose own where has no
 * qualifier (want_plain) or any; the default unit first. */
static int find_action(const struct c300x_outdoor_units *units, const char *action, int want_plain)
{
    int found = -1;

    for (int index = 0; index < units->count; index++) {
        const struct c300x_outdoor_unit *unit = &units->items[index];
        if (strcmp(unit->action_where, action) != 0
            || (want_plain && strcmp(unit->where, unit->action_where) != 0)) {
            continue;
        }
        if (index == units->default_index) {
            return index;
        }
        if (found < 0) {
            found = index;
        }
    }
    return found;
}

/* Frames name a unit by its full address (20#2, caller frames) or by its
 * plain one (20, view frames): both are the same unit, with one id. */
int c300x_outdoor_units_note_caller(struct c300x_outdoor_units *units, const char *where, int *changed)
{
    char action[C300X_UNIT_WHERE_LEN];
    char id[C300X_UNIT_WHERE_LEN];
    int index;

    *changed = 0;
    if (!c300x_unit_where_valid(where)) {
        return -1;
    }
    for (index = 0; index < units->count; index++) {
        if (strcmp(units->items[index].where, where) == 0) {
            return index;
        }
    }
    c300x_unit_action_where(where, action, sizeof(action));
    index = find_action(units, action, strcmp(action, where) != 0);
    if (index >= 0) {
        struct c300x_outdoor_unit *unit = &units->items[index];
        /* A unit known without its qualifier (conf.xml's default, a plain
         * frame) learns the caller's; the archive's address stays. */
        if (strcmp(action, where) != 0 && strcmp(unit->source, "archive") != 0) {
            c300x_copy_string(unit->where, sizeof(unit->where), where);
            *changed = 1;
        }
        return index;
    }
    c300x_unit_id_from_where(where, id, sizeof(id));
    index = c300x_outdoor_units_find_id(units, id);
    if (index >= 0) {
        return index;
    }
    index = add_unit(units, where, "", "seen");
    *changed = index >= 0;
    return index;
}

/* A unit whose line is kept: a seen one, or the default unit without an
 * archive entry once it learned a caller's qualifier. */
static int kept(const struct c300x_outdoor_unit *unit)
{
    return strcmp(unit->source, "seen") == 0
        || (strcmp(unit->source, "default") == 0 && strcmp(unit->where, unit->action_where) != 0);
}

/* One line per kept unit: its id and its where. */
int c300x_outdoor_units_save_seen(const struct c300x_outdoor_units *units, const char *path)
{
    char temp[C300X_UNIT_PATH_LEN + 8];
    FILE *file;
    int ok;

    if (path == NULL || path[0] == '\0' || snprintf(temp, sizeof(temp), "%s.tmp", path) >= (int)sizeof(temp)) {
        return 0;
    }
    file = fopen(temp, "w");
    if (file == NULL) {
        return 0;
    }
    ok = 1;
    for (int index = 0; index < units->count; index++) {
        if (kept(&units->items[index])
            && fprintf(file, "%s %s\n", units->items[index].id, units->items[index].where) < 0) {
            ok = 0;
        }
    }
    ok = fflush(file) == 0 && fsync(fileno(file)) == 0 && ok;
    ok = fclose(file) == 0 && ok;
    if (!ok || rename(temp, path) != 0) {
        (void)unlink(temp);
        return 0;
    }
    return 1;
}

void c300x_outdoor_units_load_seen(struct c300x_outdoor_units *units, const char *path)
{
    const char *state = "missing";
    char *text = path != NULL && path[0] != '\0' ? c300x_station_file_read(path, SEEN_MAX_BYTES, &state) : NULL;
    char *line = text;

    while (line != NULL && *line != '\0') {
        char *next = strchr(line, '\n');
        char id[C300X_UNIT_WHERE_LEN], where[C300X_UNIT_WHERE_LEN];
        char plain[C300X_UNIT_WHERE_LEN], own[C300X_UNIT_WHERE_LEN];
        if (next != NULL) {
            *next++ = '\0';
        }
        if (sscanf(line, "%23s %23s", id, where) != 2 || !c300x_unit_where_valid(where)) {
            line = next;
            continue;
        }
        c300x_unit_action_where(where, plain, sizeof(plain));
        c300x_unit_id_from_where(where, own, sizeof(own));
        int found = c300x_outdoor_units_find_id(units, id);
        struct c300x_outdoor_unit *unit = found >= 0 ? &units->items[found] : NULL;
        /* The default unit without an archive entry takes its learned
         * qualifier back; an archive unit keeps its own where. */
        if (unit != NULL && strcmp(id, plain) == 0 && strcmp(unit->source, "default") == 0
            && strcmp(unit->where, plain) == 0) {
            c300x_copy_string(unit->where, sizeof(unit->where), where);
        }
        /* Its id is its where's, or its plain address once it learned a
         * qualifier. A unit the station's files name now is not added again. */
        int known = (strcmp(id, own) != 0 && strcmp(id, plain) != 0)
            || unit != NULL
            || (strcmp(where, plain) == 0 && find_action(units, plain, 0) >= 0);
        for (int index = 0; !known && index < units->count; index++) {
            known = strcmp(units->items[index].where, where) == 0;
        }
        int index = known ? -1 : add_unit(units, where, "", "seen");
        if (index >= 0) {
            c300x_copy_string(units->items[index].id, sizeof(units->items[index].id), id);
        }
        line = next;
    }
    free(text);
}

const struct c300x_outdoor_unit *c300x_outdoor_units_default(const struct c300x_outdoor_units *units)
{
    return units->default_index >= 0 && units->default_index < units->count
        ? &units->items[units->default_index] : NULL;
}

int c300x_outdoor_units_json(const struct c300x_outdoor_units *units, const struct c300x_door_contacts *doors,
                             long long now, char *out, size_t out_len)
{
    size_t used = 0;
    char name[C300X_JSON_QUOTED_LEN(C300X_UNIT_NAME_LEN)];
    char door[64];
    const struct c300x_outdoor_unit *fallback = c300x_outdoor_units_default(units);

    if (!c300x_appendf(out, out_len, &used, "{\"ok\":true,\"default_unit\":\"%s\",\"archive\":\"%s\",\"units\":[",
                       fallback != NULL ? fallback->id : "", units->archive)) {
        return 0;
    }
    for (int index = 0; index < units->count; index++) {
        const struct c300x_outdoor_unit *unit = &units->items[index];
        if (!c300x_door_contact_json(c300x_door_contacts_find(doors, unit->id), now, door, sizeof(door))
            || !c300x_appendf(out, out_len, &used,
                "%s{\"id\":\"%s\",\"where\":\"%s\",\"action_where\":\"%s\",\"lock_where\":\"%s\","
                "\"name\":%s,\"source\":\"%s\",\"default\":%s,\"door\":%s}",
                index > 0 ? "," : "", unit->id, unit->where, unit->action_where, unit->lock_where,
                c300x_json_string(unit->name, name, sizeof(name)), unit->source,
                index == units->default_index ? "true" : "false", door)) {
            return 0;
        }
    }
    return c300x_appendf(out, out_len, &used, "]}\n");
}
