# RF session 2026-10-18

- Instrument: NanoVNA-F V2 (SYSJOINT), fw 0.6.0 (build Jun 18 2025), SN 4A3639384505514B
- Capture: `tools/nanovna_capture.py`, 600 MHz - 3 GHz, 401 points (2 interleaved 201-pt scans), 4x averaged
- Calibration: SOL at the VNA port 1 SMA (probe cable is part of the DUT), 600 MHz - 3 GHz, 201 points,
  saved to device slot 0. Load residual after cal (401 pts, 4x avg): median -62..-65 dB below 1.5 GHz,
  -51..-59 dB up to 3 GHz (worst point -44 dB).
- Probe: improvised open-coax E-field probe: cut coax, shield removed, ~3 mm centre conductor exposed.
  Not the J4 loop; numbers will not transfer to the detector board. Cable taped down, wallet moved, not the probe.
- Probe-to-surface gap: 0 mm, bare tip touching the shell directly
- Wallets: Ledger Nano X, genuine unit u1 (reference); real modified (implanted) Nano X "tamp" (test)
- Position A: behind the left button (where the antenna sits on the tampered unit)

## Log
- 19:1x: first calibration discarded. Device got stuck returning 0 for every point above ~900 MHz (also with
  `cal off`), cleared only by a power cycle. Not reproducible with 16 back-to-back scans afterwards.
  The capture tool now rejects/retries any scan containing zero points. Recalibrated after the power cycle.
- air_1..3: free-air drift median 0.005 dB (max 0.024 dB). Probe+cable alone has a broad -1 dB dip ~2.14-2.23 GHz.
- ref_A_1..3 (genuine u1): placement 1 is an outlier (0.3-0.37 dB vs p2/p3 near 2.1 GHz); p2/p3 agree to 0.14 dB.
  Median placement sd: low band 0.011 dB, mid 0.092 dB, high 0.030 dB.
- tamp_A_1..3 (modified unit): analyze_s1p verdict "no change clearly above placement repeatability".
  Low band: tampered reads consistently lower than genuine across 600-1000 MHz (all 3 placements), max -0.11 dB at
  702 MHz (9.6x band-median ref sd, but < 0.5 dB and only ~2x the local ref sd near 700 MHz); -0.02..-0.04 dB at
  800-1000 MHz. Effect grows towards the 600 MHz sweep edge -> worth sweeping lower. Mid/high bands: nothing (2-4x).
- ref_A_4 (genuine, after the tampered set): reads LOWER than ref_A_1..3 in every band (median -0.06 dB low band,
  -0.24 dB mid, -0.16 dB high), i.e. further from the earlier refs than the tampered unit was. The tampered-vs-genuine
  low-band offset above is therefore explained by drift during the session, not the implant.
- air_4 (after ref_A_4): within 0.00..-0.02 dB (median) of air_1..3, max 0.06 dB. Instrument/cable drift is
  small; the ref_A_4 shift (up to -0.24 dB) comes from the probe-wallet contact (tip seating/pressure, bent tip,
  or wallet position), so 3 consecutive placements underestimated the real placement spread with a bare touching tip.

## Session 2: commercial H-field loop probes

- Probe kit: AliExpress 5-piece near-field kit (item 1005009045353546): 5 mm H loop, ~10-12 mm shielded H loop
  (green board), ~20 mm H loop, E-field paddle, "T" edge probe. Sizes other than "5mm H" estimated from photos.
- Calibration: SOL at the end of a short coax extension cable, 50 MHz - 3 GHz, 201 points, saved to slot 0.
  Load residual (401 pts, 4x avg): median -63..-64 dB below 1.8 GHz, -52..-56 dB above (worst -42 dB).
- File prefix: `h5_` = 5 mm loop, `h10_` = green ~10 mm loop.
- h5 (5 mm loop, 1 layer tape spacer, probe fixed, wallet moved): h5_air_1..3 drift median 0.004 dB. Loop
  self-resonance ~2.84 GHz in air (-2.56 dB); with a wallet it moves 2779-2860 MHz depending on placement.
  Wallet vs air: only 0.01-0.06 dB. Alternating ref/tamp x5 each (R1 T1 R2 T2 ... R5 T5).
  analyze_s1p verdict: no change above repeatability (best 2.0x; ref sd 0.010/0.012/0.021 dB low/mid/high,
  max |dMag| 0.01/0.02/0.04 dB). Apparent early separation at 2159/2366 MHz (frequencies picked after the first
  placements) did not survive T4/R5. 5 mm loop couples too weakly through shell + tape.

### Tampered unit's antenna (photo: img/tamp_antenna_feed.png)

- Black solder-masked flex (FPC) antenna stuck to the inside of the (pink) shell, silkscreen "AC-A2016-NANO-V1.1",
  i.e. apparently made specifically for a Nano. L-shaped outline with a notch.
