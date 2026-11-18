#pragma once
#include <stdbool.h>
#include <stdint.h>

#define LCD_W 240
#define LCD_H 320

#define RGB(r, g, b) ((uint16_t)((((r) & 0xf8) << 8) | (((g) & 0xfc) << 3) | ((b) >> 3)))
#define C_BLACK  0x0000
#define C_WHITE  0xffff
#define C_RED    RGB(255, 0, 0)
#define C_GREEN  RGB(0, 255, 0)
#define C_BLUE   RGB(0, 0, 255)
#define C_YELLOW RGB(255, 255, 0)
#define C_GREY   RGB(96, 96, 96)

void lcd_init(void);
void lcd_backlight(int percent);
void lcd_rotate180(bool on);
void lcd_fill(int x, int y, int w, int h, uint16_t c);
void lcd_test_pattern(void);
// 5x7 font scaled by `s`, upper case only; returns the x after the text
int lcd_text(int x, int y, const char *t, int s, uint16_t fg, uint16_t bg);
