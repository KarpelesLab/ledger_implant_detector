# RF session 2026-10-26: TEM cell and slot line fixtures

- Instrument: NanoVNA-F V2 (SYSJOINT), fw 0.6.0 (build Jun 18 2025), SN 4A3639384505514B
- Capture: `tools/nanovna_capture.py`, 50 MHz - 3 GHz, 401 points (2 interleaved 201-pt scans), 4x averaged,
  .s2p (S11 + S21). 7.4 MHz point spacing.
- Calibration: full OSLT at the ends of the two cables (thru = F-F SMA adapter), 50 MHz - 3 GHz, 201 points,
  saved to slot 0. Check with the thru still in: |S21| within +-0.1 dB over 50 MHz - 3 GHz; |S11| -20 dB or
  better below 1 GHz, -12 dB near 3 GHz (`thru_check.s2p`, 201 points, 2x avg).
- Fixtures: `hardware/fixtures/` (docs/fixtures.md), as ordered.
  - **TEM cell** (`tem_h20_`): septum on 20 mm nylon spacers. Before the session the septum plate and both
    ramps were trimmed by ~2 mm at each end so the ramp tips land on the base (the generated landing marks
    ignored the ramp's 4 mm tab; fixed in `tools/gen_fixtures.py` after these boards were made).
  - **Slot line** (`slot_z2_`): on >= 20 mm feet. Wallets on the copper-free carrier lying directly on the
    board (z = 1.6 mm, the closest case in the simulation).
- Wallets: genuine Nano X `u1` (reference), real implanted Nano X `tamp`. Both lying back (shell) down, screen up.
- Placement codes: `r0` = 0 deg, `r90` = 90 deg; `c0` = centred, `y20` = 20 mm along the fixture toward PORT 2,
  `x20` = 20 mm across (TEM: to the right seen from PORT 1; slot: toward the SIG strip); `_n` = repeat.
  - TEM 0 deg: length across the cell, USB end to the left seen from PORT 1. 90 deg: length along the cell,
    USB toward PORT 1.
  - Slot 0 deg: length across the slot, USB toward the SIG strip. 90 deg: length along the slot, USB toward PORT 1.

## Log

- 20:5x: first empty-cell capture failed: every point above ~1 GHz came back as 0, also after a power cycle.
  Cause: the device boots into the last recalled save slot, which was slot 1 (the 2026-10-18 700-1000 MHz
  check display, with a calibration over that span). Points outside the active calibration's span read 0.
  `recall 0` fixed it at once; the "stuck above ~900 MHz" event of 2026-10-18 was very likely the same thing.
  The tool's error message now says to recall the slot instead of power-cycling.
- TEM, empty (`tem_h20_empty_1..3`): S21 -1.4..-2.4 dB in 700-960 MHz, down to -4.7 dB by 1.5 GHz;
  S11 about -10 dB in LTE low (match minimum -22 dB near 1 GHz, ripple from the two launches). Repeat
  <= 0.08 dB below 1.5 GHz. Worse match than designed (sim: ~50 ohm) but fine for comparisons.
- TEM, genuine (`u1_ref_r0c0_1..3`, `r0y20`, `r0x20`, `r90c0`), then tampered (same set), then
  `tem_h20_empty_end` (drift: broad, +0.36 dB max below 900 MHz, -0.08..-0.14 dB at 1150-1190 MHz),
  then genuine re-checks `u1_ref_r0c0_4` and `_5`.
- Slot, empty (`slot_z2_empty_1..3`, no carrier): S21 -9..-12.5 dB, S11 -1..-3 dB in LTE low, as simulated
  (`sim/results/fixtures/cps_z12_empty.s2p`: -12..-13 dB / -2 dB). Repeat <= 0.09 dB.
- Slot, genuine then tampered, same placement set as the TEM cell.
- `slot_z2_carrier_1..2`: meant as the closing empty check, but the carrier was still on the board. They
  match the genuine unit's captures to 0.9x: most of what the genuine unit "does" to the slot line
  (step at ~800 MHz, hump at ~1.1 GHz, carrier vs empty up to +-1 dB) is the carrier's FR4, not the wallet.
  Genuine minus carrier: -0.26..+0.63 dB. No drift evidence; a true empty end capture was not taken.

## Results

All differences are S21, wallet capture minus the mean of the genuine centred 0 deg captures 1-3
(90 deg: minus the genuine 90 deg capture).

### TEM cell, h = 20 mm: narrow notch at 1171 MHz on the tampered unit

| placement | genuine, min 1100-1250 MHz | tampered at 1171 MHz |
|---|---|---|
| centre 0 deg, x3 | +0.04 .. -0.17 dB | **-1.10 / -1.10 / -1.00 dB** |
| 20 mm along | +0.04 dB | **-0.81 dB** |
| 20 mm across | -0.07 dB | **-1.06 dB** |
| centre 90 deg | (reference) | **-0.52 dB** on a +0.3 dB broad offset (~-0.8 dB narrow) |
| centre 0 deg, re-check #4 | **-1.1 dB, ~100 MHz wide, centred ~1230 MHz** | |
| centre 0 deg, re-check #5 | <= -0.22 dB | |

- The notch is ~40 MHz wide, at the same frequency at every tampered placement and in both orientations.
  The simulation predicted -1.2 dB at 1185 MHz for this exact setup, from the implant's coax / modem board
  (not the antenna itself). Simulated 90 deg was stronger (-6.3 dB); measured 90 deg is weaker than 0 deg.
- **Genuine #4 is an unexplained outlier**: as deep as the tampered notch, ~60 MHz higher and wider. It was
  the first genuine placement after the tampered set; #5 right after it was clean. Cause unknown (user did
  not report anything different). Until it is understood, a single ~1 dB notch near 1.2 GHz is not proof:
  the frequency (1171 vs ~1230 MHz) and width are what separated them here.
