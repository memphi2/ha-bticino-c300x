#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#define _POSIX_C_SOURCE 200809L

#include "device_routing.h"

#include "device_patch_io.h"
#include "sha256.h"
#include "string_util.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <sys/stat.h>
#include <unistd.h>

#ifndef C300X_DEVICE_PATCH_TARGET_DIR
#define C300X_DEVICE_PATCH_TARGET_DIR "/home/bticino/bin"
#endif
#ifndef C300X_DEVICE_PATCH_BACKUP_DIR
#define C300X_DEVICE_PATCH_BACKUP_DIR "/home/bticino/cfg/extra/c300x-device-file-backups/original/home/bticino/bin"
#endif
#define C300X_DEVICE_PATCH_TARGET_MASK "b?_a?sw?rin?_?ac?ine"
#ifndef C300X_DEVICE_PATCH_STOCK_SHA256
#define C300X_DEVICE_PATCH_STOCK_SHA256 "605a808f1ed0c826c06bbf1eb4131b9198007a7ab822e7541a6666e79816c810"
#endif

/* The 2.0.2 firmware ships a rebuild of the same routing binary: the patched
 * code moved by a few bytes, the patched bytes themselves are unchanged. */
#ifndef C300X_DEVICE_PATCH_STOCK_SHA256_2_0_2
#define C300X_DEVICE_PATCH_STOCK_SHA256_2_0_2 "18a555afcfb3c1d163cdb649cdd7a61e9526e08aec8275f88dd78df4bc5f2ec7"
#endif

/* Firmware 3.0.6 ships a Qt5-era rebuild of bt_answering_machine as a PIE.
 * The routing logic is the same but recompiled: the patch sites were re-located
 * by disassembly (string xrefs + the bics/symlink structure). The rec_json_f
 * symlink that 1.7.x had to synthesise already exists inline here, so the 60-byte
 * restructure collapses to a route_ext->route_int literal redirect. */
#ifndef C300X_DEVICE_PATCH_STOCK_SHA256_3_0_6
#define C300X_DEVICE_PATCH_STOCK_SHA256_3_0_6 "7f7b28e1579c93d1c752ecab220801f639a4c5fc7eb845d79fe76563e7c9f1cb"
#endif

/* Classe 100X 1.5.8 ships its own build of the routing binary. */
#ifndef C300X_DEVICE_PATCH_STOCK_SHA256_C100X_1_5_8
#define C300X_DEVICE_PATCH_STOCK_SHA256_C100X_1_5_8 "cc53dd834361e8a76268b108ce2562b8447d597798dd2f136ce4707142485e12"
#endif

#define ARRAY_LEN(values) (sizeof(values) / sizeof((values)[0]))

static int device_patch_file_name(char *buffer, size_t buffer_len)
{
    static const struct {
        size_t offset;
        char value;
    } replacements[] = {
        {1, 't'},
        {4, 'n'},
        {7, 'e'},
        {11, 'g'},
        {13, 'm'},
        {16, 'h'},
    };

    if (buffer_len < sizeof(C300X_DEVICE_PATCH_TARGET_MASK)) {
        return 0;
    }
    c300x_copy_string(buffer, buffer_len, C300X_DEVICE_PATCH_TARGET_MASK);
    for (size_t index = 0; index < ARRAY_LEN(replacements); index++) {
        buffer[replacements[index].offset] = replacements[index].value;
    }
    return 1;
}

static int device_patch_path(char *buffer, size_t buffer_len, const char *directory)
{
    char name[sizeof(C300X_DEVICE_PATCH_TARGET_MASK)];
    int written;

    if (!device_patch_file_name(name, sizeof(name))) {
        return 0;
    }
    written = snprintf(buffer, buffer_len, "%s/%s", directory, name);
    return written >= 0 && written < (int)buffer_len;
}

static int device_patch_target_path(char *buffer, size_t buffer_len)
{
    return device_patch_path(buffer, buffer_len, C300X_DEVICE_PATCH_TARGET_DIR);
}

static int device_patch_backup_path(char *buffer, size_t buffer_len)
{
    return device_patch_path(buffer, buffer_len, C300X_DEVICE_PATCH_BACKUP_DIR);
}

static int device_patch_temp_path(char *buffer, size_t buffer_len, const char *path)
{
    int written = snprintf(buffer, buffer_len, "%s.tmp", path);

    return written >= 0 && written < (int)buffer_len;
}

