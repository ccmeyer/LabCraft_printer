#include "nvm_codec.h"

#include <stddef.h>
#include <string.h>

static uint32_t crc32_update(uint32_t crc, const void *data, size_t len) {
    const uint8_t *p = (const uint8_t*)data;
    crc = ~crc;
    for (size_t i = 0; i < len; i++) {
        crc ^= p[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc >> 1) ^ (0xEDB88320u & -(int)(crc & 1u));
        }
    }
    return ~crc;
}

uint32_t nvm_crc32_block(const void *data, size_t len) {
    return crc32_update(0u, data, len);
}

void nvm_codec_finalize(nvm_config_t *cfg) {
    if (!cfg) {
        return;
    }
    cfg->crc = nvm_crc32_block(cfg, offsetof(nvm_config_t, crc));
}

void nvm_codec_defaults(nvm_config_t *cfg) {
    if (!cfg) {
        return;
    }
    memset(cfg, 0, sizeof(*cfg));
    cfg->magic = NVM_MAGIC;
    cfg->version = NVM_VERSION;
    cfg->baud = 115200u;
    cfg->gain = 1.0f;
    cfg->flags = 0u;
    nvm_codec_finalize(cfg);
}

bool nvm_codec_is_valid(const nvm_config_t *cfg) {
    if (!cfg) {
        return false;
    }
    if (cfg->magic != NVM_MAGIC) {
        return false;
    }
    if (cfg->version != NVM_VERSION) {
        return false;
    }
    return nvm_crc32_block(cfg, offsetof(nvm_config_t, crc)) == cfg->crc;
}
