# RF measurement protocol (NanoVNA)

Goal: decide, from real data, what an **on-board RF front end** (rev 0.2, no
external VNA) has to measure. The key question is whether a hidden LTE antenna
changes the loop's reflection **magnitude** enough to be seen reliably, or
whether only the **complex** S11 (magnitude + phase) shows it.

| Outcome | rev 0.2 RF front end | Rough cost |
|---|---|---|
| clear `|S11|` change (≥ 0.5 dB, ≥ 8× placement spread) | **scalar**: PLL synthesizer (ADF4351, 35 MHz–4.4 GHz) → reflection bridge / directional coupler → log detector (AD8318) → MCU ADC | ~20 parts |
| magnitude change buried, complex change clear | **gain/phase**: same synthesizer + coupler, AD8302 comparing incident vs. reflected (magnitude ratio + phase, up to 2.7 GHz) | scalar + ~5 parts |
| only visible with full calibration / high dynamic range | **NanoVNA-style** front end (synth + mixers + audio ADC, as in NanoVNA V2) | substantial |
| no change above repeatability | fix the jig/probe first; RF may not be worth integrating | — |

`tools/analyze_s1p.py` prints that verdict from your sweeps.

## Instrument

- A NanoVNA **V2 / LiteVNA** (fundamental up to 3 GHz+) is preferred. An
  original NanoVNA-H only reaches 900 MHz on its fundamental; above that it uses
  harmonics with much lower dynamic range. The mid / high LTE bands would then
  be marginal, so note which model you used.
- Sweep **600 MHz – 3 GHz**, as many points as the instrument allows (≥ 401),
  and use averaging if available. Use the same settings for every file.
- **Calibrate SOL (open/short/load) at the end of the cable**, i.e. at the SMA
  reference plane, then connect the probe. Recalibrate if you change cables or
  settings.
- Export **Touchstone `.s1p`** files (NanoVNA-Saver: *Save 1-Port file*), which
  keep magnitude **and** phase.

## Probe

Use the detector board's own loop (J4) once boards arrive, because results
depend on loop geometry. A hand-made loop before then is still useful for a
first look, but keep it at about 8 mm diameter and note that its numbers won't
transfer exactly.

## Samples

Measure each of these. Every "position" needs **≥ 3 placements**: lift the
probe and put it back each time. The spread between placements is the noise
floor everything is compared against.

1. **Free air**: probe away from everything (≥ 10 cm).
2. **Reference**: a known-genuine wallet.
3. **Mock implant**: the same genuine wallet with a commercial LTE flex (FPC)
   antenna (700–2700 MHz) taped where an implant could sit, under the shell or
   against it, at a realistic distance. If it has a u.FL connector, measure it
   both **open** and **terminated in 50 Ω**. A real implant's antenna is
   connected to a modem, which is closer to the terminated case.
4. **Copper control**: a piece of copper tape the same size as that antenna's
   radiator, in the same place. Comparing 3 and 4 shows whether the RF method
   tells a *tuned antenna* apart from *just copper*. That's the reason to have
   it at all, since the capacitive array already finds copper.
5. Optional: other genuine units of the same model. These show unit-to-unit
   variation, which a field tool has to tolerate.

Use a fixed jig or marks so "position A" is the same spot every time. Note the
probe-to-surface distance. Ideally repeat at 0 mm and ~2 mm to see how much
height matters.

## File naming

```
data/rf/<YYYY-MM-DD>/<model>_<unit>_<sample>_<position>_<n>.s1p
e.g. data/rf/2026-11-02/nanox_u1_ref_A_1.s1p
     data/rf/2026-11-02/nanox_u1_mock50_A_1.s1p
     data/rf/2026-11-02/nanox_u1_copper_A_1.s1p
```

Add a `notes.md` in each date folder: instrument model + firmware, cable,
sweep settings, probe used, probe distance, anything odd.

## Analysis

```sh
python3 tools/analyze_s1p.py --ref  data/rf/.../nanox_u1_ref_A_*.s1p \
                             --test data/rf/.../nanox_u1_mock50_A_*.s1p \
                             --air  data/rf/.../air_*.s1p --plot mock50_A.png
```

For each LTE band the script reports:

- the largest magnitude change and where it is;
- the largest phase change;
- the magnitude and complex change divided by the reference placement spread
  ("SNR").

It then prints the verdict from the table above. Run it for mock-vs-reference
**and** copper-vs-reference. Also run reference-vs-reference (split the
placements) as a sanity check: it must say "no change".

Commit the `.s1p` files and notes to `data/rf/` so the rev 0.2 RF design can be
sized from them.
