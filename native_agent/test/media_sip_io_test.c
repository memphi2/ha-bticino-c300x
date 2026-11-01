#include "../src/media_bridge.c"

#include <assert.h>
#include <poll.h>
#include <signal.h>

static const char trying[] = "SIP/2.0 100 Trying\r\nContent-Length: 0\r\n\r\n";
static const char answer[] = "SIP/2.0 200 OK\r\nContent-Length: 8\r\n\r\nv=0\r\nabc";
static const char bye[] = "BYE sip:device@example.test SIP/2.0\r\nContent-Length: 0\r\n\r\n";

static void put(int fd, const char *text)
{
    assert(send_all(fd, text, strlen(text)) == (ssize_t)strlen(text));
}

static void expect(int fd, const char *text)
{
    char buffer[1024];
    int count = read_message(fd, buffer, sizeof(buffer), 1);
    assert(count == (int)strlen(text));
    assert(strcmp(buffer, text) == 0);
}

static void pair(int *fds, int type)
{
    assert(socketpair(AF_UNIX, type, 0, fds) == 0);
}

static void finish(int *fds)
{
    close(fds[0]);
    close(fds[1]);
}

static void coalesced(void)
{
    int fds[2];
    char messages[1024];
    pair(fds, SOCK_STREAM);
    snprintf(messages, sizeof(messages), "%s%s%s", trying, answer, bye);
    put(fds[0], messages);
    expect(fds[1], trying);
    struct pollfd pending = {.fd = fds[1], .events = POLLIN};
    assert(poll(&pending, 1, 0) == 1);
    expect(fds[1], answer);
    expect(fds[1], bye);
    finish(fds);
}

typedef struct {
    int fd;
    const char *text;
    size_t step;
    long delay_ns;
} writer_t;

static void *write_fragments(void *arg)
{
    writer_t *writer = arg;
    size_t size = strlen(writer->text);
    for (size_t offset = 0; offset < size; offset += writer->step) {
        struct timespec delay = {.tv_nsec = writer->delay_ns};
        nanosleep(&delay, NULL);
        size_t count = size - offset;
        if (count > writer->step) {
            count = writer->step;
        }
        assert(send_all(writer->fd, writer->text + offset, count) == (ssize_t)count);
    }
    return NULL;
}

static void fragmented(void)
{
    const char *message = "SIP/2.0 200 OK\r\nContent-Length: 18\r\n\r\n\r\n\r\nSIP/2.0 999!!!";
    char input[512];
    snprintf(input, sizeof(input), "\r\n\r\n%s%s", message, bye);
    for (size_t split = 1; split < strlen(input); split++) {
        int fds[2];
        pthread_t writer;
        pair(fds, SOCK_STREAM);
        assert(send_all(fds[0], input, split) == (ssize_t)split);
        writer_t args = {fds[0], input + split, strlen(input), 1000000};
        assert(pthread_create(&writer, NULL, write_fragments, &args) == 0);
        expect(fds[1], message);
        expect(fds[1], bye);
        pthread_join(writer, NULL);
        finish(fds);
    }
}

static void deadline(void)
{
    int fds[2];
    pthread_t writer;
    char buffer[1024];
    pair(fds, SOCK_STREAM);
    put(fds[0], "S");
    writer_t args = {fds[0], answer + 1, 3, 20000000};
    assert(pthread_create(&writer, NULL, write_fragments, &args) == 0);
    assert(c300x_media_sip_read_message(fds[1], buffer, sizeof(buffer), 80) == -1);
    assert(buffer[0] == '\0');
    pthread_join(writer, NULL);
    finish(fds);
}

static void keepalive(void)
{
    int fds[2];
    char buffer[512];
    pair(fds, SOCK_STREAM);
    snprintf(buffer, sizeof(buffer), "\r\n\r\n%s\r\n%s\r\n\r\n", trying, answer);
    put(fds[0], buffer);
    expect(fds[1], trying);
    expect(fds[1], answer);
    assert(c300x_media_sip_read_message(fds[1], buffer, sizeof(buffer), 30) == 0);
    assert(buffer[0] == '\0');
    finish(fds);
}

static void keepalive_response(void)
{
    const int types[] = {SOCK_STREAM, SOCK_DGRAM};
    for (size_t i = 0; i < sizeof(types) / sizeof(types[0]); i++) {
        int fds[2];
        pthread_t writer;
        pair(fds, types[i]);
        put(fds[0], "\r\n\r\n");
        writer_t args = {fds[0], answer, strlen(answer), 20000000};
        assert(pthread_create(&writer, NULL, write_fragments, &args) == 0);
        expect(fds[1], answer);
        pthread_join(writer, NULL);
        finish(fds);
    }
}

