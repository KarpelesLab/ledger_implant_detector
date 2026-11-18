// Rev 0.2 board bring-up: checks each block and gives raw sweeps over USB serial.
// Not the detector firmware: no verdict, no stored reference, no clamping beyond the
// ADF4351's own range. Commands are one per line; `help` lists them.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "adf4351.h"
#include "ads1115.h"
#include "board.h"
#include "st7789.h"
#include "hardware/adc.h"
#include "hardware/i2c.h"
#include "pico/bootrom.h"
#include "pico/stdlib.h"
#include "pico/unique_id.h"

#define FW_VERSION "bringup-0.2"

static bool ads_ok, lcd_busy_usb;
static int rf_power;    // 0..3 = -4 .. +5 dBm at the chip; the cell gets ~10 dB less

static void out_pin(uint pin, bool v) {
    gpio_init(pin);
    gpio_put(pin, v);
    gpio_set_dir(pin, GPIO_OUT);
}

static bool button(void) { return !gpio_get(PIN_BTN); }

static float mcu_temp(void) {
    adc_select_input(4);    // RP2350 QFN-60 temperature sensor
    float v = adc_read() * 3.3f / 4096;
    return 27.0f - (v - 0.706f) / 0.001721f;
}

// AD8318 TEMP pin: about 0.57 V at 25 C, 2 mV/C (datasheet typical)
static double det_temp(double v) { return 25.0 + (v - 0.57) / 0.002; }

static void lcd_status(void) {
    char s[40];
    double vb = 0, vd = 0, vt = 0;
    if (ads_ok) {
        ads1115_mean(ADC_CH_VBUS, 1, &vb, 0);
        ads1115_mean(ADC_CH_DET, 2, &vd, 0);
        ads1115_mean(ADC_CH_DETTEMP, 1, &vt, 0);
    }
    lcd_text(8, 8, "LID REV0.2 BRINGUP", 2, C_WHITE, C_BLACK);
    snprintf(s, sizeof s, "ADC   %-10s", ads_ok ? "OK" : "NO ANSWER");
    lcd_text(8, 48, s, 2, ads_ok ? C_GREEN : C_RED, C_BLACK);
    snprintf(s, sizeof s, "VBUS  %.2f V   ", 2 * vb);
    lcd_text(8, 72, s, 2, C_WHITE, C_BLACK);
    snprintf(s, sizeof s, "DET   %.4f V  ", vd);
    lcd_text(8, 96, s, 2, C_WHITE, C_BLACK);
    snprintf(s, sizeof s, "TDET  %.1f C   ", det_temp(vt));
    lcd_text(8, 120, s, 2, C_WHITE, C_BLACK);
    snprintf(s, sizeof s, "TMCU  %.1f C   ", mcu_temp());
    lcd_text(8, 144, s, 2, C_WHITE, C_BLACK);
    snprintf(s, sizeof s, "LOCK  LD %d MUX %d", adf4351_locked(), adf4351_mux());
    lcd_text(8, 168, s, 2, adf4351_locked() ? C_GREEN : C_GREY, C_BLACK);
    lcd_text(8, 192, button() ? "BUTTON PRESSED" : "BUTTON        ", 2, button() ? C_YELLOW : C_GREY, C_BLACK);
    lcd_text(8, 280, lcd_busy_usb ? "USB SWEEP     " : "              ", 2, C_YELLOW, C_BLACK);
}

static void cmd_id(void) {
    char id[2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES + 1];
    pico_get_unique_board_id_string(id, sizeof id);
    printf("id lid-rev0.2 fw=%s serial=%s\n", FW_VERSION, id);
}

static void cmd_status(void) {
    double v[4] = {0}, sd = 0;
    printf("ads1115 %s rdy_pin=%d\n", ads_ok ? "ok" : "no-answer", ads_ok ? ads1115_rdy_seen() : -1);
    if (ads_ok) {
        for (int ch = 0; ch < 4; ch++) ads1115_mean(ch, 8, &v[ch], ch == 0 ? &sd : 0);
        printf("det %.5f V sd %.5f V\n", v[0], sd);
        printf("det_temp %.4f V ~%.1f C\n", v[1], det_temp(v[1]));
        printf("vbus %.3f V\n", 2 * v[2]);
        printf("adc3 %.4f V\n", v[3]);
    }
    printf("mcu_temp %.1f C\n", mcu_temp());
    printf("syn ld=%d mux=%d power=%d\n", adf4351_locked(), adf4351_mux(), rf_power);
    printf("button %d\n", button());
}

