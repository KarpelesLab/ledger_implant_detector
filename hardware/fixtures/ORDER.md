# Ordering the RF fixture kit from JLCPCB (rev 0.1, concept)

These boards have **not been built or measured yet** (see [docs/fixtures.md](../../docs/fixtures.md)).

Each board is a separate design at JLCPCB: upload each zip as its own PCB.

| board | upload this file | size (mm) | qty to order | qty needed |
|---|---|---|---|---|
| slot line | `slot/fab/slot_gerbers.zip` | 150 x 200 | 5 (minimum) | 1 |
| carrier | `carrier/fab/carrier_gerbers.zip` | 132 x 116 | 5 | 1 |
| TEM base | `tem_base/fab/tem_base_gerbers.zip` | 140 x 216 | 5 | 1 |
| TEM septum plate | `tem_plate/fab/tem_plate_gerbers.zip` | 100 x 100 | 5 | 1 |
| TEM ramp | `tem_ramp/fab/tem_ramp_gerbers.zip` | 100 x 59 | 5 | **2** |

PCB options for every board (all JLCPCB defaults except as noted):

- Base material FR-4, **2 layers**, thickness **1.6 mm**, 1 oz outer copper
- Any solder-mask colour; surface finish HASL lead-free or ENIG
- Remove order number: "Specify a location" or the paid "Remove" option, if you
  don't want JLC's number printed over the silkscreen. Either is harmless.
- The **carrier** has no copper at all (FR-4 + silkscreen + holes). JLC
  sometimes asks to confirm this during review. It is intentional.
- The **ramp** has a 3 mm wide tip tab, and the TEM base landing lines are left
  without solder mask. Both are intentional.

No PCBA (assembly) is needed. The only soldered parts are the four edge-mount
SMA jacks (two on the slot board, two on the TEM base). They take four solder
joints each and are easier and cheaper to fit by hand than through assembly.
See [bom.csv](bom.csv) for them and for the nylon hardware and copper tape.
