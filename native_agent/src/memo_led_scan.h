#ifndef C300X_MEMO_LED_SCAN_H
#define C300X_MEMO_LED_SCAN_H

struct memo_scan;
struct memo_scan *memo_scan_start(const char *text, const char *voice, int *completion);
int memo_scan_finish(struct memo_scan *scan, int *watch);

#endif
