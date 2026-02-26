/*
 * TMC2208Driver.cpp
 *
 *  Created on: Jun 28, 2025
 *      Author: conar
 */


#include "TMC2208Driver.h"
#include "TMC2208_bitfields.h"

#include "cmsis_os.h"  // for osDelay or you can use HAL_Delay


#define SET_GCONF_REG(SETTING) GCONF_register.SETTING = B;

void TMC2208Driver::I_scale_analog(bool B)		{ SET_GCONF_REG(i_scale_analog);	}
void TMC2208Driver::internal_Rsense(bool B)	{ SET_GCONF_REG(internal_rsense);	}
void TMC2208Driver::en_spreadCycle(bool B)		{ SET_GCONF_REG(en_spreadcycle);	}
void TMC2208Driver::shaft(bool B) 				{ SET_GCONF_REG(shaft);			}
void TMC2208Driver::index_otpw(bool B)			{ SET_GCONF_REG(index_otpw);		}
void TMC2208Driver::index_step(bool B)			{ SET_GCONF_REG(index_step);		}
void TMC2208Driver::pdn_disable(bool B)		{ SET_GCONF_REG(pdn_disable);		}
void TMC2208Driver::mstep_reg_select(bool B)	{ SET_GCONF_REG(mstep_reg_select);}
void TMC2208Driver::multistep_filt(bool B)		{ SET_GCONF_REG(multistep_filt);	}


#define SET_CHOP_REG(SETTING) CHOPCONF_register.SETTING = B;

void TMC2208Driver::toff	( uint8_t  B )	{ SET_CHOP_REG(toff); 	}
void TMC2208Driver::hstrt	( uint8_t  B )	{ SET_CHOP_REG(hstrt); 	}
void TMC2208Driver::hend	( uint8_t  B )	{ SET_CHOP_REG(hend); 	}
void TMC2208Driver::tbl	( uint8_t  B )	{ SET_CHOP_REG(tbl); 	}
void TMC2208Driver::vsense	( bool     B )	{ SET_CHOP_REG(vsense); 	}
void TMC2208Driver::mres	( uint8_t  B )	{ SET_CHOP_REG(mres); 	}
void TMC2208Driver::intpol	( bool     B )	{ SET_CHOP_REG(intpol); 	}
void TMC2208Driver::dedge	( bool     B )	{ SET_CHOP_REG(dedge); 	}
void TMC2208Driver::diss2g	( bool     B )	{ SET_CHOP_REG(diss2g); 	}
void TMC2208Driver::diss2vs( bool     B )	{ SET_CHOP_REG(diss2vs); }

#define SET_PWM_REG(SETTING) PWMCONF_register.SETTING = B;

void TMC2208Driver::pwm_ofs		( uint8_t B ) { SET_PWM_REG(pwm_ofs); }
void TMC2208Driver::pwm_grad		( uint8_t B ) { SET_PWM_REG(pwm_grad); }
void TMC2208Driver::pwm_freq		( uint8_t B ) { SET_PWM_REG(pwm_freq); }
void TMC2208Driver::pwm_autoscale	( bool 	  B ) { SET_PWM_REG(pwm_autoscale); }
void TMC2208Driver::pwm_autograd	( bool    B ) { SET_PWM_REG(pwm_autograd); }
void TMC2208Driver::freewheel		( uint8_t B ) { SET_PWM_REG(freewheel); }
void TMC2208Driver::pwm_reg		( uint8_t B ) { SET_PWM_REG(pwm_reg); }
void TMC2208Driver::pwm_lim		( uint8_t B ) { SET_PWM_REG(pwm_lim); }

#define SET_TPWM_REG(SETTING) TPWMTHRS_register.SETTING = B;
void TMC2208Driver::tpwmthrs     ( uint16_t B ) { SET_TPWM_REG(tpwmthrs); }

// singleton init
TMC2208Driver* TMC2208Driver::_instance = nullptr;

TMC2208Driver::TMC2208Driver(UART_HandleTypeDef* huart)
  : _huart(huart)
{
	_instance = this;
  // defaults from TMC2208 datasheet / TMCStepper library
//  GCONF_register    = TMC2208_n::GCONF_t; // i_scale_analog + multistep_filt
  GCONF_register.sr = DEFAULT_GCONF;

//  CHOPCONF_register    = TMC2208_n::CHOPCONF_t;
  CHOPCONF_register.sr = DEFAULT_CHOPCONF;

//  PWMCONF_register    = TMC2208_n::PWMCONF_t;
  PWMCONF_register.sr = DEFAULT_PWMCONF;
}

TMC2208Driver* TMC2208Driver::instance() {
  return _instance;
}

uint8_t TMC2208Driver::calcCRC(uint8_t datagram[], uint8_t len) {
	uint8_t crc = 0;
	for (uint8_t i = 0; i < len; i++) {
		uint8_t currentByte = datagram[i];
		for (uint8_t j = 0; j < 8; j++) {
			if ((crc >> 7) ^ (currentByte & 0x01)) {
				crc = (crc << 1) ^ 0x07;
			} else {
				crc = (crc << 1);
			}
			crc &= 0xff;
			currentByte = currentByte >> 1;
		}
	}
	return crc;
}

void TMC2208Driver::write(uint8_t addr, uint32_t regVal) {
	  uint8_t pkt[8];
	  pkt[0] = TMC2208_SYNC;             // sync + write
	  pkt[1] = TMC2208_SLAVE;            // always 0
	  pkt[2] = (addr & 0x7F) | WRITE_FLAG; // reg addr + write‐flag
	  // payload, MSB first:
	  pkt[3] = (regVal >> 24) & 0xFF;
	  pkt[4] = (regVal >> 16) & 0xFF;
	  pkt[5] = (regVal >>  8) & 0xFF;
	  pkt[6] = (regVal >>  0) & 0xFF;
	  // CRC covers bytes 0..6
	  pkt[7] = calcCRC(pkt, 7);

	  HAL_UART_Transmit(_huart, pkt, sizeof(pkt), HAL_MAX_DELAY);
}

void TMC2208Driver::writeGCONF() {
	write(TMC2208_n::GCONF_t::address, GCONF_register.sr);
}

void TMC2208Driver::writeCHOPCONF() {
	write(TMC2208_n::CHOPCONF_t::address, CHOPCONF_register.sr);
}

void TMC2208Driver::writePWMCONF() {
	write(TMC2208_n::PWMCONF_t::address, PWMCONF_register.sr);
}

void TMC2208Driver::writeTPWMTHRS() {
	write(TMC2208_n::TPWMTHRS_t::address, TPWMTHRS_register.sr);
}

void TMC2208Driver::push() {
	writeGCONF();
	writeCHOPCONF();
	writePWMCONF();
	writeTPWMTHRS();
}

extern "C" {

void MX_TMC2208_Init(UART_HandleTypeDef* huart) {
	static TMC2208Driver driver(huart);

	driver.I_scale_analog(true);
	driver.internal_Rsense(false);
	driver.en_spreadCycle(false);
	driver.multistep_filt(true);
	driver.pdn_disable(true);
	driver.mstep_reg_select(true);

	driver.mres(2);
	driver.dedge(true);

	driver.tpwmthrs(0);

	driver.push();
}

}

