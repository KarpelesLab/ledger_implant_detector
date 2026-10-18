#!/usr/bin/env python3
"""Figures + summary tables from sim/results/ into docs/img/ (needs matplotlib, scipy).

    python3 sim/report.py electrostatic
    python3 sim/report.py rf
"""
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IMG = os.path.join(ROOT, 'docs', 'img')
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ELS = ['E%d' % i for i in range(1, 9)]
TOL = {'jig': (0.5, 1.0), 'hand-held': (1.0, 2.0)}  # bounds on (gap / 0.1 mm, slide / 0.5 mm)
plt.rcParams.update({'font.size': 9, 'axes.spines.top': False, 'axes.spines.right': False})


def placement_residual(v, B, ga, sb):
    from scipy.optimize import lsq_linear
    sol = lsq_linear(B, v, bounds=([-ga, -sb], [ga, sb]))
    return v - B @ sol.x


def geometry_figure():
    import electrostatic as es
    fig, axs = plt.subplots(1, 2, figsize=(11, 3.4))
    for ax, batt in zip(axs, es.BATTERIES):
        for e, (x, y) in es.ELECTRODES.items():
            ax.add_patch(Rectangle((x, y), es.EL_SIZE, es.EL_SIZE, fc='#d9a441', ec='#8a6418', alpha=0.35))
            ax.text(x + 7, y + 7, 'E%d' % e, ha='center', va='center', color='#6b4c10')
        d = es.DEV
        ax.add_patch(Rectangle((d[0], d[2]), d[1] - d[0], d[3] - d[2], fc='none', ec='0.3', lw=1.2, ls='--'))
        b = es.BATTERIES[batt]
        ax.add_patch(Rectangle((b[0], b[2]), b[1] - b[0], b[3] - b[2], fc='#9aa7b8', ec='#4a5a70', alpha=0.55))
        for p in (es.ANT_PATCH, es.ANT_ARM):
            ax.add_patch(Rectangle((p[0], p[2]), p[1] - p[0], p[3] - p[2], fc='none', ec='#c0392b', lw=1.6))
        ax.set_xlim(8, 92)
        ax.set_ylim(-2, 42)
        ax.set_aspect('equal')
        ax.invert_yaxis()
        ax.set_title({'batt_covers_all': 'battery covers the whole antenna',
                      'batt_35x15': '35 x 15 battery, feed patch sticks out'}[batt])
        ax.set_xlabel('mm (detector board coordinates)')
    axs[0].plot([], [], color='#c0392b', label='antenna (est. from photos)')
    axs[0].add_patch(Rectangle((0, 0), 0, 0, fc='#9aa7b8', label='battery pouch'))
    axs[0].plot([], [], color='0.3', ls='--', label='wallet shell 72 x 18.6')
    axs[0].legend(loc='lower left', fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(IMG, 'sim_geometry.png'), dpi=140)
    plt.close(fig)


def electrostatic():
    R = json.load(open(os.path.join(HERE, 'results', 'electrostatic.json')))
    geometry_figure()
    fig, axs = plt.subplots(2, 2, figsize=(11, 6.4), sharex=True)
    rows = []
    for col, t in enumerate(('1.0', '0.6')):
        rep = R['t%s_repeat' % t]
        g0 = np.array([rep['genuine'][e] for e in ELS])
        gap = np.array([rep['gap_0.1mm'][e] for e in ELS]) - g0
        sl = np.array([rep['slide_0.5mm'][e] for e in ELS]) - g0
        B = np.stack([gap, sl], 1)
        series = [('genuine: 0.1 mm air gap', gap, '#9e9e9e'), ('genuine: 0.5 mm slide', sl, '#cfcfcf')]
        for batt, lab in (('batt_covers_all', 'antenna fully under battery'), ('batt_35x15', 'patch outside battery')):
            r = R['t%s_%s' % (t, batt)]
            G = np.array([r['genuine'][e] for e in ELS])
            v = np.array([r['tampered'][e] for e in ELS]) - G
            series.append(('tampered: ' + lab, v, '#2b6cb0' if 'fully' in lab else '#c0392b'))
            for k in ('tampered', 'tampered_ant_grounded'):
                vv = np.array([r[k][e] for e in ELS]) - G
                row = {'shell': t, 'battery': batt, 'antenna': 'floating' if k == 'tampered' else 'grounded (upper bound)',
                       'dC': vv[:4].round(0).tolist()}
                for name, (ga, sb) in TOL.items():
                    res = placement_residual(vv, B, ga, sb)
                    row['residual_' + name] = float(np.abs(res).max())
                rows.append(row)
        ax = axs[0, col]
        w = 0.8 / len(series)
        for i, (lab, v, c) in enumerate(series):
            ax.bar(np.arange(4) + (i - (len(series) - 1) / 2) * w, v[:4], w, label=lab, color=c)
        ax.axhline(0, color='k', lw=0.6)
        ax.set_title('%s mm shell: change vs. genuine reference' % t)
        ax.set_ylabel('dC (fF)')
        ax = axs[1, col]
        for i, (lab, v, c) in enumerate(series[2:]):
            res = placement_residual(v, B, *TOL['hand-held'])
            ax.bar(np.arange(4) + (i - 0.5) * 0.35, res[:4], 0.35, label=lab, color=c)
        ax.axhline(0, color='k', lw=0.6)
        ax.set_title('left after removing the best hand-held placement error')
        ax.set_ylabel('residual (fF)')
        ax.set_xticks(range(4))
        ax.set_xticklabels(ELS[:4])
    axs[0, 0].legend(fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(IMG, 'sim_electrostatic.png'), dpi=140)
    plt.close(fig)
    with open(os.path.join(HERE, 'results', 'electrostatic_summary.json'), 'w') as f:
        json.dump(rows, f, indent=1)
    print('%-5s %-16s %-24s %-28s %10s %10s' % ('shell', 'battery', 'antenna', 'dC E1..E4 (fF)', 'res jig', 'res hand'))
    for r in rows:
        print('%-5s %-16s %-24s %-28s %10.0f %10.0f' % (r['shell'], r['battery'], r['antenna'], r['dC'],
                                                        r['residual_jig'], r['residual_hand-held']))


