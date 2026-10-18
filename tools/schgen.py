"""Tiny KiCad schematic generator.

Every symbol pin gets a short wire stub ending in a net label (or a power
symbol for power nets, or a no-connect flag), so connectivity is fully
explicit and checkable with ERC without having to route schematic wires.
"""
import copy
import math
import os
import uuid

import sexpr
from sexpr import Sym, find, find1

KISYM = '/usr/share/kicad/symbols'
STUB = 2.54
POWER_NETS = {'GND': 'power:GND', '+3V3': 'power:+3V3', 'VBUS': 'power:VBUS'}


def S(x):
    return Sym(x)


def font(size=1.27):
    return [S('font'), [S('size'), size, size]]


def snap(v, g=1.27):
    return round(round(v / g) * g, 4)


class LibCache:
    def __init__(self, extra_libs):
        self.extra = extra_libs  # nickname -> path
        self.trees = {}

    def _tree(self, nick):
        if nick not in self.trees:
            path = self.extra.get(nick) or os.path.join(KISYM, nick + '.kicad_sym')
            self.trees[nick] = sexpr.parse(open(path).read())
        return self.trees[nick]

    def get(self, lib_id):
        """Return flattened symbol (extends resolved), named lib_id."""
        nick, name = lib_id.split(':', 1)
        tree = self._tree(nick)
        syms = {s[1]: s for s in find(tree, 'symbol')}
        s = copy.deepcopy(syms[name])
        ext = find1(s, 'extends')
        if ext:
            parent = copy.deepcopy(syms[ext[1]])
            pname = parent[1]
            # child properties override parent's
            cprops = {p[1]: p for p in find(s, 'property')}
            out = []
            for x in parent:
                if isinstance(x, list) and x and x[0] == 'property' and x[1] in cprops:
                    out.append(cprops.pop(x[1]))
                elif isinstance(x, list) and x and x[0] == 'symbol':
                    x[1] = x[1].replace(pname + '_', name + '_', 1)
                    out.append(x)
                else:
                    out.append(x)
            # leftover child-only properties go after the last property
            last = max(i for i, x in enumerate(out) if isinstance(x, list) and x and x[0] == 'property')
            for p in cprops.values():
                last += 1
                out.insert(last, p)
            s = out
        s[1] = lib_id
        return s


def lib_pins(sym):
    pins = []
    for sub in find(sym, 'symbol'):
        for p in find(sub, 'pin'):
            at = find1(p, 'at')
            pins.append({'num': find1(p, 'number')[1], 'name': find1(p, 'name')[1],
                         'x': float(at[1]), 'y': float(at[2]), 'ang': float(at[3]) if len(at) > 3 else 0.0,
                         'len': float(find1(p, 'length')[1])})
    return pins


def lib_bbox(sym):
    xs, ys = [], []
    for sub in find(sym, 'symbol'):
        for g in sub:
            if not isinstance(g, list):
                continue
            if g[0] == 'rectangle':
                for k in ('start', 'end'):
                    e = find1(g, k)
                    xs.append(float(e[1])); ys.append(float(e[2]))
            elif g[0] == 'polyline':
                for xy in find(find1(g, 'pts'), 'xy'):
                    xs.append(float(xy[1])); ys.append(float(xy[2]))
            elif g[0] == 'circle':
                c = find1(g, 'center'); r = float(find1(g, 'radius')[1])
                xs += [float(c[1]) - r, float(c[1]) + r]; ys += [float(c[2]) - r, float(c[2]) + r]
            elif g[0] == 'pin':
                at = find1(g, 'at')
                xs.append(float(at[1])); ys.append(float(at[2]))
    if not xs:
        return (-1.27, -1.27, 1.27, 1.27)
    return (min(xs), min(ys), max(xs), max(ys))


def xform(px, py, rot):
    """lib coords (Y up) -> schematic offset (Y down) for CCW rotation rot."""
    x, y = px, -py
    a = math.radians(rot)
    c, s = round(math.cos(a)), round(math.sin(a))
    return (x * c + y * s, -x * s + y * c)


