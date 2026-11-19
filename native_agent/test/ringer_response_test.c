/* Production OpenWebNet readback and HTTP formatting, loopback only. */
#include <assert.h>
#include <pthread.h>
#include "../src/http.c"

static int listener, normal_reply, include_muted, only_muted, mismatched, malformed_readback, short_reply;

int __wrap_nanosleep(const struct timespec *requested, struct timespec *remaining)
{
    /* No physical device needs the one-second volume-settle delay here. */
    (void)requested;
    (void)remaining;
    return 0;
}

static int read_command(int fd, char *frame, size_t capacity)
{
    size_t used = 0;
    while (used + 1 < capacity) {
        ssize_t count = recv(fd, frame + used, 1, 0);
        if (count == 0) return 0;
        assert(count == 1);
        used++;
        frame[used] = '\0';
        if (used >= 2 && !strcmp(frame + used - 2, "##")) return 1;
    }
    assert(!"oversized command");
    return 0;
}

static void *openwebnet_server(void *unused)
{
    (void)unused;
    int connections = include_muted && !only_muted ? 2 : 1;
    for (int i = 0; i < connections; i++) {
        int fd = accept(listener, NULL, NULL);
        assert(fd >= 0);
        struct timeval timeout = {3, 0};
        assert(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
        char command[64], malformed[256], padded[256];
        memset(malformed, 1, 253);
        memcpy(malformed + 253, "##", 3);
        memset(padded, '\t', 251);
        memcpy(padded, "*#8**41*", 8);
        memcpy(padded + 251, mismatched ? "20##" : "10##", 5);
        assert(send_all_bytes(fd, "*#*1##", 6));
        assert(read_command(fd, command, sizeof(command)) && !strcmp(command, "*99*0##"));
        assert(send_all_bytes(fd, "*#*1##", 6));
        while (read_command(fd, command, sizeof(command))) {
            const char *reply;
            if (!strcmp(command, "*#8**33##")) reply = "*#8**33*1##";
            else if (!strcmp(command, "*#8**#41*10##")) reply = normal_reply || short_reply ? "*#*1##" : malformed;
            else if (!strcmp(command, "*#8**41##")) {
                reply = normal_reply ? "*#8**41*10##" : malformed_readback ? malformed : padded;
                if (short_reply) reply = mismatched ? "*#8**41*20##" : "bad##";
            } else { assert(!"unexpected command"); reply = ""; }
            assert(send_all_bytes(fd, reply, strlen(reply)));
        }
        close(fd);
    }
    return NULL;
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    normal_reply = !strncmp(argv[1], "normal-", 7);
    short_reply = !strncmp(argv[1], "short-", 6);
    include_muted = strstr(argv[1], "combined") || !strcmp(argv[1], "normal-muted");
    only_muted = !strcmp(argv[1], "normal-muted");
    mismatched = strstr(argv[1], "mismatch") != NULL;
    /* In the malformed case, use an invalid readback as well as an invalid
     * write reply. Other cases reach the valid-value/mismatch branches. */
    malformed_readback = !strcmp(argv[1], "malformed");
    listener = socket(AF_INET, SOCK_STREAM, 0);
    assert(listener >= 0);
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    assert(bind(listener, (struct sockaddr *)&address, sizeof(address)) == 0);
    assert(listen(listener, 2) == 0);
    socklen_t size = sizeof(address);
    assert(getsockname(listener, (struct sockaddr *)&address, &size) == 0);
    struct c300x_config config = {.openwebnet_timeout_ms = 3000, .openwebnet_port = ntohs(address.sin_port)};
    strcpy(config.openwebnet_host, "127.0.0.1");
    struct agent_runtime *runtime = calloc(1, sizeof(*runtime));
    assert(runtime);
    runtime->config = &config;
    runtime->ringer_control.client_fd = -1;
    runtime->ringer_muted_state = (struct c300x_setting_state){.known = 1, .available = 1, .last_valid = 1};
    runtime->ringer_volume_state = (struct c300x_setting_state){.known = 1, .available = 1, .last_valid = 0};
    c300x_ui_events_init(&runtime->ui_events);
    const char *request = only_muted ? "{\"muted\":false}"
        : include_muted ? "{\"muted\":false,\"volume\":1}" : "{\"volume\":1}";
    pthread_t server;
    assert(pthread_create(&server, NULL, openwebnet_server, NULL) == 0);
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(handle_ringer_post(pair[0], &config, runtime, request, include_muted) == 1);
    close_agent_socket(pair[0]);
    char response[4096];
    size_t used = 0;
    ssize_t count;
    while ((count = recv(pair[1], response + used, sizeof(response) - used - 1, 0)) > 0) {
        used += (size_t)count;
    }
    assert(count == 0);
    response[used] = '\0';
    char *body = strstr(response, "\r\n\r\n");
    assert(body);
    body += 4;
    assert(c300x_json_object_valid(body));
    if (normal_reply) {
        assert(strstr(response, "200 OK"));
        assert(strstr(body, "\"ok\":true"));
    } else {
        char error[64];
        assert(strstr(response, short_reply && mismatched ? "409 Conflict" : "502 Bad Gateway"));
        assert(c300x_json_string_field_checked(body, "error", error, sizeof(error)) == 1);
        const char *expected = short_reply
            ? (mismatched ? "ringer_volume_not_applied" : "ringer_volume_readback_failed")
            : "ringer_response_too_large";
        assert(!strcmp(error, expected));
        assert(strlen(body) < (short_reply ? 256 : 128));
    }
    assert(pthread_join(server, NULL) == 0);
    close(pair[1]); close(listener);
    c300x_recent_events_clear(&runtime->recent_events);
    free(runtime);
    return 0;
}
