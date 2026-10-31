#!/usr/bin/env python3
"""FDTD comparison of position-independent RF test fixtures (rev 0.1 fixture kit).

The question: which field structure, spread over an 80 x 80 mm area, excites a
flat ~830 MHz antenna (an implant's LTE antenna) wherever the wallet is put on
it, without depending on finding the antenna's feed with a small probe?

Fixtures (both two-port, NanoVNA S11 + S21; ports are ideal lumped 50 ohm):

    cps   coplanar strips with a 90 mm slot: the wallet lies flat over the slot.
          In-plane E across the slot + vertical H. z0 = height of the wallet's
          back above the copper (spacers + carrier plate).
    tem   open TEM cell: septum plate at height h over a ground plane, tapered
          ramps to the ports. Vertical E + horizontal H. The wallet goes inside.

The wallet is a generic Nano X-sized model (plastic shell, battery, main PCB).
The "tampered" wallet adds a meandered LTE-style antenna tuned to ~830 MHz,
loaded by the modem's 50 ohm, a coax shield and the implant's modem board. It is
NOT the real AC-A2016 layout; only its resonance (seen in data/rf/2026-10-18)
is matched. The fixtures are compared on how much that resonance shows, and
how much it changes when the wallet is moved or turned.

    python3 sim/fixtures_fdtd.py tune [nH ...]   # tampered wallet alone: resonance vs. matching coil
    python3 sim/fixtures_fdtd.py                  # all fixture cases -> sim/results/fixtures/*.s2p
    python3 sim/fixtures_fdtd.py tune-grand [eps[:h] ...]  # Grand-style spiral implant alone: resonance vs. turn coupling
    SIM_KINDS=grand python3 sim/fixtures_fdtd.py  # the spiral implant in every fixture placement
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rf_fdtd import Sim, axis  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'results', 'fixtures')
E = 1e-6

# ------------------------------------------------------------------ wallet (local coordinates)
# x along the 72 mm length, y across (18.5), z from the outer face of the back (0) inwards.
# Everything sits on the 0.5 mm grid used around the wallet.
L, W, T = 72.0, 18.5, 11.5
BATTERY = (4.0, 34.0, 2.0, 16.5, 1.5, 5.5)
MAIN_PCB = (4.0, 60.0, 2.5, 16.0, 7.0)
PATCH = (63.0, 70.5, 2.0, 16.5)          # antenna ground side (coax shield)
FEED_X = 62.5                            # 1 mm feed gap between FEED_X - 0.5 and FEED_X + 0.5
MEANDER_Y = (2.0, 16.5)
PITCH = 3.0                              # 1 mm traces, 2 mm gaps
A0 = 25.0                                # meander runs from the feed back to x = A0
MATCH_L = 100e-9                         # series coil at the feed (modem-side matching): resonance ~835 MHz
MODEM_R = 50.0                           # modem input
MODEM = (48.0, 69.0, 3.0, 15.0, 9.0)
COAX = (68.0, 4.0, 1.0, 9.0)             # shield: vertical wire from the patch to the modem board
GROUND_TIE = (50.0, 8.0, 7.0, 9.0)       # implant powered from the wallet: modem ground -> main PCB ground


def rects_mask(rects):
    def m(xl, yl):
        out = np.zeros(xl.shape, bool)
        for x0, x1, y0, y1 in rects:
            out |= (xl >= x0 - E) & (xl <= x1 + E) & (yl >= y0 - E) & (yl <= y1 + E)
        return out
    return m


def meander(a0):
    """Runs across the shell, the first one ending at the feed (top, y = 16), joined
    alternately at the bottom and top."""
    rects, k = [], 0
    first = FEED_X - 1.5
    while first - PITCH * k >= a0 - E:
        x0 = first - PITCH * k
        rects.append((x0, x0 + 1, MEANDER_Y[0], MEANDER_Y[1]))
        if first - PITCH * (k + 1) >= a0 - E:
            yb = (MEANDER_Y[0], MEANDER_Y[0] + 1) if k % 2 == 0 else (MEANDER_Y[1] - 1, MEANDER_Y[1])
            rects.append((x0 - PITCH, x0 + 1, yb[0], yb[1]))
        k += 1
    return rects


def wallet(kind, a0=A0, tie=True, match_l=MATCH_L, modem_r=MODEM_R):
    """kind: genuine | tampered | antenna (antenna alone in its shell, feed as the source port)."""
    d = {'diel': [], 'pec': [], 'sheets': [], 'lumped': []}
    t = 1.0
    for b in ((0, L, 0, W, 0, t), (0, L, 0, W, T - t, T), (0, t, 0, W, t, T - t), (L - t, L, 0, W, t, T - t),
              (t, L - t, 0, t, t, T - t), (t, L - t, W - t, W, t, T - t)):
        d['diel'].append((b, 3.0, 0.01))
    if kind != 'antenna':
        d['pec'].append(BATTERY)
        d['sheets'].append((MAIN_PCB[4], rects_mask([MAIN_PCB[:4]])))
    if kind == 'genuine':
        return d
    d['sheets'].append((1.0, rects_mask([PATCH] + meander(a0))))
    d['diel'].append(((a0, PATCH[1], PATCH[2], PATCH[3], 1.0, 1.5), 3.4, 0.01))
    d['sheets'].append((MODEM[4], rects_mask([MODEM[:4]])))
    d['pec'].append((COAX[0], COAX[0], COAX[1], COAX[1], COAX[2], COAX[3]))
    if tie:
        d['pec'].append((GROUND_TIE[0], GROUND_TIE[0], GROUND_TIE[1], GROUND_TIE[1], GROUND_TIE[2], GROUND_TIE[3]))
    # feed: 1 mm gap between the first meander run and the patch at y = 16, bridged by
    # the matching coil and the (matched) modem input in series
    d['coil'] = ((FEED_X - 0.5, 16.0, 1.0), (FEED_X, 16.0, 1.0), match_l)
    d['lumped'].append(((FEED_X, 16.0, 1.0), (FEED_X + 0.5, 16.0, 1.0), modem_r, kind == 'antenna'))
    return d


# ---- second implant variant: Joe Grand's Nano X implant (slides pp. 33-38).
# A hand-wound pancake spiral of ~8 cm of 0.25-0.3 mm copper wire: ~6 uneven, nearly
# touching turns, ~6 mm across, lying half over the edge of the implant's own board, fed by
# the modem at its outer end. The Ledger's battery is replaced by a shorter one (44 -> 26 mm,
# scaled here to 18 of the model's 30 mm) to make room. The spiral is modelled square, 6 mm,
# 0.5 mm pitch, on a local 0.25 mm grid. Turns this close couple far more strongly than grid
# wires 0.5 mm apart: a thin slab of permittivity G_EPS in the coil's plane stands in for
# that. Its value is not known (pitch and gaps vary along the coil); with the spiral resting
# ~1 mm over the board's ground, the free-space resonance (tune-grand) is 795-865 MHz with no
# extra coupling (eps 1, h 0.5-1.5 mm) and 660-700 MHz with eps 3. The fixture runs use
# eps 1, h 1 mm: 835 MHz, in the LTE low band where the implant must work. Without a matching
# network the modem sees only ~10 ohm there: a weakly coupled, conservative case.
G_BATTERY = (4.0, 22.0, 2.0, 16.5, 1.5, 5.5)
G_BOARD = (23.0, 37.0, 3.0, 15.0, 3.0)   # implant board (ground plane), in the battery's old place
G_SPIRAL = (34.0, 4.0, 6.0)              # outer corner x, y, outer side: 3 mm over the board edge
G_HEIGHT = 1.0                           # spiral above the board's ground (it rests on components)
G_WIRE = 80.0                            # wire length (mm)
G_PITCH = 0.5
G_EPS = 1.0
G_TIE = (30.0, 9.0, 3.0, 7.0)            # implant ground -> main PCB ground


def spiral(x0, y0, side, length, pitch=G_PITCH):
    """Square spiral as zero-width segments, from the outer corner (x0, y0) inwards."""
    segs, p, left = [], (x0, y0), length
    dirs = ((1, 0), (0, 1), (-1, 0), (0, -1))
    runs = [side] + [side - pitch * ((k - 1) // 2) for k in range(1, 400)]
    for k, r in enumerate(runs):
        r = min(r, left)
        if r < pitch - E:
            break
        dx, dy = dirs[k % 4]
        q = (p[0] + dx * r, p[1] + dy * r)
        segs.append((min(p[0], q[0]), max(p[0], q[0]), min(p[1], q[1]), max(p[1], q[1])))
        p, left = q, left - r
    return segs, p


def wallet_grand(kind, eps=None, height=None):
    """kind: tampered (in a fixture) | antenna (the modem's 50 ohm is the source port)."""
    eps = G_EPS if eps is None else eps
    d = wallet('genuine')
    d['pec'] = [G_BATTERY]
    x0, y0, side = G_SPIRAL
    zb = G_BOARD[4]
    z = zb + (G_HEIGHT if height is None else height)
    segs, _ = spiral(x0, y0, side, G_WIRE)
    d['sheets'] += [(zb, rects_mask([G_BOARD[:4]])), (z, rects_mask(segs))]
    d['diel'].append(((G_BOARD[0], x0 + side + 0.5, 2.0, 16.5, zb - 0.5, z), 3.5, 0.02))  # board, parts, glue
    d['diel'].append(((x0, x0 + side, y0, y0 + side, z - 0.25, z + 0.25), eps, 0.02))     # turn coupling
    d['pec'].append((G_TIE[0], G_TIE[0], G_TIE[1], G_TIE[1], G_TIE[2], G_TIE[3]))
    # feed: modem 50 ohm from the board up to the spiral's outer end
    d['lumped'].append(((x0, y0, zb), (x0, y0, zb + 0.25), MODEM_R, kind == 'antenna'))
    d['pec'].append((x0, x0, y0, y0, zb + 0.25, z))
    d['fine'] = [(x0 - 1.0, x0 + side + 1.0, y0 - 1.0, y0 + side + 1.0, zb - 0.5, z + 1.0)]
    return d


ORIENT = {   # columns: where local x, y, z go (signed global axis)
    'flat0': ((1, 0, 0), (0, 1, 0), (0, 0, 1)),      # lying on its back, length along x
    'flat90': ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),    # lying on its back, length along y
    'flat180': ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),  # lying on its back, turned end for end
    'edge': ((0, 1, 0), (0, 0, 1), (1, 0, 0)),       # standing on a long side, length along y
}


