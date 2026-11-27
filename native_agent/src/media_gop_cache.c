/* Keyframe group cache for the RTSP video output.
 *
 * The station sends H.264 over RTP with an IDR access unit (AUD, SPS, PPS,
 * IDR) about once a second and cannot send one on request. A client that
 * starts in the middle of a group sees a broken picture until the next one.
 * The cache keeps the packets from the start of the latest IDR access unit,
 * bounded in bytes, packets and time, and a client starts with them before
 * the live packets. Each client gets its own sequence numbers and timestamps:
 * the cached frames go out 1 ms apart, so the picture is current at once and
 * in step with the audio that starts at the same moment. A client that cannot
 * take the group quickly starts at the next IDR instead. A new stream or a
 * long gap keeps the client's numbering and waits for the next IDR. */
#include "media_gop_cache.h"

#include "time_util.h"

#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define GOP_MAX_TICKS (C300X_MEDIA_GOP_CACHE_MAX_MS * 90u)
/* No packet for this long: the cached group is stale. */
#define GOP_IDLE_MS 1000
#define GOP_CACHED_FRAME_TICKS 90u
/* Sequence numbers this far behind are repeats; further ahead, a new stream. */
#define GOP_SEQ_WINDOW 1024u
/* A client that missed more packets than this, while parked, restarts. */
#define GOP_CLIENT_GAP 64u
/* The cached groups sent while one packet is forwarded, to all clients that
 * start with it, hold the relay this long at most: it reads neither the
 * video nor the audio meanwhile. A client that cannot take its group in that
 * time starts at the next IDR, with only the packets of it so far. */
#define GOP_BURST_MS 200
#define GOP_CLIENTS C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS
#define NAL_STARTS 1u
#define NAL_IDR 2u

struct gop_packet {
    uint32_t offset;
    uint16_t length;
};

struct gop_client {
    unsigned long id;
    bool live, anchored, skip;
    unsigned epoch, skip_group;
    uint32_t ssrc, ts_offset, last_out_ts;
    uint16_t seq_offset, last_out_seq, next_in_seq;
    long long last_ms;
};

struct rtp_view {
    uint32_t ts, ssrc;
    uint16_t seq;
    uint8_t payload_type;
    const unsigned char *payload;
    size_t payload_len;
};

static struct {
    pthread_mutex_t mutex;
    unsigned char *data; /* C300X_MEDIA_GOP_CACHE_BYTES while a stream runs. */
    bool alloc_failed;
    struct gop_packet packets[C300X_MEDIA_GOP_CACHE_PACKETS];
    size_t count, bytes, au_start;
    /* au_clean: the access unit being received is cached from its start.
     * group: the cache starts with an IDR access unit. */
    bool au_clean, group, stream;
    unsigned epoch, group_serial;
    uint32_t group_ts, ssrc, last_ts;
    uint16_t next_seq;
    uint8_t payload_type;
    long long last_ms;
    struct gop_client clients[GOP_CLIENTS];
} gop = {.mutex = PTHREAD_MUTEX_INITIALIZER};

static uint16_t be16(const unsigned char *in) { return (uint16_t)((in[0] << 8) | in[1]); }

static uint32_t be32(const unsigned char *in)
{
    return ((uint32_t)in[0] << 24) | ((uint32_t)in[1] << 16) | ((uint32_t)in[2] << 8) | in[3];
}

static void put16(unsigned char *out, uint16_t value)
{
    out[0] = (unsigned char)(value >> 8);
    out[1] = (unsigned char)value;
}

static void put32(unsigned char *out, uint32_t value)
{
    put16(out, (uint16_t)(value >> 16));
    put16(out + 2, (uint16_t)value);
}

static bool rtp_view(const unsigned char *packet, size_t len, struct rtp_view *view)
{
    if (len < 13 || len > 0xffffu || (packet[0] >> 6) != 2) return false;
    size_t offset = 12 + 4 * (size_t)(packet[0] & 0x0f), end = len;
    if (packet[0] & 0x10) {
        if (offset + 4 > end) return false;
        offset += 4 + 4 * (size_t)be16(packet + offset + 2);
    }
    if (packet[0] & 0x20) {
        if (packet[len - 1] == 0 || packet[len - 1] > end) return false;
        end -= packet[len - 1];
    }
    if (offset >= end) return false;
    view->seq = be16(packet + 2);
    view->ts = be32(packet + 4);
    view->ssrc = be32(packet + 8);
    view->payload_type = packet[1] & 0x7f;
    view->payload = packet + offset;
    view->payload_len = end - offset;
    return true;
}