static const unsigned char PATCH_0_WRITE_0[] = {0x00,0x50};
static const unsigned char PATCH_0_WRITE_1[] = {0x8a};
static const struct c300x_patch_write PATCH_0_WRITES[] = {
    {1, PATCH_0_WRITE_0, sizeof(PATCH_0_WRITE_0)},
    {11, PATCH_0_WRITE_1, sizeof(PATCH_0_WRITE_1)},
};
static const unsigned char PATCH_1_WRITE_0[] = {0x00,0x50};
static const unsigned char PATCH_1_WRITE_1[] = {0x00};
static const unsigned char PATCH_1_WRITE_2[] = {0x93};
static const unsigned char PATCH_1_WRITE_3[] = {0x9a,0x01};
static const unsigned char PATCH_1_WRITE_4[] = {0xe3};
static const struct c300x_patch_write PATCH_1_WRITES[] = {
    {1, PATCH_1_WRITE_0, sizeof(PATCH_1_WRITE_0)},
    {4, PATCH_1_WRITE_1, sizeof(PATCH_1_WRITE_1)},
    {7, PATCH_1_WRITE_2, sizeof(PATCH_1_WRITE_2)},
    {11, PATCH_1_WRITE_3, sizeof(PATCH_1_WRITE_3)},
    {15, PATCH_1_WRITE_4, sizeof(PATCH_1_WRITE_4)},
};
static const unsigned char PATCH_2_WRITE_0[] = {0x00,0x00,0xa0};
static const struct c300x_patch_write PATCH_2_WRITES[] = {
    {0, PATCH_2_WRITE_0, sizeof(PATCH_2_WRITE_0)},
};
static const unsigned char PATCH_3_WRITE_0[] = {0x00,0x00,0xa0,0xe1};
static const struct c300x_patch_write PATCH_3_WRITES[] = {
    {0, PATCH_3_WRITE_0, sizeof(PATCH_3_WRITE_0)},
};
static const unsigned char PATCH_4_WRITE_0[] = {0x00,0x00};
static const unsigned char PATCH_4_WRITE_1[] = {0x00,0x00};
static const unsigned char PATCH_4_WRITE_2[] = {0x00};
static const unsigned char PATCH_4_WRITE_3[] = {0x00,0x00,0xa0,0xe1};
static const struct c300x_patch_write PATCH_4_WRITES[] = {
    {0, PATCH_4_WRITE_0, sizeof(PATCH_4_WRITE_0)},
    {4, PATCH_4_WRITE_1, sizeof(PATCH_4_WRITE_1)},
    {8, PATCH_4_WRITE_2, sizeof(PATCH_4_WRITE_2)},
    {12, PATCH_4_WRITE_3, sizeof(PATCH_4_WRITE_3)},
};
static const unsigned char PATCH_5_WRITE_0[] = {0x8c,0x78};
static const struct c300x_patch_write PATCH_5_WRITES[] = {
    {0, PATCH_5_WRITE_0, sizeof(PATCH_5_WRITE_0)},
};
static const unsigned char PATCH_6_WRITE_0[] = {
    0x01,0x00,0x58,0xe3,0x05,0x00,0x00,0x1a,0x70,0x21,0x9f,0xe5,
    0x78,0x11,0x9f,0xe5,0x02,0x20,0x8f,0xe0,0x01,0x10,0x8f,0xe0,
    0x05
};
static const unsigned char PATCH_6_WRITE_1[] = {
    0xa0,0xe1,0x6c,0xc3,0xff,0xeb,0x5c,0x21,0x9f
};
static const unsigned char PATCH_6_WRITE_2[] = {
    0x5c,0x31,0x9f,0xe5,0x02,0x90,0x96,0xe7,0x03,0x60,0x96,0xe7,
    0x00,0x00,0xa0,0xe1,0x00,0x00
};
static const unsigned char PATCH_6_WRITE_3[] = {0xe1,0x00,0x00,0xa0};
static const struct c300x_patch_write PATCH_6_WRITES[] = {
    {0, PATCH_6_WRITE_0, sizeof(PATCH_6_WRITE_0)},
    {26, PATCH_6_WRITE_1, sizeof(PATCH_6_WRITE_1)},
    {36, PATCH_6_WRITE_2, sizeof(PATCH_6_WRITE_2)},
    {55, PATCH_6_WRITE_3, sizeof(PATCH_6_WRITE_3)},
};
static const unsigned char PATCH_7_WRITE_0[] = {0x48,0x54};
static const struct c300x_patch_write PATCH_7_WRITES[] = {
    {0, PATCH_7_WRITE_0, sizeof(PATCH_7_WRITE_0)},
};
static const unsigned char PATCH_8_WRITE_0[] = {0x48};
static const struct c300x_patch_write PATCH_8_WRITES[] = {
    {0, PATCH_8_WRITE_0, sizeof(PATCH_8_WRITE_0)},
};

static const struct c300x_patch_range PATCHES[] = {
    {"patch_range_0", 0x282f8, 12, "ed451a5b137b7b59ebfd3f4bb8ff6598a18abce58603b72eed97f50b8d6391b8", "59e44ff04f935f33e91e44d52771e6188e7a50c735c07b54f236087a818925d7", PATCH_0_WRITES, ARRAY_LEN(PATCH_0_WRITES)},
    {"patch_range_1", 0xda04, 16, "cad698e029e49e8557fa4259c816e318021875a348f0d2b967ed1579fce8439b", "9bf52da965bdf744685e93b31353826af7bc74bc1fc3248d91f3b89f493444fe", PATCH_1_WRITES, ARRAY_LEN(PATCH_1_WRITES)},
    {"patch_range_2", 0x35fe0, 4, "85a84a4f037c33de92504a8958803d3ca0aa78d17145ea83a7683d3f2fcc2547", "71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d", PATCH_2_WRITES, ARRAY_LEN(PATCH_2_WRITES)},
    {"patch_range_3", 0x35ff4, 4, "4954ed54e1284656fc34df4acf32b7bb7239c20a64300e0d7698c727e1de8391", "71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d", PATCH_3_WRITES, ARRAY_LEN(PATCH_3_WRITES)},
    {"patch_range_4", 0x36000, 16, "52c4701f0ebe03e78c0fed564727560fa0fc58e477656da7c254df341da5a55f", "801b48661d2b117e9d4c1065f5b27b8e68938ac8efaf47e5a1db1211d495f592", PATCH_4_WRITES, ARRAY_LEN(PATCH_4_WRITES)},
    {"patch_range_5", 0x363d8, 4, "578b7e8e1392acf5b7a042f27140fdff16d967de87b359c4629374f363061deb", "588247adc40731e7dac725b7c418ce8dedc2a7318e61f12836086f31d5d41520", PATCH_5_WRITES, ARRAY_LEN(PATCH_5_WRITES)},
    {"patch_range_6", 0x28420, 60, "4a113f9e80b59325c236497a1f60eb4c25ecfc818d846bc838d30d7a9d153d48", "16f1f5712d28c39b0e2ddf193b57ea53b9d8f498d42cee86625f2ff2792eef5c", PATCH_6_WRITES, ARRAY_LEN(PATCH_6_WRITES)},
    {"patch_range_7", 0x285a0, 4, "c77ead30bd3f6cae55371b8695c71e4c28de7b2006d3f17cd0a2629cdc98a5df", "27d18ebd92839189526cb6345d7f2d5e043d7551446dd60407975ef0e46e5cc4", PATCH_7_WRITES, ARRAY_LEN(PATCH_7_WRITES)},
    {"patch_range_8", 0x285ac, 4, "a883b9c4475398a5852aaf4ef0b4cbd8bd0557c4206c4d8bafd69832c8d56a47", "a828ca69c6e94a3592c35b9989123858720ac9b114514e040d53a604f87e1d6d", PATCH_8_WRITES, ARRAY_LEN(PATCH_8_WRITES)},
};

