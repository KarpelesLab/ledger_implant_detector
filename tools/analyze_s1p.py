#!/usr/bin/env python3
"""Compare NanoVNA S11 sweeps of the near-field loop: reference vs. unit under test.

    python3 tools/analyze_s1p.py --ref ref_*.s1p --test test_*.s1p [--air air.s1p]

Several files per group = repeated placements. The spread inside the
reference group is the repeatability floor; a test/reference difference only
means something if it stands well above it. The verdict at the end says what an
on-board (VNA-less) RF front end would need: magnitude-only detection or full
magnitude + phase.
"""
import argparse
import sys

import numpy as np

# A difference must exceed this many placement-spreads to count: the maximum of a few
# hundred points of pure noise already reaches ~4-5x.
SNR_MIN = 8

BANDS = [  # name, start Hz, stop Hz
    ('LTE low (B12-B8)', 699e6, 960e6),
    ('LTE mid (B3/B1/B2/B4)', 1710e6, 2200e6),
    ('LTE high (B40/B41/B7)', 2300e6, 2690e6),
    ('BLE (genuine Nano X/Stax/Flex)', 2400e6, 2483.5e6),
]


def read_s1p(path):
    """Minimal Touchstone v1 reader -> (freq Hz, complex S11)."""
    unit, fmt = 1.0, 'MA'
    mult = {'HZ': 1, 'KHZ': 1e3, 'MHZ': 1e6, 'GHZ': 1e9}
    f, a, b = [], [], []
    for line in open(path):
        line = line.split('!')[0].strip()
        if not line:
            continue
        if line.startswith('#'):
            tok = line[1:].upper().split()
            for t in tok:
                if t in mult:
                    unit = mult[t]
                if t in ('MA', 'DB', 'RI'):
                    fmt = t
            continue
        v = line.split()
        f.append(float(v[0]) * unit)
        a.append(float(v[1]))
        b.append(float(v[2]))
    f, a, b = map(np.array, (f, a, b))
    if fmt == 'RI':
        s = a + 1j * b
    elif fmt == 'DB':
        s = 10 ** (a / 20) * np.exp(1j * np.radians(b))
    else:
        s = a * np.exp(1j * np.radians(b))
    return f, s


def load_group(paths):
    data = [read_s1p(p) for p in paths]
    f0 = data[0][0]
    out = []
    for p, (f, s) in zip(paths, data):
        if len(f) != len(f0) or np.max(np.abs(f - f0)) > 1:
            s = np.interp(f0, f, s.real) + 1j * np.interp(f0, f, s.imag)
        out.append(s)
    return f0, np.array(out)


