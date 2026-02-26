/*
 * callbacks.cpp
 *
 *  Created on: Aug 30, 2025
 *      Author: conar
 */

#include "Logger.h"
#include "Comm.h"

extern "C" void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    if (auto L = Logger::instance(); L && huart == L->handle()) {
        L->on_tx_cplt();
    }
    if (auto C = Comm::instance(); C && huart == C->handle()) {
        C->on_tx_cplt();
    }
}



