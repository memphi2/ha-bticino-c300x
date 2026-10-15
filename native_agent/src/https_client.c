#include "https_client.h"
#include "pthread_compat.h"

#include <curl/curl.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifndef C300X_CURL_LIBRARY
#define C300X_CURL_LIBRARY "libcurl.so.4"
#endif
#ifndef C300X_CALLBACK_CA_FILE
#define C300X_CALLBACK_CA_FILE "/etc/ssl/certs/ca-certificates.crt"
#endif

struct curl_api {
    CURLcode (*global_init)(long);
    curl_version_info_data *(*version_info)(CURLversion);
    CURL *(*easy_init)(void);
    CURLcode (*easy_setopt)(CURL *, CURLoption, ...);
    CURLcode (*easy_perform)(CURL *);
    CURLcode (*easy_getinfo)(CURL *, CURLINFO, ...);
    void (*easy_cleanup)(CURL *);
    struct curl_slist *(*slist_append)(struct curl_slist *, const char *);
    void (*slist_free_all)(struct curl_slist *);
    int available;
};

static struct curl_api api;
static pthread_once_t curl_once = PTHREAD_ONCE_INIT;

static int load_symbol(void *handle, const char *name, void *out, size_t size)
{
    void *symbol = dlsym(handle, name);
    if (symbol == NULL || size != sizeof(symbol)) {
        return 0;
    }
    memcpy(out, &symbol, size);
    return 1;
}

static void load_curl(void)
{
    void *handle = dlopen(C300X_CURL_LIBRARY, RTLD_NOW | RTLD_LOCAL);
    if (handle == NULL) {
        return;
    }
#define LOAD(name) load_symbol(handle, "curl_" #name, &api.name, sizeof(api.name))
    if (!(LOAD(global_init) && LOAD(version_info) && LOAD(easy_init)
        && LOAD(easy_setopt) && LOAD(easy_perform) && LOAD(easy_getinfo)
        && LOAD(easy_cleanup) && LOAD(slist_append) && LOAD(slist_free_all))) {
        dlclose(handle);
        return;
    }
#undef LOAD
    if (api.global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) {
        dlclose(handle);
        return;
    }
    /* Keep the library and its global state for the process lifetime. */
    const curl_version_info_data *version = api.version_info(CURLVERSION_FIRST);
    /* NOSIGNAL with a synchronous resolver cannot enforce a DNS timeout. */
    if (version == NULL || version->version_num < 0x072200
        || !(version->features & CURL_VERSION_SSL)
        || !(version->features & CURL_VERSION_ASYNCHDNS)) {
        return;
    }
    for (const char *const *protocol = version->protocols; protocol && *protocol; protocol++) {
        if (strcmp(*protocol, "https") == 0) {
            api.available = 1;
            break;
        }
    }
}

int c300x_https_available(void)
{
    pthread_once(&curl_once, load_curl);
    return api.available;
}

struct response_buffer {
    char *data;
    size_t capacity;
    size_t used;
};

static size_t receive_body(char *data, size_t size, size_t count, void *user)
{
    struct response_buffer *buffer = user;
    if (size != 0 && count > SIZE_MAX / size) {
        return 0;
    }
    size_t bytes = size * count;
    size_t limit = buffer->data != NULL ? buffer->capacity - 1 : 65536;
    if (bytes > limit - buffer->used) {
        return 0;
    }
    if (buffer->data != NULL) {
        memcpy(buffer->data + buffer->used, data, bytes);
        buffer->data[buffer->used + bytes] = '\0';
    }
    buffer->used += bytes;
    return bytes;
}

int c300x_https_post(
    const char *url, const char *token_header, const char *token, const char *body,
    char *response, size_t response_len, int timeout_ms,
    long *http_status, const char **error
)
{
    CURL *easy = NULL;
    struct curl_slist *headers = NULL;
    struct response_buffer output = {response, response_len, 0};
    char token_line[1024];
    long status = 0;
    CURLcode result;
    int ok = 0;

    *error = "https_invalid_request";
    *http_status = 0;
    if (response != NULL && response_len > 0) {
        response[0] = '\0';
    }
    if (url == NULL || strncmp(url, "https://", 8) != 0 || body == NULL
        || token_header == NULL || token == NULL || timeout_ms <= 0
        || (response != NULL && response_len == 0)
        || strpbrk(token_header, "\r\n:") || strpbrk(token, "\r\n")
        || snprintf(token_line, sizeof(token_line), "%s: %s", token_header, token) >= (int)sizeof(token_line)) {
        return 0;
    }
    if (!c300x_https_available()) {
        *error = "https_unavailable";
        return 0;
    }
    *error = "https_allocation_failed";
    easy = api.easy_init();
    if (easy == NULL) {
        return 0;
    }
    const char *values[] = {"Content-Type: application/json", "Expect:", token_line};
    for (size_t index = 0; index < sizeof(values) / sizeof(values[0]); index++) {
        struct curl_slist *next = api.slist_append(headers, values[index]);
        if (next == NULL) {
            goto cleanup;
        }
        headers = next;
    }
    *error = "https_option_failed";
#define SET(option, value) if (api.easy_setopt(easy, option, value) != CURLE_OK) { goto cleanup; }
    SET(CURLOPT_URL, url);
    SET(CURLOPT_POSTFIELDS, body);
    SET(CURLOPT_POSTFIELDSIZE, (long)strlen(body));
    SET(CURLOPT_HTTPHEADER, headers);
    SET(CURLOPT_HTTP_VERSION, (long)CURL_HTTP_VERSION_1_1);
    SET(CURLOPT_PROXY, "");
    SET(CURLOPT_FOLLOWLOCATION, 0L);
    SET(CURLOPT_NOSIGNAL, 1L);
    SET(CURLOPT_CONNECTTIMEOUT_MS, (long)timeout_ms);
    SET(CURLOPT_TIMEOUT_MS, (long)timeout_ms);
    SET(CURLOPT_SSLVERSION, (long)CURL_SSLVERSION_TLSv1_2);
    SET(CURLOPT_SSL_VERIFYPEER, 1L);
    SET(CURLOPT_SSL_VERIFYHOST, 2L);
    SET(CURLOPT_CAINFO, C300X_CALLBACK_CA_FILE);
    SET(CURLOPT_WRITEFUNCTION, receive_body);
    SET(CURLOPT_WRITEDATA, &output);
#undef SET
    result = api.easy_perform(easy);
    (void)api.easy_getinfo(easy, CURLINFO_RESPONSE_CODE, &status);
    *http_status = status;
    if (result != CURLE_OK) {
        *error = result == CURLE_OPERATION_TIMEDOUT ? "https_timeout"
            : result == CURLE_PEER_FAILED_VERIFICATION ? "https_certificate_invalid"
            : result == CURLE_SSL_CACERT_BADFILE ? "https_ca_unavailable"
            : result == CURLE_WRITE_ERROR ? "https_response_too_large"
            : "https_transfer_failed";
        goto cleanup;
    }
    ok = status >= 200 && status < 300;
    *error = ok ? NULL : "https_http_status";
cleanup:
    api.slist_free_all(headers);
    api.easy_cleanup(easy);
    if (!ok && response != NULL && response_len > 0) {
        response[0] = '\0';
    }
    return ok;
}
