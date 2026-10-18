#!/usr/bin/env python3
"""FDTD model of the detector's near-field loop over a wallet (genuine / tampered).

Yee scheme on a rectilinear grid, numba-parallel kernels, graded absorbing
layers on all sides, lumped 50 ohm port at the loop gap (Thevenin source) and a
lumped 50 ohm element for the antenna's coax termination. Writes Touchstone
.s1p files in sim/results/rf/ so they can go straight into tools/analyze_s1p.py,
exactly like NanoVNA measurements.

Coordinates: wallet millimetres (x along the 72 mm shell, y across), z up,
z = 0 is the shell's outer face = detector bottom copper (B.Cu).

    python3 sim/rf_fdtd.py                 # all scenarios (parallel processes)
    python3 sim/rf_fdtd.py selftest        # bare loop vs analytic inductance
"""
import math
import os
import sys
import time

import numpy as np
from numba import njit, prange, set_num_threads

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'results', 'rf')
C0 = 299792458e3        # mm/s
EPS0 = 8.8541878128e-15  # F/mm
MU0 = 1.25663706212e-9   # H/mm
ETA0 = 376.730313668

# ------------------------------------------------------------------ kernels


@njit(parallel=True, cache=True)
def update_h(Hx, Hy, Hz, Ex, Ey, Ez, dax, dbx, day, dby, daz, dbz, idx, idy, idz):
    nx1, ny, nz = Hx.shape
    for i in prange(nx1):
        for j in range(ny):
            for k in range(nz):
                Hx[i, j, k] = dax[i, j, k] * Hx[i, j, k] - dbx[i, j, k] * (
                    (Ez[i, j + 1, k] - Ez[i, j, k]) * idy[j] - (Ey[i, j, k + 1] - Ey[i, j, k]) * idz[k])
    nx, ny1, nz = Hy.shape
    for i in prange(nx):
        for j in range(ny1):
            for k in range(nz):
                Hy[i, j, k] = day[i, j, k] * Hy[i, j, k] - dby[i, j, k] * (
                    (Ex[i, j, k + 1] - Ex[i, j, k]) * idz[k] - (Ez[i + 1, j, k] - Ez[i, j, k]) * idx[i])
    nx, ny, nz1 = Hz.shape
    for i in prange(nx):
        for j in range(ny):
            for k in range(nz1):
                Hz[i, j, k] = daz[i, j, k] * Hz[i, j, k] - dbz[i, j, k] * (
                    (Ey[i + 1, j, k] - Ey[i, j, k]) * idx[i] - (Ex[i, j + 1, k] - Ex[i, j, k]) * idy[j])


@njit(parallel=True, cache=True)
def update_e(Ex, Ey, Ez, Hx, Hy, Hz, cax, cbx, cay, cby, caz, cbz, idxd, idyd, idzd):
    nx, ny1, nz1 = Ex.shape
    for i in prange(nx):
        for j in range(1, ny1 - 1):
            for k in range(1, nz1 - 1):
                Ex[i, j, k] = cax[i, j, k] * Ex[i, j, k] + cbx[i, j, k] * (
                    (Hz[i, j, k] - Hz[i, j - 1, k]) * idyd[j] - (Hy[i, j, k] - Hy[i, j, k - 1]) * idzd[k])
    nx1, ny, nz1 = Ey.shape
    for i in prange(1, nx1 - 1):
        for j in range(ny):
            for k in range(1, nz1 - 1):
                Ey[i, j, k] = cay[i, j, k] * Ey[i, j, k] + cby[i, j, k] * (
                    (Hx[i, j, k] - Hx[i, j, k - 1]) * idzd[k] - (Hz[i, j, k] - Hz[i - 1, j, k]) * idxd[i])
    nx1, ny1, nz = Ez.shape
    for i in prange(1, nx1 - 1):
        for j in range(1, ny1 - 1):
            for k in range(nz):
                Ez[i, j, k] = caz[i, j, k] * Ez[i, j, k] + cbz[i, j, k] * (
                    (Hy[i, j, k] - Hy[i - 1, j, k]) * idxd[i] - (Hx[i, j, k] - Hx[i, j - 1, k]) * idyd[j])


