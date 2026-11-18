cmake_minimum_required(VERSION 3.13)

# Rev 0.2 board bring-up firmware. Build:
#   cmake -S firmware/bringup -B build/bringup -G Ninja -DPICO_SDK_PATH=/path/to/pico-sdk
#   ninja -C build/bringup
# or set PICO_SDK_FETCH_FROM_GIT=ON to let CMake fetch the SDK.
# Pico 2 and Pico 2 W both work: the radio of the W is never started.
set(PICO_BOARD pico2 CACHE STRING "Board type")
set(PICO_PLATFORM rp2350-arm-s CACHE STRING "Platform")

include(pico_sdk_import.cmake)
project(lid_bringup C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

add_executable(lid_bringup main.c adf4351.c ads1115.c st7789.c)
target_compile_options(lid_bringup PRIVATE -Wall -Wextra -Wno-unused-parameter)
target_link_libraries(lid_bringup pico_stdlib pico_unique_id hardware_spi hardware_i2c hardware_pwm hardware_adc)
pico_enable_stdio_usb(lid_bringup 1)
pico_enable_stdio_uart(lid_bringup 0)
target_compile_definitions(lid_bringup PRIVATE
    PICO_STDIO_USB_CONNECT_WAIT_TIMEOUT_MS=0
    USBD_PRODUCT="LID rev0.2 bringup")
pico_add_extra_outputs(lid_bringup)
