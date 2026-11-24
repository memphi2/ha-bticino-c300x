#define FLEXISIP_USERS_DIR "users"
#define FLEXISIP_USERS_FILE "users/users.db.txt"
#define FLEXISIP_ACCOUNTS_FILE "users/accounts.txt"
static char route_int_path[4096];
static char route_ext_path[4096];
#define FLEXISIP_ROUTE_INT_FILE route_int_path
#define FLEXISIP_ROUTE_EXT_FILE route_ext_path
#define FLEXISIP_ROUTE_ACTIVE_FILE "users/route.conf"
#define FLEXISIP_CONFIG_FILE "flexisip.conf"
#define FLEXISIP_DOMAIN_FILE "domain-registration.conf"
#define C300X_DEVICE_USER_ADDED_DIR "backups"
#include "../src/device_user.c"
#include "../src/http_device_user.h"
#include "../src/device_routing.h"
#include <assert.h>

const char *c300x_device_sip_user(void) { return "c100x"; }
enum c300x_device_model c300x_device_model(void)
{
    const char *model = getenv("TEST_MODEL");
    return model != NULL && strcmp(model, "c100x") == 0 ? C300X_DEVICE_MODEL_C100X : C300X_DEVICE_MODEL_C300X;
}
int c300x_device_display_files_patchable(void) { return 0; }

static int responses;
void c300x_http_send_json(int fd, int status, const char *reason, const char *body)
{
    (void)fd; (void)reason;
    if (getenv("TEST_EXPECT_OK") != NULL) {
        assert(status == 200 && strstr(body, "\"user_only\":true") != NULL);
    } else {
        assert(status >= 400 && strstr(body, "device_user_update_failed") != NULL);
    }
    responses++;
}

void close_agent_socket(int fd) { (void)fd; }

static void record_write(void *context, const char *kind, const char *reason)
{
    (void)context; (void)kind; (void)reason;
    assert(getenv("TEST_EXPECT_OK") != NULL && "Read-only rejection must not record writes");
}

int c300x_device_routing_read_status(struct c300x_device_routing_status *status)
{
    assert(getenv("TEST_EXPECT_OK") != NULL && "Rejected preflight must not start routing status job");
    memset(status, 0, sizeof(*status));
    return 0;
}

int c300x_device_routing_apply(struct c300x_device_routing_status *status, char *error, size_t size)
{
    (void)status; (void)error; (void)size;
    assert(!"Rejected active route must not patch the vendor binary");
    return 0;
}

int c300x_device_routing_restore(struct c300x_device_routing_status *status, char *error, size_t size)
{
    (void)status; (void)error; (void)size;
    assert(!"Rejected active route must not restore the vendor binary");
    return 0;
}

int main(int argc, char **argv)
{
    assert(argc == 3 && chdir(argv[1]) == 0);
    assert(snprintf(route_int_path, sizeof(route_int_path), "%s/users/route_int.conf", argv[1]) < (int)sizeof(route_int_path));
    assert(snprintf(route_ext_path, sizeof(route_ext_path), "%s/users/route_ext.conf", argv[1]) < (int)sizeof(route_ext_path));
    struct c300x_device_user_status status = {0};
    char error[128] = "";
    int ok;
    if (strcmp(argv[2], "http") == 0) {
        struct c300x_config *config = calloc(1, sizeof(*config));
        struct request *request = calloc(1, sizeof(*request));
        struct c300x_http_maintenance owner;
        assert(config != NULL && request != NULL);
        config->maintenance_enabled = config->api_no_auth = config->maintenance_no_auth_allowed = 1;
        c300x_copy_string(request->method, sizeof(request->method), "POST");
        c300x_copy_string(request->path, sizeof(request->path),
            "/api/v1/maintenance/device-user/actions/ensure-homeassistant");
        c300x_copy_string(request->body, sizeof(request->body), "{\"confirm\":\"ensure_homeassistant_user\"}");
        c300x_http_maintenance_init(&owner, record_write, NULL);
        assert(c300x_http_device_user_route(&owner, 1234, config, request));
        assert(responses == 1 && !c300x_http_maintenance_busy(&owner));
        c300x_http_maintenance_close(&owner);
        free(request);
        free(config);
        return 0;
    }
    if (strcmp(argv[2], "ensure") == 0) {
        ok = c300x_device_user_ensure_homeassistant(&status, "Home Assistant", error, sizeof(error));
    } else if (strcmp(argv[2], "remove") == 0) {
        ok = c300x_device_user_remove_added(error, sizeof(error));
        printf("remove ok=%d error=%s\n", ok, error);
        return ok ? 0 : 1;
    } else {
        assert(strcmp(argv[2], "status") == 0);
        ok = c300x_device_user_read_status(&status);
    }
    printf("ok=%d supported=%d consistent=%d active_ha=%d symlink=%d user_only=%d error=%s status_error=%s\n",
        ok, status.supported, status.routes_consistent, status.route_conf_homeassistant_present,
        status.route_conf_is_symlink, status.user_only, error, status.error);
    return ok ? 0 : 1;
}
