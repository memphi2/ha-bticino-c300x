#ifndef C300X_STATION_STATE_H
#define C300X_STATION_STATE_H

/* The station's call state: bt_answering_machine sends *#8**35*S*x*y## to
 * the monitor (the OPEN LCM channel) on every change, and answers the
 * request *#8**35## with it. Same frame on 1.7.19, 2.0.2, 3.0.6 and the
 * C100X 1.5.8. x and y were 0 in every capture. */
#define C300X_STATION_STATE_UNKNOWN (-1)

/* 1 for a state frame or reply, with its state in *code. */
int c300x_station_state_parse(const char *frame, int *code);
/* The proven meaning of a state, NULL for any other (the station also
 * sends 10, 11 and 12, without a proven meaning). */
const char *c300x_station_state_name(int code);

#endif
