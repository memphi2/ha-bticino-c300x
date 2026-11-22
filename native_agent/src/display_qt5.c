#include "display_qt5.h"

#include <dlfcn.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "device_patch_io.h"
#include "sha256.h"

#define QT5_GUI_BINARY "/home/bticino/bin/gui/BtClass"
#define QT5_PREFIX "skins/default/"
#define QT5_ENTRY_LEN 22u
#define QT5_HEADER_LEN 20u
#define QT5_MAX_FILE_LEN (4u * 1024u * 1024u)
#define QT5_MAX_PACK_LEN (16u * 1024u * 1024u)
#define QT5_MAX_NODES 256
#define QT5_MAX_NAME_LEN 96
#define QT5_MAX_PATH_LEN 512

/* Where the resource tables of a known BtClass lie, all in format version 2. */
struct qt5_layout {
    const char *sha256;
    size_t tree;
    size_t names;
    size_t data;
};

static const struct qt5_layout qt5_layouts[] = {
    /* Firmware 3.0.6 */
    {"6e114e7d9ce17d4c587a13082720bb6b5e66d5683bfd12047321b9694f2971f8", 0x35c6cu, 0x3672cu, 0x3791cu},
#ifdef C300X_DISPLAY_QT5_TEST_LAYOUT
    C300X_DISPLAY_QT5_TEST_LAYOUT,
#endif
};

/* qt5/qrc_overlay_blob.S; weak, so a build without it reports it missing. */
extern const unsigned char c300x_qrc_overlay_so[] __attribute__((weak));
extern const unsigned char c300x_qrc_overlay_so_end[] __attribute__((weak));

struct qt5_image {
    const unsigned char *bytes;
    size_t len;
    const struct qt5_layout *layout;
};

struct qt5_node {
    char name[QT5_MAX_NAME_LEN + 1];
    uint32_t hash;
    int parent;
    int dir;
    const char *rel;
    uint32_t index;
    uint32_t child_count;
    uint32_t first_child;
    uint32_t name_offset;
    uint32_t data_offset;
    unsigned char *data;
    size_t data_len;
    uint64_t mtime_ms;
};

static uint32_t be16(const unsigned char *p)
{
    return ((uint32_t)p[0] << 8) | p[1];
}

static uint32_t be32(const unsigned char *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static void put16(unsigned char *p, uint32_t value)
{
    p[0] = (unsigned char)(value >> 8);
    p[1] = (unsigned char)value;
}

static void put32(unsigned char *p, uint32_t value)
{
    p[0] = (unsigned char)(value >> 24);
    p[1] = (unsigned char)(value >> 16);
    p[2] = (unsigned char)(value >> 8);
    p[3] = (unsigned char)value;
}

static int print_result(int ok, const char *error, unsigned count)
{
    if (ok) {
        printf("{\"ok\":true,\"files\":%u}\n", count);
        return 0;
    }
    printf("{\"ok\":false,\"error\":\"%s\"}\n", error);
    return 1;
}

/* Plain names only: the paths come from the patch script and end up in the
 * resource tree and on disk. */
static int valid_rel(const char *rel)
{
    size_t segment = 0;

    if (rel[0] == '\0' || strlen(rel) > QT5_MAX_PATH_LEN - sizeof(QT5_PREFIX)) {
        return 0;
    }
    for (const char *p = rel;; p++) {
        if (*p == '/' || *p == '\0') {
            if (segment == 0 || segment > QT5_MAX_NAME_LEN
                || (segment == 1 && p[-1] == '.')
                || (segment == 2 && p[-1] == '.' && p[-2] == '.')) {
                return 0;
            }
            if (*p == '\0') {
                return 1;
            }
            segment = 0;
            continue;
        }
        if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') || (*p >= '0' && *p <= '9')
              || *p == '.' || *p == '_' || *p == '-')) {
            return 0;
        }
        segment++;
    }
}

static int image_entry(const struct qt5_image *image, uint32_t index, const unsigned char **entry)
{
    size_t offset;

    if (index >= image->len / QT5_ENTRY_LEN || image->layout->tree > image->len) {
        return 0;
    }
    offset = image->layout->tree + (size_t)index * QT5_ENTRY_LEN;
    if (offset < image->layout->tree || offset > image->len || image->len - offset < QT5_ENTRY_LEN) {
        return 0;
    }
    *entry = image->bytes + offset;
    return 1;
}

