#!/usr/bin/env python3
"""Talk to the rev 0.2 board running firmware/bringup over USB serial (no pyserial needed).

  bringup.py cmd status                  any firmware command, prints the reply
  bringup.py shell                       interactive
  bringup.py sweep 1000 1450 5 [avg] [settle_us] [-o file.csv]
  bringup.py noise 1000 1450 5 [-n 5]    repeated sweeps: per-point spread in dB (target <= 0.05 dB)
  bringup.py watch 1430 [-t 60]          CW at one frequency, prints the level ~20 times a second
  bringup.py slope 1200                  detector slope from the four ADF4351 power steps (3 dB apart)

The board is found by its USB IDs (2e8a:0009 or 000a), so the script never opens another ttyACM device.
"""
import argparse
import glob
import os
import select
import statistics
import sys
import termios
import time

VID, PIDS = '2e8a', ('0009', '000a')
SLOPE_V_PER_DB = -0.025     # AD8318 nominal; `slope` measures the real one


def find_port():
    for tty in sorted(glob.glob('/sys/class/tty/ttyACM*')):
        dev = os.path.realpath(os.path.join(tty, 'device'))
        for up in (dev, os.path.dirname(dev)):
            try:
                v = open(os.path.join(up, 'idVendor')).read().strip()
                p = open(os.path.join(up, 'idProduct')).read().strip()
            except OSError:
                continue
            if v == VID and p in PIDS:
                return '/dev/' + os.path.basename(tty)
    sys.exit('board not found (USB %s:%s); is the bring-up firmware running?' % (VID, '/'.join(PIDS)))


class Port:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
        a = termios.tcgetattr(self.fd)
        a[0] = 0                                    # iflag
        a[1] = 0                                    # oflag
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        a[3] = 0                                    # lflag: raw
        a[4] = a[5] = termios.B115200               # never 1200: that reboots into BOOTSEL
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
        self.buf = b''
        self.drain()

    def drain(self):
        while select.select([self.fd], [], [], 0.1)[0]:
            try:
                if not os.read(self.fd, 4096):
                    break
            except OSError:
                break
        self.buf = b''

    def send(self, line):
        os.write(self.fd, line.encode() + b'\n')

    def lines(self, timeout=5.0):
        end = time.time() + timeout
        while True:
            while b'\n' in self.buf:
                l, self.buf = self.buf.split(b'\n', 1)
                yield l.decode(errors='replace').rstrip('\r')
                end = time.time() + timeout
            r = select.select([self.fd], [], [], max(0.0, end - time.time()))[0]
            if not r:
                return
            try:
                data = os.read(self.fd, 4096)
            except OSError:         # device gone (e.g. after bootsel)
                return
            if not data:
                return
            self.buf += data

    def cmd1(self, line, timeout=1.0):
        """Send a command whose reply is a single line; returns it without waiting for more."""
        self.send(line)
        for l in self.lines(timeout):
            return l
        return ''

    def cmd(self, line, timeout=1.0):
        self.send(line)
        return list(self.lines(timeout))


