#!/usr/bin/env python3
"""Prototype of the rev 0.2 decision rule, run on NanoVNA captures of the TEM cell.

Uses |S21| only (what a scalar log detector gives): wallet sweep minus an empty-cell sweep, minus a
wide running median (placement effects are broad), then look for a narrow notch.

    python3 tools/tem_detect.py                  # every TEM capture, nominal sweep
    python3 tools/tem_detect.py --margins        # step / noise / harmonic budget for the hardware

The thresholds were picked after looking at these same captures (one genuine and one tampered Nano X),
so this shows what the hardware must deliver; it does not validate the rule.
"""
import argparse
import glob
import os
import re

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'rf', '2026-10-26')

BAND = (1000e6, 1450e6)     # where a notch counts; both implants measured so far are in 1.15-1.33 GHz
SPAN = (800e6, 1600e6)      # swept, so the baseline is defined at the band edges
BASE_W = 200e6              # running median window for the baseline
DEPTH = 0.45                # dB below the baseline
WIDTH = (10e6, 60e6)        # full width at half depth
SAME_F = 15e6               # two flagged placements must agree this closely in frequency
OUTLIER = 'u1_ref_r0c0_4'   # the unexplained genuine capture, left out of the noise budget (see notes.md)


def load(path):
    d = np.loadtxt(path, comments=['!', '#'])
    return d[:, 0], d[:, 1] + 1j * d[:, 2], d[:, 3] + 1j * d[:, 4]


def db(x):
    return 20 * np.log10(np.abs(x))


