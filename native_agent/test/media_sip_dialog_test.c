#include "../src/media_sip_dialog.h"
#include "../src/media_sip.h"
#include "../src/media_sip_io.h"
#include "../src/time_util.h"

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

time_t __wrap_time(time_t *out)
{
    if (out) *out = 1700000000;
    return 1700000000;
}

static void expect(int fd, const char *expected)
{
    char wire[4096];
    int count = c300x_media_sip_read_message(fd, wire, sizeof(wire), 100);
    assert(count == (int)strlen(expected));
    assert(strcmp(wire, expected) == 0);
}

static void empty(int fd)
{
    char byte;
    assert(recv(fd, &byte, 1, MSG_DONTWAIT) == -1);
    assert(errno == EAGAIN || errno == EWOULDBLOCK);
}

static void requests(int *fds)
{
    c300x_media_sip_send_ack(fds[0], "local@example.test", "door@example.test", "127.0.0.1", 5060,
        "TCP", "<sip:door@example.test>;tag=remote", "local-tag", "call-id",
        "sip:contact@example.test:5070", 21);
    expect(fds[1], "ACK sip:contact@example.test:5070 SIP/2.0\r\n"
        "Via: SIP/2.0/TCP 127.0.0.1:5060;branch=z9hG4bKack1700000000;rport\r\n"
        "Max-Forwards: 70\r\nTo: <sip:door@example.test>;tag=remote\r\n"
        "From: <sip:local@example.test>;tag=local-tag\r\nCall-ID: call-id\r\nCSeq: 21 ACK\r\n"
        "User-Agent: VctLinphoneService/1.17.3\r\nContent-Length: 0\r\n\r\n");
    c300x_media_sip_send_ack(fds[0], "a", "b", "127.0.0.1", 5061, "UDP", "to", "tag", "id", NULL, 7);
    expect(fds[1], "ACK sip:b SIP/2.0\r\n"
        "Via: SIP/2.0/UDP 127.0.0.1:5061;branch=z9hG4bKack1700000000;rport\r\n"
        "Max-Forwards: 70\r\nTo: to\r\nFrom: <sip:a>;tag=tag\r\nCall-ID: id\r\nCSeq: 7 ACK\r\n"
        "User-Agent: VctLinphoneService/1.17.3\r\nContent-Length: 0\r\n\r\n");
    c300x_media_sip_send_bye(fds[0], "a", "b", "127.0.0.1", 5060, "TCP", "to", "tag", "id", "");
    expect(fds[1], "BYE sip:b SIP/2.0\r\n"
        "Via: SIP/2.0/TCP 127.0.0.1:5060;branch=z9hG4bKbye1700000000;rport\r\n"
        "Max-Forwards: 70\r\nTo: to\r\nFrom: <sip:a>;tag=tag\r\nCall-ID: id\r\nCSeq: 22 BYE\r\n"
        "User-Agent: VctLinphoneService/1.17.3\r\nContent-Length: 0\r\n\r\n");
    c300x_media_sip_send_cancel(fds[0], "b", "a", "tag", "id", "original-branch", "127.0.0.1", 5060, "TCP");
    expect(fds[1], "CANCEL sip:b SIP/2.0\r\n"
        "Via: SIP/2.0/TCP 127.0.0.1:5060;branch=original-branch;rport\r\n"
        "Max-Forwards: 70\r\nTo: <sip:b>\r\nFrom: <sip:a>;tag=tag\r\n"
        "Call-ID: id\r\nCSeq: 21 CANCEL\r\nContent-Length: 0\r\n\r\n");
}

static const char invite[] = "INVITE sip:local@example.test SIP/2.0\r\n"
    "Via: first\r\nvIa: second\r\nRecord-Route: <sip:proxy>\r\n"
    "To: <sip:local@example.test>\r\nFrom: <sip:door@example.test>;tag=remote\r\n"
    "Call-ID: call-id\r\nCSeq: 20 INVITE\r\nContent-Length: 0\r\n\r\n";

