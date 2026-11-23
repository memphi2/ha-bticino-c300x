/* Inject transaction results at the real HTTP route, never remount the host. */
#include "../src/agent_update.h"
#include "../src/c300x_agent.h"
#include "../src/file_io.h"
#include "../src/string_util.h"

#include <assert.h>
#include <stdlib.h>
#include <string.h>

int __wrap_apply_agent_update_files(
    const struct c300x_config *config, const char *manifest, const char *installed_manifest,
    struct agent_update_change_summary *summary,
    int (*activate)(const struct c300x_config *, struct agent_update_change_summary *))
{
    char base[C300X_MAX_PATH_LEN], path[C300X_MAX_PATH_LEN], value[16];
    (void)manifest;
    (void)installed_manifest;
    (void)activate;
    assert(agent_base_dir(config, base, sizeof(base)));
    assert(c300x_join_path(path, sizeof(path), base, "update-error"));
    assert(read_bounded_text_file(path, value, sizeof(value), NULL));
    memset(summary, 0, sizeof(*summary));
    summary->error = (enum agent_update_error)atoi(value);
    /* A finalization failure can occur after the replacement is committed. */
    if (summary->error == AGENT_UPDATE_ROOT_READONLY_FAILED) {
        summary->changed_files = 17;
        summary->runtime_changed = summary->manifest_changed = 1;
    }
    return 0;
}
