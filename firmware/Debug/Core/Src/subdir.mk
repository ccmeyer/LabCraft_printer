################################################################################
# Automatically-generated file. Do not edit!
# Toolchain: GNU Tools for STM32 (13.3.rel1)
################################################################################

# Add inputs and outputs from these tool invocations to the build variables 
CPP_SRCS += \
../Core/Src/Comm.cpp \
../Core/Src/Flash.cpp \
../Core/Src/Gantry.cpp \
../Core/Src/Gripper.cpp \
../Core/Src/LEDController.cpp \
../Core/Src/LEDStrip.cpp \
../Core/Src/Logger.cpp \
../Core/Src/Orchestrator.cpp \
../Core/Src/PressureRegulator.cpp \
../Core/Src/PressureSensor.cpp \
../Core/Src/Printer.cpp \
../Core/Src/Stepper.cpp \
../Core/Src/TMC2208Driver.cpp \
../Core/Src/callbacks.cpp 

C_SRCS += \
../Core/Src/Heartbeat.c \
../Core/Src/freertos.c \
../Core/Src/main.c \
../Core/Src/nvm.c \
../Core/Src/stm32f4xx_hal_msp.c \
../Core/Src/stm32f4xx_hal_timebase_tim.c \
../Core/Src/stm32f4xx_it.c \
../Core/Src/syscalls.c \
../Core/Src/sysmem.c \
../Core/Src/system_stm32f4xx.c 

C_DEPS += \
./Core/Src/Heartbeat.d \
./Core/Src/freertos.d \
./Core/Src/main.d \
./Core/Src/nvm.d \
./Core/Src/stm32f4xx_hal_msp.d \
./Core/Src/stm32f4xx_hal_timebase_tim.d \
./Core/Src/stm32f4xx_it.d \
./Core/Src/syscalls.d \
./Core/Src/sysmem.d \
./Core/Src/system_stm32f4xx.d 

OBJS += \
./Core/Src/Comm.o \
./Core/Src/Flash.o \
./Core/Src/Gantry.o \
./Core/Src/Gripper.o \
./Core/Src/Heartbeat.o \
./Core/Src/LEDController.o \
./Core/Src/LEDStrip.o \
./Core/Src/Logger.o \
./Core/Src/Orchestrator.o \
./Core/Src/PressureRegulator.o \
./Core/Src/PressureSensor.o \
./Core/Src/Printer.o \
./Core/Src/Stepper.o \
./Core/Src/TMC2208Driver.o \
./Core/Src/callbacks.o \
./Core/Src/freertos.o \
./Core/Src/main.o \
./Core/Src/nvm.o \
./Core/Src/stm32f4xx_hal_msp.o \
./Core/Src/stm32f4xx_hal_timebase_tim.o \
./Core/Src/stm32f4xx_it.o \
./Core/Src/syscalls.o \
./Core/Src/sysmem.o \
./Core/Src/system_stm32f4xx.o 

CPP_DEPS += \
./Core/Src/Comm.d \
./Core/Src/Flash.d \
./Core/Src/Gantry.d \
./Core/Src/Gripper.d \
./Core/Src/LEDController.d \
./Core/Src/LEDStrip.d \
./Core/Src/Logger.d \
./Core/Src/Orchestrator.d \
./Core/Src/PressureRegulator.d \
./Core/Src/PressureSensor.d \
./Core/Src/Printer.d \
./Core/Src/Stepper.d \
./Core/Src/TMC2208Driver.d \
./Core/Src/callbacks.d 


# Each subdirectory must supply rules for building sources it contributes
Core/Src/%.o Core/Src/%.su Core/Src/%.cyclo: ../Core/Src/%.cpp Core/Src/subdir.mk
	arm-none-eabi-g++ "$<" -mcpu=cortex-m4 -std=gnu++14 -g3 -DDEBUG -DUSE_HAL_DRIVER -DSTM32F446xx -c -I../Core/Inc -I../Drivers/STM32F4xx_HAL_Driver/Inc -I../Drivers/STM32F4xx_HAL_Driver/Inc/Legacy -I../Drivers/CMSIS/Device/ST/STM32F4xx/Include -I../Drivers/CMSIS/Include -I../Middlewares/Third_Party/FreeRTOS/Source/include -I../Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS -I../Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F -O0 -ffunction-sections -fdata-sections -fno-exceptions -fno-rtti -fno-use-cxa-atexit -Wall -fstack-usage -fcyclomatic-complexity -MMD -MP -MF"$(@:%.o=%.d)" -MT"$@" --specs=nano.specs -mfpu=fpv4-sp-d16 -mfloat-abi=hard -mthumb -o "$@"
