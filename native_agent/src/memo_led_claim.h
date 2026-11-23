#ifndef C300X_MEMO_LED_CLAIM_H
#define C300X_MEMO_LED_CLAIM_H

enum memo_claim_state { MEMO_UNCLAIMED, MEMO_ACTIVE, MEMO_RELEASING };
int c300x_memo_claim_open(enum memo_claim_state *state);
int c300x_memo_claim_create(int dir);
int c300x_memo_claim_remove(int dir);
int c300x_memo_claim_pending(int dir, int pending);

#endif
