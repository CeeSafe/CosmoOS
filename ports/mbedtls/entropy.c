/* mbedTLS's strong entropy source on CosmoOS (cosmo_config.h,
 * MBEDTLS_ENTROPY_HARDWARE_ALT; ports/mbedtls/README.md): getentropy(3),
 * getrandom(2) on CosmoOS, which blocks until the kernel's pool is seeded.
 * At most 256 bytes a call. Declared in the library's private
 * entropy_poll.h. Every program linked with this configuration of the
 * library links this file: ssl_client, cosmo-fetch, and the ports that use
 * mbedTLS (ports/curl/, as libcosmo_entropy.a). */

#define _DEFAULT_SOURCE
#include <errno.h>
#include <stddef.h>
#include <sys/random.h>
#include <unistd.h>

#include "mbedtls/entropy.h"

int mbedtls_hardware_poll(void *data, unsigned char *out, size_t len, size_t *olen);
int mbedtls_hardware_poll(void *data, unsigned char *out, size_t len, size_t *olen)
{
    (void)data;
    *olen = 0;
    while (*olen < len) {
        size_t n = len - *olen > 256 ? 256 : len - *olen;
        if (getentropy(out + *olen, n) != 0) {
            if (errno == EINTR)
                continue;
            return MBEDTLS_ERR_ENTROPY_SOURCE_FAILED;
        }
        *olen += n;
    }
    return 0;
}
