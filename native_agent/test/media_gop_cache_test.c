/* The keyframe group cache against a synthetic station stream: AUD, SPS, PPS
 * and a fragmented IDR, then P frames, 15 per second. */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>

long long test_clock(void);
static void *test_malloc(size_t size);
#define c300x_monotonic_ms test_clock
#define malloc test_malloc
#include "../src/media_gop_cache.c"
#undef malloc
#undef c300x_monotonic_ms

static long long clock_ms = 1000000;
long long test_clock(void) { return clock_ms; }
static bool fail_malloc;
static void *test_malloc(size_t size) { return fail_malloc ? NULL : malloc(size); }

#define FRAG 1274
#define MAX_RX 2048

/* ---- station ---- */

struct station {
    uint32_t ssrc, ts;
    uint16_t seq;
};

struct client {
    int fd[2];
    struct c300x_rtsp_writer *writer;
    int slot;
    unsigned long id;
    bool joined;
};

static struct client clients[GOP_CLIENTS];

static void forward_raw(const unsigned char *packet, size_t len)
{
    rtsp_send_target_t targets[GOP_CLIENTS];
    size_t count = 0;
    for (int index = 0; index < (int)GOP_CLIENTS; index++) {
        struct client *client = &clients[index];
        if (!client->joined) continue;
        targets[count] = (rtsp_send_target_t){
            .fd = fcntl(client->fd[0], F_DUPFD_CLOEXEC, 0), .writer = client->writer,
            .transport_tcp = true, .channel = 2, .slot = client->slot, .video_id = client->id,
        };
        assert(targets[count].fd >= 0);
        c300x_rtsp_writer_retain(client->writer);
        count++;
    }
    c300x_media_gop_forward(targets, count, packet, len);
    assert(gop.bytes <= C300X_MEDIA_GOP_CACHE_BYTES);
    assert(gop.count <= C300X_MEDIA_GOP_CACHE_PACKETS);
}

static void send_packet(struct station *station, const unsigned char *payload, size_t len, bool marker)
{
    unsigned char packet[1600];
    assert(len + 12 <= sizeof(packet));
    packet[0] = 0x80;
    packet[1] = (unsigned char)((marker ? 0x80 : 0) | 96);
    put16(packet + 2, station->seq++);
    put32(packet + 4, station->ts);
    put32(packet + 8, station->ssrc);
    memcpy(packet + 12, payload, len);
    forward_raw(packet, len + 12);
}

/* A frame: AUD, for an IDR also SPS and PPS, then the slice in FU-A parts. */
static void send_frame(struct station *station, bool idr, int fragments)
{
    unsigned char aud[2] = {0x09, 0xf0};
    unsigned char sps[10] = {0x67, 0x42, 0x80, 0x1f, 0xda, 0x02, 0x80, 0xf6, 0x80, 0x6d};
    unsigned char pps[4] = {0x68, 0xce, 0x06, 0xe2};
    unsigned char part[2 + FRAG];
    send_packet(station, aud, sizeof(aud), false);
    if (idr) {
        send_packet(station, sps, sizeof(sps), false);
        send_packet(station, pps, sizeof(pps), false);
    }
    for (int index = 0; index < fragments; index++) {
        part[0] = 0x7c;
        part[1] = (unsigned char)((idr ? 5 : 1) | (index == 0 ? 0x80 : 0)
                                  | (index == fragments - 1 ? 0x40 : 0));
        memset(part + 2, (int)(station->seq & 0xff), FRAG);
        send_packet(station, part, sizeof(part), index == fragments - 1);
    }
    station->ts += 6000;
    clock_ms += 66;
}

/* ---- what a client received ---- */

struct rx {
    uint16_t seq;
    uint32_t ts, ssrc;
    uint8_t nal, fu;
    size_t len;
};

/* Whole interleaved frames; a frame the writer has only begun stays for the
 * next call. */
static size_t receive(struct client *client, struct rx *out, size_t max)
{
    static unsigned char buffers[GOP_CLIENTS][1 << 20];
    static size_t kept[GOP_CLIENTS];
    unsigned char *buffer = buffers[client - clients];
    size_t used = kept[client - clients], count = 0, at = 0;
    for (;;) {
        ssize_t n = recv(client->fd[1], buffer + used, sizeof(buffers[0]) - used, MSG_DONTWAIT);
        if (n <= 0) break;
        used += (size_t)n;
    }
    while (at + 4 <= used) {
        assert(buffer[at] == '$' && buffer[at + 1] == 2);
        size_t len = be16(buffer + at + 2);
        assert(len >= 13);
        if (at + 4 + len > used) break;
        const unsigned char *packet = buffer + at + 4;
        assert(count < max);
        out[count++] = (struct rx){be16(packet + 2), be32(packet + 4), be32(packet + 8),
                                   (uint8_t)(packet[12] & 0x1f), (uint8_t)(packet[13] & 0x9f), len};
        at += 4 + len;
    }
    memmove(buffer, buffer + at, used - at);
    kept[client - clients] = used - at;
    return count;
}