/* Firmware 2.0.2: same writes as above, at the offsets of that build. Only
 * range 4 has a different stock hash, its call moved with the code. */
static const struct c300x_patch_range PATCHES_2_0_2[] = {
    {"patch_range_0", 0x28300, 12, "ed451a5b137b7b59ebfd3f4bb8ff6598a18abce58603b72eed97f50b8d6391b8", "59e44ff04f935f33e91e44d52771e6188e7a50c735c07b54f236087a818925d7", PATCH_0_WRITES, ARRAY_LEN(PATCH_0_WRITES)},
    {"patch_range_1", 0xda08, 16, "cad698e029e49e8557fa4259c816e318021875a348f0d2b967ed1579fce8439b", "9bf52da965bdf744685e93b31353826af7bc74bc1fc3248d91f3b89f493444fe", PATCH_1_WRITES, ARRAY_LEN(PATCH_1_WRITES)},
    {"patch_range_2", 0x35fe8, 4, "85a84a4f037c33de92504a8958803d3ca0aa78d17145ea83a7683d3f2fcc2547", "71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d", PATCH_2_WRITES, ARRAY_LEN(PATCH_2_WRITES)},
    {"patch_range_3", 0x35ffc, 4, "4954ed54e1284656fc34df4acf32b7bb7239c20a64300e0d7698c727e1de8391", "71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d", PATCH_3_WRITES, ARRAY_LEN(PATCH_3_WRITES)},
    {"patch_range_4", 0x36008, 16, "e5843cd556cbbd9fc95fa4ae7b7291050d9a66615285f82804755eaf14039f2a", "801b48661d2b117e9d4c1065f5b27b8e68938ac8efaf47e5a1db1211d495f592", PATCH_4_WRITES, ARRAY_LEN(PATCH_4_WRITES)},
    {"patch_range_5", 0x363e0, 4, "578b7e8e1392acf5b7a042f27140fdff16d967de87b359c4629374f363061deb", "588247adc40731e7dac725b7c418ce8dedc2a7318e61f12836086f31d5d41520", PATCH_5_WRITES, ARRAY_LEN(PATCH_5_WRITES)},
    {"patch_range_6", 0x28428, 60, "4a113f9e80b59325c236497a1f60eb4c25ecfc818d846bc838d30d7a9d153d48", "16f1f5712d28c39b0e2ddf193b57ea53b9d8f498d42cee86625f2ff2792eef5c", PATCH_6_WRITES, ARRAY_LEN(PATCH_6_WRITES)},
    {"patch_range_7", 0x285a8, 4, "c77ead30bd3f6cae55371b8695c71e4c28de7b2006d3f17cd0a2629cdc98a5df", "27d18ebd92839189526cb6345d7f2d5e043d7551446dd60407975ef0e46e5cc4", PATCH_7_WRITES, ARRAY_LEN(PATCH_7_WRITES)},
    {"patch_range_8", 0x285b4, 4, "a883b9c4475398a5852aaf4ef0b4cbd8bd0557c4206c4d8bafd69832c8d56a47", "a828ca69c6e94a3592c35b9989123858720ac9b114514e040d53a604f87e1d6d", PATCH_8_WRITES, ARRAY_LEN(PATCH_8_WRITES)},
};

/* Firmware 3.0.6 (PIE). Patch sites re-derived from the recompiled binary;
 * p6 redirects the rec_json_f symlink instead of the 1.7.x code insertion. */
