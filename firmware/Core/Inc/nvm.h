/*
 * nwm.h
 *
 *  Created on: Aug 30, 2025
 *      Author: conar
 */

#ifndef INC_NWM_H_
#define INC_NWM_H_

// nvm.h
#include <stdint.h>
#include <stdbool.h>

#define NVM_ADDR        0x08060000u  // start of sector 7 on 512KB F446
#define NVM_MAGIC       0x4C434647u  // "LCFG"
#define NVM_VERSION     1

#if defined(_MSC_VER)
#pragma pack(push, 1)
#endif

typedef struct
#if defined(__GNUC__)
__attribute__((packed))
#endif
{
    uint32_t magic;      // "LCFG"
    uint32_t version;    // structure version
    // ---- your settings go here ----
    uint32_t baud;       // example
    float    gain;       // example
    uint32_t flags;      // example
    // --------------------------------
    uint32_t crc;        // CRC32 over [magic..flags]
} nvm_config_t;

#if defined(_MSC_VER)
#pragma pack(pop)
#endif

bool nvm_load(nvm_config_t *out);          // returns true if valid
void nvm_defaults(nvm_config_t *cfg);      // fill defaults
bool nvm_save(const nvm_config_t *cfg);    // erase sector & program



#endif /* INC_NWM_H_ */
