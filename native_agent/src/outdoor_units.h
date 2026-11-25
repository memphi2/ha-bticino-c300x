#ifndef C300X_OUTDOOR_UNITS_H
#define C300X_OUTDOOR_UNITS_H

#include <stddef.h>

#define C300X_MAX_OUTDOOR_UNITS 16
#define C300X_UNIT_WHERE_LEN 24
#define C300X_UNIT_NAME_LEN 64
#define C300X_ARCHIVE_XML_PATH "/home/bticino/cfg/extra/0/archive.xml"
#define C300X_CONF_XML_PATH "/var/tmp/conf.xml"

/* One outdoor unit. where is the caller frame's address (20#2), action_where
 * the plain address its lock and video use (20), id the where with '_' for
 * '#'. Strings, never numbers. */
struct c300x_outdoor_unit {
    char id[C300X_UNIT_WHERE_LEN];
    char where[C300X_UNIT_WHERE_LEN];
    char action_where[C300X_UNIT_WHERE_LEN];
    char lock_where[C300X_UNIT_WHERE_LEN];
    char name[C300X_UNIT_NAME_LEN];
    char source[8]; /* archive, default, seen */
};

struct c300x_outdoor_units {
    struct c300x_outdoor_unit items[C300X_MAX_OUTDOOR_UNITS];
    int count;
    int default_index;
    int loaded;
    char archive[12]; /* ok, empty, missing, unreadable */
};

int c300x_unit_where_valid(const char *where);
void c300x_unit_id_from_where(const char *where, char *out, size_t out_len);
void c300x_unit_action_where(const char *where, char *out, size_t out_len);

/* Pure: archive_xml or conf_xml may be NULL. Seen units of units survive. */
void c300x_outdoor_units_build(struct c300x_outdoor_units *units, const char *archive_xml,
                               const char *archive_state, const char *conf_xml,
                               const char *fallback_devaddr, const char *default_lock);
/* Reads the station files; seen units stay. */
void c300x_outdoor_units_load(struct c300x_outdoor_units *units, const char *archive_path,
                              const char *conf_path, const char *fallback_devaddr,
                              const char *default_lock);
int c300x_outdoor_units_find_id(const struct c300x_outdoor_units *units, const char *id);
int c300x_outdoor_units_find_lock(const struct c300x_outdoor_units *units, const char *address);
/* The unit a caller frame names; a new one is added as seen (*changed set).
 * -1 for an invalid where or a full table. */
int c300x_outdoor_units_note_caller(struct c300x_outdoor_units *units, const char *where, int *changed);
const struct c300x_outdoor_unit *c300x_outdoor_units_default(const struct c300x_outdoor_units *units);
int c300x_outdoor_units_json(const struct c300x_outdoor_units *units, char *out, size_t out_len);

#endif