- Second, weaker feature: a dip at 736-751 MHz (vs 706-714 / 765-780 MHz), **-0.12 to -0.14 dB at all 6
  tampered placements**, genuine +0.01 to -0.08 dB on placements not in the reference mean. Predicted by
  the sim (-0.17 dB at 750 MHz, the antenna's own resonance detuned by lying flat near ground). Window chosen
  after looking at the data; margin too thin to use alone.

### TEM cell, interleaved run (21:47-22:01)

Cables moved back from the slot line; `tem_h20_empty_i0` within ~0.2 dB of the first empty captures.
Then 6 genuine / 6 tampered placements alternated, all centred 0 deg, full lift-out each time
(`*_r0c0_i1..6`, order G1 T1 G2 T2 ... G6 T6), then `tem_h20_empty_i1`.

| | deepest point in 1100-1300 MHz, minus the mean of G1..G6 |
|---|---|
| tampered T1..T6 | **-0.96 / -0.96 / -0.99 / -0.98 / -0.97 / -0.95 dB, all at 1171 MHz** (half-depth 1164-1186 MHz) |
| genuine G1..G6 | all within -0.16..+0.07 dB (G1 -0.16 lowest, consistent with the drift trend) |

- No genuine placement reproduced the #4 event: it is 1 of 13 genuine centred placements this session,
  still unexplained.
- Empty-cell drift over the run: +0.22..+0.50 dB, broad (+0.26..+0.30 dB flat across 1150-1200 MHz), so
  it shifts the baseline but cannot make or hide a 40 MHz notch.
- The 736-751 MHz "dip" reads -0.10..-0.13 dB on **both** units in this run against the earlier genuine
  reference: it is a baseline shift of the cell after the cables were moved, not an implant feature. Dropped.

### Slot line, z = 1.6 mm: small dip at 817-861 MHz at 0 deg only

Dip = mean 817-861 MHz minus the mean of 773-802 and 876-906 MHz.

| placement | genuine | tampered |
|---|---|---|
| centre 0 deg, x3 | +0.02 / -0.02 / +0.00 dB | **-0.16 / -0.20 / -0.13 dB** |
| 20 mm along | +0.03 dB | **-0.16 dB** |
| 20 mm across (toward SIG) | -0.05 dB | **-0.18 dB** |
| centre 90 deg | (reference) | +0.06 dB (nothing; sim also predicted none) |

- Consistent at all 5 tampered 0 deg placements, at the antenna resonance seen with the 10 mm loop
  (824-846 MHz, 2026-10-18), but about a third of the simulated depth (-0.5 dB). Genuine centre captures
  1-3 are in the reference mean, so their numbers are optimistic; the independent genuine placements
  (along/across) give -0.05..+0.03 dB.
- A broad -0.3..-0.9 dB dip around 980-1060 MHz on the tampered unit is **not usable**: the genuine unit
  moved 20 mm toward SIG gives -0.29 dB there.
- No genuine capture after the tampered set on this fixture (unlike the TEM cell), so slow drift is not
  ruled out for the slot numbers.

## Takeaways

- The TEM cell gives a position-independent signature on this implant: a ~1 dB, ~40 MHz notch at 1171 MHz
  at every placement and orientation (12 of 12 tampered captures, repeating to 0.04 dB in the interleaved
  run), against <= 0.2 dB for 18 of 19 genuine captures. One genuine placement (#4) produced a similar
  notch at ~1230 MHz and has not recurred in 7 later placements; its cause is unknown.
- The slot line sees the antenna resonance only at 0 deg and only weakly (~0.15 dB).
- Next: narrow, higher-resolution sweeps around 700-800 and 1100-1300 MHz (more points, more averaging);
  a second genuine unit; a true empty slot capture to close the slot data.
