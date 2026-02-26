/*
 * comm_usb_bridge.h
 *
 *  Created on: Jan 29, 2026
 *      Author: conar
 */

#ifndef INC_COMM_USB_BRIDGE_H_
#define INC_COMM_USB_BRIDGE_H_

// comm_usb_bridge.h
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void LC_Comm_OnUsbRx(const uint8_t* data, uint32_t len);
void LC_Comm_OnUsbTxCpltFromISR(void);

#ifdef __cplusplus
}
#endif



#endif /* INC_COMM_USB_BRIDGE_H_ */