- Fed by a thin black micro-coax (~1.1 mm): shield soldered to a tinned pad on the wide strip (ground side),
  centre conductor (white dielectric visible) to a round pad leading into the meander (faint parallel bands under
  the mask on the other side).
- Feed = current maximum (H-loop target); meander open end = voltage maximum (E-probe target). The micro-coax run
  can carry common-mode current too.
- H-loop orientation: a flat loop centred over a single straight trace mostly cancels; offset (edge on the trace)
  or edge-on (loop plane along the trace) couples better. Relevant for the flat J4 loop as well.

## Session 3: transmission (S21) through the implant antenna

- NanoVNA-F V2 returns S21 = exactly 0 over USB while the applied calibration has no thru step (SOL only).
  After `cal reset` S21 reads normally; full OSLT makes it corrected.
- Calibration: OSLT, `cal reset` first, 5 s (2-3 sweeps) per standard; port 1 = short cable end, thru via F-F SMA
  adapter to the port-2 cable end. 50 MHz - 3 GHz, 201 points, saved to slot 0.
  Thru check (401 pts, 4x avg): |S21| within +-0.09 dB, phase within +-1.6 deg over 50 MHz - 3 GHz.
  S11 into port 2 + adapter: -35 dB (low) .. -17 dB (3 GHz); not corrected (1.5-port VNA).
- Files: `.s2p` with S11 and S21 (S12/S22 written as 0).
- Receive antenna: "GSM antenna for BTS" (gsm_rx_antenna_s11.s1p): matched 891-935, 1776-1953 and 2469-2624 MHz
  (|S11| < -6 dB); weak at 700-850, 2.0-2.2 and 2.3-2.45 GHz. Fixed 20-30 cm from the probe.
- x10_ files: port 1 = green ~10 mm H loop flat + tape, port 2 = GSM antenna. Position B = over the implant
  antenna feed (solder joint), same spot on the genuine unit. x10_air_1..3: S21 -40..-53 dB in LTE bands,
  noise floor ~-90 dB, capture-to-capture sd 0.02-0.15 dB.
- Alternating R1 T1 R2 T2 R3 T3 at position B. **Clear, repeatable difference in the LTE low band:**
  mean S21 relative to free air over 740-860 MHz: genuine -5.1 / -5.4 / -2.4 dB, tampered +4.4 / +6.1 / +5.4 dB.
  The genuine wallet shields the loop (S21 below free air); the tampered one re-radiates (S21 above free air),
  peaking at ~820-850 MHz with a sharp drop at ~930 MHz and weaker response below 650 MHz: resonant shape.
  Smaller but 3/3-separated effects: 1710-1800 MHz tampered +0.4..+0.8 vs genuine -0.3..-0.6 dB;
  2400-2484 MHz tampered -1.4..-1.9 vs genuine 0.0..-0.8 dB.
  analyze_s1p --s21 verdict: MAGNITUDE-ONLY enough (24x); its 24.7 dB max is at a room null (876 MHz), the
  robust figure is the >= 6.8 dB gap between the band means. R3 sat higher than R1/R2 at 800-850 MHz (up to
  +5 dB): genuine placement range is wider than 2 placements suggested.
- Position P (user-found best placement): loop under the RIGHT button, ~2 mm of the loop sticking out past the
  bottom end of the Nano X, wallet side flush with the loop board's side. (Position A/B were on the left-button side.)
- Alternating R1 T1 R2 T2 R3 T3 at position P. Mean S21 relative to free air over 740-860 MHz:
  genuine -3.6 / -5.6 / -6.9 dB, tampered +3.5 / +2.8 / +3.8 dB (gap >= 6.4 dB; tampered spread 1.0 dB,
  genuine 3.3 dB). Peak at 824-846 MHz as at B; the sharp ~930 MHz drop seen at B is absent at P.
  analyze_s1p --s21 picks LTE mid (7.3 dB @ 2063 MHz, 19x) but that is a room null (air -55.7 dB there) and R3
  overlaps the tampered placements at 2040-2090 MHz: not a usable feature. LTE low (14x) is the robust one.
- Placement sensitivity: one tampered placement during the on-screen check, slightly off B, showed NO hump
  (S21 at free-air level); re-placing it brought the hump back. A miss does not prove a clean unit.
- On-screen check: device slot 1 = 700-1000 MHz, trace 0 LOGMAG S21 5 dB/div refpos 14, marker 1 824.5 MHz,
  marker 2 929.5 MHz (slot 0 = full 50 MHz - 3 GHz OSLT cal). Rule: marker 1 minus a fresh free-air reading
  > +4 dB = tampered pattern, < +2 dB = genuine pattern. The M1-M2 difference rule was NOT reliable (a genuine
  placement gave +13.3 dB).