static int image_name_is(const struct qt5_image *image, uint32_t name_offset, const char *name, size_t len)
{
    size_t offset;
    uint32_t count;

    if (image->layout->names > image->len || name_offset > image->len - image->layout->names) {
        return 0;
    }
    offset = image->layout->names + name_offset;
    if (image->len - offset < 6) {
        return 0;
    }
    count = be16(image->bytes + offset);
    if (count != len || (image->len - offset - 6) / 2 < count) {
        return 0;
    }
    for (size_t i = 0; i < len; i++) {
        if (image->bytes[offset + 6 + 2 * i] != 0
            || image->bytes[offset + 7 + 2 * i] != (unsigned char)name[i]) {
            return 0;
        }
    }
    return 1;
}

static int image_find(const struct qt5_image *image, const char *path, const unsigned char **found)
{
    const unsigned char *current;
    const char *segment = path;

    if (!image_entry(image, 0, &current)) {
        return 0;
    }
    while (*segment != '\0') {
        const char *end = strchr(segment, '/');
        size_t len = end != NULL ? (size_t)(end - segment) : strlen(segment);
        uint32_t count;
        uint32_t first;
        const unsigned char *match = NULL;

        if (!(be16(current + 4) & 2u)) {
            return 0;
        }
        count = be32(current + 6);
        first = be32(current + 10);
        for (uint32_t i = 0; i < count && i < 4096u; i++) {
            const unsigned char *child;
            if (first + i < first || !image_entry(image, first + i, &child)) {
                return 0;
            }
            if (image_name_is(image, be32(child), segment, len)) {
                match = child;
                break;
            }
        }
        if (match == NULL) {
            return 0;
        }
        current = match;
        segment += len + (end != NULL ? 1 : 0);
    }
    if (be16(current + 4) & 2u) {
        return 0;
    }
    *found = current;
    return 1;
}

typedef int (*qt5_uncompress_fn)(unsigned char *, unsigned long *, const unsigned char *, unsigned long);

/* The device has zlib, the agent does not link it: loaded for this only. */
static int inflate_resource(const unsigned char *source, size_t source_len, unsigned char *out, size_t out_len)
{
    void *library = dlopen("libz.so.1", RTLD_NOW | RTLD_LOCAL);
    void *symbol;
    qt5_uncompress_fn uncompress_data;
    unsigned long written = (unsigned long)out_len;
    int ok;

    if (library == NULL) {
        return 0;
    }
    symbol = dlsym(library, "uncompress");
    if (symbol == NULL || sizeof(symbol) != sizeof(uncompress_data)) {
        dlclose(library);
        return 0;
    }
    memcpy(&uncompress_data, &symbol, sizeof(uncompress_data));
    ok = uncompress_data(out, &written, source, (unsigned long)source_len) == 0 && written == out_len;
    dlclose(library);
    return ok;
}

static const char *image_read(const struct qt5_image *image, const unsigned char *entry,
    unsigned char **out, size_t *out_len)
{
    uint32_t flags = be16(entry + 4);
    uint32_t data_offset = be32(entry + 10);
    size_t offset;
    uint32_t size;
    const unsigned char *blob;

    if (image->layout->data > image->len || data_offset > image->len - image->layout->data) {
        return "display_resource_damaged";
    }
    offset = image->layout->data + data_offset;
    if (image->len - offset < 4) {
        return "display_resource_damaged";
    }
    size = be32(image->bytes + offset);
    if (size > image->len - offset - 4 || size > QT5_MAX_FILE_LEN) {
        return "display_resource_damaged";
    }
    blob = image->bytes + offset + 4;
    if (flags & ~1u) {
        return "display_resource_compression_unsupported";
    }
    if (!(flags & 1u)) {
        *out = malloc(size + 1u);
        if (*out == NULL) {
            return "out_of_memory";
        }
        memcpy(*out, blob, size);
        *out_len = size;
        return NULL;
    }
    /* Compressed as qCompress does it: the plain length, then a zlib stream. */
    if (size < 4 || be32(blob) > QT5_MAX_FILE_LEN) {
        return "display_resource_damaged";
    }
    *out_len = be32(blob);
    *out = malloc(*out_len + 1u);
    if (*out == NULL) {
        return "out_of_memory";
    }
    if (!inflate_resource(blob + 4, size - 4u, *out, *out_len)) {
        free(*out);
        *out = NULL;
        return "display_resource_inflate_failed";
    }
    return NULL;
}