def db(s):
    return 20 * np.log10(np.maximum(np.abs(s), 1e-9))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ref', nargs='+', required=True, help='known-genuine unit, repeated placements')
    ap.add_argument('--test', nargs='+', required=True, help='unit under test (or genuine + mock antenna)')
    ap.add_argument('--air', nargs='*', default=[], help='probe in free air (optional)')
    ap.add_argument('--plot', help='write a PNG plot (needs matplotlib)')
    a = ap.parse_args()

    f, ref = load_group(a.ref)
    _, test = load_group(a.test)
    if test.shape[1] != len(f):
        sys.exit('ref and test sweeps must cover the same frequencies')

    ref_mean, test_mean = ref.mean(0), test.mean(0)
    # repeatability: spread of individual reference placements around their mean
    ref_mag_sd = db(ref).std(0) if len(ref) > 1 else np.zeros(len(f))
    # RMS complex deviation of one placement from the mean (sample-corrected)
    ref_vec_sd = (np.sqrt((np.abs(ref - ref_mean) ** 2).sum(0) / (len(ref) - 1)) if len(ref) > 1
                  else np.zeros(len(f)))
    d_mag = db(test_mean) - db(ref_mean)                  # dB
    d_phase = np.degrees(np.angle(test_mean / ref_mean))  # deg
    d_vec = np.abs(test_mean - ref_mean)                  # linear |dS11|

    print('sweep: %.0f - %.0f MHz, %d points; ref x%d, test x%d'
          % (f[0] / 1e6, f[-1] / 1e6, len(f), len(ref), len(test)))
    if len(ref) < 3:
        print('WARNING: fewer than 3 reference placements, repeatability estimate is weak')
    print()
    print('%-32s %9s %9s %10s %9s %9s %8s' % ('band', 'max|dMag|', 'at MHz', 'max|dPh|', 'mag SNR', 'vec SNR', 'ref sd'))
    print('%-32s %9s %9s %10s %9s %9s %8s' % ('', 'dB', '', 'deg', '', '', 'dB'))
    verdict = []
    for name, lo, hi in BANDS:
        m = (f >= lo) & (f <= hi)
        if not m.any():
            print('%-32s  (not covered by sweep)' % name)
            continue
        i = np.argmax(np.abs(d_mag[m]))
        fm = f[m][i]
        floor_mag = max(np.median(ref_mag_sd[m]), 0.01)
        floor_vec = max(np.median(ref_vec_sd[m]), 1e-4)
        snr_mag = np.max(np.abs(d_mag[m])) / floor_mag
        snr_vec = np.max(d_vec[m]) / floor_vec
        print('%-32s %9.2f %9.0f %10.1f %9.1f %9.1f %8.3f'
              % (name, np.max(np.abs(d_mag[m])), fm / 1e6, np.max(np.abs(d_phase[m])), snr_mag, snr_vec, floor_mag))
        if 'BLE' not in name:
            verdict.append((name, np.max(np.abs(d_mag[m])), snr_mag, snr_vec))

    print()
    best = max(verdict, key=lambda v: v[2]) if verdict else None
    bestv = max(verdict, key=lambda v: v[3]) if verdict else None
    if not best:
        print('verdict: sweep does not cover any LTE band')
    elif best[2] >= SNR_MIN and best[1] >= 0.5:
        print('verdict: MAGNITUDE-ONLY is enough (%s: %.2f dB, %.0fx the placement spread).'
              % (best[0], best[1], best[2]))
        print('         -> scalar front end: PLL synth + reflection bridge + log detector (e.g. ADF4351 + AD8318).')
    elif bestv[3] >= SNR_MIN:
        print('verdict: magnitude change too small/noisy, but the COMPLEX S11 change is clear (%s, %.0fx).' % (bestv[0], bestv[3]))
        print('         -> needs magnitude + phase: AD8302-class gain/phase detector, or a NanoVNA-style mixer front end.')
    else:
        print('verdict: no change clearly above placement repeatability (best %.1fx). Improve the jig / probe'
              ' distance, or this unit really matches the reference.' % max(best[2], bestv[3]))

    if a.plot:
        try:
            import matplotlib
        except ImportError:
            sys.exit('--plot needs matplotlib (pip install matplotlib)')
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        for s in ref:
            ax[0].plot(f / 1e6, db(s), color='tab:blue', alpha=0.35, lw=0.8)
        for s in test:
            ax[0].plot(f / 1e6, db(s), color='tab:red', alpha=0.35, lw=0.8)
        if a.air:
            _, air = load_group(a.air)
            ax[0].plot(f / 1e6, db(air.mean(0)), color='0.5', lw=1, label='free air')
        ax[0].plot(f / 1e6, db(ref_mean), color='tab:blue', lw=1.6, label='reference')
        ax[0].plot(f / 1e6, db(test_mean), color='tab:red', lw=1.6, label='test')
        ax[0].set_ylabel('|S11| (dB)')
        ax[0].legend()
        ax[1].plot(f / 1e6, d_mag, color='tab:red', lw=1.2, label='test - ref (dB)')
        ax[1].fill_between(f / 1e6, -3 * ref_mag_sd, 3 * ref_mag_sd, color='tab:blue', alpha=0.2, label='3x placement spread')
        ax[1].set_ylabel('d|S11| (dB)')
        ax[1].set_xlabel('MHz')
        ax[1].legend()
        for _, lo, hi in BANDS[:3]:
            for x in ax:
                x.axvspan(lo / 1e6, hi / 1e6, color='0.9', zorder=0)
        fig.tight_layout()
        fig.savefig(a.plot, dpi=120)
        print('plot:', a.plot)


if __name__ == '__main__':
    main()