static void cmd_i2cscan(void) {
    printf("i2c:");
    for (int a = 0x08; a < 0x78; a++) {
        uint8_t b;
        if (i2c_read_timeout_us(i2c0, a, &b, 1, false, 2000) >= 0) printf(" 0x%02x", a);
    }
    printf("\n");
}

static void cmd_freq(double mhz) {
    adf4351_cfg_t c;
    if (!adf4351_set((uint64_t)(mhz * 1e6 + 0.5), rf_power, &c)) { printf("err range\n"); return; }
    bool ok = adf4351_wait_lock(10000, 0);
    printf("freq %lu Hz int=%lu frac=%lu mod=%lu div=%lu lock=%d\n", (unsigned long)c.f_hz,
           (unsigned long)c.intv, (unsigned long)c.frac, (unsigned long)c.mod, (unsigned long)c.div, ok);
    printf("regs");
    for (int i = 0; i < 6; i++) printf(" R%d=%08lx", i, (unsigned long)c.reg[i]);
    printf("\n");
}

// sweep start stop step(MHz) [avg] [settle_us]: source-off reading first, then one line per point
static void cmd_sweep(double f0, double f1, double df, int avg, int settle) {
    if (!ads_ok) { printf("err adc\n"); return; }
    if (df <= 0 || f1 < f0 || (f1 - f0) / df > 4000) { printf("err args\n"); return; }
    if (avg < 1) avg = 1;
    lcd_busy_usb = true;
    lcd_status();
    gpio_put(PIN_LED_G, 0);
    absolute_time_t t0 = get_absolute_time();
    double bg, bgsd;
    adf4351_off();
    sleep_ms(2);
    ads1115_mean(ADC_CH_DET, avg * 4, &bg, &bgsd);
    printf("# sweep start=%.3f stop=%.3f step=%.3f avg=%d settle_us=%d power=%d\n", f0, f1, df, avg, settle, rf_power);
    printf("bg,%.6f,%.6f\n", bg, bgsd);
    int n = (int)((f1 - f0) / df + 1.5e-6) + 1, unlocked = 0;
    for (int i = 0; i < n; i++) {
        double f = f0 + i * df;
        adf4351_cfg_t c;
        adf4351_set((uint64_t)(f * 1e6 + 0.5), rf_power, &c);
        bool ok = adf4351_wait_lock(5000, settle);
        double v = 0, sd = 0;
        ads1115_mean(ADC_CH_DET, avg, &v, &sd);
        if (!ok) unlocked++;
        printf("%lu,%.6f,%.6f,%d\n", (unsigned long)c.f_hz, v, sd, ok);   // pico printf mangles %f above 1e9
        gpio_put(PIN_LED_R, (i >> 3) & 1);      // blinks while sweeping
    }
    adf4351_off();
    gpio_put(PIN_LED_R, 0);
    gpio_put(PIN_LED_G, 1);
    printf("end points=%d unlocked=%d ms=%lld\n", n, unlocked, absolute_time_diff_us(t0, get_absolute_time()) / 1000);
    lcd_busy_usb = false;
}

static void help(void) {
    printf("commands:\n"
           "  id | status | i2cscan | help\n"
           "  led g|r 0|1      bl <0-100>      lcd test|status|init|rot0|rot180\n"
           "  adc <ch 0-3> [n]                 raw ADS1115 mean and sd\n"
           "  power <0-3>      ADF4351 level: -4/-1/+2/+5 dBm (default 0)\n"
           "  freq <MHz>       CW, stays on      rf 0|1 (PDBRF)      off\n"
           "  out a|b          synth output: a = cell (default), b = J5 U.FL with a off\n"
           "  sweep <start> <stop> <step MHz> [avg=4] [settle_us=300]\n"
           "  bootsel          reboot into the USB bootloader\n");
}

