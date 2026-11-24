#ifndef C300X_FIREWALL_FILE_H
#define C300X_FIREWALL_FILE_H

#include <stddef.h>
#include <sys/types.h>

/* The vendor firewall scripts and their backups. All return nonzero on
 * success. */
int c300x_firewall_read_file(const char *path, char *buffer, size_t buffer_len, int *exists);
/* Temp file, fsync, rename, fsync of the directories: the old or the new
 * script survives a power cut, never neither. A replaced file keeps its
 * owner and mode (the vendor's); a new one gets new_mode. */
int c300x_firewall_write_file(const char *path, const char *content, mode_t new_mode);
int c300x_firewall_backup_available(const char *backup_path);
/* Writes the backup once and reads it back: a later restore relies on it. */
int c300x_firewall_backup_original(const char *backup_path, const char *content, int *written);
void c300x_firewall_use_matching_backup(const char *backup_path, char *desired, size_t desired_len);
/* Backup of the original (once), then the desired script when it differs
 * from the current one, inside one write window on /. changed counts the
 * files written. */
int c300x_firewall_install(const char *path, const char *backup_path, const char *original,
                           const char *current, const char *desired, int *changed);
/* Only paths under /etc live on the read-only root. */
int c300x_firewall_remount(const char *path, const char *mode);

#endif