static void poll_keepalive(void)
{
    const int types[] = {SOCK_STREAM, SOCK_DGRAM};
    for (size_t i = 0; i < sizeof(types) / sizeof(types[0]); i++) {
        int fds[2];
        char buffer[512];
        pair(fds, types[i]);
        put(fds[0], "\r\n\r\n");
        long long start = c300x_monotonic_ms();
        assert(read_message_poll(fds[1], buffer, sizeof(buffer), 1) == 0);
        assert(buffer[0] == '\0');
        assert(c300x_monotonic_ms() - start < 500);
        put(fds[0], answer);
        assert(read_message_poll(fds[1], buffer, sizeof(buffer), 1) == (int)strlen(answer));
        assert(strcmp(buffer, answer) == 0);
        finish(fds);
    }

    int fds[2];
    char buffer[512];
    pair(fds, SOCK_STREAM);
    snprintf(buffer, sizeof(buffer), "\r\n\r\n%s%s", trying, answer);
    put(fds[0], buffer);
    assert(read_message_poll(fds[1], buffer, sizeof(buffer), 1) == (int)strlen(trying));
    assert(strcmp(buffer, trying) == 0);
    assert(read_message_poll(fds[1], buffer, sizeof(buffer), 1) == (int)strlen(answer));
    assert(strcmp(buffer, answer) == 0);
    finish(fds);
}

static void poll_fragmented(void)
{
    int fds[2];
    pthread_t writer;
    char buffer[512];
    pair(fds, SOCK_STREAM);
    writer_t args = {fds[0], answer, 1, 1000000};
    assert(pthread_create(&writer, NULL, write_fragments, &args) == 0);
    assert(read_message_poll(fds[1], buffer, sizeof(buffer), 1) == (int)strlen(answer));
    assert(strcmp(buffer, answer) == 0);
    pthread_join(writer, NULL);
    shutdown(fds[0], SHUT_WR);
    assert(read_message_poll(fds[1], buffer, sizeof(buffer), 1) == -1);
    assert(buffer[0] == '\0');
    finish(fds);
}

static void invalid(const char *field)
{
    int fds[2];
    char input[512];
    char buffer[256];
    pair(fds, SOCK_STREAM);
    snprintf(input, sizeof(input), "SIP/2.0 200 OK\r\n%s\r\n", field);
    put(fds[0], input);
    assert(c300x_media_sip_read_message(fds[1], buffer, sizeof(buffer), 30) == -1);
    assert(buffer[0] == '\0');
    finish(fds);
}

static void incomplete(const char *input, bool eof)
{
    int fds[2];
    char buffer[256];
    pair(fds, SOCK_STREAM);
    put(fds[0], input);
    if (eof) {
        shutdown(fds[0], SHUT_WR);
    }
    assert(c300x_media_sip_read_message(fds[1], buffer, sizeof(buffer), 30) == -1);
    assert(buffer[0] == '\0');
    finish(fds);
}

static void lengths(void)
{
    const char *messages[] = {
        "SIP/2.0 200 OK\r\nl: 3\r\n\r\nabc",
        "SIP/2.0 200 OK\r\nCoNtEnT-LeNgTh \t: \t3 \t\r\n\r\nabc",
        "SIP/2.0 200 OK\r\nContent-Length:\r\n \t3\r\n\r\nabc",
        "SIP/2.0 200 OK\r\nX-Test: ignore\r\n Content-Length: 999\r\nl: 3\r\n\r\nabc"
    };
    for (size_t i = 0; i < sizeof(messages) / sizeof(messages[0]); i++) {
        int fds[2];
        pair(fds, SOCK_STREAM);
        put(fds[0], messages[i]);
        expect(fds[1], messages[i]);
        finish(fds);
    }
}

