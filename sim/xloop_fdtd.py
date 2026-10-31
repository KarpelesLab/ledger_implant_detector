#!/usr/bin/env python3
"""FDTD model of a crossed-loop fixture: two large H-field loops at 90 degrees.

Suggested as an alternative to the slot line and TEM cell (docs/fixtures.md).
Port 1 drives one loop, port 2 is the other loop, terminated in 50 ohm. The
loops are orthogonal and symmetric, so they barely couple: empty, S21 is close
to zero. A tuned object that couples to both (an implant antenna) should show
up as a narrow S21 peak over that null, like an induction-balance metal
detector. S11 of the driven loop also shows absorption, as with the small probe.

A 110 mm loop is more than a wavelength around at 1 GHz, so each loop is cut
into 12 segments of 35-40 mm. Every gap holds the same series capacitor and
damping resistor (XLOOP_R, default 50 ohm); at the two port gaps the resistor
is the port itself. With 50 ohm everywhere the loops are electrically
symmetric and their resonance is flat (Q ~ 5); lower values give a sharper,
stronger resonance.

Configurations (wallet lying flat, back at z = 2 mm, test area centred on 0):

    xv   two vertical loops, crossed: loop 1 in the plane y = 0 (H along y),
         loop 2 in the plane x = 0 (H along x). The wallet sits in the middle.
    hv   loop 1 horizontal, 5 mm under the wallet (H vertical, through the flat
         antenna); loop 2 vertical in the plane y = 0 (H along y).
    cx   not crossed: two wallet-sized loops on the same axis, under and over the
         wallet (S21 through, no null). The wallet sits in a jig.

    python3 sim/xloop_fdtd.py cal [pF ...]   # empty xv fixture: loop resonance vs. gap capacitor
    python3 sim/xloop_fdtd.py [xv|hv ...]    # all cases -> sim/results/fixtures/xloop_*.s2p
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rf_fdtd import Sim, axis  # noqa: E402
from fixtures_fdtd import OUT, PLACES, Place, put_wallet, wallet, wallet_lines, write_s2p  # noqa: E402

GAP_C = 0.8e-12         # per gap, set with `cal` so the loops resonate near 850 MHz
GAP_R = float(os.environ.get('XLOOP_R', '50'))   # damping resistor per gap
Z0 = 2.0                # wallet back above z = 0

# loop: normal axis, plane coordinate, (u0, u1), (v0, v1), gap offsets from the middle of the
# u-sides and of the v-sides, port gap (axis along the wire, node), gap capacitor scale.
# u, v are the two other axes in xyz order. Each port sits on the other loop's mirror plane, so
# the empty loops cancel by symmetry. In xv the loops cross 5 mm apart at the middle of their
# top and bottom sides: port 1 at the bottom crossing, port 2 at the top one. There the other
# loop's wire is at the middle of its far side, at zero potential.
LOOPS = {
    'xv': [dict(normal='y', c=0.0, u=(-55.0, 55.0), v=(-47.0, 63.0), gu=(-37.0, 0.0, 37.0),
                gv=(-37.0, 0.0, 37.0), port=('x', (0.0, 0.0, -47.0)), cs=1.0),
           dict(normal='x', c=0.0, u=(-60.0, 60.0), v=(-52.0, 68.0), gu=(-40.0, 0.0, 40.0),
                gv=(-40.0, 0.0, 40.0), port=('y', (0.0, 0.0, 68.0)), cs=0.9)],
    'hv': [dict(normal='z', c=-3.0, u=(-55.0, 55.0), v=(-55.0, 55.0), gu=(-37.0, 0.0, 37.0),
                gv=(-37.0, 0.0, 37.0), port=('y', (55.0, 0.0, -3.0)), cs=1.0),
           dict(normal='y', c=0.0, u=(-58.0, 58.0), v=(-50.0, 66.0), gu=(-39.0, 0.0, 39.0),
                gv=(-39.0, 0.0, 39.0), port=('z', (58.0, 0.0, 8.0)), cs=0.95)],
    # coaxial pair, about the size of the wallet: 82 x 30 mm loops 5 mm under and 3 mm over it,
    # S21 straight through (strong, no null). A jig holds the wallet, so it only moves a little.
    'cx': [dict(normal='z', c=-3.0, u=(-41.0, 41.0), v=(-15.0, 15.0), gu=(-20.0, 20.0),
                gv=(0.0,), port=('y', (41.0, 0.0, -3.0)), cs=1.0, gap_c=1.4e-12),
           dict(normal='z', c=Z0 + 11.5 + 3.0, u=(-41.0, 41.0), v=(-15.0, 15.0), gu=(-20.0, 20.0),
                gv=(0.0,), port=('y', (41.0, 0.0, Z0 + 11.5 + 3.0)), cs=1.0, gap_c=1.4e-12)],
}


def in_plane(normal):
    return [a for a in 'xyz' if a != normal]


def sides(lp):
    """Each side: (axis along it, start, end, fixed coordinates of the other two axes, gap positions)."""
    u, v = in_plane(lp['normal'])
    um, vm = sum(lp['u']) / 2, sum(lp['v']) / 2
    out = []
    for vv in lp['v']:
        out.append((u, lp['u'][0], lp['u'][1], {lp['normal']: lp['c'], v: vv}, [um + g for g in lp['gu']], um))
    for uu in lp['u']:
        out.append((v, lp['v'][0], lp['v'][1], {lp['normal']: lp['c'], u: uu}, [vm + g for g in lp['gv']], vm))
    return out


def loop_points(lp):
    """Corner and gap node coordinates, per axis, so the grid contains them."""
    pts = {'x': [], 'y': [], 'z': []}
    for ax, a0, a1, fixed, gaps, _ in sides(lp):
        pts[ax] += [a0, a1] + list(gaps)
        for k, val in fixed.items():
            pts[k].append(val)
    return pts


def build_loop(s, lp, port_role):
    """Wire loop with C + R in series in every gap (two neighbouring edges, the capacitor on the
    side's middle side, so mirror-image gaps are mirror images). The port gap holds the port
    resistor (50 ohm) instead of the damping resistor. port_role: 'src' or 'probe'."""
    port_ax, port_node = lp['port']
    for ax, a0, a1, fixed, gaps, mid in sides(lp):
        idx = {k: s.ni(k, val) for k, val in fixed.items()}
        sl = [slice(s.ni(ax, a0), s.ni(ax, a1)) if k == ax else idx[k] for k in 'xyz']
        s.pec[ax][tuple(sl)] = True
        for g in gaps:
            ig = s.ni(ax, g)
            if abs(g - mid) < 1e-6:
                ic, ir = ig - 1, ig          # middle gap: the two edges either side of the node
            else:
                ic, ir = (ig, ig + 1) if g > mid else (ig - 1, ig - 2)
            e = lambda i: (ax, *[i if k == ax else idx[k] for k in 'xyz'])
            s.add_capacitor(e(ic), lp.get('gap_c', GAP_C) * lp['cs'])
            node = [g if k == ax else fixed[k] for k in 'xyz']
            if ax == port_ax and np.allclose(node, port_node):
                s.add_lumped(e(ir), 50.0, port=port_role == 'src', probe=port_role == 'probe')
            elif GAP_R > 0:
                s.add_lumped(e(ir), GAP_R)
            else:
                s.pec[ax][e(ir)[1:]] = True


def build(cfg, pl=None, d=None):
    loops = LOOPS[cfg]
    fixed = {'x': [0.0], 'y': [0.0], 'z': [0.0]}
    for lp in loops:
        for k, v in loop_points(lp).items():
            fixed[k] += v
    fine = {'x': [], 'y': [], 'z': []}
    if pl is not None:
        for k, w in zip('xyz', wallet_lines(pl, d=d)):
            fine[k] += w
    ext = {k: (min(fixed[k]), max(fixed[k])) for k in 'xyz'}
    ax = {}
    for k in 'xyz':
        lo, hi = ext[k]
        ax[k] = axis(fixed[k], fine[k] + [(lo - 2, hi + 2, 1.0)], lo - 25, hi + 25, base=1.0, maxstep=3.0)
    s = Sim(ax['x'], ax['y'], ax['z'])
    build_loop(s, loops[0], 'src')
    build_loop(s, loops[1], 'probe')
    if pl is not None:
        put_wallet(s, d, pl)
    return s


ORIENTS = ('flat0', 'flat90')
# cx: the jig fixes the orientation; test a small slip, and the wallet turned end for end
# (implant antenna at the other end of the loops).
CX_PLACES = [('flat0', (0.0, 0.0)), ('flat0', (2.0, 1.0)), ('flat180', (0.0, 0.0))]


def case_list(cfgs):
    out = []
    for cfg in cfgs:
        out.append((cfg, None, None, None))
        places = CX_PLACES if cfg == 'cx' else [(o, p) for o in ORIENTS for p in PLACES[o]]
        for o, p in places:
            for kind in ('genuine', 'tampered'):
                out.append((cfg, o, p, kind))
    return out


def tag():
    return 'R%g' % GAP_R


def run_case(args):
    cfg, o, p, kind, threads = args
    if o is None:
        name = 'xloop%s_%s_empty' % (tag(), cfg)
        s = build(cfg)
    else:
        name = 'xloop%s_%s_%s_%+03.0f%+03.0f_%s' % (tag(), cfg, o, p[0], p[1], kind)
        s = build(cfg, Place(o, p[0], p[1], Z0), wallet(kind))
    t = time.time()
    f, S11, Z = s.run(t_end=float(os.environ.get('SIM_TEND', '45e-9')), fmin=0.3e9, fmax=3.0e9, nf=541,
                      threads=threads)
    os.makedirs(OUT, exist_ok=True)
    write_s2p(os.path.join(OUT, name + '.s2p'), f, S11, s.S21[0], name + ', gap C %.2f pF' % (GAP_C * 1e12))
    return name, time.time() - t, int(np.prod(s.n)), s.tail


def cal(pfs):
    """Empty fixture: where does the driven loop resonate (Im Z = 0), and how decoupled are the loops?"""
    global GAP_C
    for cfg in os.environ.get('XLOOP_CFG', 'xv hv').split():
        for pf in pfs:
            GAP_C = pf * 1e-12
            for lp in LOOPS[cfg]:
                lp.pop('gap_c', None)
            s = build(cfg)
            t = time.time()
            f, S, Z = s.run(t_end=float(os.environ.get('SIM_TEND', '30e-9')), fmin=0.3e9, fmax=3.0e9, nf=541,
                            threads=int(os.environ.get('SIM_THREADS', '16')))
            s21 = 20 * np.log10(np.abs(s.S21[0]) + 1e-30)
            m = (f > 0.6e9) & (f < 1.3e9)
            row = '  '.join('%.1f:%.0f%+.0fj' % (fq / 1e9, Z[i].real, Z[i].imag)
                            for fq in (0.7e9, 0.85e9, 1.0e9, 1.2e9) for i in [int(np.argmin(abs(f - fq)))])
            print('%s R=%g C=%.2f pF  Re Z peak %.0f ohm at %.0f MHz  Z %s  S21 max %.1f dB in 0.6-1.3 GHz  '
                  '(%.0f s, tail %.1e)' % (cfg, GAP_R, pf, Z.real[m].max(), f[m][np.argmax(Z.real[m])] / 1e6, row,
                                           s21[m].max(), time.time() - t, s.tail), flush=True)
            write_s2p(os.path.join(OUT, 'tune_xloop%s_%s_C%gpF.s2p' % (tag(), cfg, pf)), f, S, s.S21[0],
                      'empty %s, gap C %g pF' % (cfg, pf))


def main():
    import multiprocessing as mp
    threads = int(os.environ.get('SIM_THREADS', '4'))
    cfgs = sys.argv[1:] or list(LOOPS)
    cases = [c + (threads,) for c in case_list(cfgs)]
    cases.sort(key=lambda c: c[1] is not None)
    procs = int(os.environ.get('SIM_PROCS', '4'))
    with mp.get_context('spawn').Pool(procs) as pool:
        for name, dt, ncell, tail in pool.imap_unordered(run_case, cases):
            print('%-44s %6.0f s  %d cells  tail %.1e' % (name, dt, ncell, tail), flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'cal':
        cal([float(a) for a in sys.argv[2:]] or [GAP_C * 1e12])
    else:
        main()
