#include "door_contact.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "string_util.h"

#define DOORS_MAX_BYTES 1024

int c300x_door_frame_parse(const char *frame, int *open, char *where, size_t where_len)
{
    size_t length = frame != NULL ? strlen(frame) : 0;
    size_t where_length;

    if (length < sizeof("*8*65*##") || strncmp(frame, "*8*6", 4) != 0 || (frame[4] != '5' && frame[4] != '6')
        || frame[5] != '*' || strcmp(frame + length - 2, "##") != 0) {
        return 0;
    }
    where_length = length - 8;
    if (where_length >= where_len) {
        return 0;
    }
    memcpy(where, frame + 6, where_length);
    where[where_length] = '\0';
    *open = frame[4] == '6';
    return c300x_unit_where_valid(where);
}

static int find(const struct c300x_door_contacts *doors, const char *unit)
{
    for (int index = 0; index < doors->count; index++) {
        if (strcmp(doors->items[index].unit, unit) == 0) {
            return index;
        }
    }
    return -1;
}

static int add(struct c300x_door_contacts *doors, const char *unit)
{
    struct c300x_door_contact *door;

    if (doors->count >= C300X_MAX_OUTDOOR_UNITS || strlen(unit) >= sizeof(door->unit)) {
        return -1;
    }
    door = &doors->items[doors->count];
    c300x_copy_string(door->unit, sizeof(door->unit), unit);
    door->open = -1;
    door->changed_ms = 0;
    return doors->count++;
}

int c300x_door_contacts_note(struct c300x_door_contacts *doors, const char *unit, int open, long long now)
{
    int index = find(doors, unit);
    int result = 1;

    if (index < 0) {
        index = add(doors, unit);
        result = 2;
    }
    if (index < 0) {
        return -1;
    }
    if (doors->items[index].open == open) {
        return 0;
    }
    doors->items[index].open = open;
    doors->items[index].changed_ms = now;
    return result;
}

const struct c300x_door_contact *c300x_door_contacts_find(const struct c300x_door_contacts *doors,
                                                          const char *unit)
{
    int index = doors != NULL && unit != NULL ? find(doors, unit) : -1;
    return index >= 0 ? &doors->items[index] : NULL;
}

int c300x_door_contacts_save(const struct c300x_door_contacts *doors, const char *path)
{
    char temp[C300X_UNIT_PATH_LEN + 8];
    FILE *file;
    int ok = 1;

    if (path == NULL || path[0] == '\0' || snprintf(temp, sizeof(temp), "%s.tmp", path) >= (int)sizeof(temp)) {
        return 0;
    }
    file = fopen(temp, "w");
    if (file == NULL) {
        return 0;
    }
    for (int index = 0; index < doors->count; index++) {
        if (fprintf(file, "%s\n", doors->items[index].unit) < 0) {
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

void c300x_door_contacts_load(struct c300x_door_contacts *doors, const char *path)
{
    const char *state = "missing";
    char *text = path != NULL && path[0] != '\0' ? c300x_station_file_read(path, DOORS_MAX_BYTES, &state) : NULL;
    char *line = text;

    while (line != NULL && *line != '\0') {
        char *next = strchr(line, '\n');
        if (next != NULL) {
            *next++ = '\0';
        }
        char where[C300X_UNIT_WHERE_LEN];
        c300x_copy_string(where, sizeof(where), line);
        for (char *p = where; *p != '\0'; p++) {
            *p = *p == '_' ? '#' : *p;
        }
        /* An id is a where with '_' for '#'. */
        if (strlen(line) < sizeof(where) && c300x_unit_where_valid(where) && find(doors, line) < 0) {
            (void)add(doors, line);
        }
        line = next;
    }
    free(text);
}

int c300x_door_contact_json(const struct c300x_door_contact *door, long long now, char *out, size_t out_len)
{
    int written;

    if (door == NULL) {
        written = snprintf(out, out_len, "null");
    } else if (door->open < 0) {
        written = snprintf(out, out_len, "{\"state\":null,\"age_ms\":null}");
    } else {
        written = snprintf(out, out_len, "{\"state\":\"%s\",\"age_ms\":%lld}", door->open ? "open" : "closed",
                           now - door->changed_ms);
    }
    return written >= 0 && (size_t)written < out_len;
}
