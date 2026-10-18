#!/usr/bin/env python3
"""Capture S11 (or S11 + S21) sweeps from a NanoVNA text-shell firmware (NanoVNA-H / NanoVNA-F) into Touchstone.

    python3 tools/nanovna_capture.py info
    python3 tools/nanovna_capture.py cal reset|open|short|load|thru|done   # SOL at the cable end (+ thru)
    python3 tools/nanovna_capture.py capture out.s1p [--start 600e6 --stop 3e9 --points 401 --avg 4]
    python3 tools/nanovna_capture.py capture out.s2p ...   # also S21 (port 1 -> port 2)
    python3 tools/nanovna_capture.py raw 'scan 700000000 900000000 11 3'

Calibration is done over the device's current sweep span (set by `cal reset`, which also sets the
span from --start/--stop/--cal-points). Outside that span the NanoVNA-F V2 returns zeros, so
`capture` refuses to sweep past it. The firmware returns at most 201 points per scan; more points
are fetched as interleaved segments, with the on-device calibration interpolated between them.
A .s2p output holds S11 and S21 only; this firmware does not measure S12/S22, which are written as 0.
`cal done` also saves the calibration to device slot 0 (it is recalled at power-on).
"""
import argparse
import os
import select
import sys
import termios
import time

import numpy as np

MAX_SCAN = 201
PROMPT = b'ch> '


class Shell:
    def __init__(self, port):
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
        a = termios.tcgetattr(self.fd)
        a[0] = a[1] = a[3] = 0
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        a[4] = a[5] = termios.B115200  # CDC-ACM ignores it
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
        self.cmd('')

    def cmd(self, line, timeout=30):
        """Send one command, return its output lines (echo and prompt stripped)."""
        termios.tcflush(self.fd, termios.TCIFLUSH)
        os.write(self.fd, line.encode() + b'\r')
        buf, end = b'', time.time() + timeout
        while not buf.endswith(PROMPT):
            if time.time() > end:
                raise TimeoutError('no prompt after %r: %r' % (line, buf[-200:]))
            r, _, _ = select.select([self.fd], [], [], 0.2)
            if r:
                buf += os.read(self.fd, 65536)
        lines = buf[:-len(PROMPT)].decode(errors='replace').replace('\r', '').split('\n')
        if lines and lines[0].strip() == line.strip():
            lines = lines[1:]
        return [l for l in lines if l.strip()]

    def sweep(self):
        f0, f1, n = map(int, self.cmd('sweep')[0].split())
        return f0, f1, n

    def scan(self, f0, f1, n, s21=False):
        """-> freq, complex array (n, 1) = S11 or (n, 2) = S11, S21"""
        out = self.cmd('scan %d %d %d %d' % (f0, f1, n, 7 if s21 else 3))
        if len(out) != n:
            raise RuntimeError('scan %d-%d/%d: %s' % (f0, f1, n, out[:3]))
        v = np.array([[float(x) for x in l.split()[:5 if s21 else 3]] for l in out])
        return v[:, 0], v[:, 1::2] + 1j * v[:, 2::2]