static void join(int index)
{
    struct client *client = &clients[index];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, client->fd) == 0);
    int size = 4 << 20;
    (void)setsockopt(client->fd[0], SOL_SOCKET, SO_SNDBUF, &size, sizeof(size));
    (void)setsockopt(client->fd[1], SOL_SOCKET, SO_RCVBUF, &size, sizeof(size));
    client->writer = c300x_rtsp_writer_create();
    assert(client->writer);
    static unsigned long serial;
    client->slot = index;
    client->id = ++serial;
    client->joined = true;
}

static void leave(int index)
{
    struct client *client = &clients[index];
    if (!client->joined) return;
    close(client->fd[0]);
    close(client->fd[1]);
    c300x_rtsp_writer_release(client->writer);
    client->joined = false;
}

/* Starts with AUD, SPS, PPS and the IDR's first part; every sequence number
 * follows the one before; the cached frames 1 ms apart, then the station's
 * own spacing. Returns the number of IDR parts. */
static int assert_clean_start(const struct rx *rx, size_t count, size_t cached_frames)
{
    assert(count >= 4);
    assert(rx[0].nal == 9 && rx[1].nal == 7 && rx[2].nal == 8 && rx[3].nal == 28 && rx[3].fu == 0x85);
    int idr_parts = 0;
    size_t frame = 0;
    for (size_t index = 0; index < count; index++) {
        assert(rx[index].ssrc == rx[0].ssrc);
        if (index > 0) {
            assert(rx[index].seq == (uint16_t)(rx[index - 1].seq + 1));
            uint32_t step = rx[index].ts - rx[index - 1].ts;
            if (step != 0) {
                frame++;
                assert(step == (frame < cached_frames ? 90u : 6000u));
            }
        }
        if (rx[index].nal == 28 && (rx[index].fu & 0x1f) == 5) idr_parts++;
    }
    return idr_parts;
}

static struct rx rx[MAX_RX];

static void late_join(void)
{
    struct station station = {.ssrc = 0x6007c441, .ts = 1308642029, .seq = 1281};
    join(0);
    /* Joined before the stream: waits for the IDR, then gets it whole. */
    send_frame(&station, false, 3);
    assert(receive(&clients[0], rx, MAX_RX) == 0);
    send_frame(&station, true, 121);
    for (int frame = 0; frame < 5; frame++) send_frame(&station, false, 4);
    size_t count = receive(&clients[0], rx, MAX_RX);
    assert(count == 3 + 121 + 5 * 5);
    assert(assert_clean_start(rx, count, 1) == 121);
    assert(rx[0].seq == 1281 + 4 && rx[0].ts == 1308642029 + 6000 && rx[0].ssrc == 0x6007c441);
    /* A late client: the cached group, then live, its own numbering. */
    join(1);
    send_frame(&station, false, 4);
    for (int frame = 0; frame < 3; frame++) send_frame(&station, false, 4);
    count = receive(&clients[1], rx, MAX_RX);
    assert(count == 3 + 121 + 6 * 5 + 3 * 5);
    assert(assert_clean_start(rx, count, 7) == 121);
    /* The first client stayed live and unchanged. */
    count = receive(&clients[0], rx, MAX_RX);
    assert(count == 4 * 5);
    for (size_t index = 1; index < count; index++) assert(rx[index].seq == (uint16_t)(rx[index - 1].seq + 1));
    /* The next group replaces the cache. */
    send_frame(&station, true, 10);
    assert(gop.group && gop.packets[0].length == 14 && gop.count == 13);
    leave(0);
    leave(1);
}

static void cap(void)
{
    struct station station = {.ssrc = 1, .ts = 1, .seq = 65000};
    /* An IDR bigger than the cache never starts a client half-way. */
    send_frame(&station, true, 420);
    assert(!gop.group && gop.count == 0);
    join(0);
    send_frame(&station, false, 4);
    assert(receive(&clients[0], rx, MAX_RX) == 0);
    send_frame(&station, true, 50);
    size_t count = receive(&clients[0], rx, MAX_RX);
    assert(count == 53 && assert_clean_start(rx, count, 1) == 50);
    /* A group growing past the cap stops caching; a new client waits. */
    for (int frame = 0; frame < 6; frame++) send_frame(&station, false, 60);
    assert(!gop.group);
    join(1);
    send_frame(&station, false, 4);
    assert(receive(&clients[1], rx, MAX_RX) == 0);
    send_frame(&station, true, 5);
    count = receive(&clients[1], rx, MAX_RX);
    assert(count == 8 && assert_clean_start(rx, count, 1) == 5);
    /* The packet limit holds for small packets as well. */
    unsigned char aud[2] = {0x09, 0xf0};
    for (unsigned index = 0; index < C300X_MEDIA_GOP_CACHE_PACKETS + 10; index++) {
        send_packet(&station, aud, sizeof(aud), false);
    }
    assert(!gop.group);
    leave(0);
    leave(1);
}

