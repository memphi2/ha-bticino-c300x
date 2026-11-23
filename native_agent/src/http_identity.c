#include "http_identity.h"

#include "http_util.h"
#include "json_util.h"
#include "mdns.h"
#include "sha256.h"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>

/* Below this a single proof would let anyone on the LAN guess the token offline. */
#define C300X_IDENTITY_MIN_TOKEN_LEN 32
#define C300X_IDENTITY_NONCE_LEN 64

/* HA asks a station at a new address to prove it holds the API token before it
 * moves the entry there. The proof covers the address and port this connection
 * arrived on, so a relay to the real station proves nothing for its own address. */
static int identity_local_endpoint(int client_fd, char *out, size_t out_len)
{
    struct sockaddr_storage local;
    socklen_t local_len = sizeof(local);
    struct in_addr ipv4;
    unsigned int port;
    char text[INET_ADDRSTRLEN];
    int written;

    if (getsockname(client_fd, (struct sockaddr *)&local, &local_len) != 0) {
        return 0;
    }
    if (local.ss_family == AF_INET) {
        const struct sockaddr_in *v4 = (const struct sockaddr_in *)&local;
        ipv4 = v4->sin_addr;
        port = ntohs(v4->sin_port);
    } else if (local.ss_family == AF_INET6) {
        const struct sockaddr_in6 *v6 = (const struct sockaddr_in6 *)&local;
        if (!IN6_IS_ADDR_V4MAPPED(&v6->sin6_addr)) {
            return 0;
        }
        memcpy(&ipv4, &v6->sin6_addr.s6_addr[12], sizeof(ipv4));
        port = ntohs(v6->sin6_port);
    } else {
        return 0;
    }
    if (inet_ntop(AF_INET, &ipv4, text, sizeof(text)) == NULL) {
        return 0;
    }
    written = snprintf(out, out_len, "%s:%u", text, port);
    return written > 0 && (size_t)written < out_len;
}

static int identity_nonce_valid(const char *nonce)
{
    size_t length = 0;

    for (; nonce[length] != '\0'; length++) {
        char ch = nonce[length];
        if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f'))) {
            return 0;
        }
    }
    return length == C300X_IDENTITY_NONCE_LEN;
}

static void identity_fail(int client_fd, int status, const char *reason, const char *error)
{
    char body[96];

    (void)snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}\n", error);
    c300x_http_send_json(client_fd, status, reason, body);
}

int c300x_http_identity_route(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    char nonce[C300X_IDENTITY_NONCE_LEN + 2];
    char endpoint[INET_ADDRSTRLEN + 8];
    char device_id[64];
    char quoted_id[C300X_JSON_QUOTED_LEN(sizeof(device_id))];
    char message[sizeof("c300x-identity-v1\n\n\n") + sizeof(device_id) + sizeof(endpoint) + sizeof(nonce)];
    char proof[65];
    char body[sizeof(quoted_id) + 128];
    size_t token_len;
    int written;

    if (strcmp(request->path, "/api/v1/identity/proof") != 0) {
        return 0;
    }
    if (strcmp(request->method, "POST") != 0) {
        identity_fail(client_fd, 405, "Method Not Allowed", "method_not_allowed");
        return 1;
    }
    token_len = strlen(config->api_token);
    if (config->api_no_auth || token_len < C300X_IDENTITY_MIN_TOKEN_LEN
        || !identity_local_endpoint(client_fd, endpoint, sizeof(endpoint))) {
        identity_fail(client_fd, 404, "Not Found", "identity_proof_unavailable");
        return 1;
    }
    if (c300x_json_string_field_checked(request->body, "nonce", nonce, sizeof(nonce)) != 1
        || !identity_nonce_valid(nonce)) {
        identity_fail(client_fd, 400, "Bad Request", "invalid_nonce");
        return 1;
    }
    c300x_mdns_device_id(device_id, sizeof(device_id));
    written = snprintf(message, sizeof(message), "c300x-identity-v1\n%s\n%s\n%s",
        device_id, endpoint, nonce);
    if (written <= 0 || (size_t)written >= sizeof(message)
        || !c300x_hmac_sha256_hex((const unsigned char *)config->api_token, token_len,
            (const unsigned char *)message, (size_t)written, proof, sizeof(proof))) {
        identity_fail(client_fd, 500, "Internal Server Error", "identity_proof_failed");
        return 1;
    }
    (void)snprintf(body, sizeof(body), "{\"ok\":true,\"id\":%s,\"proof\":\"%s\"}\n",
        c300x_json_string(device_id, quoted_id, sizeof(quoted_id)), proof);
    c300x_http_send_json(client_fd, 200, "OK", body);
    return 1;
}
