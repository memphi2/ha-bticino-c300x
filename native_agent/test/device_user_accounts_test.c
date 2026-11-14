#include "../src/device_user.c"

static int ensure(const char *content, const char *label, char *out, size_t out_len)
{
    struct file_buffer accounts = {0};
    char error[64] = "";
    int changed = 0;
    int ok;

    accounts.len = strlen(content);
    accounts.data = malloc(accounts.len + 1);
    memcpy(accounts.data, content, accounts.len + 1);
    accounts.mode = 0644;
    accounts.exists = 1;
    ok = ensure_account_line(&accounts, label, &changed, error, sizeof(error));
    if (!ok) {
        snprintf(out, out_len, "ERROR:%s", error);
    } else {
        snprintf(out, out_len, "%s", accounts.data);
    }
    free(accounts.data);
    return ok;
}

int main(void)
{
    char out[512];

    /* The last line has no trailing newline: the new line needs one more byte. */
    if (!ensure("Alice|alice\nBob|bob", "Home Assistant", out, sizeof(out))) {
        printf("unterminated:%s\n", out);
        return 1;
    }
    printf("unterminated:%s", out);
    if (!ensure("Alice|alice\nBob|bob\n", "Home Assistant", out, sizeof(out))) {
        printf("terminated:%s\n", out);
        return 1;
    }
    printf("terminated:%s", out);
    if (!ensure("", "Home Assistant", out, sizeof(out))) {
        printf("empty:%s\n", out);
        return 1;
    }
    printf("empty:%s", out);
    return 0;
}
