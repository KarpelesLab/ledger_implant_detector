#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint64_t f_hz;      // frequency actually programmed
    uint32_t intv, frac, mod, div;
    uint32_t reg[6];
} adf4351_cfg_t;

void adf4351_init(void);
// power: 0..3 = -4, -1, +2, +5 dBm at the chip. Returns false if out of range (35 MHz - 4.4 GHz)
bool adf4351_set(uint64_t f_hz, int power, adf4351_cfg_t *out);
// false (default): output A to the cell; true: aux output B to J5 instead, A off. Applies at the next set
void adf4351_output_b(bool b);
void adf4351_rf(bool on);       // PDBRF: output stage on/off, synth keeps running
void adf4351_off(void);         // chip enable low
bool adf4351_locked(void);      // LD pin
bool adf4351_mux(void);         // MUXOUT pin
// waits for lock, then settle_us. Returns false on lock timeout
bool adf4351_wait_lock(uint32_t timeout_us, uint32_t settle_us);
