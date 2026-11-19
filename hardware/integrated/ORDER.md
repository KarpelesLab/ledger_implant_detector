# Ordering the integrated TEM cell from JLCPCB (rev 0.3, concept)

The files here are **rev 0.3, not yet built**. Rev 0.2 (5 boards, 2026-11) works, but has a
12-15 dB notch around 1.4 GHz. The most likely cause (not yet confirmed) is the ADF4351's RFOUTA-
termination, wired through 45 mm of trace, and the AD8318's INLO decoupling, 22 mm away. Rev 0.3 places and wires those parts
by hand at the pins (`rf_terminations()` in `tools/gen_integrated_pcb.py`), so the rest of the board
is re-routed too. A review of that layout found the same kind of fault elsewhere, so rev 0.3 also:

- places every decoupling, bias and loop-filter part of U2 and U3 by hand, next to its pin
  (`support_parts()`). VTUNE is about 15 mm, buried on In1 under U2;
- keeps the router out of the gaps between the pads of small parts and off In1 under the chips;
- makes +5VA a pour on In1 under the detector, like +3V3A under the source, with FB1 where VBUS
  enters the detector frame and a new 10 uF bulk capacitor (C35) next to U3;
- adds ground vias round the cell feed vias, and moves the exposed-pad vias of U2 and U3 out of
  the paste windows (4 windows, about 50 % of the pad; KiCad reports the two footprints as modified
  on purpose), and gives Y1 its own ground via;
- adds C36 and C37 (100 pF) at the supply ends of the RFOUTA- and RFOUTA+ pull-ups (C37 is
  0402, like C38 below);
- adds thermal reliefs on the ground pads except the RF ones, and keeps every generated ground via
  0.2 mm off the pads (rev 0.2's U3 fault);
- moves C25 (100 pF) from AD8318's ENBL pin to its input supply, and C31 next to the ADS1115;
- runs the synthesizer's control lines on In1 from U2's fan-out vias to outside the source frame;
- moves every test point and J5 (U.FL) just outside the frames, so they work with the cans fitted.
  TP2 (VTUNE) reads through R38 (10k) at the loop filter; J5 is fed by an In1 stripline;
- adds C38 (100 nF, 0402) on U2's pin 32;
- uses the Pico symbol's passive alternate for AGND, which clears the last ERC error.

The stack-up is set in the board file, so the gerber job file names it too.

Bring-up firmware: `firmware/bringup`.

**Check in JLC's preview:** J5 (U.FL) moved outside the source frame, below the mounting hole, and Y1 is turned 180 degrees. Confirm J5's
signal pin lands on the round pad and Y1's pin 1 marking matches, as you did for rev 0.2.

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

## First power-up

The board's only power input is VBUS from the Pico's micro-USB (Pico pin 40), so nothing on it
is powered before the Pico is fitted. Either fit the Pico, plug in USB and measure straight away,
or, before fitting it, feed 5 V from a supply limited to about 200 mA into pin 40 of the Pico
footprint (VBUS), with ground on pin 38. Expect about 3.3 V on TP4 (+3V3A) and about 5 V on TP5 (+5VA).

## Known issue on the first run (2026-11 boards)

JLC found U3 (AD8318) pins 1-2 (CMIP, the input ground) short of solder on all five boards: a
ground stitching via sat across both pads and drew the solder away. The boards were shipped
as they were. The generator and Gerbers are fixed since `bb96cfe`; on boards from that run,
reflow pins 1-2 with flux and a fine tip.
