#include <assert.h>
#include <string.h>

#include "../src/sha256.h"

static void check(const unsigned char *key, size_t key_len, const char *data, const char *expected)
{
    char out[65];

    assert(c300x_hmac_sha256_hex(key, key_len, (const unsigned char *)data, strlen(data), out, sizeof(out)));
    assert(strcmp(out, expected) == 0);
}

int main(void)
{
    unsigned char key[131];
    char small[64];

    /* RFC 4231 test cases 1, 2, 6 and 7. */
    memset(key, 0x0b, 20);
    check(key, 20, "Hi There",
        "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7");
    check((const unsigned char *)"Jefe", 4, "what do ya want for nothing?",
        "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843");
    memset(key, 0xaa, sizeof(key));
    check(key, sizeof(key), "Test Using Larger Than Block-Size Key - Hash Key First",
        "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54");
    check(key, sizeof(key),
        "This is a test using a larger than block-size key and a larger than block-size data."
        " The key needs to be hashed before being used by the HMAC algorithm.",
        "9b09ffa71b942fcb27635fbcd5b0e944bfdc63644f0713938a7f51535c3a35e2");
    assert(!c300x_hmac_sha256_hex(key, 4, (const unsigned char *)"x", 1, small, sizeof(small)));
    return 0;
}