/* Single NAL units, STAP-A and the first FU-A fragment begin a NAL unit. */
static unsigned nal_flags(const unsigned char *payload, size_t len)
{
    unsigned type = payload[0] & 0x1fu, flags = NAL_STARTS;
    if (type >= 1 && type <= 23) return type == 5 ? NAL_STARTS | NAL_IDR : NAL_STARTS;
    if (type == 24) {
        for (size_t at = 1; at + 2 < len;) {
            size_t size = be16(payload + at);
            if (size == 0 || size > len - at - 2) break;
            if ((payload[at + 2] & 0x1f) == 5) flags |= NAL_IDR;
            at += 2 + size;
        }
        return flags;
    }
    if (type == 28 && len >= 2 && (payload[1] & 0x80)) {
        return (payload[1] & 0x1f) == 5 ? NAL_STARTS | NAL_IDR : NAL_STARTS;
    }
    return 0;
}

static void drop_cached(void)
{
    gop.count = gop.bytes = gop.au_start = 0;
    gop.group = false;
}

static bool cache_append(const unsigned char *packet, size_t len)
{
    if (gop.data == NULL && !gop.alloc_failed) {
        gop.data = malloc(C300X_MEDIA_GOP_CACHE_BYTES);
        gop.alloc_failed = gop.data == NULL;
    }
    if (gop.data == NULL || gop.count >= C300X_MEDIA_GOP_CACHE_PACKETS
        || len > C300X_MEDIA_GOP_CACHE_BYTES - gop.bytes) {
        return false;
    }
    memcpy(gop.data + gop.bytes, packet, len);
    gop.packets[gop.count++] = (struct gop_packet){(uint32_t)gop.bytes, (uint16_t)len};
    gop.bytes += len;
    return true;
}

/* The access unit being received has an IDR: it starts the cached group. */
static void start_group(uint32_t ts)
{
    size_t first = gop.au_start, base = first < gop.count ? gop.packets[first].offset : gop.bytes;
    memmove(gop.data, gop.data + base, gop.bytes - base);
    for (size_t index = first; index < gop.count; index++) {
        gop.packets[index - first] = gop.packets[index];
        gop.packets[index - first].offset -= (uint32_t)base;
    }
    gop.count -= first;
    gop.bytes -= base;
    gop.au_start = 0;
    gop.group = true;
    gop.group_ts = ts;
    gop.group_serial++;
}

/* False for a packet that is not forwarded: a repeat or a late one. */
static bool cache_note(const unsigned char *packet, size_t len, const struct rtp_view *view, long long now)
{
    uint16_t ahead = (uint16_t)(view->seq - gop.next_seq);
    bool idle = now - gop.last_ms > GOP_IDLE_MS;
    /* After a pause a packet that does not follow on is a restarted stream,
     * even with the same SSRC and an earlier sequence number. */
    bool fresh = !gop.stream || view->ssrc != gop.ssrc || view->payload_type != gop.payload_type
        || (ahead >= GOP_SEQ_WINDOW && ahead < 0x10000u - GOP_SEQ_WINDOW) || (idle && ahead != 0);
    if (!fresh && ahead >= 0x10000u - GOP_SEQ_WINDOW) return false;
    /* After a pause the cached group is not sent to anyone any more. */
    bool lost = !fresh && (ahead != 0 || idle);
    bool new_unit = fresh || view->ts != gop.last_ts;
    unsigned flags = nal_flags(view->payload, view->payload_len);
    if (fresh) {
        gop.epoch++;
        gop.stream = true;
        gop.ssrc = view->ssrc;
        gop.payload_type = view->payload_type;
    }
    if (fresh || lost) drop_cached();
    if (new_unit || lost) {
        if (!gop.group) drop_cached();
        gop.au_start = gop.count;
        gop.au_clean = new_unit && !lost && (flags & NAL_STARTS);
    }
    if ((gop.group || gop.au_clean) && !cache_append(packet, len)) {
        drop_cached();
        gop.au_clean = false;
    }
    if ((flags & NAL_IDR) && gop.au_clean && !(gop.group && gop.au_start == 0)) start_group(view->ts);
    int32_t age = (int32_t)(view->ts - gop.group_ts);
    if (gop.group && (age < 0 || (uint32_t)age > GOP_MAX_TICKS)) {
        drop_cached();
        gop.au_clean = false;
    }
    gop.next_seq = (uint16_t)(view->seq + 1);
    gop.last_ts = view->ts;
    gop.last_ms = now;
    return true;
}

/* Maps the client's next packet, with this sequence number and timestamp, so
 * its numbering goes on; a client's first packet keeps the station's. */
static void anchor(struct gop_client *client, uint16_t seq, uint32_t ts, uint32_t ssrc, long long now)
{
    uint32_t out_ts = ts;
    uint16_t out_seq = seq;
    if (client->anchored) {
        long long gap = now - client->last_ms;
        gap = gap < 1 ? 1 : (gap > 10000 ? 10000 : gap);
        out_ts = client->last_out_ts + (uint32_t)gap * 90u;
        out_seq = (uint16_t)(client->last_out_seq + 1);
    } else {
        client->ssrc = ssrc;
        client->anchored = true;
    }
    client->seq_offset = (uint16_t)(out_seq - seq);
    client->ts_offset = out_ts - ts;
}