class Place:
    def __init__(self, orient, cx, cy, z0):
        self.R = np.array(ORIENT[orient], float).T      # global = R @ local + t
        c = self.R @ np.array([L / 2, W / 2, T / 2])
        corners = [self.R @ np.array([a * L, b * W, e * T]) for a in (0, 1) for b in (0, 1) for e in (0, 1)]
        self.t = np.array([cx - c[0], cy - c[1], z0 - min(p[2] for p in corners)])
        self.t = np.round(self.t * 2) / 2          # keep the wallet on the 0.5 mm grid

    def g(self, p):
        return tuple(np.round(self.R @ np.array(p, float) + self.t, 4))

    def box(self, b):
        a = np.array([self.g((x, y, z)) for x in b[:2] for y in b[2:4] for z in b[4:6]])
        lo, hi = a.min(0), a.max(0)
        return lo, hi

    def bbox(self):
        return self.box((0, L, 0, W, 0, T))


def put_wallet(s, d, pl):
    for b, er, td in d['diel']:
        lo, hi = pl.box(b)
        s.dielectric((lo[0], hi[0], lo[1], hi[1]), lo[2], hi[2], er, td)
    for b in d['pec']:
        lo, hi = pl.box(b)
        s.box((lo[0], hi[0], lo[1], hi[1]), lo[2], hi[2])
    Ri = pl.R.T
    for zl, m in d['sheets']:
        a = int(np.argmax(np.abs(pl.R[:, 2])))
        coord = pl.R[a, 2] * zl + pl.t[a]

        def inside(X, Y, Z, m=m):
            lx = Ri[0, 0] * (X - pl.t[0]) + Ri[0, 1] * (Y - pl.t[1]) + Ri[0, 2] * (Z - pl.t[2])
            ly = Ri[1, 0] * (X - pl.t[0]) + Ri[1, 1] * (Y - pl.t[1]) + Ri[1, 2] * (Z - pl.t[2])
            return m(lx, ly)
        s.plane('xyz'[a], round(coord, 4), inside)
    if 'coil' in d:
        p, q, Lh = d['coil']
        s.add_inductor(s.edge(pl.g(p), pl.g(q)), Lh)
    for p, q, R, port in d['lumped']:
        s.add_lumped(s.edge(pl.g(p), pl.g(q)), R, port=port)


