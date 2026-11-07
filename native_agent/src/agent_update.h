#ifndef C300X_AGENT_UPDATE_H
#define C300X_AGENT_UPDATE_H

#include <stddef.h>

struct c300x_config;

#define C300X_AGENT_UPDATE_STAGE ".update"
#define C300X_AGENT_BUNDLE_MANIFEST "bundle.json"
#define C300X_AGENT_BUNDLE_HASH_LEN 96
#define C300X_AGENT_INIT_SCRIPT "/etc/init.d/c300x-native-agent"
#define C300X_AGENT_INIT_LINK "/etc/rc5.d/S40c300x-native-agent"

struct agent_update_change_summary {
    int changed_files;
    int runtime_changed;
    int qml_patch_changed;
    int script_changed;
    int firewall_patch_changed;
    int ipv6_firewall_patch_changed;
    int config_schema_changed;
    int manifest_changed;
};

int agent_base_dir(const struct c300x_config *config, char *out, size_t out_len);

int agent_update_stage_dir(
    const struct c300x_config *config,
    char *out,
    size_t out_len
);

int agent_bundle_manifest_path(
    const struct c300x_config *config,
    char *out,
    size_t out_len
);

int agent_update_stage_path(
    const struct c300x_config *config,
    const char *bundle_path,
    char *out,
    size_t out_len
);

int read_agent_bundle_metadata(
    const struct c300x_config *config,
    char *bundle_hash,
    size_t bundle_hash_len,
    char *agent_version,
    size_t agent_version_len,
    char *api_version,
    size_t api_version_len
);

int agent_init_link_matches(void);

int apply_agent_update_files(
    const struct c300x_config *config,
    const char *manifest,
    const char *installed_manifest,
    struct agent_update_change_summary *summary,
    int (*activate)(const struct c300x_config *, struct agent_update_change_summary *)
);

#endif