static const unsigned char PATCH_306_0_WRITE_0[] = {0x00,0x50};
static const unsigned char PATCH_306_0_WRITE_1[] = {0x8a};
static const struct c300x_patch_write PATCH_306_0_WRITES[] = {{1, PATCH_306_0_WRITE_0, sizeof(PATCH_306_0_WRITE_0)}, {11, PATCH_306_0_WRITE_1, sizeof(PATCH_306_0_WRITE_1)}};
static const unsigned char PATCH_306_1_WRITE_0[] = {0x00,0x50};
static const unsigned char PATCH_306_1_WRITE_1[] = {0x00};
static const unsigned char PATCH_306_1_WRITE_2[] = {0x93};
static const unsigned char PATCH_306_1_WRITE_3[] = {0x9a,0x01};
static const unsigned char PATCH_306_1_WRITE_4[] = {0xe3};
static const struct c300x_patch_write PATCH_306_1_WRITES[] = {{1, PATCH_306_1_WRITE_0, sizeof(PATCH_306_1_WRITE_0)}, {4, PATCH_306_1_WRITE_1, sizeof(PATCH_306_1_WRITE_1)}, {7, PATCH_306_1_WRITE_2, sizeof(PATCH_306_1_WRITE_2)}, {11, PATCH_306_1_WRITE_3, sizeof(PATCH_306_1_WRITE_3)}, {15, PATCH_306_1_WRITE_4, sizeof(PATCH_306_1_WRITE_4)}};
static const unsigned char PATCH_306_2_WRITE_0[] = {0x00,0x00,0xa0};
static const struct c300x_patch_write PATCH_306_2_WRITES[] = {{0, PATCH_306_2_WRITE_0, sizeof(PATCH_306_2_WRITE_0)}};
static const unsigned char PATCH_306_3_WRITE_0[] = {0x00,0x00,0xa0,0xe1};
static const struct c300x_patch_write PATCH_306_3_WRITES[] = {{0, PATCH_306_3_WRITE_0, sizeof(PATCH_306_3_WRITE_0)}};
static const unsigned char PATCH_306_4_WRITE_0[] = {0x00,0x00};
static const unsigned char PATCH_306_4_WRITE_1[] = {0x00,0x00};
static const unsigned char PATCH_306_4_WRITE_2[] = {0x00};
static const unsigned char PATCH_306_4_WRITE_3[] = {0x00,0x00,0xa0,0xe1};
static const struct c300x_patch_write PATCH_306_4_WRITES[] = {{0, PATCH_306_4_WRITE_0, sizeof(PATCH_306_4_WRITE_0)}, {4, PATCH_306_4_WRITE_1, sizeof(PATCH_306_4_WRITE_1)}, {8, PATCH_306_4_WRITE_2, sizeof(PATCH_306_4_WRITE_2)}, {12, PATCH_306_4_WRITE_3, sizeof(PATCH_306_4_WRITE_3)}};
static const unsigned char PATCH_306_5_WRITE_0[] = {0x7c,0x83,0x00,0x00};
static const struct c300x_patch_write PATCH_306_5_WRITES[] = {{0, PATCH_306_5_WRITE_0, sizeof(PATCH_306_5_WRITE_0)}};
static const unsigned char PATCH_306_6_WRITE_0[] = {0xf0,0x5e,0x01,0x00};
static const struct c300x_patch_write PATCH_306_6_WRITES[] = {{0, PATCH_306_6_WRITE_0, sizeof(PATCH_306_6_WRITE_0)}};

static const struct c300x_patch_range PATCHES_3_0_6[] = {
    {"p0_mode_recjson", 0x27014, 12, "a9db5d94fdd0cb9b4dae85941ac99762a33abcc5237db4edf051259c973b146e", "bfac450eff18576df39e787372d02b01c4ea3b4099d7cb1507ab4a21700d67cb", PATCH_306_0_WRITES, ARRAY_LEN(PATCH_306_0_WRITES)},
    {"p1_mode_sigusr2", 0xa1dc, 16, "cad698e029e49e8557fa4259c816e318021875a348f0d2b967ed1579fce8439b", "9bf52da965bdf744685e93b31353826af7bc74bc1fc3248d91f3b89f493444fe", PATCH_306_1_WRITES, ARRAY_LEN(PATCH_306_1_WRITES)},
    {"p2_nop_blx", 0x34d04, 4, "85a84a4f037c33de92504a8958803d3ca0aa78d17145ea83a7683d3f2fcc2547", "71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d", PATCH_306_2_WRITES, ARRAY_LEN(PATCH_306_2_WRITES)},
    {"p3_nop_str", 0x34d1c, 4, "4954ed54e1284656fc34df4acf32b7bb7239c20a64300e0d7698c727e1de8391", "71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d", PATCH_306_3_WRITES, ARRAY_LEN(PATCH_306_3_WRITES)},
    {"p4_nop_block", 0x34d24, 16, "cea97ef00435c2c2429911a495511a3f914c7b055dd04c4176c141c71a6d7b27", "801b48661d2b117e9d4c1065f5b27b8e68938ac8efaf47e5a1db1211d495f592", PATCH_306_4_WRITES, ARRAY_LEN(PATCH_306_4_WRITES)},
    {"p5_redir_update", 0x350dc, 4, "60b7b33fa991351fdc7658edb4d51d7f1193979428b4a5516d302911a4352b9b", "2ddad22425195d27460390320d8ed0b8bdd67a6bcbc94b36a5b16af16fa3f678", PATCH_306_5_WRITES, ARRAY_LEN(PATCH_306_5_WRITES)},
    {"p6_redir_recjson", 0x272d8, 4, "7bd214987c21b0d60e03be16fe943d682bdb18e9c85c006b1b8a363d31398245", "b4fe8af24b6dbb176ec9f93a250610fe56bad6c2807b5c0f2c10dab1722fbc89", PATCH_306_6_WRITES, ARRAY_LEN(PATCH_306_6_WRITES)},
};

/* Classe 100X 1.5.8: the same routing code as the C300X 1.7.19, built for
 * that device. Same patch sites, other offsets and call targets. */
