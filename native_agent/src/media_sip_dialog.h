#ifndef C300X_MEDIA_SIP_DIALOG_H
#define C300X_MEDIA_SIP_DIALOG_H

#include <stdint.h>

#define C300X_MEDIA_SIP_DEFAULT_PORT 5060
#define C300X_MEDIA_SIP_USER_AGENT "VctLinphoneService/1.17.3"

/* Internal, stateless dialog messages. Strings and fd are borrowed for the
 * call only. The bridge decides when to send and owns dialog/session state,
 * locking, response reads and socket shutdown. No retained state or workers. */
void c300x_media_sip_send_ack(
    int fd,
    const char *from_aor,
    const char *to_aor,
    const char *local_ip,
    uint16_t local_port,
    const char *transport,
    const char *to_header,
    const char *from_tag,
    const char *call_id,
    const char *contact_uri,
    int cseq
);

void c300x_media_sip_send_ok(int fd, const char *message);

void c300x_media_sip_send_ring_bye(
    int fd,
    const char *invite,
    const char *to_tag,
    const char *remote_contact_uri
);

void c300x_media_sip_send_bye(
    int fd,
    const char *from_aor,
    const char *to_aor,
    const char *local_ip,
    uint16_t local_port,
    const char *transport,
    const char *to_header,
    const char *from_tag,
    const char *call_id,
    const char *contact_uri
);

void c300x_media_sip_send_cancel(
    int fd,
    const char *to_aor,
    const char *from_aor,
    const char *from_tag,
    const char *call_id,
    const char *invite_branch,
    const char *local_ip,
    uint16_t local_port,
    const char *transport
);

#endif
