#include "../src/display_alerts.h"
#include "../src/http_util.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static long long now = 1000;
static int status, writes, write_success = 1;
static char response[8192];
static struct request request;

long long c300x_monotonic_ms(void) { return now; }
void close_agent_socket(int fd) { if (fd >= 0) close(fd); }
void c300x_http_send_json(int fd, int code, const char *reason, const char *body)
{
    (void)fd; (void)reason;
    status = code;
    snprintf(response, sizeof(response), "%s", body);
}
int c300x_http_write(int fd, const char *data, size_t size)
{
    (void)fd;
    assert(size < sizeof(response));
    memcpy(response, data, size);
    response[size] = 0;
    assert(strstr(response, "\"remaining_ms\":1000"));
    assert(strstr(response, "\"message_expires\":"));
    writes++;
    return write_success;
}

static int listen_gui_mode(struct c300x_display_alerts *alerts, int protected)
{
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    memset(&request, 0, sizeof(request));
    strcpy(request.method, "GET");
    if (protected) strcpy(request.query, "protected=1");
    assert(c300x_display_alerts_handle_ui(alerts, pair[0], &request) == 0);
    return pair[1];
}

static int listen_gui(struct c300x_display_alerts *alerts)
{
    return listen_gui_mode(alerts, 0);
}

static void post(struct c300x_display_alerts *alerts, int id)
{
    memset(&request, 0, sizeof(request));
    strcpy(request.method, "POST");
    snprintf(request.body, sizeof(request.body),
        "{\"id\":\"%032x\",\"notification_id\":\"n\",\"revision\":\"%032x\","
        "\"severity\":\"info\",\"title\":\"\",\"message\":\"\","
        "\"wake_duration\":0,\"sound_duration\":300,\"expires_in\":1}", id, id);
    request.body_len = strlen(request.body);
    status = 0;
    c300x_display_alerts_handle_api(alerts, -1, &request);
}

static void protected_receipts_test(void)
{
    struct c300x_display_alerts alerts;
    c300x_display_alerts_init(&alerts);
    int peer = listen_gui_mode(&alerts, 1), fd = alerts.gui_fd;
    for (int i = 0; i < C300X_DISPLAY_ALERTS_DEDUP_SLOTS; i++) {
        post(&alerts, i);
        assert(status == 200 && strstr(response, "\"accepted\":false"));
        assert(strstr(response, "display_protected") && writes == 0);
        assert(alerts.gui_fd == fd && alerts.gui_protected);
    }
    post(&alerts, 99);
    assert(status == 503 && strstr(response, "dedup_full"));
    now += C300X_DISPLAY_ALERTS_DEDUP_MS;
    post(&alerts, 99);
    assert(status == 200 && strstr(response, "display_protected") && writes == 0);
    close(peer);
    post(&alerts, 100);
    assert(status == 503 && alerts.gui_fd == -1 && !alerts.gui_protected);
    peer = listen_gui(&alerts);
    post(&alerts, 99);
    assert(status == 200 && strstr(response, "display_protected") && writes == 0);
    post(&alerts, 100);
    assert(status == 200 && writes == 1 && alerts.gui_fd == -1);
    close(peer);
    c300x_display_alerts_close(&alerts);
}

int main(void)
{
    protected_receipts_test();
    now = 1000;
    writes = 0;
    struct c300x_display_alerts alerts;
    struct pollfd snapshot;
    c300x_display_alerts_init(&alerts);
    assert(c300x_display_alerts_prepare(&alerts, &snapshot) == -1);
    assert(snapshot.fd == -1);
    post(&alerts, 0);
    assert(status == 503 && writes == 0);
    for (int i = 0; i < C300X_DISPLAY_ALERTS_DEDUP_SLOTS; i++) {
        int peer = listen_gui(&alerts);
        post(&alerts, i);
        assert(status == 200 && alerts.gui_fd == -1);
        close(peer);
    }
    assert(writes == C300X_DISPLAY_ALERTS_DEDUP_SLOTS);
    int peer = listen_gui(&alerts);
    int fd = alerts.gui_fd;
    now += 2000; /* Message already expired; dedup must still block replay. */
    post(&alerts, 0);
    assert(status == 200 && alerts.gui_fd == fd);
    assert(writes == C300X_DISPLAY_ALERTS_DEDUP_SLOTS);
    post(&alerts, 99);
    assert(status == 503 && strstr(response, "dedup_full") && alerts.gui_fd == fd);
    now = 1000 + C300X_DISPLAY_ALERTS_DEDUP_MS - 1;
    post(&alerts, 0); /* A retry must not extend retention. */
    assert(status == 200 && alerts.gui_fd == fd);
    now++;
    post(&alerts, 99);
    assert(status == 200 && alerts.gui_fd == -1);
    close(peer);

    peer = listen_gui(&alerts);
    write_success = 0;
    post(&alerts, 100);
    assert(status == 503 && strstr(response, "delivery_failed") && alerts.gui_fd == -1);
    close(peer);
    peer = listen_gui(&alerts);
    write_success = 1;
    int previous = writes;
    post(&alerts, 100);
    assert(status == 503 && writes == previous && alerts.gui_fd >= 0);

    assert(c300x_display_alerts_prepare(&alerts, &snapshot) == -1);
    snapshot.fd++;
    snapshot.revents = POLLHUP;
    c300x_display_alerts_tick(&alerts, &snapshot);
    assert(alerts.gui_fd >= 0);
    c300x_display_alerts_prepare(&alerts, &snapshot);
    snapshot.revents = POLLIN;
    c300x_display_alerts_tick(&alerts, &snapshot);
    assert(alerts.gui_fd == -1);
    char byte;
    assert(read(peer, &byte, 1) == 0);
    close(peer);

    peer = listen_gui(&alerts);
    close(peer);
    post(&alerts, 101); /* Detect hangup even before the main poll snapshot. */
    assert(status == 503 && alerts.gui_fd == -1 && writes == previous);
    peer = listen_gui(&alerts);
    c300x_display_alerts_close(&alerts);
    assert(alerts.gui_fd == -1 && read(peer, &byte, 1) == 0);
    close(peer);
    c300x_display_alerts_close(&alerts);
    return 0;
}