/* deadline: 0 for a live packet, which has the writer's own budget. */
static ssize_t send_mapped(const rtsp_send_target_t *target, struct gop_client *client,
                           const unsigned char *packet, size_t len, long long now, long long deadline)
{
    unsigned char head[16];
    uint16_t seq = (uint16_t)(be16(packet + 2) + client->seq_offset);
    uint32_t ts = be32(packet + 4) + client->ts_offset;
    head[0] = '$';
    head[1] = (unsigned char)target->channel;
    put16(head + 2, (uint16_t)len);
    head[4] = packet[0];
    head[5] = packet[1];
    put16(head + 6, seq);
    put32(head + 8, ts);
    put32(head + 12, client->ssrc);
    client->last_out_seq = seq;
    client->last_out_ts = ts;
    client->next_in_seq = (uint16_t)(be16(packet + 2) + 1);
    client->last_ms = now;
    return c300x_rtsp_send_pair_by(target->writer, target->fd, head, sizeof(head), packet + 12, len - 12,
                                   deadline);
}

/* The whole group, the current packet last, by the deadline. False when the
 * client could not take it: it then waits for the next group instead of a
 * repeated start. */
static bool replay(const rtsp_send_target_t *target, struct gop_client *client, long long now,
                   long long deadline)
{
    const unsigned char *first = gop.data + gop.packets[0].offset;
    uint32_t in_ts = be32(first + 4);
    anchor(client, be16(first + 2), in_ts, be32(first + 8), now);
    uint32_t out_ts = in_ts + client->ts_offset;
    for (size_t index = 0; index < gop.count; index++) {
        const unsigned char *packet = gop.data + gop.packets[index].offset;
        if (be32(packet + 4) != in_ts) {
            in_ts = be32(packet + 4);
            out_ts += GOP_CACHED_FRAME_TICKS;
            client->ts_offset = out_ts - in_ts;
        }
        if (send_mapped(target, client, packet, gop.packets[index].length, now, deadline) <= 0) return false;
    }
    return true;
}

/* *burst: the deadline of this packet's cached groups, 0 until the first. */
static void deliver(const rtsp_send_target_t *target, const unsigned char *packet, size_t len,
                    const struct rtp_view *view, long long now, long long *burst)
{
    if (target->slot < 0 || target->slot >= (int)GOP_CLIENTS || !target->transport_tcp) return;
    struct gop_client *client = &gop.clients[target->slot];
    if (client->id != target->video_id) {
        memset(client, 0, sizeof(*client));
        client->id = target->video_id;
    }
    if (client->live && (client->epoch != gop.epoch
                         || (uint16_t)(view->seq - client->next_in_seq) > GOP_CLIENT_GAP)) {
        client->live = false;
    }
    if (!client->live && gop.data == NULL && gop.alloc_failed) {
        /* Without memory for a cache, start as before: at this packet. */
        anchor(client, view->seq, view->ts, view->ssrc, now);
        client->live = true;
        client->epoch = gop.epoch;
    }
    if (client->live) {
        (void)send_mapped(target, client, packet, len, now, 0);
        return;
    }
    if (!gop.group || (client->skip && client->skip_group == gop.group_serial)) return;
    if (*burst == 0) *burst = c300x_rtsp_deadline_in(GOP_BURST_MS);
    client->epoch = gop.epoch;
    client->live = replay(target, client, now, *burst);
    client->skip = !client->live;
    client->skip_group = gop.group_serial;
}

void c300x_media_gop_forward(const rtsp_send_target_t *targets, size_t count,
                             const unsigned char *packet, size_t packet_len)
{
    struct rtp_view view;
    long long now = c300x_monotonic_ms();
    long long burst = 0;
    pthread_mutex_lock(&gop.mutex);
    bool usable = packet != NULL && rtp_view(packet, packet_len, &view)
        && cache_note(packet, packet_len, &view, now);
    for (size_t index = 0; index < count; index++) {
        if (usable) deliver(&targets[index], packet, packet_len, &view, now, &burst);
        close(targets[index].fd);
        c300x_rtsp_writer_release(targets[index].writer);
    }
    pthread_mutex_unlock(&gop.mutex);
}

void c300x_media_gop_reset(void)
{
    pthread_mutex_lock(&gop.mutex);
    free(gop.data);
    gop.data = NULL;
    gop.alloc_failed = false;
    drop_cached();
    gop.au_clean = false;
    gop.stream = false;
    pthread_mutex_unlock(&gop.mutex);
}
