/*
 * nvm.c
 *
 *  Created on: Aug 30, 2025
 *      Author: conar
 */




// nvm.c
#include "nvm.h"
#include "nvm_codec.h"
#include "stm32f4xx_hal.h"

bool nvm_load(nvm_config_t *out) {
    const nvm_config_t *rom = (const nvm_config_t*)NVM_ADDR;
    // quick blank check
    if (*(const uint32_t*)NVM_ADDR == 0xFFFFFFFFu) return false;
    // copy & verify
    *out = *rom;
    return nvm_codec_is_valid(out);
}

void nvm_defaults(nvm_config_t *cfg) {
    nvm_codec_defaults(cfg);
}

bool nvm_save(const nvm_config_t *cfg_in) {
    nvm_config_t tmp = *cfg_in;
    nvm_codec_finalize(&tmp);

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