static void age(void)
{
    struct station station = {.ssrc = 2, .ts = 7, .seq = 9};
    send_frame(&station, true, 20);
    /* 1.5 s of P frames; the group is too old after that. */
    for (int frame = 0; frame < 22; frame++) send_frame(&station, false, 1);
    assert(gop.group);
    send_frame(&station, false, 1);
    assert(!gop.group);
    join(0);
    send_frame(&station, false, 1);
    assert(receive(&clients[0], rx, MAX_RX) == 0);
    send_frame(&station, true, 3);
    size_t count = receive(&clients[0], rx, MAX_RX);
    assert(count == 6 && assert_clean_start(rx, count, 1) == 3);
    leave(0);
}

static void stale(void)
{
    struct station station = {.ssrc = 3, .ts = 70, .seq = 90};
    send_frame(&station, true, 20);
    send_frame(&station, false, 2);
    /* The stream paused: its group is not sent to anyone afterwards. */
    clock_ms += 2000;
    join(0);
    send_frame(&station, false, 2);
    assert(receive(&clients[0], rx, MAX_RX) == 0);
    send_frame(&station, true, 2);
    size_t count = receive(&clients[0], rx, MAX_RX);
    assert(count == 5 && assert_clean_start(rx, count, 1) == 2);
    leave(0);
    /* A session end drops the cache as well. */
    send_frame(&station, true, 20);
    c300x_media_gop_reset();
    assert(gop.data == NULL && !gop.group);
    join(1);
    send_frame(&station, false, 2);
    assert(receive(&clients[1], rx, MAX_RX) == 0);
    leave(1);
}

static void restart(void)
{
    struct station first = {.ssrc = 4, .ts = 100, .seq = 500};
    struct station second = {.ssrc = 0xabcdef, .ts = 99999999, .seq = 40000};
    join(0);
    send_frame(&first, true, 3);
    send_frame(&first, false, 2);
    size_t count = receive(&clients[0], rx, MAX_RX);
    assert(count == 6 + 3);
    struct rx last = rx[count - 1];
    /* A new stream: nothing until its IDR, then the numbering goes on. */
    send_frame(&second, false, 2);
    assert(receive(&clients[0], rx, MAX_RX) == 0);
    send_frame(&second, true, 2);
    count = receive(&clients[0], rx, MAX_RX);
    assert(count == 5 && assert_clean_start(rx, count, 1) == 2);
    assert(rx[0].seq == (uint16_t)(last.seq + 1) && rx[0].ssrc == last.ssrc);
    uint32_t step = rx[0].ts - last.ts;
    assert(step >= 90 && step <= 90 * 200);
    leave(0);
}

/* The station restarts its stream after a pause with the same SSRC and an
 * earlier sequence number: that is a new stream, not a run of repeats. */
static void resume(void)
{
    struct station station = {.ssrc = 8, .ts = 5000, .seq = 3000};
    join(0);
    send_frame(&station, true, 2);
    send_frame(&station, false, 2);
    size_t count = receive(&clients[0], rx, MAX_RX);
    assert(count == 5 + 3);
    struct rx last = rx[count - 1];
    clock_ms += 3000;
    station.seq = (uint16_t)(station.seq - 500);
    station.ts += 777777;
    send_frame(&station, false, 2);
    assert(receive(&clients[0], rx, MAX_RX) == 0);
    send_frame(&station, true, 2);
    send_frame(&station, false, 2);
    count = receive(&clients[0], rx, MAX_RX);
    assert(count == 5 + 3 && assert_clean_start(rx, count, 1) == 2);
    assert(rx[0].seq == (uint16_t)(last.seq + 1) && rx[0].ssrc == last.ssrc);
    /* A pause without a restart: the stream goes on where it was. */
    clock_ms += 3000;
    send_frame(&station, false, 2);
    count = receive(&clients[0], rx, MAX_RX);
    assert(count == 3 && rx[0].nal == 9);
    leave(0);
}