# ------------------------------------------------------------------ grid / model


def axis(fixed, fine, lo, hi, base, grow=1.3, maxstep=None):
    """Monotonic coordinate list containing `fixed`, spacing `h` inside each
    (a, b, h) of `fine`, `base` elsewhere in [min fine, max fine], growing outside."""
    maxstep = maxstep or 4 * base
    pts = set(round(v, 4) for v in fixed)
    for a, b, h in fine:
        n = max(1, int(round((b - a) / h)))
        pts.update(round(a + i * (b - a) / n, 4) for i in range(n + 1))
    core = sorted(pts)
    out = [core[0]]
    for p in core[1:]:
        while p - out[-1] > base + 1e-9:
            out.append(round(out[-1] + base, 4))
        if p - out[-1] > 1e-6:
            out.append(p)
    h = base
    while out[0] > lo + 1e-9:
        h = min(h * grow, maxstep)
        out.insert(0, round(out[0] - h, 4))
    h = base
    while out[-1] < hi - 1e-9:
        h = min(h * grow, maxstep)
        out.append(round(out[-1] + h, 4))
    # merge slivers, always keeping the requested planes
    fx = np.array(sorted(set(round(v, 4) for v in fixed)))
    a = np.array(out)
    tol = 0.5 * min(h for _, _, h in fine)
    near_fixed = np.array([1e-6 < np.min(np.abs(fx - v)) < tol for v in a])
    a = a[~near_fixed]
    keep = np.concatenate([[True], np.diff(a) > 0.02])
    return a[keep]