static const unsigned char PATCH_C100X_0_WRITE_0[] = {0x00,0x50};
static const unsigned char PATCH_C100X_0_WRITE_1[] = {0x8a};
static const struct c300x_patch_write PATCH_C100X_0_WRITES[] = {{1, PATCH_C100X_0_WRITE_0, sizeof(PATCH_C100X_0_WRITE_0)}, {11, PATCH_C100X_0_WRITE_1, sizeof(PATCH_C100X_0_WRITE_1)}};
static const unsigned char PATCH_C100X_1_WRITE_0[] = {0x00,0x50};
static const unsigned char PATCH_C100X_1_WRITE_1[] = {0x00};
static const unsigned char PATCH_C100X_1_WRITE_2[] = {0x93};
static const unsigned char PATCH_C100X_1_WRITE_3[] = {0x9a,0x01};
static const unsigned char PATCH_C100X_1_WRITE_4[] = {0xe3};
static const struct c300x_patch_write PATCH_C100X_1_WRITES[] = {{1, PATCH_C100X_1_WRITE_0, sizeof(PATCH_C100X_1_WRITE_0)}, {4, PATCH_C100X_1_WRITE_1, sizeof(PATCH_C100X_1_WRITE_1)}, {7, PATCH_C100X_1_WRITE_2, sizeof(PATCH_C100X_1_WRITE_2)}, {11, PATCH_C100X_1_WRITE_3, sizeof(PATCH_C100X_1_WRITE_3)}, {15, PATCH_C100X_1_WRITE_4, sizeof(PATCH_C100X_1_WRITE_4)}};
static const unsigned char PATCH_C100X_2_WRITE_0[] = {0x00,0x00,0xa0};
static const struct c300x_patch_write PATCH_C100X_2_WRITES[] = {{0, PATCH_C100X_2_WRITE_0, sizeof(PATCH_C100X_2_WRITE_0)}};
static const unsigned char PATCH_C100X_3_WRITE_0[] = {0x00,0x00,0xa0,0xe1};
static const struct c300x_patch_write PATCH_C100X_3_WRITES[] = {{0, PATCH_C100X_3_WRITE_0, sizeof(PATCH_C100X_3_WRITE_0)}};
static const unsigned char PATCH_C100X_4_WRITE_0[] = {0x00,0x00};
static const unsigned char PATCH_C100X_4_WRITE_1[] = {0x00,0x00};
static const unsigned char PATCH_C100X_4_WRITE_2[] = {0x00};
static const unsigned char PATCH_C100X_4_WRITE_3[] = {0x00,0x00,0xa0,0xe1};
static const struct c300x_patch_write PATCH_C100X_4_WRITES[] = {{0, PATCH_C100X_4_WRITE_0, sizeof(PATCH_C100X_4_WRITE_0)}, {4, PATCH_C100X_4_WRITE_1, sizeof(PATCH_C100X_4_WRITE_1)}, {8, PATCH_C100X_4_WRITE_2, sizeof(PATCH_C100X_4_WRITE_2)}, {12, PATCH_C100X_4_WRITE_3, sizeof(PATCH_C100X_4_WRITE_3)}};
static const unsigned char PATCH_C100X_5_WRITE_0[] = {0x64,0x7a,0x00,0x00};
static const struct c300x_patch_write PATCH_C100X_5_WRITES[] = {{0, PATCH_C100X_5_WRITE_0, sizeof(PATCH_C100X_5_WRITE_0)}};
static const unsigned char PATCH_C100X_6_WRITE_0[] = {0x01,0x00,0x58,0xe3,0x05,0x00,0x00,0x1a,0x70,0x21,0x9f,0xe5,0x78,0x11,0x9f,0xe5,0x02,0x20,0x8f,0xe0,0x01,0x10,0x8f,0xe0,0x05};
static const unsigned char PATCH_C100X_6_WRITE_1[] = {0xa0,0xe1,0x40,0xc2,0xff,0xeb,0x5c,0x21,0x9f};
static const unsigned char PATCH_C100X_6_WRITE_2[] = {0x5c,0x31,0x9f,0xe5,0x02,0x90,0x96,0xe7,0x03,0x60,0x96,0xe7,0x00,0x00,0xa0,0xe1,0x00,0x00};
static const unsigned char PATCH_C100X_6_WRITE_3[] = {0xe1,0x00,0x00,0xa0};
static const struct c300x_patch_write PATCH_C100X_6_WRITES[] = {{0, PATCH_C100X_6_WRITE_0, sizeof(PATCH_C100X_6_WRITE_0)}, {26, PATCH_C100X_6_WRITE_1, sizeof(PATCH_C100X_6_WRITE_1)}, {36, PATCH_C100X_6_WRITE_2, sizeof(PATCH_C100X_6_WRITE_2)}, {55, PATCH_C100X_6_WRITE_3, sizeof(PATCH_C100X_6_WRITE_3)}};
static const unsigned char PATCH_C100X_7_WRITE_0[] = {0xa0,0x53,0x01,0x00};
static const struct c300x_patch_write PATCH_C100X_7_WRITES[] = {{0, PATCH_C100X_7_WRITE_0, sizeof(PATCH_C100X_7_WRITE_0)}};
static const unsigned char PATCH_C100X_8_WRITE_0[] = {0x14,0x3e,0x01,0x00};
static const struct c300x_patch_write PATCH_C100X_8_WRITES[] = {{0, PATCH_C100X_8_WRITE_0, sizeof(PATCH_C100X_8_WRITE_0)}};