static int write_whole_file(const char *path, const unsigned char *data, size_t len)
{
    char temp[QT5_MAX_PATH_LEN + 16];
    FILE *file;
    int ok;

    if (snprintf(temp, sizeof(temp), "%s.tmp", path) >= (int)sizeof(temp)
        || !c300x_patch_ensure_parent_dir(path)) {
        return 0;
    }
    file = fopen(temp, "wb");
    if (file == NULL) {
        return 0;
    }
    ok = fwrite(data, 1, len, file) == len;
    ok = fflush(file) == 0 && ok;
    ok = fsync(fileno(file)) == 0 && ok;
    ok = fclose(file) == 0 && ok;
    if (!ok || chmod(temp, 0644) != 0 || rename(temp, path) != 0) {
        unlink(temp);
        return 0;
    }
    return 1;
}

static int extract(int argc, char **argv)
{
    const char *binary = getenv("C300X_QT5_GUI_BINARY");
    unsigned char *bytes = NULL;
    size_t len = 0;
    char sha256[65];
    struct qt5_image image = {0};
    const char *error = NULL;
    unsigned written = 0;

    if (argc < 2) {
        return print_result(0, "invalid_arguments", 0);
    }
    if (binary == NULL || binary[0] == '\0') {
        binary = QT5_GUI_BINARY;
    }
    if (!c300x_patch_read_file(binary, &bytes, &len)) {
        return print_result(0, "display_program_unreadable", 0);
    }
    if (!c300x_sha256_bytes_hex(bytes, len, sha256, sizeof(sha256))) {
        free(bytes);
        return print_result(0, "display_program_unreadable", 0);
    }
    for (size_t i = 0; i < sizeof(qt5_layouts) / sizeof(qt5_layouts[0]); i++) {
        if (strcmp(qt5_layouts[i].sha256, sha256) == 0) {
            image.layout = &qt5_layouts[i];
        }
    }
    if (image.layout == NULL) {
        free(bytes);
        return print_result(0, "display_program_unknown", 0);
    }
    image.bytes = bytes;
    image.len = len;
    for (int i = 1; i < argc && error == NULL; i++) {
        char path[QT5_MAX_PATH_LEN];
        char target[QT5_MAX_PATH_LEN * 2];
        const unsigned char *entry;
        unsigned char *data = NULL;
        size_t data_len = 0;

        if (!valid_rel(argv[i])) {
            error = "invalid_arguments";
            break;
        }
        snprintf(path, sizeof(path), "%s%s", QT5_PREFIX, argv[i]);
        if (!image_find(&image, path, &entry)) {
            error = "display_resource_missing";
            break;
        }
        error = image_read(&image, entry, &data, &data_len);
        if (error != NULL) {
            break;
        }
        if (snprintf(target, sizeof(target), "%s/%s", argv[0], argv[i]) >= (int)sizeof(target)
            || !write_whole_file(target, data, data_len)) {
            error = "write_failed";
        } else {
            written++;
        }
        free(data);
    }
    free(bytes);
    return print_result(error == NULL, error, written);
}

static uint32_t qt_hash(const char *name)
{
    uint32_t hash = 0;

    for (const unsigned char *p = (const unsigned char *)name; *p != '\0'; p++) {
        hash = (hash << 4) + *p;
        hash ^= (hash & 0xf0000000u) >> 23;
        hash &= 0x0fffffffu;
    }
    return hash;
}

static int pack_child(struct qt5_node *nodes, int *count, int parent, const char *name, size_t len, int dir)
{
    for (int i = 1; i < *count; i++) {
        if (nodes[i].parent == parent && strlen(nodes[i].name) == len && memcmp(nodes[i].name, name, len) == 0) {
            return nodes[i].dir && dir ? i : -1;
        }
    }
    if (*count >= QT5_MAX_NODES) {
        return -1;
    }
    memset(&nodes[*count], 0, sizeof(nodes[*count]));
    memcpy(nodes[*count].name, name, len);
    nodes[*count].name[len] = '\0';
    nodes[*count].hash = qt_hash(nodes[*count].name);
    nodes[*count].parent = parent;
    nodes[*count].dir = dir;
    return (*count)++;
}

