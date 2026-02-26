/*
 * BoardConfig.h
 *
 *  Created on: Jan 22, 2026
 *      Author: conar
 */

#ifndef INC_BOARDCONFIG_H_
#define INC_BOARDCONFIG_H_


#if defined(LC_BOARD_LEGACY)

  #define LC_PRESSURE_PORTS   1
  #define LC_HAS_TCA9548A     0
  #define LC_HAS_IMAGING      0
  #define LC_HAS_LED_STRIP    0
  #define LC_COMM_USE_USB_CDC 0


#else // current machine

  #define LC_PRESSURE_PORTS   2
  #define LC_HAS_TCA9548A     1
  #define LC_HAS_IMAGING      1
  #define LC_HAS_LED_STRIP    1
  #define LC_COMM_USE_USB_CDC 0

#endif



#endif /* INC_BOARDCONFIG_H_ */
