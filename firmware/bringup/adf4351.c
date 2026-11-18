// ADF4351 driver: 25 MHz reference, PFD 25 MHz, fractional-N, fundamental feedback.
// Loop filter on the board is designed for Icp 2.5 mA (CP code 7 with RSET 5.1k).
#include "adf4351.h"
#include "board.h"
#include "pico/stdlib.h"

#define PFD_HZ      SYN_REF_HZ
#define BS_DIV      200         // band select clock = 25 MHz / 200 = 125 kHz (max 125 kHz)
#define CP_CODE     7           // 2.50 mA with RSET 5.1k

static uint32_t gcd32(uint32_t a, uint32_t b) {
    while (b) { uint32_t t = a % b; a = b; b = t; }
    return a;
}

static void write_reg(uint32_t v) {
    gpio_put(PIN_SYN_LE, 0);
    for (int i = 31; i >= 0; i--) {
        gpio_put(PIN_SYN_DATA, (v >> i) & 1);
        busy_wait_us_32(1);
        gpio_put(PIN_SYN_CLK, 1);
        busy_wait_us_32(1);
        gpio_put(PIN_SYN_CLK, 0);
    }
    busy_wait_us_32(1);
    gpio_put(PIN_SYN_LE, 1);
    busy_wait_us_32(1);
    gpio_put(PIN_SYN_LE, 0);
}

static void out_pin(uint pin, bool v) {
    gpio_init(pin);
    gpio_put(pin, v);
    gpio_set_dir(pin, GPIO_OUT);
}

void adf4351_init(void) {
    out_pin(PIN_SYN_CLK, 0);
    out_pin(PIN_SYN_DATA, 0);
    out_pin(PIN_SYN_LE, 0);
    out_pin(PIN_SYN_CE, 0);
    out_pin(PIN_SYN_PDBRF, 0);
    gpio_init(PIN_SYN_LD);
    gpio_set_dir(PIN_SYN_LD, GPIO_IN);
    gpio_init(PIN_SYN_MUX);
    gpio_set_dir(PIN_SYN_MUX, GPIO_IN);
}

static bool out_b;      // false: RFA (the cell), true: RFB (J5) with RFA off

void adf4351_output_b(bool b) { out_b = b; }

bool adf4351_set(uint64_t f_hz, int power, adf4351_cfg_t *out) {
    if (f_hz < 35000000ull || f_hz > 4400000000ull || power < 0 || power > 3)
        return false;
    uint32_t div = 1, dsel = 0;
    while (f_hz * div < 2200000000ull && div < 64) { div <<= 1; dsel++; }
    uint64_t vco = f_hz * div;
    uint32_t intv = (uint32_t)(vco / PFD_HZ);
    uint32_t rem = (uint32_t)(vco % PFD_HZ);
    uint32_t mod, frac;
    if (rem == 0) {
        mod = 2; frac = 0;
    } else {
        uint32_t g = gcd32(PFD_HZ, rem);
        mod = PFD_HZ / g;
        frac = rem / g;
        if (mod > 4095) {   // nearest step with MOD 4095
            mod = 4095;
            frac = (uint32_t)(((uint64_t)rem * mod + PFD_HZ / 2) / PFD_HZ);
            if (frac >= mod) { frac = 0; intv++; }
        }
        if (mod < 2) mod = 2;
    }
    uint32_t r[6];
    r[0] = (intv << 15) | (frac << 3) | 0;
    r[1] = (1u << 27)               // prescaler 8/9 (INT >= 88 here anyway)
         | (1u << 15)               // phase = 1
         | (mod << 3) | 1;
    r[2] = (0u << 29)               // low noise mode
         | (6u << 26)               // MUXOUT = digital lock detect
         | (1u << 14)               // R counter = 1, no doubler, no /2
         | ((uint32_t)CP_CODE << 9)
         | (0u << 8)                // LDF: fractional-N
         | (0u << 7)                // LDP: 10 ns
         | (1u << 6)                // phase detector polarity: positive (passive filter)
         | 2;
    r[3] = (0u << 22)               // ABP 6 ns (frac-N)
         | (150u << 3) | 3;         // clock divider value (unused, CDM off)
    r[4] = (1u << 23)               // feedback from the VCO
         | (dsel << 20)
         | ((uint32_t)BS_DIV << 12)
         | (1u << 10)               // mute till lock detect
         | (out_b ? (1u << 9) | ((uint32_t)power << 6) : 0)  // aux output RFB -> J5 U.FL (divided, like A)
         | (out_b ? 0 : (1u << 5))  // RF out A -> cell
         | ((uint32_t)power << 3) | 4;
    r[5] = (1u << 22)               // LD pin: digital lock detect
         | (3u << 19) | 5;
    gpio_put(PIN_SYN_CE, 1);
    for (int i = 5; i >= 0; i--)
        write_reg(r[i]);
    gpio_put(PIN_SYN_PDBRF, 1);
    if (out) {
        out->intv = intv; out->frac = frac; out->mod = mod; out->div = div;
        out->f_hz = ((uint64_t)intv * PFD_HZ + (uint64_t)frac * PFD_HZ / mod) / div;
        for (int i = 0; i < 6; i++) out->reg[i] = r[i];
    }
    return true;
}

void adf4351_rf(bool on) { gpio_put(PIN_SYN_PDBRF, on); }

void adf4351_off(void) {
    gpio_put(PIN_SYN_PDBRF, 0);
    gpio_put(PIN_SYN_CE, 0);
}

bool adf4351_locked(void) { return gpio_get(PIN_SYN_LD); }
bool adf4351_mux(void) { return gpio_get(PIN_SYN_MUX); }

bool adf4351_wait_lock(uint32_t timeout_us, uint32_t settle_us) {
    absolute_time_t end = make_timeout_time_us(timeout_us);
    busy_wait_us_32(50);            // LD can still show the previous lock
    while (!adf4351_locked()) {
        if (time_reached(end)) return false;
        tight_loop_contents();
    }
    busy_wait_us_32(settle_us);
    return true;
}