static const struct c300x_patch_range PATCHES_C100X_1_5_8[] = {
    {"patch_range_0", 0x27958, 12, "ed451a5b137b7b59ebfd3f4bb8ff6598a18abce58603b72eed97f50b8d6391b8", "59e44ff04f935f33e91e44d52771e6188e7a50c735c07b54f236087a818925d7", PATCH_C100X_0_WRITES, ARRAY_LEN(PATCH_C100X_0_WRITES)},
    {"patch_range_1", 0xccdc, 16, "cad698e029e49e8557fa4259c816e318021875a348f0d2b967ed1579fce8439b", "9bf52da965bdf744685e93b31353826af7bc74bc1fc3248d91f3b89f493444fe", PATCH_C100X_1_WRITES, ARRAY_LEN(PATCH_C100X_1_WRITES)},
    {"patch_range_2", 0x353c0, 4, "85a84a4f037c33de92504a8958803d3ca0aa78d17145ea83a7683d3f2fcc2547", "71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d", PATCH_C100X_2_WRITES, ARRAY_LEN(PATCH_C100X_2_WRITES)},
    {"patch_range_3", 0x353d4, 4, "4954ed54e1284656fc34df4acf32b7bb7239c20a64300e0d7698c727e1de8391", "71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d", PATCH_C100X_3_WRITES, ARRAY_LEN(PATCH_C100X_3_WRITES)},
    {"patch_range_4", 0x353e0, 16, "a3c4925a787f8f0a30438bd324e0aa354bfddce3b559dff84bff2ac2997f8d1b", "801b48661d2b117e9d4c1065f5b27b8e68938ac8efaf47e5a1db1211d495f592", PATCH_C100X_4_WRITES, ARRAY_LEN(PATCH_C100X_4_WRITES)},
    {"patch_range_5", 0x357b0, 4, "86fee0a47ad59e05660f2942600617081e2566a6dfae1e91eb677916b4343f51", "536d1d675a6befffe6b908d9f5dbee941995f64fa735e852375f65c4c1ac0fd9", PATCH_C100X_5_WRITES, ARRAY_LEN(PATCH_C100X_5_WRITES)},
    {"patch_range_6", 0x27a80, 60, "4a113f9e80b59325c236497a1f60eb4c25ecfc818d846bc838d30d7a9d153d48", "0798984c1f9bff3d03759999f8b3f110b2752d77de089fa60a5659e60d8e1935", PATCH_C100X_6_WRITES, ARRAY_LEN(PATCH_C100X_6_WRITES)},
    {"patch_range_7", 0x27c00, 4, "4b59487eb8ab373488f734840d731a784b012a9efcd74b32524d5b910fa625af", "f41460fb396a434b65dcb784d93cb083e8fefcd641430ee4dd36e68a0e69add5", PATCH_C100X_7_WRITES, ARRAY_LEN(PATCH_C100X_7_WRITES)},
    {"patch_range_8", 0x27c0c, 4, "1522ff5a062ae5f276461e938415126b0cd09935ed9de2fee73d7f6294512bee", "f70bee9ce146862e6e2c2bad32fdda100b0b2705a523971840050b55f9c26567", PATCH_C100X_8_WRITES, ARRAY_LEN(PATCH_C100X_8_WRITES)},
};

struct routing_variant {
    const char *stock_sha256;
    const struct c300x_patch_range *patches;
    size_t patch_count;
};

static const struct routing_variant VARIANTS[] = {
    {C300X_DEVICE_PATCH_STOCK_SHA256, PATCHES, ARRAY_LEN(PATCHES)},
    {C300X_DEVICE_PATCH_STOCK_SHA256_2_0_2, PATCHES_2_0_2, ARRAY_LEN(PATCHES_2_0_2)},
    {C300X_DEVICE_PATCH_STOCK_SHA256_3_0_6, PATCHES_3_0_6, ARRAY_LEN(PATCHES_3_0_6)},
    {C300X_DEVICE_PATCH_STOCK_SHA256_C100X_1_5_8, PATCHES_C100X_1_5_8, ARRAY_LEN(PATCHES_C100X_1_5_8)},
};

static void set_error(char *error, size_t error_len, const char *message)
{
    if (error != NULL && error_len > 0) {
        c300x_copy_string(error, error_len, message != NULL ? message : "device_routing_failed");
    }
}

static void set_status_error(struct c300x_device_routing_status *status, const char *message)
{
    if (status != NULL) {
        c300x_copy_string(status->error, sizeof(status->error), message);
    }
}

static int remount_root_ro_or_error(char *error, size_t error_len)
{
    if (c300x_patch_remount_root("ro")) {
        return 1;
    }
    set_error(error, error_len, "remount_ro_failed");
    return 0;
}

static int variant_ranges_match(
    const struct routing_variant *variant,
    const unsigned char *data,
    size_t len,
    int patched
)
{
    for (size_t index = 0; index < variant->patch_count; index++) {
        const struct c300x_patch_range *patch = &variant->patches[index];
        const char *expected_sha256 = patched
            ? patch->patched_range_sha256
            : patch->expected_range_sha256;

        if (!c300x_patch_range_matches(data, len, patch, expected_sha256)) {
            return 0;
        }
    }
    return 1;
}