def rf():
    from analyze_s1p import read_s1p, db
    files = sorted(glob.glob(os.path.join(HERE, 'results', 'rf', '*.s1p')))
    data = {os.path.basename(p)[:-4]: read_s1p(p) for p in files}
    positions = ['patch', 'arm', 'tip']
    fig, axs = plt.subplots(3, 2, figsize=(11, 8.5), sharex=True)
    bands = [(699e6, 960e6), (1710e6, 2200e6), (2300e6, 2690e6)]
    summary = []
    for r_, pos in enumerate(positions):
        g = data.get('%s_genuine_batt35' % pos)
        if g is None:
            continue
        f, sg = g
        for kind, c, lab in (('antenna_50', '#c0392b', 'tampered (antenna, 50 ohm modem)'),
                             ('copper', '#e69f00', 'control: plain copper, same outline')):
            d = data.get('%s_%s_batt35' % (pos, kind))
            if d is None:
                continue
            s = d[1]
            axs[r_, 0].plot(f / 1e9, db(s) - db(sg), color=c, lw=1.2, label=lab)
            ph = np.degrees(np.angle(s / sg))
            axs[r_, 1].plot(f / 1e9, ph, color=c, lw=1.2)
            for lo, hi in bands:
                m = (f >= lo) & (f <= hi)
                summary.append((pos, kind, lo / 1e6, hi / 1e6, float(np.abs(db(s) - db(sg))[m].max()),
                                float(np.abs(ph[m]).max()), float(np.abs(s - sg)[m].max())))
        dall = data.get('%s_antenna_50_battall' % pos)
        gall = data.get('%s_genuine_battall' % pos)
        if dall is not None and gall is not None:
            axs[r_, 0].plot(f / 1e9, db(dall[1]) - db(gall[1]), color='#2b6cb0', lw=1.2, label='tampered, battery covers it all')
            axs[r_, 1].plot(f / 1e9, np.degrees(np.angle(dall[1] / gall[1])), color='#2b6cb0', lw=1.2)
        for ax in axs[r_]:
            for lo, hi in bands:
                ax.axvspan(lo / 1e9, hi / 1e9, color='0.93', zorder=0)
            ax.axhline(0, color='k', lw=0.5)
        axs[r_, 0].set_ylabel('loop over %s\nd|S11| (dB)' % pos)
        axs[r_, 1].set_ylabel('d phase (deg)')
    axs[0, 0].legend(fontsize=7, frameon=False)
    axs[0, 0].set_title('change in |S11| vs. genuine (grey: LTE bands)')
    axs[0, 1].set_title('change in phase vs. genuine')
    for ax in axs[-1]:
        ax.set_xlabel('GHz')
    fig.tight_layout()
    fig.savefig(os.path.join(IMG, 'sim_rf.png'), dpi=140)
    plt.close(fig)
    # raw S11 of the probe itself
    if 'patch_air_batt35' in data:
        fig, ax = plt.subplots(figsize=(6, 3))
        f, s = data['patch_air_batt35']
        ax.plot(f / 1e9, db(s), color='0.4', label='loop in free air')
        if 'patch_genuine_batt35' in data:
            ax.plot(f / 1e9, db(data['patch_genuine_batt35'][1]), color='#2b6cb0', label='over genuine wallet')
        if 'patch_antenna_50_batt35' in data:
            ax.plot(f / 1e9, db(data['patch_antenna_50_batt35'][1]), color='#c0392b', label='over tampered wallet')
        ax.set_xlabel('GHz')
        ax.set_ylabel('|S11| (dB)')
        ax.legend(fontsize=7, frameon=False)
        fig.tight_layout()
        fig.savefig(os.path.join(IMG, 'sim_rf_raw.png'), dpi=140)
        plt.close(fig)
    print('%-6s %-11s %-13s %10s %10s %10s' % ('pos', 'kind', 'band MHz', 'max|dMag|', 'max|dPh|', 'max|dS11|'))
    for row in summary:
        print('%-6s %-11s %4.0f-%-8.0f %8.2f dB %8.1f deg %9.3f' % row)