static void limits(void)
{
    int fds[2];
    char buffer[sizeof(answer)];
    pair(fds, SOCK_STREAM);
    put(fds[0], answer);
    put(fds[0], trying);
    assert(c300x_media_sip_read_message(fds[1], buffer, sizeof(buffer), 100) == (int)strlen(answer));
    assert(strcmp(buffer, answer) == 0);
    expect(fds[1], trying);
    finish(fds);

    pair(fds, SOCK_STREAM);
    put(fds[0], answer);
    assert(c300x_media_sip_read_message(fds[1], buffer, sizeof(buffer) - 1, 100) == -1);
    finish(fds);

    pair(fds, SOCK_STREAM);
    put(fds[0], "SIP/2.0 200 OK\r\nX-Long: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
    assert(c300x_media_sip_read_message(fds[1], buffer, sizeof(buffer), 100) == -1);
    finish(fds);
}

static void datagrams(void)
{
    int fds[2];
    char buffer[512];
    pair(fds, SOCK_DGRAM);
    put(fds[0], answer);
    put(fds[0], trying);
    expect(fds[1], answer);
    expect(fds[1], trying);
    put(fds[0], "SIP/2.0 200 OK\r\n\r\nv=0");
    expect(fds[1], "SIP/2.0 200 OK\r\n\r\nv=0");
    put(fds[0], "SIP/2.0 200 OK\r\nContent-Length: 8\r\n\r\nv=");
    put(fds[0], trying);
    assert(c300x_media_sip_read_message(fds[1], buffer, sizeof(buffer), 100) == -1);
    expect(fds[1], trying);
    put(fds[0], answer);
    assert(c300x_media_sip_read_message(fds[1], buffer, sizeof(answer) - 1, 100) == -1);
    put(fds[0], "SIP/2.0 200 OK\r\nContent-Length: 0\r\n\r\nignored");
    expect(fds[1], "SIP/2.0 200 OK\r\nContent-Length: 0\r\n\r\n");
    put(fds[0], "\r\n\r\n");
    assert(c300x_media_sip_read_message(fds[1], buffer, sizeof(buffer), 100) == 0);
    finish(fds);
}

static void independent(void)
{
    int first[2], second[2];
    pair(first, SOCK_STREAM);
    pair(second, SOCK_STREAM);
    put(first[0], trying);
    put(first[0], answer);
    put(second[0], bye);
    expect(first[1], trying);
    expect(second[1], bye);
    expect(first[1], answer);
    finish(first);
    finish(second);
}

static void tcp(void)
{
    int server = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    socklen_t size = sizeof(address);
    int fds[2];
    char input[512];
    assert(server >= 0);
    assert(bind(server, (struct sockaddr *)&address, sizeof(address)) == 0);
    assert(listen(server, 1) == 0);
    assert(getsockname(server, (struct sockaddr *)&address, &size) == 0);
    fds[0] = socket(AF_INET, SOCK_STREAM, 0);
    assert(fds[0] >= 0);
    assert(connect(fds[0], (struct sockaddr *)&address, size) == 0);
    fds[1] = accept(server, NULL, NULL);
    assert(fds[1] >= 0);
    close(server);
    snprintf(input, sizeof(input), "%s%s%s", trying, answer, bye);
    put(fds[0], input);
    expect(fds[1], trying);
    expect(fds[1], answer);
    expect(fds[1], bye);
    finish(fds);
}

static volatile sig_atomic_t interruptions;
static pthread_t reader_thread;

static void interrupt_reader(int signal_number)
{
    (void)signal_number;
    interruptions++;
}

static void *interrupt_then_write(void *arg)
{
    int fd = *(int *)arg;
    struct timespec delay = {.tv_nsec = 20000000};
    nanosleep(&delay, NULL);
    assert(pthread_kill(reader_thread, SIGUSR1) == 0);
    nanosleep(&delay, NULL);
    put(fd, answer);
    return NULL;
}

static void interrupted(void)
{
    int fds[2];
    pthread_t writer;
    struct sigaction handler = {.sa_handler = interrupt_reader};
    struct sigaction previous;
    sigemptyset(&handler.sa_mask);
    assert(sigaction(SIGUSR1, &handler, &previous) == 0);
    pair(fds, SOCK_STREAM);
    reader_thread = pthread_self();
    assert(pthread_create(&writer, NULL, interrupt_then_write, &fds[0]) == 0);
    expect(fds[1], answer);
    pthread_join(writer, NULL);
    assert(interruptions == 1);
    assert(sigaction(SIGUSR1, &previous, NULL) == 0);
    finish(fds);
}

static void binary_body(void)
{
    int fds[2];
    const char message[] = "SIP/2.0 200 OK\r\nContent-Length: 3\r\n\r\na\0b";
    char buffer[512];
    pair(fds, SOCK_STREAM);
    assert(send_all(fds[0], message, sizeof(message) - 1) == (ssize_t)sizeof(message) - 1);
    put(fds[0], trying);
    int count = c300x_media_sip_read_message(fds[1], buffer, sizeof(buffer), 100);
    assert(count == sizeof(message) - 1);
    assert(memcmp(buffer, message, sizeof(message)) == 0);
    expect(fds[1], trying);
    finish(fds);
}

static void idle_and_eof(void)
{
    int fds[2];
    char buffer[512];
    pair(fds, SOCK_STREAM);
    assert(c300x_media_sip_read_message(fds[1], buffer, sizeof(buffer), 30) == 0);
    put(fds[0], answer);
    shutdown(fds[0], SHUT_WR);
    expect(fds[1], answer);
    assert(c300x_media_sip_read_message(fds[1], buffer, sizeof(buffer), 30) == -1);
    assert(c300x_media_sip_read_message(-1, buffer, sizeof(buffer), 30) == -1);
    assert(c300x_media_sip_read_message(fds[1], buffer, 1, 30) == -1);
    assert(c300x_media_sip_read_message(fds[1], NULL, 0, 30) == -1);
    finish(fds);
}

static void stop_responses(void)
{
    int fds[2];
    pair(fds, SOCK_STREAM);
    put(fds[0], "SIP/2.0 200 OK\r\nCSeq: 21 CANCEL\r\nContent-Length: 0\r\n\r\n"
                "SIP/2.0 487 Request Terminated\r\nCSeq: 21 INVITE\r\nContent-Length: 0\r\n\r\n");
    put(fds[0], bye);
    drain_home_call_stop_responses(fds[1], "CANCEL", true);
    expect(fds[1], bye);
    finish(fds);
}

static void stop_eof(void)
{
    int fds[2];
    pair(fds, SOCK_STREAM);
    shutdown(fds[0], SHUT_WR);
    long long start = c300x_monotonic_ms();
    drain_home_call_stop_responses(fds[1], "BYE", false);
    assert(c300x_monotonic_ms() - start < 1000);
    finish(fds);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    const char *name = argv[1];
    if (strcmp(name, "coalesced") == 0) coalesced();
    else if (strcmp(name, "fragmented") == 0) fragmented();
    else if (strcmp(name, "keepalive") == 0) keepalive();
    else if (strcmp(name, "keepalive_response") == 0) keepalive_response();
    else if (strcmp(name, "poll_keepalive") == 0) poll_keepalive();
    else if (strcmp(name, "poll_fragmented") == 0) poll_fragmented();
    else if (strcmp(name, "deadline") == 0) deadline();
    else if (strcmp(name, "lengths") == 0) lengths();
    else if (strcmp(name, "limits") == 0) limits();
    else if (strcmp(name, "datagrams") == 0) datagrams();
    else if (strcmp(name, "independent") == 0) independent();
    else if (strcmp(name, "tcp") == 0) tcp();
    else if (strcmp(name, "interrupted") == 0) interrupted();
    else if (strcmp(name, "binary_body") == 0) binary_body();
    else if (strcmp(name, "stop_responses") == 0) stop_responses();
    else if (strcmp(name, "stop_eof") == 0) stop_eof();
    else if (strcmp(name, "idle_and_eof") == 0) idle_and_eof();
    else if (strcmp(name, "negative_length") == 0) invalid("Content-Length: -1\r\n");
    else if (strcmp(name, "oversize_length") == 0) invalid("Content-Length: 99999999999999999999999999999\r\n");
    else if (strcmp(name, "duplicate_length") == 0) invalid("Content-Length: 0\r\nl: 0\r\n");
    else if (strcmp(name, "garbage_length") == 0) invalid("Content-Length: 0oops\r\n");
    else if (strcmp(name, "empty_length") == 0) invalid("Content-Length: \r\n");
    else if (strcmp(name, "missing_length") == 0) invalid("Via: SIP/2.0/TCP example.test\r\n");
    else if (strcmp(name, "partial_header") == 0) incomplete("SIP/2.0 200 OK\r\nContent-Length: 0\r\n", false);
    else if (strcmp(name, "partial_body") == 0) incomplete("SIP/2.0 200 OK\r\nContent-Length: 8\r\n\r\nv=0", false);
    else if (strcmp(name, "eof_header") == 0) incomplete("SIP/2.0 200 OK\r\n", true);
    else if (strcmp(name, "eof_body") == 0) incomplete("SIP/2.0 200 OK\r\nContent-Length: 8\r\n\r\nv=0", true);
    else assert(false);
    return 0;
}
