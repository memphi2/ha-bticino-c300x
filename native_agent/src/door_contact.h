#ifndef C300X_DOOR_CONTACT_H
#define C300X_DOOR_CONTACT_H

#include <stddef.h>

#include "outdoor_units.h"

/* The door contact of an outdoor unit: bt_vct sends *8*66*<where>## when
 * the door opens and *8*65*<where>## when it closes, only on units wired
 * with a contact. A unit has one once a frame of it was seen; that is kept
 * across agent restarts, its state is not (unknown until the next frame). */
struct c300x_door_contact {
    char unit[C300X_UNIT_WHERE_LEN]; /* the unit's id */
    int open;                        /* 1 open, 0 closed, -1 unknown */
    long long changed_ms;            /* monotonic; 0 while unknown */
};

struct c300x_door_contacts {
    struct c300x_door_contact items[C300X_MAX_OUTDOOR_UNITS];
    int count;
};

/* 1 for a door frame, with *open and its where. */
int c300x_door_frame_parse(const char *frame, int *open, char *where, size_t where_len);
/* 0 unchanged, 1 the state changed, 2 the unit's first door frame (its
 * contact is new), -1 the table is full. */
int c300x_door_contacts_note(struct c300x_door_contacts *doors, const char *unit, int open, long long now);
const struct c300x_door_contact *c300x_door_contacts_find(const struct c300x_door_contacts *doors,
                                                          const char *unit);
/* The units with a contact, one id per line. */
int c300x_door_contacts_save(const struct c300x_door_contacts *doors, const char *path);
void c300x_door_contacts_load(struct c300x_door_contacts *doors, const char *path);
/* "null", or {"state":"open"|"closed"|null,"age_ms":N|null}. 0 when it does not fit. */
int c300x_door_contact_json(const struct c300x_door_contact *door, long long now, char *out, size_t out_len);

#endif