/* The variant whose ranges all hold the stock (or patched) bytes, if any. */
static const struct routing_variant *variant_matching(
    const unsigned char *data,
    size_t len,
    int patched
)
{
    for (size_t index = 0; index < ARRAY_LEN(VARIANTS); index++) {
        if (variant_ranges_match(&VARIANTS[index], data, len, patched)) {
            return &VARIANTS[index];
        }
    }
    return NULL;
}

static const struct routing_variant *variant_for_stock_sha(const char *sha256)
{
    for (size_t index = 0; index < ARRAY_LEN(VARIANTS); index++) {
        if (strcmp(sha256, VARIANTS[index].stock_sha256) == 0) {
            return &VARIANTS[index];
        }
    }
    return NULL;
}

/* The firmware build a target file belongs to: by its stock hash, else by its
 * patched ranges, else by its stock ranges. NULL for a file of neither build. */
static const struct routing_variant *target_variant(const char *target_path)
{
    char sha256[65];
    unsigned char *data = NULL;
    size_t len = 0;
    const struct routing_variant *variant = NULL;

    if (c300x_sha256_file_hex(target_path, sha256, sizeof(sha256))) {
        variant = variant_for_stock_sha(sha256);
    }
    if (variant == NULL && c300x_patch_read_file(target_path, &data, &len)) {
        variant = variant_matching(data, len, 1);
        if (variant == NULL) {
            variant = variant_matching(data, len, 0);
        }
        free(data);
    }
    return variant;
}

/* A backup is only worth restoring when it is the stock file: a truncated copy,
 * one of another firmware, or a patched one must never replace the target.
 * The backup folder outlives a firmware update, so the stock file of the other
 * supported firmware can lie there; it is refused whenever the target shows
 * which build the device runs. Only a target of neither build leaves that
 * open, and then any supported stock file is the better content. */
static int backup_is_stock(const char *backup_path, const char *target_path)
{
    const struct routing_variant *expected = target_variant(target_path);
    const struct routing_variant *found;
    char sha256[65];
    unsigned char *data = NULL;
    size_t len = 0;

    if (c300x_sha256_file_hex(backup_path, sha256, sizeof(sha256))) {
        found = variant_for_stock_sha(sha256);
        if (found != NULL) {
            return expected == NULL || found == expected;
        }
    }
    if (!c300x_patch_read_file(backup_path, &data, &len)) {
        return 0;
    }
    /* The ranges only cover the patched bytes. A copy that was cut off behind
     * the last range would pass them, so it must also be as long as the file
     * it is a backup of: the patch never changes the length. */
    if (!c300x_patch_file_size_matches(target_path, len)) {
        free(data);
        return 0;
    }
    found = expected != NULL
        ? (variant_ranges_match(expected, data, len, 0) ? expected : NULL)
        : variant_matching(data, len, 0);
    free(data);
    return found != NULL;
}

int c300x_device_routing_read_status(
    struct c300x_device_routing_status *status
)
{
    char backup_path[C300X_MAX_PATH_LEN];
    char target_path[C300X_MAX_PATH_LEN];
    unsigned char *data = NULL;
    size_t len = 0;

    memset(status, 0, sizeof(*status));
    status->supported = 1;
    if (!device_patch_target_path(target_path, sizeof(target_path))) {
        c300x_copy_string(status->state, sizeof(status->state), "missing");
        set_status_error(status, "target_path_failed");
        return 0;
    }
    if (!device_patch_backup_path(backup_path, sizeof(backup_path))) {
        c300x_copy_string(status->state, sizeof(status->state), "missing");
        set_status_error(status, "backup_path_failed");
        return 0;
    }
    if (!c300x_sha256_file_hex(target_path, status->file_sha256, sizeof(status->file_sha256))) {
        c300x_copy_string(status->state, sizeof(status->state), "missing");
        set_status_error(status, "routing_target_missing");
        return 0;
    }
    if (access(backup_path, F_OK) == 0) {
        status->backup_present = 1;
        (void)c300x_sha256_file_hex(backup_path, status->backup_sha256, sizeof(status->backup_sha256));
    }
    if (variant_for_stock_sha(status->file_sha256) != NULL) {
        c300x_copy_string(status->state, sizeof(status->state), "stock");
        return 1;
    }
    if (!c300x_patch_read_file(target_path, &data, &len)) {
        c300x_copy_string(status->state, sizeof(status->state), "unsupported");
        set_status_error(status, "routing_target_read_failed");
        return 0;
    }
    if (variant_matching(data, len, 1) != NULL) {
        status->patched = 1;
        c300x_copy_string(status->state, sizeof(status->state), "patched");
        free(data);
        return 1;
    }
    if (variant_matching(data, len, 0) != NULL) {
        c300x_copy_string(status->state, sizeof(status->state), "stock");
        free(data);
        return 1;
    }
    free(data);
    c300x_copy_string(status->state, sizeof(status->state), "unsupported");
    set_status_error(status, "unsupported_routing_target_hash");
    return 1;
}

