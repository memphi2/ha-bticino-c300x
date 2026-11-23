#ifndef C300X_PROC_PROBE_H
#define C300X_PROC_PROBE_H

/* Read-only probes: a running process by its command line, and a literal in a
 * bounded text file. */
int c300x_process_cmdline_contains(const char *needle);
int c300x_file_contains_literal(const char *path, const char *needle);

#endif