def wallet_lines(pl, margin=1.0, d=None):
    """Grid regions per axis: 0.5 mm over the wallet, 0.25 mm over any d['fine'] box."""
    lo, hi = pl.bbox()
    fine = [[(lo[n] - margin, hi[n] + margin, 0.5)] for n in range(3)]
    for b in (d or {}).get('fine', []):
        blo, bhi = pl.box(b)
        for n in range(3):
            fine[n].append((blo[n], bhi[n], 0.25))
    return fine


# ------------------------------------------------------------------ fixtures (global coordinates)
# Board top copper at z = 0. The 80 x 80 mm test area is centred on (0, 0).

CPS = dict(gap=90.0, strip=25.0, straight=45.0, taper_end=95.0, tip_w=10.0)


def cps_inside(X, Y, Z):
    c = CPS
    ay = np.abs(Y)
    t = np.clip((ay - c['straight']) / (c['taper_end'] - c['straight']), 0, 1)
    inner = c['gap'] / 2 + (0.5 - c['gap'] / 2) * t
    outer = c['gap'] / 2 + c['strip'] + (c['tip_w'] - c['gap'] / 2 - c['strip']) * t
    ax = np.abs(X)
    return (ay <= c['taper_end'] + E) & (ax >= inner - E) & (ax <= outer + E)