def residual(f, wallet_db, empty_db):
    """Wallet minus empty minus its wide running median."""
    d = wallet_db - empty_db
    step = f[1] - f[0]
    n = max(3, int(round(BASE_W / step)) | 1)
    pad = np.pad(d, n // 2, mode='reflect')
    return d - np.array([np.median(pad[i:i + n]) for i in range(len(d))])


def notch(f, r):
    """-> (depth dB, centre Hz, width Hz) of the deepest dip in BAND, width by interpolated half depth."""
    m = np.where((f >= BAND[0]) & (f <= BAND[1]))[0]
    i = m[np.argmin(r[m])]
    v = r[i]
    if v >= 0:
        return 0.0, f[i], 0.0

    def edge(k, s):
        while 0 <= k + s < len(f) and r[k] < v / 2:
            k += s
        if r[k] < v / 2:
            return f[k]
        return f[k] + (f[k - s] - f[k]) * (r[k] - v / 2) / (r[k] - r[k - s])
    return -v, f[i], abs(edge(i, 1) - edge(i, -1))


def verdict(depth, width):
    return depth >= DEPTH and WIDTH[0] <= width <= WIDTH[1]


def sweep(f0, f, s21, step=None, noise=0.0, h2=None, h3=None, rng=None):
    """Scalar detector reading on a regular grid: harmonics add in power, noise in dB (per point)."""
    fg = f0 if step is None else np.arange(SPAN[0], SPAN[1] + 1, step)
    p = np.interp(fg, f, np.abs(s21) ** 2)
    for mult, lvl in ((2, h2), (3, h3)):
        if lvl is not None:
            p = p + 10 ** (lvl / 10) * np.interp(mult * fg, f, np.abs(s21) ** 2, right=np.abs(s21[-1]) ** 2)
    out = 10 * np.log10(p)
    if noise:
        out = out + rng.normal(0, noise, len(out))
    return fg, out


def captures():
    """-> [(name, kind, path, empty paths taken in the same cable setup)]"""
    def cal(*pats):
        return [os.path.join(DATA, p) for p in pats]
    out = []
    for p in sorted(glob.glob(os.path.join(DATA, 'tem_h20_nanox_*.s2p'))):
        n = os.path.basename(p)[len('tem_h20_nanox_'):-4]
        kind = 'tampered' if n.startswith('tamp') else 'genuine'
        emp = cal('tem_h20_empty_i0.s2p') if re.search(r'_i\d$', n) else cal('tem_h20_empty_1.s2p', 'tem_h20_empty_2.s2p',
                                                                             'tem_h20_empty_3.s2p')
        out.append((n, kind, p, emp))
    return out


def run_all(**kw):
    """Worst-case numbers over all captures, with both the same-setup and the drifted empty reference."""
    rng = kw.pop('rng', None)
    res = []
    for n, kind, p, emp in captures():
        f, _, s = load(p)
        m = (f >= SPAN[0]) & (f <= SPAN[1])
        for e in emp:
            _, _, se = load(e)
            fg, w = sweep(f[m], f, s, rng=rng, **kw)
            _, ee = sweep(f[m], f, se, rng=rng, **kw)
            r = residual(fg, w, ee)
            res.append((n, kind, *notch(fg, r)))
    return res


def summary(res):
    t = [r for r in res if r[1] == 'tampered']
    g = [r for r in res if r[1] == 'genuine']
    miss = sum(not verdict(r[2], r[4]) for r in t)
    fa = sum(verdict(r[2], r[4]) for r in g)
    return min(r[2] for r in t), max(r[2] for r in g), miss, len(t), fa, len(g)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--margins', action='store_true')
    a = ap.parse_args()
    if not a.margins:
        seen = {}
        for n, kind, d, fc, w in run_all():
            seen.setdefault((kind, n), []).append((d, fc, w))
        for (kind, n), v in sorted(seen.items()):
            d, fc, w = max(v) if kind == 'genuine' else min(v)
            print('%-9s %-22s %.2f dB at %5.0f MHz, width %3.0f MHz  -> %s'
                  % (kind, n, d, fc / 1e6, w / 1e6, 'IMPLANT' if verdict(d, w) else 'clean'))
        print('smallest tampered depth %.2f dB, largest genuine depth %.2f dB; missed %d/%d, false alarms %d/%d'
              % summary(run_all()))
        return
    print('step, noise per point -> tampered min depth, genuine max depth, misses, false alarms (without %s, 20 trials)'
          % OUTLIER)
    for step in (5e6, 7.375e6, 10e6, 15e6):
        for noise in (0.0, 0.02, 0.05, 0.1, 0.2):
            res = []
            for seed in range(20 if noise else 1):
                res += [r for r in run_all(step=step, noise=noise, rng=np.random.default_rng(seed)) if r[0] != OUTLIER]
            print('%4.1f MHz  %.2f dB -> %.2f / %.2f dB, missed %d/%d, false alarms %d/%d'
                  % (step / 1e6, noise, *summary(res)))
    print('two placements in a row, both flagged within %.0f MHz of each other (5 MHz step, all genuine included):'
          % (SAME_F / 1e6))
    seq = {'genuine': ['u1_ref_r0c0_%d' % i for i in range(1, 6)] + ['u1_ref_r0c0_i%d' % i for i in range(1, 7)],
           'tampered': ['tamp_r0c0_%d' % i for i in (1, 2, 3)] + ['tamp_r0c0_i%d' % i for i in range(1, 7)]}
    for noise in (0.0, 0.05, 0.1):
        for kind, names in seq.items():
            hit = tot = 0
            for seed in range(20 if noise else 1):
                first = {}
                for r in run_all(step=5e6, noise=noise, rng=np.random.default_rng(seed)):
                    first.setdefault(r[0], r)
                for x, y in zip(names, names[1:]):
                    x, y = first[x], first[y]
                    tot += 1
                    hit += verdict(x[2], x[4]) and verdict(y[2], y[4]) and abs(x[3] - y[3]) <= SAME_F
            print('  noise %.2f dB, %-8s flagged %d/%d' % (noise, kind, hit, tot))
    print('harmonics of the source (dBc at the detector input), 7.4 MHz step:')
    for h2, h3 in ((None, None), (-40, -40), (-30, -30), (-20, -13), (-10, -10)):
        s = summary(run_all(step=7.375e6, h2=h2, h3=h3))
        print('  H2 %s, H3 %s dBc -> %.2f / %.2f dB, missed %d/%d, false alarms %d/%d' % (h2, h3, *s))


if __name__ == '__main__':
    main()
