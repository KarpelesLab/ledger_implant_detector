#pragma once
#include <stdbool.h>
#include <stdint.h>

#define ADS1115_LSB_V   0.000125    // +-4.096 V range

bool ads1115_init(void);                    // false if it doesn't answer
bool ads1115_read(int ch, int16_t *raw);    // one single-shot conversion at 860 SPS
bool ads1115_mean(int ch, int n, double *volts, double *sd_volts);
bool ads1115_rdy_seen(void);                // RDY pin went low after the last conversion