def build_cps(pl=None, d=None):
    xe = CPS['gap'] / 2 + CPS['strip']
    ye = CPS['taper_end']
    fine = [(-12, 12, 0.5)]
    fy = [(-ye - 3, -ye + 8, 0.5), (ye - 8, ye + 3, 0.5)]
    fz = [(-2.0, 2.0, 0.5)]
    if pl is not None:
        w = wallet_lines(pl, d=d)
        fine += w[0]
        fy += w[1]
        fz += w[2]
    x = axis([0, -xe, xe], fine + [(-xe - 2, xe + 2, 1.0)], -xe - 25, xe + 25, base=1.0, maxstep=3.0)
    y = axis([0, -ye, ye], fy + [(-ye - 2, ye + 2, 1.0)], -ye - 25, ye + 25, base=1.0, maxstep=3.0)
    z = axis([0.0, -1.5], fz + [(-2.0, 40.0, 1.0)], -25.0, 60.0, base=1.0, maxstep=3.0)
    s = Sim(x, y, z)
    s.dielectric((-xe, xe, -ye - 5, ye + 5), -1.5, 0.0, 4.4, 0.02)
    s.plane('z', 0.0, cps_inside)
    i0, i1, i2 = s.ni('x', -0.5), s.ni('x', 0.0), s.ni('x', 0.5)
    for yp, src in ((-ye, True), (ye, False)):
        j, k = s.ni('y', yp), s.ni('z', 0.0)
        s.pec['x'][i0:i2, j, k] = True                 # bridge to the GND tip, the port on its first edge
        s.pec['x'][i1, j, k] = False
        s.add_lumped(('x', i1, j, k), 50.0, port=src, probe=not src)
    if pl is not None:
        put_wallet(s, d, pl)
    return s


TEM = dict(w=100.0, length=100.0, ramp=50.0, tip_z=0.5, tip_w=2.5, base_w=140.0)


def build_tem(h, pl=None, d=None):
    c = TEM
    hl = c['length'] / 2
    ye = hl + c['ramp']
    fine = [(-6, 6, 0.5)]
    fy = [(-ye - 3, -ye + 6, 0.5), (ye - 6, ye + 3, 0.5)]
    fz = [(-0.5, 2.0, 0.5)]
    if pl is not None:
        w = wallet_lines(pl, d=d)
        fine += w[0]
        fy += w[1]
        fz += w[2]
    bx = c['base_w'] / 2
    x = axis([0, -bx, bx, -c['w'] / 2, c['w'] / 2], fine + [(-bx - 2, bx + 2, 1.0)], -bx - 25, bx + 25,
             base=1.0, maxstep=3.0)
    y = axis([0, -hl, hl, -ye, ye, -ye - 8, ye + 8], fy + [(-ye - 10, ye + 10, 1.0)], -ye - 35, ye + 35,
             base=1.0, maxstep=3.0)
    z = axis([0.0, c['tip_z'], h], fz + [(-1.0, h + 5, 1.0)], -20.0, h + 35.0, base=1.0, maxstep=3.0)
    s = Sim(x, y, z)
    s.plane('z', 0.0, lambda X, Y, Z: (np.abs(X) <= bx + E) & (np.abs(Y) <= ye + 8 + E))
    s.plane('z', h, lambda X, Y, Z: (np.abs(X) <= c['w'] / 2 + E) & (np.abs(Y) <= hl + E))
    for sgn in (-1, 1):
        ramp(s, sgn, hl, ye, h)
    for sgn, src in ((-1, True), (1, False)):
        s.add_lumped(s.edge((0.0, sgn * ye, 0.0), (0.0, sgn * ye, c['tip_z'])), 50.0, port=src, probe=not src)
    if pl is not None:
        put_wallet(s, d, pl)
    return s