def capture(sh, f0, f1, n, avg, s21=False):
    """n points in [f0, f1], fetched as k interleaved scans of <= MAX_SCAN points each."""
    k = -(-n // MAX_SCAN)
    step = (f1 - f0) / (n - 1)
    f, s = np.zeros(0), np.zeros((0, 2 if s21 else 1), complex)
    for j in range(k):
        m = len(range(j, n, k))
        a = f0 + j * step
        b = a + (m - 1) * k * step
        acc = 0
        for _ in range(avg):
            for retry in range(3):
                fj, sj = sh.scan(round(a), round(b), m, s21)
                if np.all(np.abs(sj[:, 0]) > 0):
                    break
                # seen on the NanoVNA-F V2: everything above ~900 MHz comes back as 0 until a power cycle
                print('scan returned %d zero points (first at %.0f MHz), retrying'
                      % ((sj[:, 0] == 0).sum(), fj[sj[:, 0] == 0][0] / 1e6), file=sys.stderr)
            else:
                sys.exit('device keeps returning zeros: power-cycle it (cal is in save slot 0 if saved)')
            acc = acc + sj
        f, s = np.concatenate([f, fj]), np.concatenate([s, acc / avg])
    o = np.argsort(f)
    return f[o], s[o]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default='/dev/ttyACM1')
    ap.add_argument('--start', type=float, default=600e6)
    ap.add_argument('--stop', type=float, default=3e9)
    ap.add_argument('--points', type=int, default=401)
    ap.add_argument('--cal-points', type=int, default=MAX_SCAN)
    ap.add_argument('--avg', type=int, default=4, help='scans averaged per segment')
    ap.add_argument('--note', default='', help='free text stored in the file header')
    ap.add_argument('action', choices=['info', 'cal', 'capture', 'raw'])
    ap.add_argument('arg', nargs='*')
    a = ap.parse_args()
    sh = Shell(a.port)

    if a.action == 'info':
        for c in ('version', 'info', 'SN', 'cal', 'sweep', 'vbat'):
            print('%-8s %s' % (c, ' | '.join(sh.cmd(c))))
    elif a.action == 'raw':
        print('\n'.join(sh.cmd(' '.join(a.arg))))
    elif a.action == 'cal':
        step = a.arg[0] if a.arg else ''
        if step == 'reset':
            sh.cmd('sweep %d %d %d' % (a.start, a.stop, a.cal_points))
            sh.cmd('cal reset')
        elif step in ('open', 'short', 'load', 'thru', 'done'):
            if step != 'done':
                time.sleep(5)  # manual: wait 2-3 sweeps with the standard attached
                sh.sweep()  # let a fresh sweep run with the standard attached
            sh.cmd('cal ' + step)
            if step == 'done':
                sh.cmd('save 0')
        else:
            sys.exit('cal needs: reset | open | short | load | thru | done')
        print('sweep %d %d %d; %s' % (*sh.sweep(), ' '.join(sh.cmd('cal'))))
    else:
        if not a.arg:
            sys.exit('capture needs an output .s1p / .s2p path')
        s21 = a.arg[0].lower().endswith('.s2p')
        cal = ' '.join(sh.cmd('cal'))
        c0, c1, cn = sh.sweep()
        if not all(w in cal for w in ('open', 'short', 'load')):
            sys.exit('device is not SOL-calibrated (%r); run the cal steps first' % cal)
        if s21 and 'thru' not in cal:
            print('WARNING: no thru calibration, S21 is uncorrected (fine for A/B comparisons only)', file=sys.stderr)
        if a.start < c0 or a.stop > c1:
            sys.exit('requested %.0f-%.0f MHz but the device sweep/cal span is %.0f-%.0f MHz'
                     % (a.start / 1e6, a.stop / 1e6, c0 / 1e6, c1 / 1e6))
        f, s = capture(sh, a.start, a.stop, a.points, a.avg, s21)
        sh.cmd('sweep %d %d %d' % (c0, c1, cn))  # scan changes the live sweep; put it back
        if not np.all(np.abs(s[:, 0]) > 0):
            sys.exit('device returned zero points (outside calibrated span?)')
        hdr = [
            'nanovna_capture.py %s' % time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            '%s fw %s SN %s' % (sh.cmd('info')[0].split(':', 1)[-1].strip(), sh.cmd('version')[0], sh.cmd('SN')[0]),
            'cal: %s over %d-%d Hz, %d points' % (cal, c0, c1, cn),
            'points %d, avg %d' % (a.points, a.avg),
        ] + ([a.note] if a.note else [])
        os.makedirs(os.path.dirname(os.path.abspath(a.arg[0])), exist_ok=True)
        with open(a.arg[0], 'w') as fh:
            fh.write(''.join('! %s\n' % h for h in hdr))
            fh.write('# HZ S RI R 50\n')
            if s21:
                fh.write('! S12 and S22 are not measured (written as 0)\n')
            for fi, si in zip(f, s):
                fh.write('%d' % fi + ''.join(' %.6g %.6g' % (x.real, x.imag) for x in si)
                         + (' 0 0 0 0' if s21 else '') + '\n')
        db = 20 * np.log10(np.maximum(np.abs(s), 1e-12))
        print('%s: %d pts %.0f-%.0f MHz, |S11| %.2f..%.2f dB (min at %.0f MHz)'
              % (a.arg[0], len(f), f[0] / 1e6, f[-1] / 1e6, db[:, 0].min(), db[:, 0].max(), f[np.argmin(db[:, 0])] / 1e6)
              + (', |S21| %.1f..%.1f dB (max at %.0f MHz)' % (db[:, 1].min(), db[:, 1].max(), f[np.argmax(db[:, 1])] / 1e6)
                 if s21 else ''))


if __name__ == '__main__':
    main()
