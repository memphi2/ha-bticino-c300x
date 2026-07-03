#include "c300x_agent.h"

#include <signal.h>
#include <stdio.h>
#include <string.h>

static void print_usage(const char *program)
{
    fprintf(
        stderr,
        "Usage: %s [--config PATH] [--check-config] [--diagnose-startup] [--version]\n",
        program
    );
}

static const char *json_bool(int value)
{
    return value ? "true" : "false";
}

static void print_json_string(FILE *out, const char *value)
{
    const unsigned char *ptr = (const unsigned char *)(value != NULL ? value : "");

    fputc('"', out);
    for (; *ptr != '\0'; ptr++) {
        switch (*ptr) {
        case '"':
            fputs("\\\"", out);
            break;
        case '\\':
            fputs("\\\\", out);
            break;
        case '\n':
            fputs("\\n", out);
            break;
        case '\r':
            fputs("\\r", out);
            break;
        case '\t':
            fputs("\\t", out);
            break;
        default:
            if (*ptr < 0x20) {
                fprintf(out, "\\u%04x", (unsigned int)*ptr);
            } else {
                fputc((int)*ptr, out);
            }
            break;
        }
    }
    fputc('"', out);
}

static void print_startup_diagnosis(const struct c300x_config *config)
{
    puts("{");
    puts("  \"ok\": true,");
    printf("  \"agent_version\": ");
    print_json_string(stdout, C300X_NATIVE_AGENT_VERSION);
    puts(",");
    printf("  \"config_path\": ");
    print_json_string(stdout, config->config_path);
    puts(",");
    puts("  \"effective_config\": {");
    printf("    \"api_no_auth\": %s,\n", json_bool(config->api_no_auth));
    printf("    \"api_token_configured\": %s,\n", json_bool(config->api_token[0] != '\0'));
    printf("    \"api_token_from_env\": %s,\n", json_bool(config->api_token_from_env));
    printf("    \"listen_host\": ");
    print_json_string(stdout, config->listen_host);
    puts(",");
    printf("    \"api_port\": %u,\n", (unsigned int)config->api_port);
    printf("    \"ui_port\": %u,\n", (unsigned int)config->ui_port);
    printf("    \"allow_lan\": %s,\n", json_bool(config->allow_lan));
    printf("    \"events_udp_enabled\": %s,\n", json_bool(config->events_enabled));
    printf("    \"video_enabled\": %s,\n", json_bool(config->video_enabled));
    printf("    \"display_bridge_enabled\": %s,\n", json_bool(config->display_bridge_enabled));
    printf("    \"maintenance_enabled\": %s\n", json_bool(config->maintenance_enabled));
    puts("  },");
    puts("  \"startup_plan\": {");
    puts("    \"api_listener\": true,");
    puts("    \"ui_listener\": true,");
    printf("    \"udp_events\": %s,\n", json_bool(config->events_enabled));
    printf("    \"video_runtime\": %s,\n", json_bool(config->video_enabled));
    printf("    \"rtsp_bridge\": %s,\n", json_bool(config->video_enabled));
    printf("    \"ring_call_media\": %s,\n", json_bool(config->video_enabled));
    printf("    \"home_call_media\": %s\n", json_bool(config->video_enabled));
    puts("  },");
    puts("  \"side_effects\": {");
    puts("    \"opens_listeners\": false,");
    puts("    \"starts_media\": false,");
    puts("    \"writes_files\": false");
    puts("  }");
    puts("}");
}

int main(int argc, char **argv)
{
    const char *config_path = "config.json";
    int check_config = 0;
    int diagnose_startup = 0;
    struct c300x_config config;
    char error[256] = {0};

    for (int index = 1; index < argc; index++) {
        if (strcmp(argv[index], "--config") == 0) {
            if (index + 1 >= argc) {
                fprintf(stderr, "fatal: invalid_arguments: --config requires a path\n");
                print_usage(argv[0]);
                return 2;
            }
            config_path = argv[++index];
        } else if (strcmp(argv[index], "--check-config") == 0) {
            check_config = 1;
        } else if (strcmp(argv[index], "--diagnose-startup") == 0) {
            diagnose_startup = 1;
        } else if (strcmp(argv[index], "--version") == 0) {
            printf("%s\n", C300X_NATIVE_AGENT_VERSION);
            return 0;
        } else {
            fprintf(stderr, "fatal: invalid_arguments: unsupported option: %s\n", argv[index]);
            print_usage(argv[0]);
            return 2;
        }
    }

    if (!c300x_load_config(config_path, &config, error, sizeof(error))) {
        fprintf(stderr, "fatal: config_error: %s\n", error);
        return 2;
    }

    if (diagnose_startup) {
        print_startup_diagnosis(&config);
        return 0;
    }

    if (check_config) {
        printf("config ok\n");
        return 0;
    }

    (void)signal(SIGPIPE, SIG_IGN);
    return c300x_run(&config);
}
