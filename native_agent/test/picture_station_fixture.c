/* Link-time substitutes only in the host picture test: the station's model
 * and firmware come from the file "station" in the working directory. */
#include "../src/device_detect.h"
#include "../src/firmware_version.h"
#include <stdio.h>
#include <string.h>

static void station(char *model, size_t model_len, char *firmware, size_t firmware_len)
{
    char line[64] = "";
    FILE *f = fopen("station", "r");
    if (f) {
        if (!fgets(line, sizeof(line), f)) line[0] = '\0';
        fclose(f);
    }
    char *split = strchr(line, ' ');
    if (split) *split++ = '\0';
    snprintf(model, model_len, "%s", line);
    snprintf(firmware, firmware_len, "%s", split ? split : "");
    firmware[strcspn(firmware, "\r\n")] = '\0';
}

void __wrap_resolve_device_firmware(const struct c300x_config *config, char *out, size_t size)
{
    char model[16];
    if (config) {
        snprintf(out, size, "%s", config->device_firmware);
        return;
    }
    station(model, sizeof(model), out, size);
}

enum c300x_device_model __wrap_c300x_device_model(void)
{
    char model[16], firmware[16];
    station(model, sizeof(model), firmware, sizeof(firmware));
    return strcmp(model, "C100X") ? C300X_DEVICE_MODEL_C300X : C300X_DEVICE_MODEL_C100X;
}