static int pack_add(struct qt5_node *nodes, int *count, const char *path, const char *rel)
{
    int parent = 0;
    const char *segment = path;

    for (;;) {
        const char *end = strchr(segment, '/');
        size_t len = end != NULL ? (size_t)(end - segment) : strlen(segment);
        int node = pack_child(nodes, count, parent, segment, len, end != NULL);

        if (node < 0) {
            return 0;
        }
        if (end == NULL) {
            nodes[node].rel = rel;
            return 1;
        }
        parent = node;
        segment = end + 1;
    }
}

static int node_before(const struct qt5_node *a, const struct qt5_node *b)
{
    return a->hash != b->hash ? a->hash < b->hash : strcmp(a->name, b->name) < 0;
}

/* Qt finds a name by a binary search over the hashes of a folder's entries, so
 * the entries of each folder lie together, ordered by hash. */
static int pack_order(struct qt5_node *nodes, int count, int *order)
{
    int ordered = 1;

    order[0] = 0;
    nodes[0].index = 0;
    for (int at = 0; at < ordered; at++) {
        struct qt5_node *dir = &nodes[order[at]];
        int first = ordered;

        if (!dir->dir) {
            continue;
        }
        for (int i = 1; i < count; i++) {
            if (nodes[i].parent == order[at]) {
                int slot = ordered++;
                while (slot > first && node_before(&nodes[i], &nodes[order[slot - 1]])) {
                    order[slot] = order[slot - 1];
                    slot--;
                }
                order[slot] = i;
            }
        }
        dir->first_child = (uint32_t)first;
        dir->child_count = (uint32_t)(ordered - first);
        for (int slot = first; slot < ordered; slot++) {
            nodes[order[slot]].index = (uint32_t)slot;
        }
    }
    return ordered == count;
}

/* Opened without following a link; the old device glibc has no stat calls. */
static const char *pack_read(struct qt5_node *node, const char *root, uint64_t mtime_ms)
{
    char path[QT5_MAX_PATH_LEN * 2];
    unsigned char *data;
    size_t len = 0;
    int fd;

    if (snprintf(path, sizeof(path), "%s/%s", root, node->rel) >= (int)sizeof(path)) {
        return "display_file_missing";
    }
    fd = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) {
        return "display_file_missing";
    }
    data = malloc(QT5_MAX_FILE_LEN + 1u);
    if (data == NULL) {
        close(fd);
        return "out_of_memory";
    }
    for (;;) {
        ssize_t got = read(fd, data + len, QT5_MAX_FILE_LEN + 1u - len);
        if (got < 0) {
            len = QT5_MAX_FILE_LEN + 1u;
            break;
        }
        if (got == 0 || (len += (size_t)got) > QT5_MAX_FILE_LEN) {
            break;
        }
    }
    close(fd);
    if (len > QT5_MAX_FILE_LEN) {
        free(data);
        return "display_file_unreadable";
    }
    node->data = data;
    node->data_len = len;
    node->mtime_ms = mtime_ms;
    return NULL;
}

static const char *pack_write(struct qt5_node *nodes, int count, const int *order, const char *out)
{
    size_t names_len = 0;
    size_t data_len = 0;
    size_t tree_len = (size_t)count * QT5_ENTRY_LEN;
    size_t total;
    unsigned char *file;
    unsigned char *p;
    const char *error = NULL;

    for (int slot = 1; slot < count; slot++) {
        struct qt5_node *node = &nodes[order[slot]];
        node->name_offset = (uint32_t)names_len;
        names_len += 6 + 2 * strlen(node->name);
        if (!node->dir) {
            node->data_offset = (uint32_t)data_len;
            data_len += 4 + node->data_len;
        }
    }
    total = QT5_HEADER_LEN + tree_len + names_len + data_len;
    if (total > QT5_MAX_PACK_LEN) {
        return "display_files_too_large";
    }
    file = calloc(1, total);
    if (file == NULL) {
        return "out_of_memory";
    }
    memcpy(file, "qres", 4);
    put32(file + 4, 2);
    put32(file + 8, QT5_HEADER_LEN);
    put32(file + 12, (uint32_t)(QT5_HEADER_LEN + tree_len + names_len));
    put32(file + 16, (uint32_t)(QT5_HEADER_LEN + tree_len));
    for (int slot = 0; slot < count; slot++) {
        struct qt5_node *node = &nodes[order[slot]];
        unsigned char *entry = file + QT5_HEADER_LEN + (size_t)slot * QT5_ENTRY_LEN;
        put32(entry, node->name_offset);
        if (node->dir) {
            put16(entry + 4, 2);
            put32(entry + 6, node->child_count);
            put32(entry + 10, node->first_child);
        } else {
            put16(entry + 4, 0);
            /* No country, the C locale: the file every locale gets. */
            put16(entry + 6, 0);
            put16(entry + 8, 1);
            put32(entry + 10, node->data_offset);
        }
        put32(entry + 14, (uint32_t)(node->mtime_ms >> 32));
        put32(entry + 18, (uint32_t)node->mtime_ms);
        if (slot > 0) {
            p = file + QT5_HEADER_LEN + tree_len + node->name_offset;
            put16(p, (uint32_t)strlen(node->name));
            put32(p + 2, node->hash);
            for (size_t i = 0; node->name[i] != '\0'; i++) {
                p[6 + 2 * i] = 0;
                p[7 + 2 * i] = (unsigned char)node->name[i];
            }
        }
        if (!node->dir) {
            p = file + QT5_HEADER_LEN + tree_len + names_len + node->data_offset;
            put32(p, (uint32_t)node->data_len);
            memcpy(p + 4, node->data, node->data_len);
        }
    }
    if (!write_whole_file(out, file, total)) {
        error = "write_failed";
    }
    free(file);
    return error;
}

