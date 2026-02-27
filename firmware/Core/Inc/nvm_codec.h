#ifndef INC_NVM_CODEC_H_
#define INC_NVM_CODEC_H_

#include "nvm.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

uint32_t nvm_crc32_block(const void *data, size_t len);
void nvm_codec_finalize(nvm_config_t *cfg);
void nvm_codec_defaults(nvm_config_t *cfg);
bool nvm_codec_is_valid(const nvm_config_t *cfg);

#ifdef __cplusplus
}
#endif

#endif /* INC_NVM_CODEC_H_ */