class Sim:
    def __init__(self, x, y, z, npml=10):
        # extend with uniform absorbing layers
        def ext(a):
            h0, h1 = a[1] - a[0], a[-1] - a[-2]
            return np.concatenate([a[0] - h0 * np.arange(npml, 0, -1), a, a[-1] + h1 * np.arange(1, npml + 1)])
        self.x, self.y, self.z = ext(x), ext(y), ext(z)
        self.npml = npml
        self.core = (x[0], x[-1], y[0], y[-1], z[0], z[-1])
        nx, ny, nz = len(self.x) - 1, len(self.y) - 1, len(self.z) - 1
        self.n = (nx, ny, nz)
        self.epsr = np.ones((nx, ny, nz), np.float32)
        self.sig = np.zeros((nx, ny, nz), np.float32)     # S/mm
        self.pec = {c: np.zeros(s, bool) for c, s in (('x', (nx, ny + 1, nz + 1)), ('y', (nx + 1, ny, nz + 1)),
                                                       ('z', (nx + 1, ny + 1, nz)))}
        self.lumped = []   # (comp, i, j, k, R, is_port, is_probe)
        self.inductors = []  # (comp, i, j, k, L)

    # --- geometry helpers (snap to the grid) ---
    def _ci(self, a, lo, hi):
        c = (a[:-1] + a[1:]) / 2
        return np.where((c > lo) & (c < hi))[0]

    def _ni(self, a, lo, hi):
        return np.where((a >= lo - 1e-6) & (a <= hi + 1e-6))[0]

    def zi(self, z):
        return self.ni('z', z)

    def ni(self, ax, v):
        a = getattr(self, ax)
        i = int(np.argmin(np.abs(a - v)))
        if abs(a[i] - v) > 1e-3:
            raise ValueError('%s=%g not a grid plane' % (ax, v))
        return i

    def plane(self, normal, coord, inside):
        """PEC sheet in the plane `normal` = coord: every in-plane edge whose two end nodes
        satisfy inside(X, Y, Z) (X, Y, Z: node coordinates of that plane)."""
        i = self.ni(normal, coord)
        if normal == 'z':
            X, Y = np.meshgrid(self.x, self.y, indexing='ij')
            m = inside(X, Y, np.full_like(X, coord))
            self.pec['x'][:, :, i] |= m[:-1, :] & m[1:, :]
            self.pec['y'][:, :, i] |= m[:, :-1] & m[:, 1:]
        elif normal == 'y':
            X, Z = np.meshgrid(self.x, self.z, indexing='ij')
            m = inside(X, np.full_like(X, coord), Z)
            self.pec['x'][:, i, :] |= m[:-1, :] & m[1:, :]
            self.pec['z'][:, i, :] |= m[:, :-1] & m[:, 1:]
        else:
            Y, Z = np.meshgrid(self.y, self.z, indexing='ij')
            m = inside(np.full_like(Y, coord), Y, Z)
            self.pec['y'][i, :, :] |= m[:-1, :] & m[1:, :]
            self.pec['z'][i, :, :] |= m[:, :-1] & m[:, 1:]

    def edge(self, p, q):
        """The single Yee edge between grid nodes p and q (adjacent along one axis)."""
        a = [self.ni(ax, v) for ax, v in zip('xyz', p)]
        b = [self.ni(ax, v) for ax, v in zip('xyz', q)]
        d = [bb - aa for aa, bb in zip(a, b)]
        ax = [n for n in range(3) if d[n]]
        if len(ax) != 1 or abs(d[ax[0]]) != 1:
            raise ValueError('nodes %s %s are not neighbours' % (p, q))
        n = ax[0]
        lo = [min(aa, bb) for aa, bb in zip(a, b)]
        return ('xyz'[n], lo[0], lo[1], lo[2])

    def dielectric(self, box, z0, z1, er, tand=0.0, f0=1.5e9):
        ix, iy, iz = self._ci(self.x, box[0], box[1]), self._ci(self.y, box[2], box[3]), self._ci(self.z, z0, z1)
        self.epsr[np.ix_(ix, iy, iz)] = er
        self.sig[np.ix_(ix, iy, iz)] = 2 * math.pi * f0 * EPS0 * er * tand

    def sheet(self, z, inside):
        """PEC sheet in the plane z: every in-plane edge whose two end nodes satisfy inside(x, y)."""
        k = self.zi(z)
        X, Y = np.meshgrid(self.x, self.y, indexing='ij')
        m = inside(X, Y)
        self.pec['x'][:, :, k] |= m[:-1, :] & m[1:, :]
        self.pec['y'][:, :, k] |= m[:, :-1] & m[:, 1:]

    def box(self, b, z0, z1):
        """Solid PEC box (all edges inside or on the surface)."""
        ix, iy, iz = self._ni(self.x, b[0], b[1]), self._ni(self.y, b[2], b[3]), self._ni(self.z, z0, z1)
        sx = slice(ix[0], ix[-1] + 1)
        sy = slice(iy[0], iy[-1] + 1)
        sz = slice(iz[0], iz[-1] + 1)
        self.pec['x'][ix[0]:ix[-1], sy, sz] = True
        self.pec['y'][sx, iy[0]:iy[-1], sz] = True
        self.pec['z'][sx, sy, iz[0]:iz[-1]] = True

    def rect_sheet(self, b, z):
        self.sheet(z, lambda X, Y: (X >= b[0] - 1e-6) & (X <= b[1] + 1e-6) & (Y >= b[2] - 1e-6) & (Y <= b[3] + 1e-6))

    def loop(self, cx, cy, r, z, w=0.5):
        """Loop of a `w`-wide strip (needs ~0.25 mm cells), gap at the -y side; returns the port edge.
        The gap is bridged by one PEC edge and the lumped port edge, at the strip centre line."""
        k = self.zi(z)
        X, Y = np.meshgrid(self.x, self.y, indexing='ij')
        rr = np.hypot(X - cx, Y - cy)
        on = (rr >= r - w / 2 - 1e-6) & (rr <= r + w / 2 + 1e-6)
        ig = int(np.argmin(np.abs(self.x - cx)))
        on &= ~((np.abs(X - self.x[ig]) < 1e-6) & (Y < cy))          # cut one node column -> gap
        self.pec['x'][:, :, k] |= on[:-1, :] & on[1:, :]
        self.pec['y'][:, :, k] |= on[:, :-1] & on[:, 1:]
        jc = int(np.argmin(np.abs(self.y - (cy - r))))
        self.pec['x'][ig - 1, jc, k] = True                          # bridge: PEC edge + port edge
        return ('x', ig, jc, k)

    def add_lumped(self, edge, R, port=False, probe=False):
        """Lumped resistor on one edge; port=True makes it the Thevenin source, probe=True
        records the voltage across it (a terminated second port: S21 = 2 V / Vs)."""
        c, i, j, k = edge
        self.pec[c][i, j, k] = False
        self.lumped.append((c, i, j, k, R, port, probe))

    def add_inductor(self, edge, L):
        """Lumped inductor (henry) on one edge, e.g. a matching coil in series with a load."""
        c, i, j, k = edge
        self.pec[c][i, j, k] = False
        self.inductors.append((c, i, j, k, L))

    # --- run ---
    def prepare(self):
        x, y, z = self.x, self.y, self.z
        dx, dy, dz = np.diff(x), np.diff(y), np.diff(z)
        dxd = np.concatenate([[dx[0]], (dx[:-1] + dx[1:]) / 2, [dx[-1]]])
        dyd = np.concatenate([[dy[0]], (dy[:-1] + dy[1:]) / 2, [dy[-1]]])
        dzd = np.concatenate([[dz[0]], (dz[:-1] + dz[1:]) / 2, [dz[-1]]])
        self.d = (dx, dy, dz, dxd, dyd, dzd)
        self.dt = 0.98 / (C0 * math.sqrt(1 / dx.min() ** 2 + 1 / dy.min() ** 2 + 1 / dz.min() ** 2))
        dt = self.dt
        nx, ny, nz = self.n
        # edge-averaged materials
        ep = np.pad(self.epsr, 1, mode='edge')
        sg = np.pad(self.sig, 1, mode='edge')

        def avg(a, comp):
            if comp == 'x':
                return (a[1:-1, :-1, :-1] + a[1:-1, 1:, :-1] + a[1:-1, :-1, 1:] + a[1:-1, 1:, 1:]) / 4
            if comp == 'y':
                return (a[:-1, 1:-1, :-1] + a[1:, 1:-1, :-1] + a[:-1, 1:-1, 1:] + a[1:, 1:-1, 1:]) / 4
            return (a[:-1, :-1, 1:-1] + a[1:, :-1, 1:-1] + a[:-1, 1:, 1:-1] + a[1:, 1:, 1:-1]) / 4

        # absorbing-layer conductivity, graded (cubic), from position
        npml = self.npml
        x0, x1, y0, y1, z0, z1 = self.core

        def prof(a, lo, hi, h):
            if npml == 0:
                return np.zeros_like(a)
            L = npml * h
            d = np.maximum(np.maximum(lo - a, a - hi), 0) / L
            smax = 0.8 * 4 / (ETA0 * h)          # 1/ohm/mm
            return smax * np.minimum(d, 1) ** 3
        xc, yc, zc = (x[:-1] + x[1:]) / 2, (y[:-1] + y[1:]) / 2, (z[:-1] + z[1:]) / 2
        px = lambda a: prof(a, x0, x1, dx[0])
        py = lambda a: prof(a, y0, y1, dy[0])
        pz = lambda a: prof(a, z0, z1, dz[0])
        pos = {'x': (xc, y, z), 'y': (x, yc, z), 'z': (x, y, zc)}
        hpos = {'x': (x, yc, zc), 'y': (xc, y, zc), 'z': (xc, yc, z)}
        self.co = {}
        for c in 'xyz':
            ax_, ay_, az_ = pos[c]
            sabs = px(ax_)[:, None, None] + py(ay_)[None, :, None] + pz(az_)[None, None, :]
            e = avg(ep, c) * EPS0
            s = avg(sg, c) + sabs
            a = s * dt / (2 * e)
            ca = (1 - a) / (1 + a)
            cb = (dt / e) / (1 + a)
            ca[self.pec[c]] = 0
            cb[self.pec[c]] = 0
            self.co['ca' + c] = ca.astype(np.float32)
            self.co['cb' + c] = cb.astype(np.float32)
            hx_, hy_, hz_ = hpos[c]
            sm = (px(hx_)[:, None, None] + py(hy_)[None, :, None] + pz(hz_)[None, None, :]) * MU0 / EPS0
            am = sm * dt / (2 * MU0)
            self.co['da' + c] = ((1 - am) / (1 + am)).astype(np.float32)
            self.co['db' + c] = ((dt / MU0) / (1 + am)).astype(np.float32)
        # lumped elements: semi-implicit resistor (+ Thevenin source on the port)
        self.src = []
        self.probes = []
        for c, i, j, k, R, port, probe in self.lumped:
            if c == 'x':
                dl, A = dx[i], dyd[j] * dzd[k]
            elif c == 'y':
                dl, A = dy[j], dxd[i] * dzd[k]
            else:
                dl, A = dz[k], dxd[i] * dyd[j]
            e = avg(ep, c)[i, j, k] * EPS0
            a = dl * dt / (2 * R * A * e)
            self.co['ca' + c][i, j, k] = (1 - a) / (1 + a)
            self.co['cb' + c][i, j, k] = (dt / e) / (1 + a)
            if port:
                self.port = (c, i, j, k, dl, R, (dt / (e * R * A)) / (1 + a))
            if probe:
                self.probes.append((c, i, j, k, dl))
        self.coils = []
        for c, i, j, k, Lh in self.inductors:
            if c == 'x':
                dl, A = dx[i], dyd[j] * dzd[k]
            elif c == 'y':
                dl, A = dy[j], dxd[i] * dzd[k]
            else:
                dl, A = dz[k], dxd[i] * dyd[j]
            e = avg(ep, c)[i, j, k] * EPS0
            self.coils.append((c, i, j, k, dl, dt / Lh, dt / (e * A)))

    def run(self, t_end=30e-9, fmin=0.4e9, fmax=3.6e9, nf=641, threads=4, log=None):
        set_num_threads(threads)
        self.prepare()
        dx, dy, dz, dxd, dyd, dzd = self.d
        f32 = lambda a: np.ascontiguousarray(a, dtype=np.float32)
        idx, idy, idz, idxd, idyd, idzd = map(lambda a: f32(1 / a), (dx, dy, dz, dxd, dyd, dzd))
        nx, ny, nz = self.n
        Ex = np.zeros((nx, ny + 1, nz + 1), np.float32)
        Ey = np.zeros((nx + 1, ny, nz + 1), np.float32)
        Ez = np.zeros((nx + 1, ny + 1, nz), np.float32)
        Hx = np.zeros((nx + 1, ny, nz), np.float32)
        Hy = np.zeros((nx, ny + 1, nz), np.float32)
        Hz = np.zeros((nx, ny, nz + 1), np.float32)
        co = self.co
        c, i, j, k, dl, R, sc = self.port
        E = {'x': Ex, 'y': Ey, 'z': Ez}[c]
        dt = self.dt
        nsteps = int(t_end / dt)
        tau = math.sqrt(2.3) / (math.pi * fmax)
        t0 = 4.5 * tau
        V = np.zeros(nsteps)
        P = np.zeros((len(self.probes), nsteps))
        PE = [({'x': Ex, 'y': Ey, 'z': Ez}[pc], pi, pj, pk, pdl) for pc, pi, pj, pk, pdl in self.probes]
        CE = [({'x': Ex, 'y': Ey, 'z': Ez}[cc], ci, cj, ck, cdl, cg, cs) for cc, ci, cj, ck, cdl, cg, cs in self.coils]
        IL = [0.0] * len(CE)
        tstart = time.time()
        for n in range(nsteps):
            update_h(Hx, Hy, Hz, Ex, Ey, Ez, co['dax'], co['dbx'], co['day'], co['dby'], co['daz'], co['dbz'],
                     idx, idy, idz)
            ts = (n + 0.5) * dt
            vs = math.exp(-((ts - t0) / tau) ** 2)
            for m, (ca_, ci, cj, ck, cdl, cg, cs) in enumerate(CE):
                IL[m] += cg * ca_[ci, cj, ck] * cdl          # I^(n+1/2) = I^(n-1/2) + dt/L V^n
            update_e(Ex, Ey, Ez, Hx, Hy, Hz, co['cax'], co['cbx'], co['cay'], co['cby'], co['caz'], co['cbz'],
                     idxd, idyd, idzd)
            for m, (ca_, ci, cj, ck, cdl, cg, cs) in enumerate(CE):
                ca_[ci, cj, ck] -= cs * IL[m]
            E[i, j, k] += sc * vs
            V[n] = E[i, j, k] * dl
            for m, (pa, pi, pj, pk, pdl) in enumerate(PE):
                P[m, n] = pa[pi, pj, pk] * pdl
            if log and n and n % 5000 == 0:
                log('    step %d/%d  %.0f s' % (n, nsteps, time.time() - tstart))
        # discrete Thevenin relation of the semi-implicit port: I = (Vs^(n+1/2) - (V^n + V^(n+1))/2) / R
        Vh = (V + np.concatenate([[0.0], V[:-1]])) / 2
        th = (np.arange(nsteps) + 0.5) * dt
        Vsh = np.exp(-((th - t0) / tau) ** 2)
        dec = max(1, int(1 / (20 * fmax * dt)))          # decimate (signal is band-limited by the pulse)
        f = np.linspace(fmin, fmax, nf)
        ker = np.exp(-2j * np.pi * np.outer(f, th[::dec]))
        Vf = ker @ Vh[::dec]
        Vsf = ker @ Vsh[::dec]
        Z = Vf * R / (Vsf - Vf)
        S11 = (Z - R) / (Z + R)
        self.tail = float(np.abs(V[-nsteps // 20:]).max() / np.abs(V).max())
        # terminated probe ports: b2 = V2 (no incident wave), a1 = Vs / 2
        Ph = (P + np.concatenate([np.zeros((len(PE), 1)), P[:, :-1]], 1)) / 2
        self.S21 = [2 * (ker @ ph[::dec]) / Vsf for ph in Ph]
        return f, S11, Z


def write_s1p(path, f, s, comment=''):
    with open(path, 'w') as fh:
        fh.write('! %s\n! simulated by sim/rf_fdtd.py\n# HZ S RI R 50\n' % comment)
        for fi, si in zip(f, s):
            fh.write('%d %.7f %.7f\n' % (fi, si.real, si.imag))


# ------------------------------------------------------------------ scenario

T_CASE = 1.0
SHELL = (0.0, 72.0, 0.0, 18.6)
PATCH = (58.0, 70.0, 2.0, 17.0)
ARM = (28.0, 58.0, 10.5, 17.0)
# slots (0.5 mm) approximating the photo: frame ~1.5 mm wide, open towards the far end
PATCH_SLOTS = [(60.0, 68.5, 3.5, 3.5),      # along the top, inside the frame
               (60.0, 60.0, 3.5, 15.5),     # down the arm-side ... (x = 60)
               (60.0, 63.0, 15.5, 15.5),    # ... along the bottom towards the feed corner
               (63.0, 63.0, 9.5, 15.5),     # up the middle
               (63.0, 67.0, 9.5, 9.5)]      # short tongue
FEED_X = 58.0                       # coax feed between patch (shield) and arm (centre conductor)
BATTERY = (26.0, 61.0, 2.0, 17.0)   # 35 x 15 pouch: hides the arm, most of the patch sticks out
BATTERY_ALL = (27.0, 71.0, 1.5, 17.5)
PCB = (4.0, 68.0, 2.3, 16.3)
LOOP_R = 4.0
POSITIONS = {'patch': (64.0, 9.5), 'arm': (43.0, 13.75), 'tip': (31.0, 13.75)}


def build(position, kind, t_case=T_CASE, battery=BATTERY, with_device=True):
    """kind: genuine | antenna_50 (photo-based: slotted patch + arm, 50 ohm feed) | copper
    (same outline, plain copper: no slots, no feed)."""
    lx, ly = POSITIONS[position]
    inner = -t_case
    za = inner - 0.15                       # antenna copper (glued to the shell)
    zb = inner - (0.30 if kind != 'genuine' else 0.15)   # battery top face
    zfix = [0.0, 1.3, 1.5, 1.6, inner, za, inner - 0.15, inner - 0.30, inner - 4.15, inner - 4.30, inner - 6.0]
    z = axis(zfix, [(inner - 0.6, 1.8, 0.15), (inner - 6.3, inner - 0.6, 0.3)], inner - 14.0, 10.0, base=0.3, maxstep=1.5)
    xs = [lx, lx - 8, lx + 8] + [v for b in (SHELL, PATCH, ARM, battery) for v in b[:2]]
    ys = [ly, ly - 8, ly + 8] + [v for b in (SHELL, PATCH, ARM, battery) for v in b[2:]]
    x = axis(xs, [(lx - 6, lx + 6, 0.25), (-6, 80, 0.5)], -10.0, 84.0, base=0.5, maxstep=2.0)
    y = axis(ys, [(ly - 6, ly + 6, 0.25), (-6, 26, 0.5)], -12.0, 31.0, base=0.5, maxstep=2.0)
    s = Sim(x, y, z)
    # detector board around the loop: FR4, In1 + F.Cu ground with the 6 mm keep-out,
    # nose outline (r = 8 around (lx + 2, ly)) and body from lx + 6 on (+x), 40 mm wide
    s.dielectric((lx - 6, 200, ly - 20, ly + 20), 0.0, 1.6, 4.4, 0.02)

    def board(X, Y):
        nose = ((X - (lx + 2)) ** 2 + (Y - ly) ** 2 <= 64) | ((X >= lx + 2) & (np.abs(Y - ly) <= 8))
        body = (X >= lx + 6) & (np.abs(Y - ly) <= 20)
        hole = (X - lx) ** 2 + (Y - ly) ** 2 < 36
        return (nose | body) & ~hole
    s.sheet(1.3, board)
    s.sheet(1.5, lambda X, Y: board(X, Y) & ((X - lx) ** 2 + (Y - ly) ** 2 > 36))
    port = s.loop(lx, ly, LOOP_R, 1.5)
    s.add_lumped(port, 50.0, port=True)
    # detector electrodes (floating plates on B.Cu), relative to the loop as on the real board
    for c in range(4):
        for r0 in (-16.0, 4.0):
            s.rect_sheet((lx + 9 + 17 * c, lx + 23 + 17 * c, ly + r0, ly + r0 + 14), 0.0)
    if not with_device:
        return s
    s.dielectric(SHELL, inner, 0.0, 3.0, 0.01)
    s.box(battery, zb - 4.0, zb)
    s.rect_sheet(PCB, inner - 6.0)
    if kind == 'genuine':
        return s
    s.dielectric((PATCH[0], PATCH[1], PATCH[2], PATCH[3]), zb, inner, 3.4, 0.01)
    s.dielectric((ARM[0], ARM[1], ARM[2], ARM[3]), zb, inner, 3.4, 0.01)
    s.rect_sheet(PATCH, za)
    s.rect_sheet(ARM, za)
    jx = int(np.argmin(np.abs(s.x - FEED_X)))
    kz = s.zi(za)
    jy = np.where((s.y >= ARM[2] - 1e-6) & (s.y <= ARM[3] + 1e-6))[0]
    mid = jy[len(jy) // 2]
    if kind == 'antenna_50':
        # etched slots seen on the real part (underside photo): an outer C-shaped frame
        # around an inner tongue, which lengthens the current path through the patch
        for sl in PATCH_SLOTS:
            cut(s, sl, za)
        # one-cell gap between arm and patch (the coax feed), bridged by the 50 ohm modem input
        s.pec['x'][jx - 1, jy, kz] = False
        s.add_lumped(('x', jx - 1, mid, kz), 50.0)
    return s


def cut(s, box, z):
    """Remove PEC edges touching any node strictly inside `box` (an etched slot) in plane z."""
    k = s.zi(z)
    X, Y = np.meshgrid(s.x, s.y, indexing='ij')
    m = (X > box[0] - 1e-6) & (X < box[1] + 1e-6) & (Y > box[2] - 1e-6) & (Y < box[3] + 1e-6)
    s.pec['x'][:, :, k] &= ~(m[:-1, :] | m[1:, :])
    s.pec['y'][:, :, k] &= ~(m[:, :-1] | m[:, 1:])


def run_case(args):
    position, kind, battery_name, threads = args
    battery = {'batt35': BATTERY, 'battall': BATTERY_ALL}[battery_name]
    name = '%s_%s_%s' % (position, kind, battery_name)
    t = time.time()
    s = build(position, kind, battery=battery, with_device=(kind != 'air'))
    f, S, Z = s.run(t_end=float(os.environ.get('SIM_TEND', '20e-9')), threads=threads)
    os.makedirs(OUT, exist_ok=True)
    write_s1p(os.path.join(OUT, name + '.s1p'), f, S, name)
    return name, time.time() - t, int(np.prod(s.n)), s.tail


def selftest():
    """Bare loop (no board, no device) vs. the analytic small-loop inductance."""
    x = axis([0, -8, 8], [(-6, 6, 0.25), (-12, 12, 0.5)], -20, 20, base=0.5)
    z = axis([0], [(-2, 2, 0.15)], -15, 15, base=0.3, maxstep=1.5)
    s = Sim(x, x.copy(), z)
    port = s.loop(0, 0, LOOP_R, 0.0)
    s.add_lumped(port, 50.0, port=True)
    f, S, Z = s.run(t_end=6e-9, threads=16)
    # 0.5 mm strip: equivalent round-wire radius w/4
    a = 0.5 / 4
    L = MU0 * LOOP_R * (math.log(8 * LOOP_R / a) - 2)
    for fq in (0.5e9, 1e9, 2e9):
        i = int(np.argmin(abs(f - fq)))
        print('f=%.1f GHz  Z=%7.1f%+7.1fj ohm  analytic X=%6.1f ohm  |S11|=%.3f' % (
            fq / 1e9, Z[i].real, Z[i].imag, 2 * math.pi * fq * L * 1e-0, abs(S[i])))
    print('L analytic = %.1f nH' % (L * 1e9))


def main():
    import multiprocessing as mp
    threads = int(os.environ.get('SIM_THREADS', '4'))
    cases = [('patch', 'air', 'batt35', threads)]
    for pos in POSITIONS:
        for kind in ('genuine', 'antenna_50', 'copper'):
            cases.append((pos, kind, 'batt35', threads))
    for pos in ('patch', 'arm'):
        for kind in ('genuine', 'antenna_50'):
            cases.append((pos, kind, 'battall', threads))
    procs = int(os.environ.get('SIM_PROCS', '8'))
    with mp.get_context('spawn').Pool(procs) as pool:
        for name, dt, ncell, tail in pool.imap_unordered(run_case, cases):
            print('%-32s %6.0f s  %d cells  tail %.1e' % (name, dt, ncell, tail), flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'selftest':
        selftest()
    else:
        main()