def ramp(s, sgn, y0, y1, h):
    """Staircased plate from (|y| = y0, z = h, width w) down to (|y| = y1, tip_z, tip_w)."""
    c = TEM
    js = np.where((np.abs(s.y) >= y0 - E) & (np.abs(s.y) <= y1 + E) & (np.sign(s.y) == sgn))[0]
    js = js if sgn > 0 else js[::-1]
    prev = None
    for j in js:
        u = (abs(s.y[j]) - y0) / (y1 - y0)
        k = int(np.argmin(np.abs(s.z - (h + (c['tip_z'] - h) * u))))
        if u >= 1 - E:
            k = s.ni('z', c['tip_z'])
        w = c['w'] + (c['tip_w'] - c['w']) * u
        inx = np.abs(s.x) <= w / 2 + E
        ii = np.where(inx)[0]
        s.pec['x'][ii[0]:ii[-1], j, k] = True
        if prev is not None:
            pj, pk, pii = prev
            both = np.intersect1d(ii, pii)
            jl = min(j, pj)
            s.pec['y'][both, jl, pk] = True
            k0, k1 = sorted((pk, k))
            s.pec['z'][np.ix_(ii, [j], range(k0, k1))] = True
        prev = (j, k, ii)


# ------------------------------------------------------------------ cases

def write_s2p(path, f, s11, s21, comment=''):
    with open(path, 'w') as fh:
        fh.write('! %s\n! simulated by sim/fixtures_fdtd.py (S12 = S21, S22 not computed)\n# HZ S RI R 50\n'
                 % comment)
        for fi, a, b in zip(f, s11, s21):
            fh.write('%d %.7f %.7f %.7f %.7f %.7f %.7f 0 0\n' % (fi, a.real, a.imag, b.real, b.imag, b.real, b.imag))


FIXTURES = {
    # name: (builder, z0 of the wallet's lowest point for flat placements, orientations)
    'cps_z2': (lambda pl, d: build_cps(pl, d), 2.0, ('flat0', 'flat90')),
    'cps_z12': (lambda pl, d: build_cps(pl, d), 12.0, ('flat0', 'flat90')),
    'tem_h20': (lambda pl, d: build_tem(20.0, pl, d), 2.0, ('flat0', 'flat90')),
    'tem_h25': (lambda pl, d: build_tem(25.0, pl, d), 0.5, ('edge',)),
}
PLACES = {   # placements over the 80 x 80 area: centre and shifted across the wallet's short side
    'flat0': [(0.0, 0.0), (0.0, 28.0)],
    'flat90': [(0.0, 0.0), (28.0, 0.0)],
    'edge': [(0.0, 0.0), (28.0, 0.0)],
}


KINDS = os.environ.get('SIM_KINDS', 'genuine,tampered').split(',')


def case_list():
    out = []
    for fx, (_, z0, orients) in FIXTURES.items():
        out.append((fx, None, None, None))
        for o in orients:
            for p in PLACES[o]:
                for kind in KINDS:
                    out.append((fx, o, p, kind))
    return out


def run_case(args):
    fx, o, p, kind, threads = args
    builder, z0, _ = FIXTURES[fx]
    if o is None:
        name = '%s_empty' % fx
        s = builder(None, None)
    else:
        name = '%s_%s_%+03.0f%+03.0f_%s' % (fx, o, p[0], p[1], kind)
        if kind == 'grand':
            d = wallet_grand('tampered')
        elif kind == 'gref':                           # genuine on the grand case's refined grid
            d = dict(wallet('genuine'), fine=wallet_grand('tampered')['fine'])
        else:
            d = wallet(kind)
        s = builder(Place(o, p[0], p[1], z0), d)
    t = time.time()
    f, S11, Z = s.run(t_end=float(os.environ.get('SIM_TEND', '45e-9')), fmin=0.3e9, fmax=3.0e9, nf=541,
                      threads=threads)
    os.makedirs(OUT, exist_ok=True)
    write_s2p(os.path.join(OUT, name + '.s2p'), f, S11, s.S21[0], name)
    return name, time.time() - t, int(np.prod(s.n)), s.tail