static void replies(int *fds)
{
    c300x_media_sip_send_ok(fds[0], invite);
    expect(fds[1], "SIP/2.0 200 OK\r\nVia: first\r\nvIa: second\r\n"
        "To: <sip:local@example.test>\r\nFrom: <sip:door@example.test>;tag=remote\r\n"
        "Call-ID: call-id\r\nCSeq: 20 INVITE\r\nContent-Length: 0\r\n\r\n");
    c300x_media_sip_send_ring_bye(fds[0], invite, "local-tag", "sip:remote-contact");
    expect(fds[1], "BYE sip:remote-contact SIP/2.0\r\n"
        "Via: SIP/2.0/TCP 127.0.0.1:5060;branch=z9hG4bKringbye1700000000;rport\r\n"
        "Max-Forwards: 70\r\nFrom: <sip:local@example.test>;tag=local-tag\r\n"
        "To: <sip:door@example.test>;tag=remote\r\nCall-ID: call-id\r\nCSeq: 111 BYE\r\n"
        "User-Agent: VctLinphoneService/1.17.3\r\nContent-Length: 0\r\n\r\n");
    c300x_media_sip_send_ring_bye(fds[0], invite, "local-tag", NULL);
    expect(fds[1], "BYE sip:c300x@127.0.0.1:5060 SIP/2.0\r\n"
        "Via: SIP/2.0/TCP 127.0.0.1:5060;branch=z9hG4bKringbye1700000000;rport\r\n"
        "Max-Forwards: 70\r\nFrom: <sip:local@example.test>;tag=local-tag\r\n"
        "To: <sip:door@example.test>;tag=remote\r\nCall-ID: call-id\r\nCSeq: 111 BYE\r\n"
        "User-Agent: VctLinphoneService/1.17.3\r\nContent-Length: 0\r\n\r\n");
}

static void rejected(int *fds)
{
    c300x_media_sip_send_ok(fds[0], "OPTIONS x SIP/2.0\r\nTo: x\r\n\r\n");
    c300x_media_sip_send_ring_bye(fds[0], "INVITE x SIP/2.0\r\n\r\n", "tag", NULL);
    c300x_media_sip_send_ack(fds[0], "", "b", "ip", 5060, "TCP", "to", "tag", "id", NULL, 1);
    c300x_media_sip_send_bye(fds[0], "a", "b", "ip", 5060, "TCP", "", "tag", "id", NULL);
    c300x_media_sip_send_cancel(fds[0], "b", "a", "tag", "id", "", "ip", 5060, "TCP");
    char long_uri[2048];
    memset(long_uri, 'x', sizeof(long_uri) - 1);
    long_uri[sizeof(long_uri) - 1] = '\0';
    c300x_media_sip_send_ack(fds[0], "a", "b", "ip", 5060, "TCP", "to", "tag", "id", long_uri, 1);
    empty(fds[1]);
}

static void header_capacity(void)
{
    char out[24] = "prefix\r\n";
    size_t used = strlen(out);
    c300x_media_sip_append_headers(out, sizeof(out), &used,
        "Via: too-long-to-fit-in-the-buffer\r\nVia: x\r\nVia: y\r\n", "Via:");
    assert(strcmp(out, "prefix\r\nVia: x\r\n") == 0);
    assert(used == strlen(out));
}

static void write_budget(void)
{
    int fds[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, fds) == 0);
    int size = 4096;
    assert(setsockopt(fds[0], SOL_SOCKET, SO_SNDBUF, &size, sizeof(size)) == 0);
    size_t length = 1024 * 1024;
    char *data = calloc(1, length);
    assert(data);
    long long start = c300x_monotonic_ms();
    assert(c300x_media_sip_send_all(fds[0], data, length) == -1);
    long long elapsed = c300x_monotonic_ms() - start;
    assert(elapsed >= 1800 && elapsed < 4000);
    assert(fcntl(fds[0], F_GETFD) >= 0);
    free(data);
    close(fds[1]);
    assert(c300x_media_sip_send_all(fds[0], "x", 1) == -1);
    assert(fcntl(fds[0], F_GETFD) >= 0);
    close(fds[0]);
}

int main(void)
{
    int fds[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, fds) == 0);
    requests(fds);
    replies(fds);
    rejected(fds);
    header_capacity();
    /* Calls do not close, shutdown or retain the borrowed descriptors. */
    assert(c300x_media_sip_send_all(fds[0], "ok", 2) == 2);
    char check[2];
    assert(recv(fds[1], check, sizeof(check), 0) == 2);
    assert(memcmp(check, "ok", 2) == 0);
    close(fds[0]);
    close(fds[1]);
    write_budget();
    return 0;
}
