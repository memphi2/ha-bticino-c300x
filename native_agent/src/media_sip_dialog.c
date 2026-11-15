#include "media_sip_dialog.h"
#include "media_sip.h"
#include "media_sip_io.h"
#include "string_util.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

void send_sip_ack(
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
) {
    if (
        fd < 0
        || from_aor[0] == '\0'
        || to_aor[0] == '\0'
        || local_ip[0] == '\0'
        || transport[0] == '\0'
        || to_header[0] == '\0'
        || from_tag[0] == '\0'
        || call_id[0] == '\0'
    ) {
        return;
    }
    char fallback_uri[512];
    const char *request_uri = contact_uri != NULL && contact_uri[0] != '\0' ? contact_uri : fallback_uri;
    if (contact_uri == NULL || contact_uri[0] == '\0') {
        if (snprintf(fallback_uri, sizeof(fallback_uri), "sip:%s", to_aor) >= (int)sizeof(fallback_uri)) {
            return;
        }
    }
    char request[1024];
    int length = snprintf(
        request,
        sizeof(request),
        "ACK %s SIP/2.0\r\n"
        "Via: SIP/2.0/%s %s:%u;branch=z9hG4bKack%ld;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: %s\r\n"
        "From: <sip:%s>;tag=%s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: %d ACK\r\n"
        "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
        "Content-Length: 0\r\n\r\n",
        request_uri,
        transport,
        local_ip,
        local_port,
        (long)time(NULL),
        to_header,
        from_aor,
        from_tag,
        call_id,
        cseq
    );
    if (length < 0 || length >= (int)sizeof(request)) return;
    (void)c300x_media_sip_send_all(fd, request, strlen(request));
}

void send_sip_ok_response(int fd, const char *message) {
    char to[512];
    char from[512];
    char call_id[128];
    char cseq[64];
    char response[4096];
    size_t used = 0;

    c300x_media_sip_header_value(message, "To:", to, sizeof(to));
    c300x_media_sip_header_value(message, "From:", from, sizeof(from));
    c300x_media_sip_header_value(message, "Call-ID:", call_id, sizeof(call_id));
    c300x_media_sip_header_value(message, "CSeq:", cseq, sizeof(cseq));
    if (to[0] == '\0' || from[0] == '\0' || call_id[0] == '\0' || cseq[0] == '\0') {
        return;
    }

    used += (size_t)snprintf(response + used, sizeof(response) - used, "SIP/2.0 200 OK\r\n");
    c300x_media_sip_append_headers(response, sizeof(response), &used, message, "Via:");
    if (used >= sizeof(response)) {
        return;
    }
    (void)c300x_appendf(
        response,
        sizeof(response),
        &used,
        "To: %s\r\n"
        "From: %s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: %s\r\n"
        "Content-Length: 0\r\n\r\n",
        to,
        from,
        call_id,
        cseq
    );
    if (used < sizeof(response)) {
        (void)c300x_media_sip_send_all(fd, response, used);
    }
}

void send_ring_bye(
    int fd,
    const char *invite,
    const char *to_tag,
    const char *remote_contact_uri
) {
    char to[512];
    char from[512];
    char call_id[128];
    char tagged_to[640];
    char request[2048];
    const char *request_uri = remote_contact_uri != NULL && remote_contact_uri[0] != '\0'
        ? remote_contact_uri
        : "sip:c300x@127.0.0.1:5060";

    c300x_media_sip_header_value(invite, "To:", to, sizeof(to));
    c300x_media_sip_header_value(invite, "From:", from, sizeof(from));
    c300x_media_sip_header_value(invite, "Call-ID:", call_id, sizeof(call_id));
    c300x_media_sip_make_tagged_to(to, to_tag, tagged_to, sizeof(tagged_to));
    if (tagged_to[0] == '\0' || from[0] == '\0' || call_id[0] == '\0') {
        return;
    }
    snprintf(
        request,
        sizeof(request),
        "BYE %s SIP/2.0\r\n"
        "Via: SIP/2.0/TCP 127.0.0.1:%d;branch=z9hG4bKringbye%ld;rport\r\n"
        "Max-Forwards: 70\r\n"
        "From: %s\r\n"
        "To: %s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: 111 BYE\r\n"
        "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
        "Content-Length: 0\r\n\r\n",
        request_uri,
        DEFAULT_SIP_PORT,
        (long)time(NULL),
        tagged_to,
        from,
        call_id
    );
    (void)c300x_media_sip_send_all(fd, request, strlen(request));
}

void send_sip_bye(
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
) {
    if (
        fd < 0
        || from_aor[0] == '\0'
        || to_aor[0] == '\0'
        || local_ip[0] == '\0'
        || transport[0] == '\0'
        || to_header[0] == '\0'
        || from_tag[0] == '\0'
        || call_id[0] == '\0'
    ) {
        return;
    }
    char fallback_uri[512];
    const char *request_uri = contact_uri != NULL && contact_uri[0] != '\0' ? contact_uri : fallback_uri;
    if (contact_uri == NULL || contact_uri[0] == '\0') {
        if (snprintf(fallback_uri, sizeof(fallback_uri), "sip:%s", to_aor) >= (int)sizeof(fallback_uri)) {
            return;
        }
    }
    char request[1024];
    snprintf(
        request,
        sizeof(request),
        "BYE %s SIP/2.0\r\n"
        "Via: SIP/2.0/%s %s:%u;branch=z9hG4bKbye%ld;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: %s\r\n"
        "From: <sip:%s>;tag=%s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: 22 BYE\r\n"
        "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
        "Content-Length: 0\r\n\r\n",
        request_uri,
        transport,
        local_ip,
        local_port,
        (long)time(NULL),
        to_header,
        from_aor,
        from_tag,
        call_id
    );
    (void)c300x_media_sip_send_all(fd, request, strlen(request));
}

void send_home_call_cancel(
    int fd,
    const char *to_aor,
    const char *from_aor,
    const char *from_tag,
    const char *call_id,
    const char *invite_branch,
    const char *local_ip,
    uint16_t local_port,
    const char *transport
) {
    char request[2048];
    int len;

    if (
        fd < 0
        || to_aor[0] == '\0'
        || from_aor[0] == '\0'
        || from_tag[0] == '\0'
        || call_id[0] == '\0'
        || invite_branch[0] == '\0'
        || local_ip[0] == '\0'
        || transport[0] == '\0'
    ) {
        return;
    }
    len = snprintf(
        request,
        sizeof(request),
        "CANCEL sip:%s SIP/2.0\r\n"
        "Via: SIP/2.0/%s %s:%u;branch=%s;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: <sip:%s>\r\n"
        "From: <sip:%s>;tag=%s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: 21 CANCEL\r\n"
        "Content-Length: 0\r\n\r\n",
        to_aor,
        transport,
        local_ip,
        local_port,
        invite_branch,
        to_aor,
        from_aor,
        from_tag,
        call_id
    );
    if (len > 0 && len < (int)sizeof(request)) {
        (void)c300x_media_sip_send_all(fd, request, (size_t)len);
    }
}
