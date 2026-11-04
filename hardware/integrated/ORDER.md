# Ordering the integrated TEM cell from JLCPCB (rev 0.2, concept)

This board has **not been built or tested, and there is no firmware yet** (see
[docs/rev02_integrated.md](../../docs/rev02_integrated.md)). Treat the first order as a prototype.

## Main board

Upload `fab/integrated_gerbers.zip`. It is 200 x 216 mm.

- **4 layers, 1.6 mm, stack-up JLC04161H-7628.** The 50 ohm RF lines are only right on this stack-up.
- 1 oz outer copper, any mask colour, ENIG or lead-free HASL.
- The bare landing lines on top and the bare ground frames underneath are intentional.

## Assembly

Choose assembly on **both sides** and upload `fab/bom_jlc.csv` and `fab/cpl_jlc.csv`. Every line has
an exact LCSC part. JLC places the underside SMD parts and solders the LEDs and button on top.

- **Check stock first for U3 (AD8318ACPZ-REEL7, C578694) and U2 (ADF4351BCPZ, C654681).** If either is
  short, pre-order it through JLC or consign it. They are leadless and shouldn't be hand-soldered
  without hot air.
- **Check in the preview:** the rotation of U2, U3, U4, U5 and Y1, pin 1 of each, and the polarity of
  D1 and D2 (the square pad is the cathode).
- Parts marked DNP in the schematic stay empty: C1, C2, C13, R31, J1, J2, J4.

## Hand-soldered by you

| part | what | side |
|---|---|---|
| U1 | Raspberry Pi Pico 2 (SC1631), on 2 x 20 pin headers, micro-USB towards the board edge | underside |
| J3 | 8-pin 2.54 mm header, for the LCD | top |
| LCD | 2 inch ST7789 SPI module. **Check its pin order against J3 before ordering**: GND, VCC, SCK, SDA, RES, DC, CS, BL. They vary by seller, and a different order needs jumper wires | top |

## Cell and hardware

- Plate and ramps: the fixture's `tem_plate` (1) and `tem_ramp` (2), from
  `hardware/fixtures/`. You can reuse the ones you already have.
- 4 x M3 nylon spacers, 20 mm, with nylon screws, for the plate at (+-45, +-40) mm.
- 6 x M3 nylon feet, 20 mm or longer: the parts hang underneath and the USB plugs in from the side.
- Copper tape and solder tacks for the ramp joints: each ramp goes **under** the plate with a 4 mm
  overlap, and its tip is soldered to the landing line at the `h20` mark.
- Nothing metal near the cell.

Keep the micro-USB reachable, and BOOTSEL as well: that is the button on the Pico.