static void handle(char *line) {
    char *argv[8];
    int argc = 0;
    for (char *t = strtok(line, " \t"); t && argc < 8; t = strtok(0, " \t")) argv[argc++] = t;
    if (!argc) return;
    const char *c = argv[0];
#define ARG(i, d) (argc > (i) ? atof(argv[i]) : (d))
    if (!strcmp(c, "help")) help();
    else if (!strcmp(c, "id")) cmd_id();
    else if (!strcmp(c, "status")) cmd_status();
    else if (!strcmp(c, "i2cscan")) cmd_i2cscan();
    else if (!strcmp(c, "led") && argc == 3) {
        gpio_put(argv[1][0] == 'g' ? PIN_LED_G : PIN_LED_R, atoi(argv[2]) != 0);
        printf("ok\n");
    } else if (!strcmp(c, "bl") && argc == 2) { lcd_backlight(atoi(argv[1])); printf("ok\n"); }
    else if (!strcmp(c, "lcd") && argc == 2) {
        if (!strcmp(argv[1], "test")) lcd_test_pattern();
        else if (!strcmp(argv[1], "init")) { lcd_init(); lcd_test_pattern(); }
        else if (!strcmp(argv[1], "rot0") || !strcmp(argv[1], "rot180")) {
            lcd_rotate180(argv[1][3] == '1');
            lcd_fill(0, 0, LCD_W, LCD_H, C_BLACK);
            lcd_status();
        }
        else { lcd_fill(0, 0, LCD_W, LCD_H, C_BLACK); lcd_status(); }
        printf("ok\n");
    } else if (!strcmp(c, "adc") && argc >= 2) {
        double v, sd;
        int ch = atoi(argv[1]) & 3, n = (int)ARG(2, 16);
        if (ads1115_mean(ch, n, &v, &sd)) printf("adc%d %.6f V sd %.6f V n=%d\n", ch, v, sd, n);
        else printf("err adc\n");
    } else if (!strcmp(c, "power") && argc == 2) {
        int p = atoi(argv[1]);
        if (p < 0 || p > 3) printf("err range\n");
        else { rf_power = p; printf("ok power=%d\n", p); }
    } else if (!strcmp(c, "freq") && argc == 2) cmd_freq(atof(argv[1]));
    else if (!strcmp(c, "rf") && argc == 2) { adf4351_rf(atoi(argv[1]) != 0); printf("ok\n"); }
    else if (!strcmp(c, "off")) { adf4351_off(); printf("ok\n"); }
    else if (!strcmp(c, "out") && argc == 2 && (argv[1][0] == 'a' || argv[1][0] == 'b')) {
        adf4351_output_b(argv[1][0] == 'b'); printf("ok out=%c\n", argv[1][0]);
    }
    else if (!strcmp(c, "sweep") && argc >= 4)
        cmd_sweep(atof(argv[1]), atof(argv[2]), atof(argv[3]), (int)ARG(4, 4), (int)ARG(5, 300));
    else if (!strcmp(c, "bootsel")) { printf("ok\n"); stdio_flush(); sleep_ms(100); reset_usb_boot(0, 0); }
    else printf("err unknown command (try help)\n");
}

int main(void) {
    stdio_init_all();
    out_pin(PIN_LED_G, 0);
    out_pin(PIN_LED_R, 0);
    gpio_init(PIN_BTN);
    gpio_set_dir(PIN_BTN, GPIO_IN);
    gpio_pull_up(PIN_BTN);
    adc_init();
    adc_set_temp_sensor_enabled(true);
    adf4351_init();

    // power-on: both LEDs, then the LCD test pattern for 2 s
    gpio_put(PIN_LED_G, 1);
    gpio_put(PIN_LED_R, 1);
    lcd_init();
    lcd_test_pattern();
    ads_ok = ads1115_init();
    sleep_ms(2000);
    gpio_put(PIN_LED_R, 0);
    lcd_fill(0, 0, LCD_W, LCD_H, C_BLACK);

    char line[96];
    int len = 0;
    absolute_time_t next_ui = get_absolute_time();
    bool btn_prev = false;
    for (;;) {
        int ch = getchar_timeout_us(1000);
        if (ch >= 0) {
            if (ch == '\r' || ch == '\n') {
                line[len] = 0;
                if (len) handle(line);
                len = 0;
            } else if (len < (int)sizeof line - 1) {
                line[len++] = (char)ch;
            }
        }
        if (time_reached(next_ui)) {
            next_ui = make_timeout_time_ms(250);
            bool b = button();
            gpio_put(PIN_LED_R, b);            // button test: red follows the button
            if (b && !btn_prev) {              // press: set the screen up again (for a hot-plugged LCD)
                lcd_init();
                lcd_fill(0, 0, LCD_W, LCD_H, C_BLACK);
            }
            btn_prev = b;
            lcd_status();
        }
    }
}
