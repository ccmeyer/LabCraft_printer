/*
 * nvm.c
 *
 *  Created on: Aug 30, 2025
 *      Author: conar
 */




// nvm.c
#include "nvm.h"
#include "stm32f4xx_hal.h"
#include <string.h>

static uint32_t crc32_update(uint32_t crc, const void *data, size_t len) {
    // simple, small CRC32 (poly 0xEDB88320); good enough for config
    const uint8_t *p = (const uint8_t*)data;
    crc = ~crc;
    for (size_t i=0;i<len;i++) {
        crc ^= p[i];
        for (int b=0;b<8;b++)
            crc = (crc>>1) ^ (0xEDB88320u & -(int)(crc & 1));
    }
    return ~crc;
}
static uint32_t crc32_block(const void *data, size_t len) {
    return crc32_update(0, data, len);
}

bool nvm_load(nvm_config_t *out) {
    const nvm_config_t *rom = (const nvm_config_t*)NVM_ADDR;
    // quick blank check
    if (*(const uint32_t*)NVM_ADDR == 0xFFFFFFFFu) return false;
    // copy & verify
    *out = *rom;
    if (out->magic != NVM_MAGIC) return false;
    if (out->version != NVM_VERSION) return false;
    uint32_t calc = crc32_block(out, offsetof(nvm_config_t, crc));
    return (calc == out->crc);
}

void nvm_defaults(nvm_config_t *cfg) {
    memset(cfg, 0, sizeof(*cfg));
    cfg->magic   = NVM_MAGIC;
    cfg->version = NVM_VERSION;
    cfg->baud    = 115200;
    cfg->gain    = 1.0f;
    cfg->flags   = 0;
    cfg->crc     = crc32_block(cfg, offsetof(nvm_config_t, crc));
}

bool nvm_save(const nvm_config_t *cfg_in) {
    nvm_config_t tmp = *cfg_in;
    tmp.crc = crc32_block(&tmp, offsetof(nvm_config_t, crc));

    HAL_FLASH_Unlock();

    // Erase sector 7
    FLASH_EraseInitTypeDef ei = {0};
    uint32_t err = 0;
    ei.TypeErase    = FLASH_TYPEERASE_SECTORS;
    ei.VoltageRange = FLASH_VOLTAGE_RANGE_3;      // 2.7–3.6 V
    ei.Sector       = FLASH_SECTOR_7;
    ei.NbSectors    = 1;
    if (HAL_FLASHEx_Erase(&ei, &err) != HAL_OK) { HAL_FLASH_Lock(); return false; }

    // Program the struct as 32-bit words
    const uint32_t *w = (const uint32_t*)&tmp;
    size_t words = (sizeof(tmp) + 3)/4;
    uint32_t addr = NVM_ADDR;
    for (size_t i=0; i<words; i++, addr+=4) {
        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, addr, w[i]) != HAL_OK) {
            HAL_FLASH_Lock();
            return false;
        }
    }

    HAL_FLASH_Lock();
    // verify
    nvm_config_t check;
    return nvm_load(&check);
}
