// Rev 0.2 / 0.3 integrated board: Pico pin map, the same on both (tools/gen_integrated_sch.py, docs/rev02_integrated.md)
#pragma once

#define PIN_I2C_SDA     0   // ADS1115 at 0x48, 4.7k pull-ups
#define PIN_I2C_SCL     1
#define PIN_SYN_CLK     2   // ADF4351 3-wire bus (bit-banged)
#define PIN_SYN_DATA    3
#define PIN_ADC_RDY     4   // ADS1115 ALERT/RDY, 10k pull-up
#define PIN_SYN_LE      5
#define PIN_SYN_CE      6
#define PIN_SYN_PDBRF   7
#define PIN_SYN_LD      8   // lock detect pin
#define PIN_SYN_MUX     9   // MUXOUT, programmed as digital lock detect too
#define PIN_LCD_SCK     10  // SPI1
#define PIN_LCD_SDA     11
#define PIN_LCD_BL      12
#define PIN_LCD_CS      13
#define PIN_LCD_DC      14
#define PIN_LCD_RST     15
#define PIN_LED_G       16
#define PIN_LED_R       17
#define PIN_BTN         18  // to GND, internal pull-up

#define ADS1115_ADDR    0x48
#define ADC_CH_DET      0   // AD8318 VOUT through 1k / 10n
#define ADC_CH_DETTEMP  1   // AD8318 TEMP
#define ADC_CH_5VA      2   // +5VA / 2 (after FB1, not VBUS)
#define ADC_CH_SPARE    3   // J4 pin 10, TP6

#define SYN_REF_HZ      25000000u
