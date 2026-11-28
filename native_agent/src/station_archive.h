#ifndef C300X_STATION_ARCHIVE_H
#define C300X_STATION_ARCHIVE_H

#include <stddef.h>

#define C300X_ARCHIVE_XML_PATH "/home/bticino/cfg/extra/0/archive.xml"
#ifndef C300X_CONF_XML_PATH
#define C300X_CONF_XML_PATH "/var/tmp/conf.xml"
#endif
#define C300X_UNIT_WHERE_LEN 24
#define C300X_UNIT_NAME_LEN 64
#define C300X_ARCHIVE_MAX_ENTRIES 16

/* One object of the station's own configuration: its bus address and the
 * name the installer gave it. */
struct c300x_archive_entry {
    char where[C300X_UNIT_WHERE_LEN];
    char name[C300X_UNIT_NAME_LEN];
};

/* What archive.xml and conf.xml say, read as the station's display reads
 * them; an <ist> attribute it lacks is its <obj>'s. Objects by cid:
 * 10050 outdoor units (each <ist> without cid) and their door locks (<ist
 * cid="10060">, but dev 5 is a cloud lock, not on the bus), 3008 actuators
 * (AutomationVDE, the display's "Generic": each <ist>, at 2N), 2009 the
 * stair light (at the station's own address). Other cids name nothing. */
struct c300x_station_archive {
    struct c300x_archive_entry units[C300X_ARCHIVE_MAX_ENTRIES];
    int unit_count;
    struct c300x_archive_entry locks[C300X_ARCHIVE_MAX_ENTRIES];
    int lock_count;
    struct c300x_archive_entry actuators[C300X_ARCHIVE_MAX_ENTRIES];
    int actuator_count;
    int stair_light;                          /* the archive has the stair light */
    char stair_light_name[C300X_UNIT_NAME_LEN];
    char default_where[C300X_UNIT_WHERE_LEN]; /* conf.xml p_default, empty when unknown */
    char own_where[C300X_UNIT_WHERE_LEN];     /* conf.xml communication: the station itself */
};

int c300x_unit_where_valid(const char *where);
/* Pure: either text may be NULL. */
void c300x_station_archive_parse(struct c300x_station_archive *archive, const char *archive_xml,
                                 const char *conf_xml);
/* Reads and parses both files; *archive_state is ok, missing or unreadable. */
void c300x_station_archive_load(struct c300x_station_archive *archive, const char *archive_path,
                                const char *conf_path, const char **archive_state);
/* The station's own address from conf.xml (communication dev + address,
 * 11 for dev 1, address 1); zero when it is unknown. */
int c300x_station_own_where(const char *conf_path, char *out, size_t out_len);
/* A whole bounded text file, NULL with *state missing or unreadable. */
char *c300x_station_file_read(const char *path, size_t limit, const char **state);

#endif