def fixtures():
    """Fixture comparison (sim/fixtures_fdtd.py): S21 change tampered vs. genuine at each placement,
    against the change a genuine wallet shows when it is merely moved."""
    from analyze_s1p import read_s1p, db
    d = os.path.join(HERE, 'results', 'fixtures')
    data = {}
    for p in glob.glob(os.path.join(d, '*.s2p')):
        n = os.path.basename(p)[:-4]
        if n.startswith('tune'):
            continue
        f, s11 = read_s1p(p)
        _, s21 = read_s1p(p, 1)
        data[n] = (f, s11, s21)
    fixtures_ = sorted({n.split('_')[0] + '_' + n.split('_')[1] for n in data})
    titles = {'cps_z2': 'slot line, wallet 2 mm above', 'cps_z12': 'slot line, wallet 12 mm above',
              'tem_h20': 'TEM cell h = 20, wallet flat', 'tem_h25': 'TEM cell h = 25, wallet on edge'}
    fig, axs = plt.subplots(len(fixtures_), 2, figsize=(11, 2.6 * len(fixtures_)), sharex=True, squeeze=False)
    band = (699e6, 960e6)
    rows = []
    for r, fx in enumerate(fixtures_):
        cases = sorted(n for n in data if n.startswith(fx + '_') and n.endswith('_genuine'))
        e = data.get(fx + '_empty')
        if e is not None:
            f = e[0]
            axs[r, 0].plot(f / 1e9, db(e[2]), color='0.6', lw=1, label='empty |S21|')
            axs[r, 0].plot(f / 1e9, db(e[1]), color='0.6', lw=1, ls=':', label='empty |S11|')
        g0 = None
        for k, gname in enumerate(cases):
            tname = gname[:-len('genuine')] + 'tampered'
            if tname not in data:
                continue
            f, g11, g21 = data[gname]
            _, t11, t21 = data[tname]
            place = gname[len(fx) + 1:-len('_genuine')]
            c = plt.cm.tab10(k)
            axs[r, 1].plot(f / 1e9, db(t21) - db(g21), color=c, lw=1.3, label='tampered - genuine, ' + place)
            if g0 is None:
                g0 = (place, g21)
            else:
                axs[r, 1].plot(f / 1e9, db(g21) - db(g0[1]), color=c, lw=0.9, ls='--',
                               label='genuine moved: %s - %s' % (place, g0[0]))
            m = (f >= band[0]) & (f <= band[1])
            dd = (db(t21) - db(g21))[m]
            rows.append((fx, place, float(dd.max()), float(dd.min()), float(f[m][np.argmax(np.abs(dd))] / 1e6),
                         float(np.abs(t11 - g11)[m].max())))
        for ax in axs[r]:
            ax.axvspan(band[0] / 1e9, band[1] / 1e9, color='0.93', zorder=0)
            ax.axhline(0, color='k', lw=0.5)
        axs[r, 0].set_ylabel('%s\ndB' % titles.get(fx, fx))
        axs[r, 1].set_ylabel('d|S21| (dB)')
        axs[r, 1].legend(fontsize=6, frameon=False, ncol=2)
    axs[0, 0].legend(fontsize=7, frameon=False)
    axs[0, 0].set_title('empty fixture')
    axs[0, 1].set_title('tampered vs. genuine at the same placement (solid), genuine moved (dashed)')
    for ax in axs[-1]:
        ax.set_xlabel('GHz')
        ax.set_xlim(0.3, 2.0)
    fig.tight_layout()
    fig.savefig(os.path.join(IMG, 'sim_fixtures.png'), dpi=130)
    plt.close(fig)
    print('%-8s %-16s %8s %8s %8s %8s' % ('fixture', 'placement', 'max dB', 'min dB', 'at MHz', 'max|dS11|'))
    for row in rows:
        print('%-8s %-16s %8.2f %8.2f %8.0f %8.3f' % row)


if __name__ == '__main__':
    os.makedirs(IMG, exist_ok=True)
    {'electrostatic': electrostatic, 'rf': rf, 'fixtures': fixtures}[sys.argv[1]]()