static void loss(void)
{
    struct station station = {.ssrc = 5, .ts = 1, .seq = 1};
    join(0);
    send_frame(&station, true, 2);
    assert(receive(&clients[0], rx, MAX_RX) == 5);
    station.seq++; /* one packet lost */
    send_frame(&station, false, 2);
    assert(!gop.group);
    size_t count = receive(&clients[0], rx, MAX_RX);
    assert(count == 3 && rx[0].seq == 7);
    /* A repeated packet is not sent again. */
    station.seq--;
    station.ts -= 6000;
    unsigned char aud[2] = {0x09, 0xf0};
    send_packet(&station, aud, sizeof(aud), false);
    assert(receive(&clients[0], rx, MAX_RX) == 0);
    station.ts += 6000;
    send_frame(&station, false, 2);
    count = receive(&clients[0], rx, MAX_RX);
    assert(count == 3 && rx[0].seq == 10);
    join(1);
    station.seq += 3;
    send_frame(&station, false, 2);
    assert(receive(&clients[1], rx, MAX_RX) == 0);
    leave(0);
    leave(1);
}

static void slow(void)
{
    struct station station = {.ssrc = 6, .ts = 1, .seq = 1};
    send_frame(&station, true, 60);
    join(0);
    int size = 4096;
    assert(setsockopt(clients[0].fd[0], SOL_SOCKET, SO_SNDBUF, &size, sizeof(size)) == 0);
    send_frame(&station, false, 2);
    /* The group did not fit: no repeated start within the same group. */
    size_t count = receive(&clients[0], rx, MAX_RX);
    assert(count < 63 && !gop.clients[0].live);
    send_frame(&station, false, 2);
    assert(receive(&clients[0], rx, MAX_RX) == 0);
    /* The client reads again: the next group starts it, after the frame the
     * writer had begun. */
    size = 4 << 20;
    assert(setsockopt(clients[0].fd[0], SOL_SOCKET, SO_SNDBUF, &size, sizeof(size)) == 0);
    send_frame(&station, true, 2);
    count = receive(&clients[0], rx, MAX_RX);
    assert(count >= 5 && gop.clients[0].live);
    assert(rx[count - 5].nal == 9 && rx[count - 4].nal == 7 && rx[count - 3].nal == 8);
    leave(0);
}

static int open_fds(void)
{
    int count = 0;
    for (int fd = 0; fd < 1024; fd++) count += fcntl(fd, F_GETFD) >= 0;
    return count;
}

static void malformed(void)
{
    join(0);
    int before = open_fds();
    unsigned char packet[64] = {0x80, 96, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0x65};
    forward_raw(packet, 12);                 /* no payload */
    packet[0] = 0x40;
    forward_raw(packet, 13);                 /* version 1 */
    packet[0] = 0x8f;
    forward_raw(packet, 40);                 /* CSRCs beyond the end */
    packet[0] = 0x90;
    packet[14] = 0xff;
    forward_raw(packet, 20);                 /* extension beyond the end */
    packet[0] = 0xa0;
    packet[19] = 0;
    forward_raw(packet, 20);                 /* zero padding */
    packet[19] = 30;
    forward_raw(packet, 20);                 /* padding beyond the end */
    packet[0] = 0x80;
    packet[12] = 0x7c;
    forward_raw(packet, 13);                 /* FU-A without its header */
    packet[12] = 0x18;
    packet[13] = 0xff;
    forward_raw(packet, 20);                 /* STAP-A sizes beyond the end */
    c300x_media_gop_forward(NULL, 0, NULL, 0);
    assert(receive(&clients[0], rx, MAX_RX) == 0);
    assert(open_fds() == before);
    leave(0);
}

static void no_memory(void)
{
    c300x_media_gop_reset();
    fail_malloc = true;
    struct station station = {.ssrc = 7, .ts = 1, .seq = 1};
    join(0);
    send_frame(&station, false, 2);
    /* Without a cache the client starts at once, as before. */
    size_t count = receive(&clients[0], rx, MAX_RX);
    assert(count == 3 && rx[0].seq == 1);
    fail_malloc = false;
    leave(0);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (strcmp(argv[1], "late_join") == 0) late_join();
    else if (strcmp(argv[1], "cap") == 0) cap();
    else if (strcmp(argv[1], "age") == 0) age();
    else if (strcmp(argv[1], "stale") == 0) stale();
    else if (strcmp(argv[1], "restart") == 0) restart();
    else if (strcmp(argv[1], "resume") == 0) resume();
    else if (strcmp(argv[1], "loss") == 0) loss();
    else if (strcmp(argv[1], "slow") == 0) slow();
    else if (strcmp(argv[1], "malformed") == 0) malformed();
    else if (strcmp(argv[1], "no_memory") == 0) no_memory();
    else return 2;
    c300x_media_gop_reset();
    puts("ok");
    return 0;
}
