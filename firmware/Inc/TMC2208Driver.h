/*
 * TMC2208Driver.h
 *
 *  Created on: Jun 28, 2025
 *      Author: conar
 */

#ifndef INC_TMC2208DRIVER_H_
#define INC_TMC2208DRIVER_H_


#include "stm32f4xx_hal.h"
#include "TMC2208_bitfields.h"
#include <cstdint>

/**
 * Simple driver for TMC2208 in UART mode.
 * Internally tracks GCONF and CHOPCONF register values,
 * lets you modify bitfields, and writes them over HAL_UART6.
 */
class TMC2208Driver {
public:
  /**
   * @param huart     &huart6
   */
  TMC2208Driver(UART_HandleTypeDef* huart);

  static TMC2208Driver* instance();

  void write(uint8_t addr, uint32_t regVal);

  void writeGCONF();
  void writeCHOPCONF();
  void writePWMCONF();
  void writeTPWMTHRS();

  void push();

  void I_scale_analog(bool B);
  void internal_Rsense(bool B);
  void en_spreadCycle(bool B);
  void shaft(bool B);
  void index_otpw(bool B);
  void index_step(bool B);
  void pdn_disable(bool B);
  void mstep_reg_select(bool B);
  void multistep_filt(bool B);

  void toff	( uint8_t  B );
  void hstrt	( uint8_t  B );
  void hend	( uint8_t  B );
  void tbl	( uint8_t  B );
  void vsense	( bool     B );
  void mres	( uint8_t  B );
  void intpol	( bool     B );
  void dedge	( bool     B );
  void diss2g	( bool     B );
  void diss2vs( bool     B );

  void pwm_ofs		( uint8_t B );
  void pwm_grad		( uint8_t B );
  void pwm_freq		( uint8_t B );
  void pwm_autoscale	( bool 	  B );
  void pwm_autograd	( bool    B );
  void freewheel		( uint8_t B );
  void pwm_reg		( uint8_t B );
  void pwm_lim		( uint8_t B );

  void tpwmthrs     ( uint16_t B );

private:
  static TMC2208Driver* _instance;
//  void writeRegister(uint8_t reg, uint32_t val);
  uint8_t calcCRC(uint8_t datagram[], uint8_t len);

  UART_HandleTypeDef* _huart;

  TMC2208_n::GCONF_t            GCONF_register;
  TMC2208_n::CHOPCONF_t         CHOPCONF_register;
  TMC2208_n::PWMCONF_t          PWMCONF_register;
  TMC2208_n::TPWMTHRS_t			TPWMTHRS_register;

  static constexpr uint8_t TMC2208_SYNC       = 0x05;
  static constexpr uint8_t WRITE_FLAG = 0x80;
  static constexpr uint8_t TMC2208_SLAVE    = 0x00;

  static constexpr uint32_t DEFAULT_GCONF = 0x00000101;
  static constexpr uint32_t DEFAULT_CHOPCONF = 0x10000053;
  static constexpr uint32_t DEFAULT_PWMCONF = 0xC10D0024;

};

#endif /* INC_TMC2208DRIVER_H_ */
