#include "sha256.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

struct sha256_context {
    uint32_t state[8];
    uint64_t bit_count;
    unsigned char buffer[64];
};

static uint32_t sha256_rotr(uint32_t value, unsigned int bits)
{
    return (value >> bits) | (value << (32U - bits));
}

static void sha256_transform(struct sha256_context *context, const unsigned char block[64])
{
    static const uint32_t constants[64] = {
        0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U,
        0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
        0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
        0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
        0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
        0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
        0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
        0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
        0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
        0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
        0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U,
        0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
        0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U,
        0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
        0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
        0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U,
    };
    uint32_t words[64];
    uint32_t a;
    uint32_t b;
    uint32_t c;
    uint32_t d;
    uint32_t e;
    uint32_t f;
    uint32_t g;
    uint32_t h;

    for (size_t index = 0; index < 16; index++) {
        words[index] = ((uint32_t)block[index * 4] << 24)
            | ((uint32_t)block[index * 4 + 1] << 16)
            | ((uint32_t)block[index * 4 + 2] << 8)
            | (uint32_t)block[index * 4 + 3];
    }
    for (size_t index = 16; index < 64; index++) {
        uint32_t s0 = sha256_rotr(words[index - 15], 7)
            ^ sha256_rotr(words[index - 15], 18)
            ^ (words[index - 15] >> 3);
        uint32_t s1 = sha256_rotr(words[index - 2], 17)
            ^ sha256_rotr(words[index - 2], 19)
            ^ (words[index - 2] >> 10);
        words[index] = words[index - 16] + s0 + words[index - 7] + s1;
    }

    a = context->state[0];
    b = context->state[1];
    c = context->state[2];
    d = context->state[3];
    e = context->state[4];
    f = context->state[5];
    g = context->state[6];
    h = context->state[7];

    for (size_t index = 0; index < 64; index++) {
        uint32_t s1 = sha256_rotr(e, 6) ^ sha256_rotr(e, 11) ^ sha256_rotr(e, 25);
        uint32_t ch = (e & f) ^ ((~e) & g);
        uint32_t temp1 = h + s1 + ch + constants[index] + words[index];
        uint32_t s0 = sha256_rotr(a, 2) ^ sha256_rotr(a, 13) ^ sha256_rotr(a, 22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t temp2 = s0 + maj;

        h = g;
        g = f;
        f = e;
        e = d + temp1;
        d = c;
        c = b;
        b = a;
        a = temp1 + temp2;
    }

    context->state[0] += a;
    context->state[1] += b;
    context->state[2] += c;
    context->state[3] += d;
    context->state[4] += e;
    context->state[5] += f;
    context->state[6] += g;
    context->state[7] += h;
}

static void sha256_init(struct sha256_context *context)
{
    context->state[0] = 0x6a09e667U;
    context->state[1] = 0xbb67ae85U;
    context->state[2] = 0x3c6ef372U;
    context->state[3] = 0xa54ff53aU;
    context->state[4] = 0x510e527fU;
    context->state[5] = 0x9b05688cU;
    context->state[6] = 0x1f83d9abU;
    context->state[7] = 0x5be0cd19U;
    context->bit_count = 0;
    memset(context->buffer, 0, sizeof(context->buffer));
}

static void sha256_update(
    struct sha256_context *context,
    const unsigned char *data,
    size_t len
)
{
    size_t buffer_index = (size_t)((context->bit_count / 8U) % 64U);

    context->bit_count += (uint64_t)len * 8U;
    for (size_t index = 0; index < len; index++) {
        context->buffer[buffer_index++] = data[index];
        if (buffer_index == 64) {
            sha256_transform(context, context->buffer);
            buffer_index = 0;
        }
    }
}

static void sha256_final(struct sha256_context *context, unsigned char digest[32])
{
    uint64_t bit_count = context->bit_count;
    size_t buffer_index = (size_t)((context->bit_count / 8U) % 64U);

    context->buffer[buffer_index++] = 0x80U;
    if (buffer_index > 56) {
        while (buffer_index < 64) {
            context->buffer[buffer_index++] = 0;
        }
        sha256_transform(context, context->buffer);
        buffer_index = 0;
    }
    while (buffer_index < 56) {
        context->buffer[buffer_index++] = 0;
    }
    for (int shift = 7; shift >= 0; shift--) {
        context->buffer[buffer_index++] =
            (unsigned char)((bit_count >> ((unsigned int)shift * 8U)) & 0xffU);
    }
    sha256_transform(context, context->buffer);
    for (size_t index = 0; index < 8; index++) {
        digest[index * 4] = (unsigned char)((context->state[index] >> 24) & 0xffU);
        digest[index * 4 + 1] =
            (unsigned char)((context->state[index] >> 16) & 0xffU);
        digest[index * 4 + 2] =
            (unsigned char)((context->state[index] >> 8) & 0xffU);
        digest[index * 4 + 3] = (unsigned char)(context->state[index] & 0xffU);
    }
}

int c300x_sha256_strings3(
    const char *part1,
    const char *part2,
    const char *part3,
    unsigned char digest[C300X_SHA256_DIGEST_LEN]
)
{
    struct sha256_context context;

    if (digest == NULL) {
        return 0;
    }
    sha256_init(&context);
    if (part1 != NULL) {
        sha256_update(&context, (const unsigned char *)part1, strlen(part1));
    }
    if (part2 != NULL) {
        sha256_update(&context, (const unsigned char *)part2, strlen(part2));
    }
    if (part3 != NULL) {
        sha256_update(&context, (const unsigned char *)part3, strlen(part3));
    }
    sha256_final(&context, digest);
    memset(&context, 0, sizeof(context));
    return 1;
}

static int sha256_digest_hex(
    const unsigned char digest[C300X_SHA256_DIGEST_LEN],
    char *out,
    size_t out_len
)
{
    static const char hex[] = "0123456789abcdef";

    if (out_len < 65) {
        return 0;
    }
    for (size_t index = 0; index < C300X_SHA256_DIGEST_LEN; index++) {
        out[index * 2] = hex[(digest[index] >> 4) & 0x0fU];
        out[index * 2 + 1] = hex[digest[index] & 0x0fU];
    }
    out[64] = '\0';
    return 1;
}

int c300x_sha256_bytes_hex(
    const unsigned char *data,
    size_t len,
    char *out,
    size_t out_len
)
{
    struct sha256_context context;
    unsigned char digest[C300X_SHA256_DIGEST_LEN];

    if (data == NULL || out == NULL) {
        return 0;
    }
    out[0] = '\0';
    sha256_init(&context);
    sha256_update(&context, data, len);
    sha256_final(&context, digest);
    return sha256_digest_hex(digest, out, out_len);
}

int c300x_sha256_file_hex(const char *path, char *out, size_t out_len)
{
    struct sha256_context context;
    unsigned char buffer[4096];
    unsigned char digest[C300X_SHA256_DIGEST_LEN];
    FILE *file;
    size_t read_len;

    if (out_len < 65) {
        return 0;
    }
    out[0] = '\0';
    file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    sha256_init(&context);
    while ((read_len = fread(buffer, 1, sizeof(buffer), file)) > 0) {
        sha256_update(&context, buffer, read_len);
    }
    if (ferror(file)) {
        fclose(file);
        return 0;
    }
    fclose(file);
    sha256_final(&context, digest);
    return sha256_digest_hex(digest, out, out_len);
}