Core/Src/%.o Core/Src/%.su Core/Src/%.cyclo: ../Core/Src/%.c Core/Src/subdir.mk
	arm-none-eabi-gcc "$<" -mcpu=cortex-m4 -std=gnu11 -g3 -DDEBUG -DUSE_HAL_DRIVER -DSTM32F446xx -c -I../Core/Inc -I../Drivers/STM32F4xx_HAL_Driver/Inc -I../Drivers/STM32F4xx_HAL_Driver/Inc/Legacy -I../Drivers/CMSIS/Device/ST/STM32F4xx/Include -I../Drivers/CMSIS/Include -I../Middlewares/Third_Party/FreeRTOS/Source/include -I../Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS -I../Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F -O0 -ffunction-sections -fdata-sections -Wall -fstack-usage -fcyclomatic-complexity -MMD -MP -MF"$(@:%.o=%.d)" -MT"$@" --specs=nano.specs -mfpu=fpv4-sp-d16 -mfloat-abi=hard -mthumb -o "$@"

clean: clean-Core-2f-Src

clean-Core-2f-Src:
	-$(RM) ./Core/Src/Comm.cyclo ./Core/Src/Comm.d ./Core/Src/Comm.o ./Core/Src/Comm.su ./Core/Src/Flash.cyclo ./Core/Src/Flash.d ./Core/Src/Flash.o ./Core/Src/Flash.su ./Core/Src/Gantry.cyclo ./Core/Src/Gantry.d ./Core/Src/Gantry.o ./Core/Src/Gantry.su ./Core/Src/Gripper.cyclo ./Core/Src/Gripper.d ./Core/Src/Gripper.o ./Core/Src/Gripper.su ./Core/Src/Heartbeat.cyclo ./Core/Src/Heartbeat.d ./Core/Src/Heartbeat.o ./Core/Src/Heartbeat.su ./Core/Src/LEDController.cyclo ./Core/Src/LEDController.d ./Core/Src/LEDController.o ./Core/Src/LEDController.su ./Core/Src/LEDStrip.cyclo ./Core/Src/LEDStrip.d ./Core/Src/LEDStrip.o ./Core/Src/LEDStrip.su ./Core/Src/Logger.cyclo ./Core/Src/Logger.d ./Core/Src/Logger.o ./Core/Src/Logger.su ./Core/Src/Orchestrator.cyclo ./Core/Src/Orchestrator.d ./Core/Src/Orchestrator.o ./Core/Src/Orchestrator.su ./Core/Src/PressureRegulator.cyclo ./Core/Src/PressureRegulator.d ./Core/Src/PressureRegulator.o ./Core/Src/PressureRegulator.su ./Core/Src/PressureSensor.cyclo ./Core/Src/PressureSensor.d ./Core/Src/PressureSensor.o ./Core/Src/PressureSensor.su ./Core/Src/Printer.cyclo ./Core/Src/Printer.d ./Core/Src/Printer.o ./Core/Src/Printer.su ./Core/Src/Stepper.cyclo ./Core/Src/Stepper.d ./Core/Src/Stepper.o ./Core/Src/Stepper.su ./Core/Src/TMC2208Driver.cyclo ./Core/Src/TMC2208Driver.d ./Core/Src/TMC2208Driver.o ./Core/Src/TMC2208Driver.su ./Core/Src/callbacks.cyclo ./Core/Src/callbacks.d ./Core/Src/callbacks.o ./Core/Src/callbacks.su ./Core/Src/freertos.cyclo ./Core/Src/freertos.d ./Core/Src/freertos.o ./Core/Src/freertos.su ./Core/Src/main.cyclo ./Core/Src/main.d ./Core/Src/main.o ./Core/Src/main.su ./Core/Src/nvm.cyclo ./Core/Src/nvm.d ./Core/Src/nvm.o ./Core/Src/nvm.su ./Core/Src/stm32f4xx_hal_msp.cyclo ./Core/Src/stm32f4xx_hal_msp.d ./Core/Src/stm32f4xx_hal_msp.o ./Core/Src/stm32f4xx_hal_msp.su ./Core/Src/stm32f4xx_hal_timebase_tim.cyclo ./Core/Src/stm32f4xx_hal_timebase_tim.d ./Core/Src/stm32f4xx_hal_timebase_tim.o ./Core/Src/stm32f4xx_hal_timebase_tim.su ./Core/Src/stm32f4xx_it.cyclo ./Core/Src/stm32f4xx_it.d ./Core/Src/stm32f4xx_it.o ./Core/Src/stm32f4xx_it.su ./Core/Src/syscalls.cyclo ./Core/Src/syscalls.d ./Core/Src/syscalls.o ./Core/Src/syscalls.su ./Core/Src/sysmem.cyclo ./Core/Src/sysmem.d ./Core/Src/sysmem.o ./Core/Src/sysmem.su ./Core/Src/system_stm32f4xx.cyclo ./Core/Src/system_stm32f4xx.d ./Core/Src/system_stm32f4xx.o ./Core/Src/system_stm32f4xx.su

.PHONY: clean-Core-2f-Src