class Schematic:
    def __init__(self, project, title, rev, extra_libs, paper='A3', comments=()):
        self.project = project
        self.lib = LibCache(extra_libs)
        self.ns = uuid.uuid5(uuid.NAMESPACE_URL, 'lid/' + project)
        self.root_uuid = self.uid('root')
        self.items = []
        self.used = {}
        self.pwr_count = 0
        self.title = title
        self.rev = rev
        self.paper = paper
        self.comments = comments
        self.refs = {}
        self.rects = []

    def uid(self, key):
        return str(uuid.uuid5(self.ns, key))

    def _use(self, lib_id):
        if lib_id not in self.used:
            self.used[lib_id] = self.lib.get(lib_id)
        return self.used[lib_id]

    def _instance(self, ref, lib_id, x, y, rot, props, pinnums, in_bom=True, on_board=True, key=None):
        sym = self._use(lib_id)
        key = key or ref
        u = self.uid('sym/' + key)
        node = [S('symbol'), [S('lib_id'), lib_id], [S('at'), x, y, rot], [S('unit'), 1],
                [S('exclude_from_sim'), S('no')], [S('in_bom'), S('yes' if in_bom else 'no')],
                [S('on_board'), S('yes' if on_board else 'no')], [S('dnp'), S('no')], [S('uuid'), u]]
        for k, (v, px, py, hide) in props.items():
            eff = [S('effects'), font()]
            if hide:
                eff.append([S('hide'), S('yes')])
            node.append([S('property'), k, v, [S('at'), px, py, rot % 180], eff])
        for n in sorted(set(pinnums)):
            node.append([S('pin'), n, [S('uuid'), self.uid('pin/%s/%s' % (key, n))]])
        node.append([S('instances'), [S('project'), self.project,
                                      [S('path'), '/' + self.root_uuid, [S('reference'), ref], [S('unit'), 1]]]])
        self.items.append(node)
        return u

    def wire(self, x1, y1, x2, y2):
        self.items.append([S('wire'), [S('pts'), [S('xy'), x1, y1], [S('xy'), x2, y2]],
                           [S('stroke'), [S('width'), 0], [S('type'), S('default')]],
                           [S('uuid'), self.uid('w/%s/%s/%s/%s' % (x1, y1, x2, y2))]])

    def label(self, name, x, y, direction):
        ang = {'R': 0, 'U': 90, 'L': 180, 'D': 270}[direction]
        just = [S('justify'), S('left' if direction in 'RU' else 'right'), S('bottom')]
        self.items.append([S('label'), name, [S('at'), x, y, ang],
                           [S('effects'), font(), just], [S('uuid'), self.uid('l/%s/%s/%s' % (name, x, y))]])

    def no_connect(self, x, y):
        self.items.append([S('no_connect'), [S('at'), x, y], [S('uuid'), self.uid('nc/%s/%s' % (x, y))]])

    def power(self, net, x, y, direction):
        lib_id = POWER_NETS.get(net, net)
        self.pwr_count += 1
        ref = '#PWR%03d' % self.pwr_count
        if lib_id == 'power:GND':
            rot = {'D': 0, 'U': 180, 'R': 90, 'L': 270}[direction]
        else:
            rot = {'U': 0, 'D': 180, 'L': 90, 'R': 270}[direction]
        vx, vy = {'D': (0, 5.08), 'U': (0, -5.08), 'L': (-5.08, 0), 'R': (5.08, 0)}[direction]
        if lib_id == 'power:PWR_FLAG':
            vx, vy = {'D': (0, 3.81), 'U': (0, -3.81), 'L': (-3.81, 0), 'R': (3.81, 0)}[direction]
        props = {'Reference': (ref, x, y, True), 'Value': (net if lib_id != 'power:PWR_FLAG' else 'PWR_FLAG', x + vx, y + vy, False),
                 'Footprint': ('', x, y, True), 'Datasheet': ('', x, y, True), 'Description': ('', x, y, True)}
        self._instance(ref, lib_id, x, y, rot, props, ['1'], key='pwr/%s/%s/%s' % (net, x, y))

    def pwr_flag(self, net, x, y):
        """PWR_FLAG + a stub labelled `net`."""
        x, y = snap(x, 2.54), snap(y, 2.54)
        self.power('power:PWR_FLAG', x, y, 'U')
        self.wire(x, y, x, y + STUB)
        self._net_end(net, x, y + STUB, 'D')

    def _net_end(self, net, x, y, d):
        if net in POWER_NETS:
            self.power(net, x, y, d)
        else:
            self.label(net, x, y, d)

    def add(self, ref, lib_id, value, x, y, nets, rot=0, footprint=None, fields=None, in_bom=True, ref_pos=None, val_pos=None):
        """nets: {pin_number: net_name or None (no-connect)}"""
        sym = self._use(lib_id)
        x, y = snap(x, 2.54), snap(y, 2.54)
        pins = lib_pins(sym)
        if ref in self.refs:
            raise ValueError('duplicate ref ' + ref)
        self.refs[ref] = lib_id
        nums = {p['num'] for p in pins}
        missing = nums - set(nets)
        if missing:
            raise ValueError('%s: unassigned pins %s' % (ref, sorted(missing)))
        extra = set(nets) - nums
        if extra:
            raise ValueError('%s: unknown pins %s' % (ref, sorted(extra)))
        bx0, by0, bx1, by1 = lib_bbox(sym)
        c = [xform(bx0, by0, rot), xform(bx1, by1, rot)]
        sx0, sx1 = min(c[0][0], c[1][0]), max(c[0][0], c[1][0])
        sy0, sy1 = min(c[0][1], c[1][1]), max(c[0][1], c[1][1])
        rp = ref_pos or (x + sx1 + 1.27, y + sy0 - 1.27)
        vp = val_pos or (x + sx1 + 1.27, y + sy1 + 1.27)
        if (sx1 - sx0) < 6 and ref_pos is None:  # small 2-pin parts: text above / below
            rp = (x, y + sy0 - 1.9)
            vp = (x, y + sy1 + 1.9)
        fp = footprint
        if fp is None:
            fpp = [p for p in find(sym, 'property') if p[1] == 'Footprint']
            fp = fpp[0][2] if fpp else ''
        ds = [p for p in find(sym, 'property') if p[1] == 'Datasheet']
        desc = [p for p in find(sym, 'property') if p[1] == 'Description']
        props = {'Reference': (ref, rp[0], rp[1], False), 'Value': (value, vp[0], vp[1], False),
                 'Footprint': (fp, x, y, True), 'Datasheet': (ds[0][2] if ds else '', x, y, True),
                 'Description': (desc[0][2] if desc else '', x, y, True)}
        for k, v in (fields or {}).items():
            props[k] = (v, x, y, True)
        self._instance(ref, lib_id, x, y, rot, props, [p['num'] for p in pins], in_bom=in_bom)

        # stubs, de-duplicated by position (stacked pins)
        rx0, ry0, rx1, ry1 = x + sx0, y + sy0, x + sx1, y + sy1
        seen = {}
        for p in pins:
            ox, oy = xform(p['x'], p['y'], rot)
            px, py = round(x + ox, 4), round(y + oy, 4)
            net = nets[p['num']]
            k = (px, py)
            if k in seen:
                if seen[k] != net:
                    raise ValueError('%s: stacked pins with different nets at %s' % (ref, k))
                continue
            seen[k] = net
            if net is None:
                self.no_connect(px, py)
                continue
            # outward direction = opposite of pin angle
            a = math.radians(p['ang'])
            dx, dy = xform(-round(math.cos(a)), -round(math.sin(a)), rot)
            ex, ey = round(px + dx * STUB, 4), round(py + dy * STUB, 4)
            self.wire(px, py, ex, ey)
            d = 'R' if dx > 0 else 'L' if dx < 0 else ('D' if dy > 0 else 'U')
            self._net_end(net, ex, ey, d)
            tl = 4.0 if net in POWER_NETS else 1.0 * len(net) + 0.5
            tx, ty = ex + dx * tl, ey + dy * tl
            rx0, ry0, rx1, ry1 = min(rx0, ex, tx), min(ry0, ey, ty), max(rx1, ex, tx), max(ry1, ey, ty)
        self.rects.append((ref, rx0 - 0.5, ry0 - 2.5, rx1 + 0.5, ry1 + 2.5))

    def text(self, s, x, y, size=1.27):
        self.items.append([S('text'), s, [S('exclude_from_sim'), S('no')], [S('at'), x, y, 0],
                           [S('effects'), font(size), [S('justify'), S('left'), S('top')]],
                           [S('uuid'), self.uid('t/%s/%s' % (x, y))]])

    def check_overlaps(self):
        bad = []
        r = self.rects
        for i in range(len(r)):
            for j in range(i + 1, len(r)):
                a, b = r[i], r[j]
                if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]:
                    bad.append((a[0], b[0]))
        return bad

    def save(self, path):
        tb = [S('title_block'), [S('title'), self.title], [S('date'), '2026-10-18'], [S('rev'), self.rev]]
        for i, c in enumerate(self.comments, 1):
            tb.append([S('comment'), i, c])
        root = [S('kicad_sch'), [S('version'), 20250114], [S('generator'), 'lid_gen'],
                [S('generator_version'), '10.0'], [S('uuid'), self.root_uuid], [S('paper'), self.paper], tb,
                [S('lib_symbols')] + list(self.used.values())]
        root += self.items
        root.append([S('sheet_instances'), [S('path'), '/', [S('page'), '1']]])
        root.append([S('embedded_fonts'), S('no')])
        with open(path, 'w') as f:
            f.write(sexpr.dump(root) + '\n')
