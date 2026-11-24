/* The firewall restore gives back the vendor file, blank lines included. */
#include <assert.h>
#include "../src/http.c"

static char g_dir[512];

static void path_in(char *out, size_t len, const char *name)
{
    assert(snprintf(out, len, "%s/%s", g_dir, name) < (int)len);
}

static void put(const char *path, const char *content)
{
    FILE *file = fopen(path, "wb");
    assert(file != NULL);
    assert(fputs(content, file) >= 0);
    assert(fclose(file) == 0);
}

static void expect(const char *path, const char *content)
{
    static char data[C300X_FIREWALL_BUFFER_SIZE];
    int exists = 0;
    assert(c300x_firewall_read_file(path, data, sizeof(data), &exists) && exists);
    if (strcmp(data, content) != 0) {
        fprintf(stderr, "got [%s] want [%s]\n", data, content);
        assert(0);
    }
}

static void restore(struct c300x_config *config, int ipv6, const char *current, const char *backup, const char *want)
{
    char *target = ipv6 ? config->maintenance_ipv6_firewall_path : config->maintenance_firewall_path;
    char *saved = ipv6 ? config->maintenance_ipv6_firewall_backup_path : config->maintenance_firewall_backup_path;
    char state[64];
    int exists = 0, changed = 0;

    put(target, current);
    unlink(saved);
    if (backup != NULL) {
        put(saved, backup);
    }
    assert(ipv6 ? ipv6_firewall_restore(config, &exists, &changed, state, sizeof(state))
                : firewall_restore(config, &exists, &changed, state, sizeof(state)));
    expect(target, want);
}

/* The vendor's mode stays (it was chmod 0755); a script whose rules
 * iptables refuses at once is not left behind for the next boot. */
static void apply_tests(struct c300x_config *config, const char *vendor)
{
    char tools[600], tool[640], state[64];
    struct stat info;
    int exists = 0, changed = 0;

    put(config->maintenance_firewall_path, vendor);
    assert(chmod(config->maintenance_firewall_path, 0500) == 0);
    unlink(config->maintenance_firewall_backup_path);
    path_in(tools, sizeof(tools), "tools");
    assert(mkdir(tools, 0700) == 0);
    assert(snprintf(tool, sizeof(tool), "%s/iptables", tools) < (int)sizeof(tool));
    put(tool, "#!/bin/sh\nexit 0\n");
    assert(chmod(tool, 0700) == 0);
    assert(setenv("C300X_FIREWALL_RUNTIME_PATH", tools, 1) == 0);
    assert(firewall_apply(config, &exists, &changed, state, sizeof(state)) && changed == 2);
    assert(stat(config->maintenance_firewall_path, &info) == 0 && (info.st_mode & 07777) == 0500);
    expect(config->maintenance_firewall_backup_path, vendor);
    assert(firewall_restore(config, &exists, &changed, state, sizeof(state)));
    expect(config->maintenance_firewall_path, vendor);
    assert(stat(config->maintenance_firewall_path, &info) == 0 && (info.st_mode & 07777) == 0500);

    put(tool, "#!/bin/sh\nexit 1\n");
    assert(!firewall_apply(config, &exists, &changed, state, sizeof(state)));
    assert(strcmp(state, "runtime_apply_failed") == 0);
    expect(config->maintenance_firewall_path, vendor);
    assert(stat(config->maintenance_firewall_path, &info) == 0 && (info.st_mode & 07777) == 0500);
}

int main(int argc, char **argv)
{
    static struct c300x_config config;
    static char block[C300X_FIREWALL_BUFFER_SIZE];
    static char inserted[C300X_FIREWALL_BUFFER_SIZE];
    static char inserted6[C300X_FIREWALL_BUFFER_SIZE];
    const char *vendor = "#!/bin/sh\niptables -P INPUT DROP\n\n";

    assert(argc == 2);
    snprintf(g_dir, sizeof(g_dir), "%s", argv[1]);
    path_in(config.maintenance_firewall_path, sizeof(config.maintenance_firewall_path), "iptables");
    path_in(config.maintenance_firewall_backup_path, sizeof(config.maintenance_firewall_backup_path), "iptables.orig");
    path_in(config.maintenance_ipv6_firewall_path, sizeof(config.maintenance_ipv6_firewall_path), "iptables6");
    path_in(config.maintenance_ipv6_firewall_backup_path, sizeof(config.maintenance_ipv6_firewall_backup_path), "iptables6.orig");
    config.api_port = 8080;

    /* The installer's shell puts the block right after the file. */
    assert(firewall_build_managed_content(&config, "", block, sizeof(block)));
    snprintf(inserted, sizeof(inserted), "%s%s", vendor, block);
    restore(&config, 0, inserted, vendor, vendor);
    /* The agent puts a blank line before it. */
    assert(firewall_build_managed_content(&config, vendor, inserted, sizeof(inserted)));
    restore(&config, 0, inserted, vendor, vendor);
    /* A backup of another file is not used: the block is cut out. */
    restore(&config, 0, inserted, "#!/bin/sh\nold\n", "#!/bin/sh\niptables -P INPUT DROP\n");
    restore(&config, 0, inserted, NULL, "#!/bin/sh\niptables -P INPUT DROP\n");

    assert(firewall_build_ipv6_managed_content(&config, vendor, inserted6, sizeof(inserted6)));
    restore(&config, 1, inserted6, vendor, vendor);
    restore(&config, 1, inserted6, "#!/bin/sh\nold\n", "#!/bin/sh\niptables -P INPUT DROP\n");
    apply_tests(&config, vendor);
    return 0;
}
