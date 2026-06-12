#ifndef C300X_SMARTPHONE_FORWARDING_H
#define C300X_SMARTPHONE_FORWARDING_H

const char *c300x_smartphone_mode_from_code(int code);
int c300x_smartphone_code_from_reply(const char *reply, int *code);

#endif
