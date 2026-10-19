#!/usr/bin/env python3
"""3D electrostatic model of the capacitive array over a (tampered) wallet.

Node-based finite-volume Laplace solver on a rectilinear grid (scipy sparse +
pyamg). Conductors are node sets held at fixed potential; floating conductors
(battery pouch, wallet PCB, antenna) are handled exactly through the Maxwell
capacitance matrix:  C_eff_i = C_ii - C_iF C_FF^-1 C_Fi  (others grounded).

Coordinates are detector-board millimetres (see hardware/detector): x along the
board, y across, z up. z = 0 is the electrode plane (board bottom), the wallet
lies below it (z < 0) with its plastic back against the board.

    python3 sim/electrostatic.py            # runs all scenarios, writes sim/results/
    python3 sim/electrostatic.py grand      # only the spiral-implant variant, merged into the results
"""
import json
import os
import sys
import time

import numpy as np
import pyamg
import scipy.sparse as sp

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'results')
# conductances are eps_r * mm^2 / mm = mm; eps0 = 8.854e-12 F/m = 8.854 fF/mm
EPS0_FF_PER_MM = 8.8541878128

# ---------------------------------------------------------------- geometry (mm)
ELECTRODES = {e: (15 + ((e - 1) % 4) * 17, 4 + ((e - 1) // 4) * 20) for e in range(1, 9)}  # lower-left corner
EL_SIZE = 14.0
IN1_Z = 1.3          # GND shield plane behind the electrodes
BOARD_T = 1.6
BOARD = (12.0, 105.0, 0.0, 40.0)   # head of the board (x0, x1, y0, y1), clipped to domain
EPS_FR4, EPS_CASE, EPS_FPC = 4.4, 3.0, 3.4

# wallet: Nano-X-like shell 72 x 18.6 mm, centred under electrode row 0
DEV = (12.0, 84.0, 1.7, 20.3)
# antenna estimated from the photo: feed patch 12 x 15 at one end + 30 x 6.5 arm
ANT_PATCH = (70.0, 82.0, 3.5, 18.5)
ANT_ARM = (40.0, 70.0, 12.0, 18.5)
GLUE = 0.05          # adhesive between shell and whatever is glued to it
FPC_T = 0.15         # antenna flex thickness (copper ~ in the middle)
BATT_T = 4.0
BATTERIES = {        # pouch footprints to test
    'batt_covers_all': (39.0, 83.0, 3.0, 19.0),     # antenna entirely within the battery's outline
    'batt_35x15': (38.0, 73.0, 3.5, 18.5),          # arm within the outline, most of the feed patch outside it
}
PCB_PLATE = (16.0, 80.0, 3.3, 18.3)   # wallet main board ground, below the battery
# second implant variant (Joe Grand's Nano X implant): the 44 mm battery replaced by a 26 mm
# one, the implant board and a 6-turn spiral of touching enamelled wire in the freed space.
# At the FDC2214's ~6 MHz the touching turns act as one ~6 x 6 mm plate.
G_BATTERY = (39.0, 65.0, 3.0, 19.0)
G_BOARD = (66.0, 77.5, 4.0, 17.0)     # implant board ground plane
G_SPIRAL = (78.0, 83.5, 5.0, 10.5)
G_BOARD_D, G_SPIRAL_D = 1.5, 1.0      # depth below the shell's inner face


def axis(fixed, fine_ranges, lo, hi, base=0.5, grow=1.35, maxstep=3.0):
    """Rectilinear axis: `base` spacing inside fine ranges, growing outside."""
    pts = set(round(v, 4) for v in fixed)
    for a, b, h in fine_ranges:
        n = int(round((b - a) / h))
        pts.update(round(a + i * (b - a) / n, 4) for i in range(n + 1))
    core = sorted(p for p in pts if lo <= p <= hi)
    # fill gaps larger than base inside the core extent
    out = [core[0]]
    for p in core[1:]:
        while p - out[-1] > base + 1e-9:
            out.append(round(out[-1] + base, 4))
        if p - out[-1] > 1e-6:
            out.append(p)
    # grow towards the domain limits
    h = base
    while out[0] > lo + 1e-9:
        h = min(h * grow, maxstep)
        out.insert(0, max(lo, round(out[0] - h, 4)))
    h = base
    while out[-1] < hi - 1e-9:
        h = min(h * grow, maxstep)
        out.append(min(hi, round(out[-1] + h, 4)))
    return np.array(out)


class Model:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z
        self.eps = np.ones((len(x) - 1, len(y) - 1, len(z) - 1))
        self.label = np.zeros((len(x), len(y), len(z)), dtype=np.int16)  # 0 free, -1 ground, k conductor
        self.names = {}
        self.label[[0, -1], :, :] = -1
        self.label[:, [0, -1], :] = -1
        self.label[:, :, [0, -1]] = -1

    def _rng(self, a, lo, hi, cells=False):
        if cells:
            c = (a[:-1] + a[1:]) / 2
            return np.where((c >= lo) & (c <= hi))[0]
        return np.where((a >= lo - 1e-6) & (a <= hi + 1e-6))[0]

    def dielectric(self, box, z0, z1, eps):
        ix = self._rng(self.x, box[0], box[1], True)
        iy = self._rng(self.y, box[2], box[3], True)
        iz = self._rng(self.z, z0, z1, True)
        self.eps[np.ix_(ix, iy, iz)] = eps

    def conductor(self, name, box, z0, z1=None, ground=False):
        z1 = z0 if z1 is None else z1
        ix = self._rng(self.x, box[0], box[1])
        iy = self._rng(self.y, box[2], box[3])
        iz = self._rng(self.z, z0, z1)
        if not len(iz):
            raise ValueError('no z node for %s at %s' % (name, z0))
        if ground:
            k = -1
        else:
            k = self.names.setdefault(name, len(self.names) + 1)
        self.label[np.ix_(ix, iy, iz)] = k
        return k

    def assemble(self):
        x, y, z = self.x, self.y, self.z
        nx, ny, nz = len(x), len(y), len(z)
        dx, dy, dz = np.diff(x), np.diff(y), np.diff(z)
        ep = np.zeros((nx + 1, ny + 1, nz + 1))
        ep[1:-1, 1:-1, 1:-1] = self.eps
        dxp, dyp, dzp = (np.concatenate([[0], d, [0]]) for d in (dx, dy, dz))
        idx = np.arange(nx * ny * nz).reshape(nx, ny, nz)
        rows, cols, vals = [], [], []

        def faces(axis_):
            # conductance between node n and its +axis neighbour: sum over the 4 cells around that edge
            if axis_ == 0:
                e = ep[1:-1, :, :]
                g = (e[:, :-1, :-1] * dyp[:-1, None] * dzp[None, :-1] + e[:, 1:, :-1] * dyp[1:, None] * dzp[None, :-1]
                     + e[:, :-1, 1:] * dyp[:-1, None] * dzp[None, 1:] + e[:, 1:, 1:] * dyp[1:, None] * dzp[None, 1:]) / 4
                return g / dx[:, None, None], idx[:-1], idx[1:]
            if axis_ == 1:
                e = ep[:, 1:-1, :]
                g = (e[:-1, :, :-1] * dxp[:-1, None, None] * dzp[None, None, :-1] + e[1:, :, :-1] * dxp[1:, None, None] * dzp[None, None, :-1]
                     + e[:-1, :, 1:] * dxp[:-1, None, None] * dzp[None, None, 1:] + e[1:, :, 1:] * dxp[1:, None, None] * dzp[None, None, 1:]) / 4
                return g / dy[None, :, None], idx[:, :-1], idx[:, 1:]
            e = ep[:, :, 1:-1]
            g = (e[:-1, :-1, :] * dxp[:-1, None, None] * dyp[None, :-1, None] + e[1:, :-1, :] * dxp[1:, None, None] * dyp[None, :-1, None]
                 + e[:-1, 1:, :] * dxp[:-1, None, None] * dyp[None, 1:, None] + e[1:, 1:, :] * dxp[1:, None, None] * dyp[None, 1:, None]) / 4
            return g / dz[None, None, :], idx[:, :, :-1], idx[:, :, 1:]

        diag = np.zeros(nx * ny * nz)
        for a in range(3):
            g, i0, i1 = faces(a)
            g, i0, i1 = g.ravel(), i0.ravel(), i1.ravel()
            rows += [i0, i1]
            cols += [i1, i0]
            vals += [-g, -g]
            np.add.at(diag, i0, g)
            np.add.at(diag, i1, g)
        n = nx * ny * nz
        A = sp.coo_matrix((np.concatenate(vals + [diag]),
                           (np.concatenate(rows + [np.arange(n)]), np.concatenate(cols + [np.arange(n)]))),
                          shape=(n, n)).tocsr()
        self.A = A
        lab = self.label.ravel()
        self.free = np.where(lab == 0)[0]
        self.Aff = A[self.free][:, self.free].tocsr()
        self.Afd = A[self.free]
        self.lab = lab
        t = time.time()
        self.ml = pyamg.smoothed_aggregation_solver(self.Aff, symmetry='symmetric', max_coarse=500)
        self.setup_time = time.time() - t

    def capacitance_matrix(self, drive):
        """Maxwell matrix (fF) between the named conductors in `drive`; everything else grounded."""
        ids = [self.names[n] for n in drive]
        C = np.zeros((len(ids), len(ids)))
        for j, kj in enumerate(ids):
            phi = np.zeros(len(self.lab))
            phi[self.lab == kj] = 1.0
            rhs = -(self.Afd @ phi)
            res = []
            xf = self.ml.solve(rhs, tol=1e-10, accel='cg', residuals=res, maxiter=200)
            phi[self.free] = xf
            q = self.A @ phi
            for i, ki in enumerate(ids):
                C[i, j] = q[self.lab == ki].sum() * EPS0_FF_PER_MM
        return (C + C.T) / 2


def build(t_case, scenario, battery='batt_35x15', dz_gap=0.0, dx_shift=0.0, ant_grounded=False):
    """scenario: 'genuine' | 'tampered' | 'grand' | 'grand_tied' | 'plastic_only'.
    grand: the spiral implant variant (always with its shortened battery); grand_tied: its
    board ground joined to the wallet's board, as when the implant runs off the wallet's battery."""
    top = -dz_gap                 # outer face of the shell
    inner = top - t_case          # inner face
    zf = [0.0, IN1_Z, BOARD_T, top, inner, inner - GLUE, inner - GLUE - FPC_T - GLUE,
          inner - GLUE / 2 - FPC_T / 2, inner - GLUE - BATT_T, inner - 2 * GLUE - FPC_T - BATT_T, inner - 6.0,
          inner - G_BOARD_D, inner - G_SPIRAL_D]
    z = axis(zf, [(inner - 0.45, 0.05, 0.025), (0.05, BOARD_T, 0.1), (inner - 6.2, inner - 0.45, 0.25)],
             inner - 24.0, 16.0, base=0.25, grow=1.3, maxstep=3.0)
    xs = [v for e in ELECTRODES.values() for v in (e[0], e[0] + EL_SIZE)] + list(ANT_PATCH[:2]) + list(ANT_ARM[:2])
    ys = [v for e in ELECTRODES.values() for v in (e[1], e[1] + EL_SIZE)] + list(ANT_PATCH[2:]) + list(ANT_ARM[2:])
    xs += list(G_BATTERY[:2]) + list(G_BOARD[:2]) + list(G_SPIRAL[:2])
    ys += list(G_BATTERY[2:]) + list(G_BOARD[2:]) + list(G_SPIRAL[2:])
    x = axis(xs, [(8, 92, 0.5)], -10.0, 110.0, base=0.5)
    y = axis(ys, [(-2, 44, 0.5)], -16.0, 58.0, base=0.5)
    m = Model(x, y, z)
    sx = dx_shift
    shift = lambda b: (b[0] + sx, b[1] + sx, b[2], b[3])
    # detector board
    m.dielectric(BOARD, 0.0, BOARD_T, EPS_FR4)
    m.conductor('in1', BOARD, IN1_Z, ground=True)
    for e, (ex, ey) in ELECTRODES.items():
        m.conductor('E%d' % e, (ex, ex + EL_SIZE, ey, ey + EL_SIZE), 0.0)
    # wallet shell
    m.dielectric(shift(DEV), inner, top, EPS_CASE)
    if scenario == 'plastic_only':
        return m
    if scenario.startswith('grand'):
        m.dielectric(shift(G_BATTERY), inner - GLUE, inner, EPS_FPC)
        m.conductor('battery', shift(G_BATTERY), inner - GLUE - BATT_T, inner - GLUE)
        m.dielectric(shift((G_BOARD[0], G_SPIRAL[1], G_BOARD[2], G_BOARD[3])), inner - G_BOARD_D, inner, EPS_FPC)
        m.conductor('pcb' if scenario == 'grand_tied' else 'implant', shift(G_BOARD), inner - G_BOARD_D)
        m.conductor('antenna', shift(G_SPIRAL), inner - G_SPIRAL_D)
        m.conductor('pcb', shift(PCB_PLATE), inner - 6.0)
        return m
    bx = shift(BATTERIES[battery])
    if scenario == 'tampered':
        for part in (ANT_PATCH, ANT_ARM):
            p = shift(part)
            m.dielectric((p[0] - 0.5, p[1] + 0.5, p[2] - 0.5, p[3] + 0.5), inner - GLUE - FPC_T, inner, EPS_FPC)
            m.conductor('antenna', p, inner - GLUE / 2 - FPC_T / 2, ground=ant_grounded)
        btop = inner - 2 * GLUE - FPC_T
    else:
        btop = inner - GLUE
    m.dielectric(bx, btop, inner, EPS_FPC)       # adhesive layer between shell and pouch (approx.)
    m.conductor('battery', bx, btop - BATT_T, btop)
    m.conductor('pcb', shift(PCB_PLATE), inner - 6.0)
    return m


def effective(m, floats):
    names = ['E%d' % e for e in ELECTRODES] + [f for f in floats if f in m.names]
    C = m.capacitance_matrix(names)
    ne = len(ELECTRODES)
    out = {}
    F = list(range(ne, len(names)))
    for i in range(ne):
        if F:
            ciF = C[i, F]
            out['E%d' % (i + 1)] = C[i, i] - ciF @ np.linalg.solve(C[np.ix_(F, F)], ciF)
        else:
            out['E%d' % (i + 1)] = C[i, i]
    return out


def run(t_case, scenario, **kw):
    t0 = time.time()
    m = build(t_case, scenario, **kw)
    m.assemble()
    floats = ['battery', 'pcb', 'implant'] + ([] if kw.get('ant_grounded') else ['antenna'])
    c = effective(m, floats)
    print('  %-48s %7.1fs  nodes=%d' % ('%s t=%.1f %s' % (scenario, t_case, kw), time.time() - t0, len(m.lab)), flush=True)
    return c


def _job(args):
    key, sub, t, scenario, kw = args
    return key, sub, run(t, scenario, **kw)


def jobs():
    out = []
    for t in (1.0, 0.6):
        for batt in BATTERIES:
            key = 't%.1f_%s' % (t, batt)
            out += [(key, 'genuine', t, 'genuine', {'battery': batt}),
                    (key, 'tampered', t, 'tampered', {'battery': batt}),
                    (key, 'tampered_ant_grounded', t, 'tampered', {'battery': batt, 'ant_grounded': True})]
        key = 't%.1f_grand' % t
        out += [(key, 'genuine', t, 'genuine', {'battery': 'batt_covers_all'}),
                (key, 'grand', t, 'grand', {}),
                (key, 'grand_tied', t, 'grand_tied', {})]
        # placement repeatability of a genuine unit: 0.1 mm air gap, 0.5 mm slide along x
        key = 't%.1f_repeat' % t
        out += [(key, 'genuine', t, 'genuine', {}),
                (key, 'gap_0.1mm', t, 'genuine', {'dz_gap': 0.1}),
                (key, 'slide_0.5mm', t, 'genuine', {'dx_shift': 0.5})]
    return out


def main(only=None):
    """only: run just the jobs whose key contains this string, merged into the existing results."""
    import multiprocessing as mp
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'electrostatic.json')
    results = json.load(open(path)) if only and os.path.exists(path) else {}
    todo = [j for j in jobs() if not only or only in j[0]]
    with mp.get_context('spawn').Pool(int(os.environ.get('SIM_PROCS', '18'))) as pool:
        for key, sub, c in pool.imap_unordered(_job, todo):
            results.setdefault(key, {})[sub] = c
    with open(os.path.join(OUT, 'electrostatic.json'), 'w') as f:
        json.dump(results, f, indent=1, sort_keys=True)
    report(results)


def report(results):
    lines = []
    els = ['E%d' % e for e in range(1, 5)]
    lines.append('Capacitance change per electrode (fF), row under the wallet (E1..E4). Instrument floor ~0.3 fF.')
    for t in (1.0, 0.6):
        lines.append('')
        lines.append('=== shell %.1f mm ===' % t)
        rep = results['t%.1f_repeat' % t]
        for k in ('gap_0.1mm', 'slide_0.5mm'):
            d = [rep[k][e] - rep['genuine'][e] for e in els]
            lines.append('  genuine, %-30s ' % k + ' '.join('%8.2f' % v for v in d))
        for batt in BATTERIES:
            r = results['t%.1f_%s' % (t, batt)]
            for k in ('tampered', 'tampered_ant_grounded'):
                d = [r[k][e] - r['genuine'][e] for e in els]
                lines.append('  %-38s ' % ('%s, %s' % (batt, k)) + ' '.join('%8.2f' % v for v in d))
        r = results.get('t%.1f_grand' % t, {})
        for k in ('grand', 'grand_tied'):
            if k in r:
                d = [r[k][e] - r['genuine'][e] for e in els]
                lines.append('  %-38s ' % ('spiral implant, %s' % k) + ' '.join('%8.2f' % v for v in d))
        lines.append('  absolute C (genuine) ' + ' ' * 17 + ' '.join('%8.0f' % rep['genuine'][e] for e in els))
    txt = '\n'.join(lines)
    print(txt)
    with open(os.path.join(OUT, 'electrostatic.txt'), 'w') as f:
        f.write(txt + '\n')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'report':
        report(json.load(open(os.path.join(OUT, 'electrostatic.json'))))
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else None)
