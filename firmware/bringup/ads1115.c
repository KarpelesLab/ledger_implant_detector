// ADS1115: single-ended, +-4.096 V (125 uV/LSB = 0.005 dB at the AD8318's 25 mV/dB), 860 SPS.
// RDY is enabled (thresholds 0x8000 / 0x0000) but polling the OS bit is what ends a conversion;
// the pin is only checked so bring-up can tell whether it works.
#include "ads1115.h"
#include "board.h"
#include <math.h>
#include "hardware/i2c.h"
#include "pico/stdlib.h"

#define I2C i2c0
static bool rdy_seen;

static bool wr16(uint8_t reg, uint16_t v) {
    uint8_t b[3] = {reg, v >> 8, v & 0xff};
    return i2c_write_timeout_us(I2C, ADS1115_ADDR, b, 3, false, 5000) == 3;
}

static bool rd16(uint8_t reg, uint16_t *v) {
    uint8_t b[2];
    if (i2c_write_timeout_us(I2C, ADS1115_ADDR, &reg, 1, true, 5000) != 1) return false;
    if (i2c_read_timeout_us(I2C, ADS1115_ADDR, b, 2, false, 5000) != 2) return false;
    *v = (uint16_t)(b[0] << 8 | b[1]);
    return true;
}

bool ads1115_init(void) {
    i2c_init(I2C, 400000);
    gpio_set_function(PIN_I2C_SDA, GPIO_FUNC_I2C);
    gpio_set_function(PIN_I2C_SCL, GPIO_FUNC_I2C);
    gpio_init(PIN_ADC_RDY);
    gpio_set_dir(PIN_ADC_RDY, GPIO_IN);
    gpio_pull_up(PIN_ADC_RDY);      // the board has 10k too
    return wr16(0x02, 0x0000) && wr16(0x03, 0x8000);   // RDY mode
}

bool ads1115_read(int ch, int16_t *raw) {
    uint16_t cfg = (1u << 15)               // start
                 | ((4u + (ch & 3)) << 12)  // AINx vs GND
                 | (1u << 9)                // PGA +-4.096 V
                 | (1u << 8)                // single shot
                 | (7u << 5)                // 860 SPS
                 | 0;                       // comparator: assert after one conversion (RDY)
    if (!wr16(0x01, cfg)) return false;
    absolute_time_t end = make_timeout_time_ms(10);
    busy_wait_us_32(1000);
    uint16_t v;
    bool rdy = false;
    for (;;) {
        if (!gpio_get(PIN_ADC_RDY)) rdy = true;
        if (!rd16(0x01, &v)) return false;
        if (v & 0x8000) break;
        if (time_reached(end)) return false;
        busy_wait_us_32(50);
    }
    if (!gpio_get(PIN_ADC_RDY)) rdy = true;
    rdy_seen = rdy;
    if (!rd16(0x00, &v)) return false;
    *raw = (int16_t)v;
    return true;
}

bool ads1115_mean(int ch, int n, double *volts, double *sd_volts) {
    double s = 0, s2 = 0;
    if (n < 1) n = 1;
    for (int i = 0; i < n; i++) {
        int16_t r;
        if (!ads1115_read(ch, &r)) return false;
        s += r;
        s2 += (double)r * r;
    }
    double m = s / n;
    if (volts) *volts = m * ADS1115_LSB_V;
    if (sd_volts) *sd_volts = n > 1 ? sqrt(fmax(0, (s2 - n * m * m) / (n - 1))) * ADS1115_LSB_V : 0;
    return true;
}

bool ads1115_rdy_seen(void) { return rdy_seen; }