static int pack(int argc, char **argv)
{
    struct qt5_node *nodes;
    int order[QT5_MAX_NODES];
    int count = 1;
    unsigned files = 0;
    const char *error = NULL;

    if (argc < 3) {
        return print_result(0, "invalid_arguments", 0);
    }
    nodes = calloc(QT5_MAX_NODES, sizeof(*nodes));
    if (nodes == NULL) {
        return print_result(0, "out_of_memory", 0);
    }
    nodes[0].dir = 1;
    nodes[0].parent = -1;
    for (int i = 2; i < argc && error == NULL; i++) {
        char path[QT5_MAX_PATH_LEN];
        if (!valid_rel(argv[i])) {
            error = "invalid_arguments";
        } else {
            snprintf(path, sizeof(path), "%s%s", QT5_PREFIX, argv[i]);
            if (!pack_add(nodes, &count, path, argv[i])) {
                error = "invalid_arguments";
            }
        }
    }
    for (int i = 1; i < count && error == NULL; i++) {
        if (!nodes[i].dir) {
            error = pack_read(&nodes[i], argv[0], (uint64_t)time(NULL) * 1000u);
            files++;
        }
    }
    if (error == NULL && !pack_order(nodes, count, order)) {
        error = "invalid_arguments";
    }
    if (error == NULL) {
        error = pack_write(nodes, count, order, argv[1]);
    }
    for (int i = 0; i < count; i++) {
        free(nodes[i].data);
    }
    free(nodes);
    return print_result(error == NULL, error, error == NULL ? files : 0);
}

/* Rewritten only when it differs: the running display keeps the old file. */
static int overlay(int argc, char **argv)
{
    unsigned char *current = NULL;
    size_t current_len = 0;
    size_t len;
    int same;

    if (argc != 1) {
        return print_result(0, "invalid_arguments", 0);
    }
    if (c300x_qrc_overlay_so == NULL || c300x_qrc_overlay_so_end == NULL
        || (uintptr_t)c300x_qrc_overlay_so_end <= (uintptr_t)c300x_qrc_overlay_so) {
        return print_result(0, "overlay_missing", 0);
    }
    len = (size_t)((uintptr_t)c300x_qrc_overlay_so_end - (uintptr_t)c300x_qrc_overlay_so);
    same = c300x_patch_read_file(argv[0], &current, &current_len)
        && current_len == len && memcmp(current, c300x_qrc_overlay_so, len) == 0;
    free(current);
    if (!same && !write_whole_file(argv[0], c300x_qrc_overlay_so, len)) {
        return print_result(0, "write_failed", 0);
    }
    return print_result(1, NULL, 1);
}

int c300x_display_qt5_cli(int argc, char **argv)
{
    if (argc >= 1 && strcmp(argv[0], "overlay") == 0) {
        return overlay(argc - 1, argv + 1);
    }
    if (argc >= 1 && strcmp(argv[0], "extract") == 0) {
        return extract(argc - 1, argv + 1);
    }
    if (argc >= 1 && strcmp(argv[0], "pack") == 0) {
        return pack(argc - 1, argv + 1);
    }
    fprintf(stderr, "fatal: invalid_arguments: --display-qt5 needs extract DIR REL..., pack ROOT OUT REL... or overlay PATH\n");
    return 2;
}