def tune(coils_nh):
    """Tampered wallet alone in free space, fed at the antenna feed: where is it resonant?"""
    a0 = A0
    for lnh in coils_nh:
        pl = Place('flat0', 0.0, 0.0, 0.0)
        w = wallet_lines(pl, 1.0)
        x = axis([0.0], w[0], -70, 70, base=1.0, maxstep=3.0)
        y = axis([0.0], w[1], -50, 50, base=1.0, maxstep=3.0)
        z = axis([0.0], w[2], -45, 55, base=1.0, maxstep=3.0)
        s = Sim(x, y, z)
        d = wallet('antenna', a0, match_l=lnh * 1e-9)
        d['pec'].append(BATTERY)
        d['sheets'].append((MAIN_PCB[4], rects_mask([MAIN_PCB[:4]])))
        put_wallet(s, d, pl)
        t = time.time()
        f, S, Z = s.run(t_end=25e-9, fmin=0.3e9, fmax=3.0e9, nf=541, threads=int(os.environ.get('SIM_THREADS', '16')))
        db = 20 * np.log10(np.abs(S))
        m = (f > 0.5e9) & (f < 1.2e9)
        i = np.argmin(np.where(m, db, 0))
        print('L=%4.0f nH  A0=%5.1f  runs=%2d  min |S11| %.1f dB at %.0f MHz  Z=%.0f%+.0fj  (%.0f s, %d cells, tail %.1e)' % (
            lnh, a0, sum(1 for r in meander(a0) if r[3] - r[2] > 2), db[i], f[i] / 1e6, Z[i].real, Z[i].imag,
            time.time() - t, np.prod(s.n), s.tail), flush=True)
        os.makedirs(OUT, exist_ok=True)
        write_s2p(os.path.join(OUT, 'tune_L%gnH.s2p' % lnh), f, S, np.zeros_like(S), 'tampered alone, coil %g nH' % lnh)


def tune_grand(cases):
    """Grand-style wallet alone in free space, fed at the modem: resonance vs. turn coupling
    and height over the board. cases: 'eps' or 'eps:height' strings."""
    for c in cases:
        eps, h = (list(map(float, c.split(':'))) + [G_HEIGHT])[:2]
        pl = Place('flat0', 0.0, 0.0, 0.0)
        d = wallet_grand('antenna', eps, h)
        w = wallet_lines(pl, 1.0, d)
        x = axis([0.0], w[0], -70, 70, base=1.0, maxstep=3.0)
        y = axis([0.0], w[1], -50, 50, base=1.0, maxstep=3.0)
        z = axis([0.0], w[2], -45, 55, base=1.0, maxstep=3.0)
        s = Sim(x, y, z)
        put_wallet(s, d, pl)
        t = time.time()
        f, S, Z = s.run(t_end=40e-9, fmin=0.3e9, fmax=3.0e9, nf=541, threads=int(os.environ.get('SIM_THREADS', '16')))
        db = 20 * np.log10(np.abs(S))
        m = (f > 0.4e9) & (f < 2.0e9)
        i = np.argmin(np.where(m, db, 0))
        print('eps %4.1f  h %.2f  min |S11| %.1f dB at %.0f MHz  Z=%.0f%+.0fj  (%.0f s, %d cells, tail %.1e)' % (
            eps, h, db[i], f[i] / 1e6, Z[i].real, Z[i].imag, time.time() - t, np.prod(s.n), s.tail), flush=True)
        os.makedirs(OUT, exist_ok=True)
        write_s2p(os.path.join(OUT, 'tune_grand_eps%g_h%g.s2p' % (eps, h)), f, S, np.zeros_like(S),
                  'grand-style spiral alone, coupling slab eps %g, %g mm over the board' % (eps, h))


def main():
    import multiprocessing as mp
    threads = int(os.environ.get('SIM_THREADS', '8'))
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    cases = [c + (threads,) for c in case_list() if not only or c[0] in only]
    cases.sort(key=lambda c: c[1] is not None)       # empty fixtures first: quick sanity check
    procs = int(os.environ.get('SIM_PROCS', '8'))
    with mp.get_context('spawn').Pool(procs) as pool:
        for name, dt, ncell, tail in pool.imap_unordered(run_case, cases):
            print('%-40s %6.0f s  %d cells  tail %.1e' % (name, dt, ncell, tail), flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'tune':
        tune([float(a) for a in sys.argv[2:]] or [MATCH_L * 1e9])
    elif len(sys.argv) > 1 and sys.argv[1] == 'tune-grand':
        tune_grand(sys.argv[2:] or [str(G_EPS)])
    else:
        main()