int c300x_device_routing_apply(
    struct c300x_device_routing_status *status,
    char *error,
    size_t error_len
)
{
    char backup_path[C300X_MAX_PATH_LEN];
    char target_path[C300X_MAX_PATH_LEN];
    char target_tmp_path[C300X_MAX_PATH_LEN];
    unsigned char *data = NULL;
    size_t len = 0;
    const struct routing_variant *variant;
    mode_t original_mode;
    uid_t original_uid;
    gid_t original_gid;
    FILE *fp;
    int fd;

    if (!c300x_device_routing_read_status(status)) {
        set_error(error, error_len, "routing_status_failed");
        return 0;
    }
    if (status->patched) {
        return 1;
    }
    if (strcmp(status->state, "stock") != 0) {
        set_error(error, error_len, "unsupported_routing_target_hash");
        return 0;
    }
    if (!device_patch_target_path(target_path, sizeof(target_path))) {
        set_error(error, error_len, "target_path_failed");
        return 0;
    }
    if (!device_patch_backup_path(backup_path, sizeof(backup_path))) {
        set_error(error, error_len, "backup_path_failed");
        return 0;
    }
    if (!device_patch_temp_path(target_tmp_path, sizeof(target_tmp_path), target_path)) {
        set_error(error, error_len, "target_tmp_path_failed");
        return 0;
    }
    if (!c300x_patch_file_mode(target_path, &original_mode, &original_uid, &original_gid)) {
        set_error(error, error_len, "routing_target_stat_failed");
        return 0;
    }
    if (
        (!status->backup_present || !backup_is_stock(backup_path, target_path))
        && !c300x_patch_copy_file_exact(target_path, backup_path, original_mode)
    ) {
        set_error(error, error_len, "routing_backup_failed");
        return 0;
    }
    if (!c300x_patch_read_file(target_path, &data, &len)) {
        set_error(error, error_len, "routing_target_read_failed");
        return 0;
    }
    variant = variant_for_stock_sha(status->file_sha256);
    if (variant == NULL) {
        variant = variant_matching(data, len, 0);
    }
    if (variant == NULL) {
        free(data);
        set_error(error, error_len, "unsupported_routing_target_hash");
        return 0;
    }
    for (size_t index = 0; index < variant->patch_count; index++) {
        const struct c300x_patch_range *patch = &variant->patches[index];
        if (!c300x_patch_range_matches(data, len, patch, patch->expected_range_sha256)) {
            free(data);
            set_error(error, error_len, patch->name);
            return 0;
        }
        for (size_t write_index = 0; write_index < patch->write_count; write_index++) {
            const struct c300x_patch_write *write = &patch->writes[write_index];
            if (write->offset + write->len > patch->range_len) {
                free(data);
                set_error(error, error_len, patch->name);
                return 0;
            }
            memcpy(data + patch->offset + write->offset, write->data, write->len);
        }
        if (!c300x_patch_range_matches(data, len, patch, patch->patched_range_sha256)) {
            free(data);
            set_error(error, error_len, patch->name);
            return 0;
        }
    }
    if (!c300x_patch_remount_root("rw")) {
        free(data);
        set_error(error, error_len, "remount_rw_failed");
        return 0;
    }
    fp = fopen(target_tmp_path, "wb");
    if (fp == NULL || fwrite(data, 1, len, fp) != len) {
        if (fp != NULL) {
            fclose(fp);
        }
        unlink(target_tmp_path);
        (void)c300x_patch_remount_root("ro");
        free(data);
        set_error(error, error_len, "routing_write_failed");
        return 0;
    }
    free(data);
    fd = fileno(fp);
    if (
        fd < 0
        || fchmod(fd, original_mode) != 0
        || (fchown(fd, original_uid, original_gid) != 0 && errno != EPERM)
    ) {
        fclose(fp);
        unlink(target_tmp_path);
        (void)c300x_patch_remount_root("ro");
        set_error(error, error_len, "routing_target_replace_failed");
        return 0;
    }
    (void)fsync(fd);
    if (fclose(fp) != 0 || rename(target_tmp_path, target_path) != 0) {
        unlink(target_tmp_path);
        (void)c300x_patch_remount_root("ro");
        set_error(error, error_len, "routing_target_replace_failed");
        return 0;
    }
    if (!remount_root_ro_or_error(error, error_len)) {
        return 0;
    }
    if (!c300x_device_routing_read_status(status) || !status->patched) {
        set_error(error, error_len, "patched_ranges_mismatch");
        return 0;
    }
    return 1;
}

int c300x_device_routing_restore(
    struct c300x_device_routing_status *status,
    char *error,
    size_t error_len
)
{
    char backup_path[C300X_MAX_PATH_LEN];
    char target_path[C300X_MAX_PATH_LEN];
    mode_t backup_mode;

    if (!device_patch_target_path(target_path, sizeof(target_path))) {
        set_error(error, error_len, "target_path_failed");
        return 0;
    }
    if (!device_patch_backup_path(backup_path, sizeof(backup_path))) {
        set_error(error, error_len, "backup_path_failed");
        return 0;
    }
    if (access(backup_path, F_OK) != 0) {
        set_error(error, error_len, "routing_backup_missing");
        return 0;
    }
    if (!c300x_patch_file_mode(backup_path, &backup_mode, NULL, NULL)) {
        set_error(error, error_len, "routing_backup_stat_failed");
        return 0;
    }
    if (!backup_is_stock(backup_path, target_path)) {
        set_error(error, error_len, "routing_backup_invalid");
        return 0;
    }
    if (!c300x_patch_remount_root("rw")) {
        set_error(error, error_len, "remount_rw_failed");
        return 0;
    }
    if (!c300x_patch_copy_file_exact(backup_path, target_path, backup_mode)) {
        (void)c300x_patch_remount_root("ro");
        set_error(error, error_len, "routing_restore_failed");
        return 0;
    }
    if (!remount_root_ro_or_error(error, error_len)) {
        return 0;
    }
    return c300x_device_routing_read_status(status);
}