def sweep(port, f0, f1, df, avg, settle):
    port.send('sweep %g %g %g %d %d' % (f0, f1, df, avg, settle))
    header, bg, pts = None, None, []
    for l in port.lines(10.0):
        if l.startswith('#'):
            header = l
        elif l.startswith('bg,'):
            bg = [float(x) for x in l.split(',')[1:]]
        elif l.startswith('end'):
            return header, bg, pts, l
        elif l.startswith('err'):
            sys.exit(l)
        elif l and l[0].isdigit():
            f, v, sd, ok = l.split(',')
            pts.append((float(f), float(v), float(sd), int(ok)))
    sys.exit('sweep timed out after %d points' % len(pts))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port')
    sub = ap.add_subparsers(dest='what', required=True)
    c = sub.add_parser('cmd')
    c.add_argument('line', nargs='+')
    sub.add_parser('shell')
    for name in ('sweep', 'noise'):
        s = sub.add_parser(name)
        s.add_argument('start', type=float)
        s.add_argument('stop', type=float)
        s.add_argument('step', type=float)
        s.add_argument('avg', type=int, nargs='?', default=4)
        s.add_argument('settle', type=int, nargs='?', default=300)
        s.add_argument('-o', '--out')
        if name == 'noise':
            s.add_argument('-n', type=int, default=5)
    s = sub.add_parser('slope')
    s.add_argument('mhz', type=float)
    s = sub.add_parser('watch')
    s.add_argument('mhz', type=float)
    s.add_argument('-t', type=float, default=60, help='seconds')
    a = ap.parse_args()

    port = Port(a.port or find_port())
    if a.what == 'cmd':
        for l in port.cmd(' '.join(a.line), 2.0):
            print(l)
    elif a.what == 'shell':
        print('connected; empty line or ctrl-D to quit')
        for line in sys.stdin:
            if not line.strip():
                break
            for l in port.cmd(line.strip(), 2.0):
                print(l)
    elif a.what == 'sweep':
        header, bg, pts, end = sweep(port, a.start, a.stop, a.step, a.avg, a.settle)
        out = open(a.out, 'w') if a.out else sys.stdout
        print(header, file=out)
        print('# source off: %.6f V (sd %.6f)' % tuple(bg), file=out)
        print('freq_hz,det_v,sd_v,locked', file=out)
        for p in pts:
            print('%.0f,%.6f,%.6f,%d' % p, file=out)
        print('#', end, file=sys.stderr)
    elif a.what == 'noise':
        runs = []
        for i in range(a.n):
            header, bg, pts, end = sweep(port, a.start, a.stop, a.step, a.avg, a.settle)
            runs.append(pts)
            print('run %d: %s, source off %.4f V' % (i + 1, end, bg[0]), file=sys.stderr)
        freqs = [p[0] for p in runs[0]]
        sds = [statistics.stdev(r[k][1] for r in runs) / abs(SLOPE_V_PER_DB) for k in range(len(freqs))]
        lvl = [statistics.mean(r[k][1] for r in runs) for k in range(len(freqs))]
        unl = sum(1 for r in runs for p in r if not p[3])
        print('points %d x %d sweeps, unlocked points %d' % (len(freqs), a.n, unl))
        print('detector %.3f .. %.3f V (higher = less power)' % (min(lvl), max(lvl)))
        print('per-point spread (sd between sweeps): median %.4f dB, worst %.4f dB at %.0f MHz'
              % (statistics.median(sds), max(sds), freqs[sds.index(max(sds))] / 1e6))
        print('target: <= 0.05 dB -> %s' % ('OK' if statistics.median(sds) <= 0.05 else 'NOT MET'))
        if a.out:
            with open(a.out, 'w') as f:
                f.write('freq_hz,' + ','.join('run%d_v' % (i + 1) for i in range(a.n)) + ',sd_db\n')
                for k, fr in enumerate(freqs):
                    f.write('%.0f,%s,%.5f\n' % (fr, ','.join('%.6f' % r[k][1] for r in runs), sds[k]))
    elif a.what == 'watch':
        port.cmd('freq %g' % a.mhz, 1.0)
        v0, end = None, time.time() + a.t
        try:
            while time.time() < end:
                v = float(port.cmd1('adc 0 16').split()[1])
                v0 = v if v0 is None else v0
                print('%s  %.4f V  %+6.2f dB vs start' % (time.strftime('%H:%M:%S'), v, -(v - v0) / 0.025), flush=True)
        finally:
            port.cmd('off')
    elif a.what == 'slope':
        vs = []
        for p in range(4):
            port.cmd('power %d' % p)
            port.cmd('freq %g' % a.mhz, 1.0)
            time.sleep(0.05)
            v = float(port.cmd1('adc 0 64', 2.0).split()[1])
            vs.append(v)
            print('power %d (%+d dBm at the chip): %.5f V' % (p, -4 + 3 * p, v))
        port.cmd('power 0')
        port.cmd('off')
        d = [(vs[i + 1] - vs[i]) / 3.0 * 1000 for i in range(3)]
        print('slope per step: %s mV/dB (AD8318 nominal -25; ADF4351 steps are ~3 dB, not exact)'
              % ', '.join('%.1f' % x for x in d))


if __name__ == '__main__':
    main()
