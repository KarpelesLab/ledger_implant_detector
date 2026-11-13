#!/usr/bin/env python3
"""Generate hardware/integrated/integrated.kicad_pcb: the rev 0.2 integrated TEM cell (see docs/rev02_integrated.md).

Coordinates in mm, origin at the centre of the 80 x 80 mm test area, y down, viewed from the top.
The user sits at -x, slides the wallet in from that side and reads the screen beyond the cell at +x.

    F.Cu   the cell floor: solid GND + the two 3 mm landing lines, same geometry as the measured fixture
    In1.Cu digital and power routing, shielded between the floor and In2
    In2.Cu solid GND, reference for the 50 ohm lines on B.Cu (0.35 mm on JLC04161H-7628)
    B.Cu   every SMD part + GND pour. Under the landing lines In1/In2 are cut away so that they see
           B.Cu at 1.6 mm, as on the fixture.

    FREEROUTING_JAR=... python3 tools/gen_integrated_pcb.py           # place, route, pour
    python3 tools/gen_integrated_pcb.py --fill out.kicad_pcb          # (internal)
"""
import csv
import math
import os
import re
import subprocess
import sys

import pcbnew
from pcbnew import FromMM, VECTOR2I

import gen_fixtures as gf
import sexpr
from gen_fixtures import MS_GAP, MS_W, TEM, TEM_H, TEM_PLATE_HOLES, ramp_tip_y, rect, rounded
from sexpr import find, find1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRJ = os.path.join(ROOT, 'hardware', 'integrated')
NAME = 'integrated'
OX, OY = gf.OX, gf.OY
KIFP = '/usr/share/kicad/footprints'
KICAD_ENV = dict(os.environ, **({'XDG_CONFIG_HOME': os.environ['LID_KICAD_CFG']} if 'LID_KICAD_CFG' in os.environ else {}))

X0, X1, Y1 = -70.0, 130.0, 108.0              # board outline
FEET = [(x, sy * 102.0) for x in (-64.0, 64.0, 124.0) for sy in (-1, 1)]
LAND0 = ramp_tip_y(max(TEM_H)) - 3.0          # start of the landing line
PAD_Y = Y1 - 2.6                              # SMA centre pin (J1/J2 not fitted in normal use)
VIA_Y = 102.6                                 # RF crosses the board here, inside the SMA's bottom legs
VOID_Y = 102.0                                # In1/In2 cut away up to here under the landing line
W50 = 0.35                                    # 50 ohm on B.Cu over In2
CHAIN_X = 6.0                                 # first RF part on the underside

# series parts on the RF chains, in order from the cell: (ref, x)
# shunt parts: (ref, x), on the chain with their other end towards the board centre
TX_SERIES = [('R1', 6.0), ('L1', 11.0), ('R3', 18.0), ('C3', 23.0)]
TX_SHUNT = [('C1', 8.5), ('C2', 13.5), ('R2', 15.5), ('R4', 20.5)]
RX_SERIES = [('R20', 6.0), ('R22', 11.0), ('C21', 18.5)]
RX_SHUNT = [('R21', 8.5), ('R23', 13.5), ('R24', 15.8)]
# hand-routed; hidden from the autorouter. RFA_P is not: the router adds its pull-up to the hand-drawn line
RF_NETS = ('CELL_P1', 'CELL_P2', 'TX_A', 'TX_B', 'TX_C', 'RX_A', 'RX_B', 'DET_HI')

# fixed placement: ref -> (x, y, rot, side)
FIXED = {
    'J1': (0, -PAD_Y, 90, 'F'), 'J2': (0, PAD_Y, 270, 'F'),
    'U2': (32.0, -95.0, 0, 'B'), 'U3': (27.0, 96.5, 0, 'B'), 'U4': (46.0, 92.0, 0, 'B'),
    'U5': (52.0, -82.0, 0, 'B'), 'Y1': (46.0, -84.0, 0, 'B'), 'J5': (46.0, -103.0, 180, 'B'),
    'U1': (127.5, 8.89, 90, 'B'),       # Pico 2: pin 1 and the micro-USB at the +x edge
    'J3': (93.5, 32.0, 90, 'F'), 'D1': (92.0, -45.0, 0, 'F'), 'D2': (108.0, -45.0, 0, 'F'),
    'SW1': (97.0, -66.0, 0, 'F'),
    'J4': (86.0, 60.0, 90, 'B'),
    'TP1': (40.0, 80.0, 0, 'B'), 'TP2': (40.0, -76.0, 0, 'B'), 'TP3': (46.0, -76.0, 0, 'B'),
    'TP4': (52.0, -76.0, 0, 'B'), 'TP5': (46.0, 80.0, 0, 'B'), 'TP6': (52.0, 80.0, 0, 'B'),
}
# small parts placed next to the pad they serve: ref -> (target ref, target pad)
NEAR = {
    'R5': ('U2', '12'), 'R6': ('U2', '13'), 'C4': ('U2', '13'), 'R7': ('U2', '13'),
    'R8': ('U2', '14'), 'R9': ('U2', '15'), 'C5': ('U2', '14'), 'C6': ('U2', '15'), 'R10': ('U2', '15'),
    'R11': ('U2', '22'), 'C7': ('U2', '7'), 'R12': ('U2', '7'), 'C8': ('U2', '7'), 'R13': ('U2', '20'), 'C9': ('U2', '20'),
    'C10': ('U2', '19'), 'C11': ('U2', '23'), 'C12': ('U2', '24'), 'C13': ('U2', '23'),
    'C14': ('U2', '6'), 'C15': ('U2', '16'), 'C16': ('U2', '17'), 'C17': ('U2', '10'), 'C18': ('U2', '28'), 'C19': ('U2', '32'),
    'FB2': ('U2', '16'), 'FB3': ('U2', '6'), 'R14': ('U2', '29'), 'C20': ('Y1', '4'),
    'R31': ('U3', '6'), 'C22': ('U3', '15'), 'R25': ('U3', '10'), 'C23': ('U3', '5'), 'R26': ('U3', '7'),
    'C24': ('U3', '3'), 'C25': ('U3', '4'), 'C26': ('U3', '9'), 'C27': ('U3', '9'),
    'R27': ('U4', '4'), 'C28': ('U4', '4'), 'R28': ('U4', '5'), 'C29': ('U4', '5'), 'R29': ('U4', '6'), 'R30': ('U4', '6'),
    'C30': ('U4', '6'), 'FB4': ('U4', '8'), 'C31': ('U4', '8'),
    'C32': ('U5', '1'), 'C33': ('U5', '5'),
    'FB1': ('U1', '40'), 'C34': ('U1', '36'), 'R32': ('U1', '1'), 'R33': ('U1', '2'), 'R34': ('U1', '6'),
    'R35': ('U1', '16'), 'R36': ('U1', '21'), 'R37': ('U1', '22'),
}


def P(x, y):
    return VECTOR2I(FromMM(OX + x), FromMM(OY + y))


def mm(v):
    return v.x / 1e6 - OX, v.y / 1e6 - OY


def netlist():
    out = os.path.join(PRJ, '%s.%d.net' % (NAME, os.getpid()))
    subprocess.run(['kicad-cli', 'sch', 'export', 'netlist', '--format', 'kicadsexpr', '-o', out,
                    os.path.join(PRJ, NAME + '.kicad_sch')], check=True, capture_output=True, env=KICAD_ENV)
    t = sexpr.parse(open(out).read())
    os.unlink(out)
    comps = {}
    for c in find(find1(t, 'components'), 'comp'):
        fields = {}
        fl = find1(c, 'fields')
        if fl:
            for f in find(fl, 'field'):
                if len(f) > 2:
                    fields[find1(f, 'name')[1]] = f[2]
        for k in ('datasheet', 'description'):
            n = find1(c, k)
            if n and len(n) > 1:
                fields[k.capitalize()] = n[1]
        comps[find1(c, 'ref')[1]] = {'value': find1(c, 'value')[1], 'footprint': find1(c, 'footprint')[1],
                                     'tstamp': find1(c, 'tstamps')[1], 'fields': fields}
    nets = {find1(n, 'name')[1]: [(find1(d, 'ref')[1], find1(d, 'pin')[1]) for d in find(n, 'node')]
            for n in find(find1(t, 'nets'), 'net')}
    return comps, nets


class B:
    """The board under construction."""

    def __init__(self):
        self.comps, self.nets = netlist()
        self.b = pcbnew.BOARD()
        self.rules()
        self.ni = {}
        for name in sorted(self.nets):
            n = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(n)
            self.ni[name] = n
        self.pinnet = {(r, p): name for name, nodes in self.nets.items() for r, p in nodes}
        self.fps = {}
        self.boxes = []       # placed part rectangles on B.Cu (x0, y0, x1, y1)
        self.hand = []        # every track and via drawn here, so they can be redrawn after the SES import

    def rules(self):
        b = self.b
        b.SetCopperLayerCount(4)
        b.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_POWER)
        d = b.GetDesignSettings()
        d.SetBoardThickness(FromMM(1.6))
        d.SetAuxOrigin(P(X0, Y1))
        d.SetGridOrigin(P(X0, Y1))
        d.m_TrackMinWidth = FromMM(0.15)
        d.m_MinClearance = FromMM(0.15)
        d.m_ViasMinSize = FromMM(0.6)
        d.m_MinThroughDrill = FromMM(0.3)
        d.m_CopperEdgeClearance = FromMM(0.3)
        d.m_HoleClearance = FromMM(0.25)
        d.m_HoleToHoleMin = FromMM(0.25)
        d.m_ViasMinAnnularWidth = FromMM(0.13)
        ns = d.m_NetSettings
        nc = ns.GetDefaultNetclass()
        nc.SetClearance(FromMM(0.15))
        nc.SetTrackWidth(FromMM(0.2))
        nc.SetViaDiameter(FromMM(0.6))
        nc.SetViaDrill(FromMM(0.3))
        pw = pcbnew.NETCLASS('Power')
        pw.SetClearance(FromMM(0.15))
        pw.SetTrackWidth(FromMM(0.3))
        pw.SetViaDiameter(FromMM(0.8))
        pw.SetViaDrill(FromMM(0.4))
        ns.SetNetclass('Power', pw)
        for pat in ('VBUS', '/VBUS', '+3V3', '/+3V3', '/+5VA', '+5VA'):     # the analog 3.3 V rail has to reach fine pitch pins
            ns.SetNetclassPatternAssignment(pat, 'Power')
        tb = b.GetTitleBlock()
        tb.SetTitle('Ledger Implant Detector: integrated TEM cell (CONCEPT)')
        tb.SetRevision('0.2')
        tb.SetCompany(gf.REPO)
        tb.SetComment(0, 'CONCEPT DESIGN - NOT YET BUILT OR VALIDATED')
        tb.SetComment(1, 'Stackup: JLC04161H-7628 (4L 1.6mm)')

    def net(self, name):
        for k in (name, '/' + name):
            if k in self.ni:
                return self.ni[k]
        raise KeyError(name)

    def load(self, ref):
        c = self.comps[ref]
        nick, name = c['footprint'].split(':', 1)
        fp = pcbnew.FootprintLoad(os.path.join(KIFP, nick + '.pretty'), name)
        if fp is None:
            raise SystemExit('no footprint ' + c['footprint'])
        fp.SetFPID(pcbnew.LIB_ID(nick, name))
        fp.SetReference(ref)
        fp.SetValue(c['value'])
        fp.SetPath(pcbnew.KIID_PATH('/' + c['tstamp']))
        fp.SetSheetname('/')
        fp.SetSheetfile(NAME + '.kicad_sch')
        for k, v in c['fields'].items():
            if k in ('Reference', 'Value', 'Footprint'):
                continue
            if k in ('Datasheet', 'Description'):
                fp.GetField(getattr(pcbnew, 'FIELD_T_' + k.upper())).SetText(v)
                continue
            f = pcbnew.PCB_FIELD(fp, pcbnew.FIELD_T_USER, k)
            f.SetVisible(False)
            f.SetLayer(pcbnew.F_Fab)
            f.SetText(v)
            fp.Add(f)
        if c['value'] == 'DNP' or ref.startswith('TP'):
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM)
        if c['value'] == 'DNP' or ref.startswith('TP'):
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        return fp

    def place(self, ref, x, y, rot=0, side='B'):
        fp = self.load(ref)
        self.b.Add(fp)
        fp.SetPosition(P(x, y))
        if side == 'B':
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            n = self.pinnet.get((ref, pad.GetNumber()))
            if n:
                pad.SetNet(self.ni[n])
        small = ref[0] in 'RCL' or ref.startswith('FB')
        fp.Reference().SetTextSize(VECTOR2I(FromMM(0.8), FromMM(0.8)))
        fp.Reference().SetTextThickness(FromMM(0.12))
        if small or ref.startswith('TP'):
            fp.Reference().SetLayer(pcbnew.B_Fab if side == 'B' else pcbnew.F_Fab)
        self.fps[ref] = fp
        if side == 'B':
            bb = fp.GetBoundingBox(False)
            m = {'U2': 2.8, 'U3': 1.8, 'U4': 1.8, 'U1': 3.0, 'Y1': 1.5, 'U5': 1.5}.get(ref, 0.0)      # room for the pins to escape
            self.boxes.append((bb.GetLeft() / 1e6 - OX - m, bb.GetTop() / 1e6 - OY - m, bb.GetRight() / 1e6 - OX + m, bb.GetBottom() / 1e6 - OY + m))
        return fp

    def pad(self, ref, num):
        for p in self.fps[ref].Pads():
            if p.GetNumber() == num:
                return p
        raise KeyError((ref, num))

    def padxy(self, ref, num):
        return mm(self.pad(ref, num).GetPosition())

    def padnet(self, ref, num):
        return self.pinnet.get((ref, num), '')

    def track(self, a, c, w, net, layer=pcbnew.B_Cu, record=True):
        if record:
            self.hand.append(('t', (a, c, w, net, layer)))
        t = pcbnew.PCB_TRACK(self.b)
        t.SetStart(P(*a))
        t.SetEnd(P(*c))
        t.SetWidth(FromMM(w))
        t.SetLayer(layer)
        t.SetNet(self.net(net))
        t.SetLocked(True)
        self.b.Add(t)

    def poly(self, pts, w, net, layer=pcbnew.B_Cu):
        for a, c in zip(pts, pts[1:]):
            if a != c:
                self.track(a, c, w, net, layer)

    def via(self, x, y, net, d=0.8, drill=0.4, record=True):
        if record:
            self.hand.append(('v', (x, y, net, d, drill)))
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(P(x, y))
        v.SetDrill(FromMM(drill))
        v.SetWidth(pcbnew.F_Cu, FromMM(d))
        v.SetNet(self.net(net))
        v.SetLocked(True)
        self.b.Add(v)

    def shape(self, layer, pts, w=0.1, closed=True, fill=False):
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetLayer(layer)
        s.SetWidth(FromMM(w))
        if len(pts) == 2 and not closed:
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(P(*pts[0]))
            s.SetEnd(P(*pts[1]))
        else:
            s.SetShape(pcbnew.SHAPE_T_POLY)
            ch = pcbnew.SHAPE_POLY_SET()
            ch.NewOutline()
            for x, y in pts:
                ch.Append(FromMM(OX + x), FromMM(OY + y))
            s.SetPolyShape(ch)
            s.SetFilled(fill)
        self.b.Add(s)

    def outline(self, pts):
        for a, c in zip(pts, pts[1:] + pts[:1]):
            s = pcbnew.PCB_SHAPE(self.b)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetLayer(pcbnew.Edge_Cuts)
            s.SetWidth(FromMM(0.1))
            s.SetStart(P(*a))
            s.SetEnd(P(*c))
            self.b.Add(s)

    def text(self, t, x, y, size=2.0, layer=pcbnew.F_SilkS, mirror=False, just=None):
        o = pcbnew.PCB_TEXT(self.b)
        o.SetText(t)
        o.SetLayer(layer)
        o.SetPosition(P(x, y))
        o.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
        o.SetTextThickness(FromMM(size * 0.15))
        o.SetMirrored(mirror)
        if just == 'left':
            o.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        self.b.Add(o)

    def zone(self, layers, pts, net, priority=0, clearance=0.3):
        z = pcbnew.ZONE(self.b)
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(l)
        z.SetLayerSet(ls)
        o = z.Outline()
        o.NewOutline()
        for x, y in pts:
            o.Append(FromMM(OX + x), FromMM(OY + y))
        z.SetNet(self.net(net))
        z.SetAssignedPriority(priority)
        z.SetMinThickness(FromMM(0.25))
        z.SetLocalClearance(FromMM(clearance))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        self.b.Add(z)

    def rule_area(self, pts, layers, tracks=True, vias=True, pour=True, pads=False, footprints=False):
        z = pcbnew.ZONE(self.b)
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(l)
        z.SetLayerSet(ls)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowTracks(tracks)
        z.SetDoNotAllowVias(vias)
        z.SetDoNotAllowZoneFills(pour)
        z.SetDoNotAllowPads(pads)
        z.SetDoNotAllowFootprints(footprints)
        o = z.Outline()
        o.NewOutline()
        for x, y in pts:
            o.Append(FromMM(OX + x), FromMM(OY + y))
        self.b.Add(z)

    def hole(self, x, y):
        fp = pcbnew.FootprintLoad(os.path.join(KIFP, 'MountingHole.pretty'), 'MountingHole_3.2mm_M3')
        fp.SetFPID(pcbnew.LIB_ID('MountingHole', 'MountingHole_3.2mm_M3'))
        fp.SetReference('H%d' % (len([f for f in self.b.GetFootprints() if f.GetReference().startswith('H')]) + 1))
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        fp.SetPosition(P(x, y))
        fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_POS_FILES | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_BOARD_ONLY)
        self.b.Add(fp)


def orient_series(bd, ref, x, y, in_net):
    """Place a 2-pad part along x with the pad on in_net towards -x."""
    fp = bd.place(ref, x, y, 0)
    (ax, _), (cx, _) = bd.padxy(ref, '1'), bd.padxy(ref, '2')
    left = '1' if ax < cx else '2'
    if bd.padnet(ref, left).lstrip('/') != in_net:
        fp.SetOrientationDegrees(180)


def place_shunt(bd, ref, x, y, sign):
    """Vertical 2-pad part with its signal pad on the chain (y) and its GND pad towards y + sign * 1.6."""
    fp = bd.place(ref, x, y + sign * 0.8, 90)
    # every shunt on the chains has pad 2 on GND
    if abs(bd.padxy(ref, '2')[1] - y) < 0.1:
        fp.SetOrientationDegrees(270)


def rf_chain(bd, sy, series, shunts, first_net):
    """Place a chain along y = sy * VIA_Y going +x, and draw its track from the crossing via to the last part."""
    y = sy * VIA_Y
    net = first_net
    for ref, x in series:
        orient_series(bd, ref, x, y, net)
        p1, p2 = bd.padnet(ref, '1').lstrip('/'), bd.padnet(ref, '2').lstrip('/')
        net = p2 if p1 == net else p1
    # shunts sit towards the board's own centre, so the outer side of the chain stays free
    for ref, x in shunts:
        place_shunt(bd, ref, x, y, -sy)
    prev_x, prev_net = 0.0, first_net
    for ref, x in series:
        p1, p2 = bd.padnet(ref, '1').lstrip('/'), bd.padnet(ref, '2').lstrip('/')
        pin_in, pin_out = ('1', '2') if p1 == prev_net else ('2', '1')
        bd.track((prev_x, y), bd.padxy(ref, pin_in), W50, prev_net)
        prev_x = bd.padxy(ref, pin_out)[0]
        prev_net = bd.padnet(ref, pin_out).lstrip('/')
    return prev_x, prev_net


def near_place(bd, ref, target):
    """Greedy: the free spot on a 0.5 mm grid closest to the target pad, net pad towards the target."""
    tx, ty = bd.padxy(*target)
    fp = bd.place(ref, tx, ty, 0)
    bd.boxes.pop()
    bb = fp.GetBoundingBox(False)
    w, h = bb.GetWidth() / 1e6 / 2 + 0.5, bb.GetHeight() / 1e6 / 2 + 0.5
    best = None
    for rot, (hw, hh) in ((0, (w, h)), (90, (h, w))):
        for i in range(-44, 45):
            for j in range(-44, 45):
                x, y = tx + i * 0.5, ty + j * 0.5
                if abs(y) > Y1 - 2 or x > X1 - 2 or x < X0 + 2:
                    continue
                if any(x + hw > a and x - hw < c and y + hh > b and y - hh < d for a, b, c, d in bd.boxes + keep_clear()):
                    continue
                dist = math.hypot(i, j)
                if best is None or dist < best[0]:
                    best = (dist, x, y, rot, hw, hh)
    if best is None:
        raise SystemExit('no room for ' + ref)
    _, x, y, rot, hw, hh = best
    fp.SetPosition(P(x, y))
    fp.SetOrientationDegrees(rot)
    bd.boxes.append((x - hw, y - hh, x + hw, y + hh))
    # put the pad that shares the target's net (or the non-GND pad) closest to the target
    want = bd.padnet(*target)
    pads = [p for p in fp.Pads()]
    if len(pads) == 2:
        p0 = pads[0] if pads[0].GetNetname() == want or pads[1].GetNetname() == 'GND' else pads[1]
        px, py = mm(p0.GetPosition())
        ox, oy = mm((pads[1] if p0 is pads[0] else pads[0]).GetPosition())
        if math.hypot(px - tx, py - ty) > math.hypot(ox - tx, oy - ty):
            fp.SetOrientationDegrees(rot + 180)


def keep_clear():
    """No parts here on B.Cu: under the landing lines and around holes."""
    out = []
    for sy in (-1, 1):
        y0, y1 = sorted((sy * (LAND0 - 8), sy * Y1))
        out.append((-CHAIN_X + 1, y0, CHAIN_X - 2, y1))
    for x, y in FEET + TEM_PLATE_HOLES:
        out.append((x - 4, y - 4, x + 4, y + 4))
    x0, x1, ya, yb = FRAME
    for sy in (-1, 1):                  # the shield frame
        for y in (ya, yb):
            out.append((x0 - 1.2, min(sy * y - 1.2, sy * y + 1.2), x1 + 1.2, max(sy * y - 1.2, sy * y + 1.2)))
        out.append((x1 - 1.2, min(sy * ya, sy * yb), x1 + 1.2, max(sy * ya, sy * yb)))
    return out


class Free:
    """Copper of other nets, to find free spots for GND vias after routing."""

    def __init__(self, bd):
        self.boxes, self.segs = [], []
        for fp in bd.b.GetFootprints():
            for p in fp.Pads():
                bb = p.GetBoundingBox()
                self.boxes.append((bb.GetLeft() / 1e6 - OX, bb.GetTop() / 1e6 - OY, bb.GetRight() / 1e6 - OX, bb.GetBottom() / 1e6 - OY,
                                   p.GetNetname() == 'GND' and p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH, p.GetNetname()))
            if fp.GetReference() in ('J5', 'U1'):    # footprint keepouts
                bb = fp.GetBoundingBox(False)
                self.boxes.append((bb.GetLeft() / 1e6 - OX, bb.GetTop() / 1e6 - OY, bb.GetRight() / 1e6 - OX, bb.GetBottom() / 1e6 - OY, False, ''))
        for t in bd.b.GetTracks():
            if t.GetNetname() == 'GND':
                continue
            a, c = mm(t.GetStart()), mm(t.GetEnd())
            if t.Type() == pcbnew.PCB_VIA_T:
                w = pcbnew.Cast_to_PCB_VIA(t).GetWidth(pcbnew.F_Cu)
            else:
                w = t.GetWidth()
            self.segs.append((a, c, w / 2e6))

    def ok(self, x, y, r, net=None, on_pads=True):
        """on_pads=False keeps off every pad, ground ones too: a via in a pad wicks its solder away."""
        for a, b, c, d, gnd, name in self.boxes:
            if (not on_pads or not gnd or net not in (None, 'GND')) and (not on_pads or name != net) \
                    and x + r > a and x - r < c and y + r > b and y - r < d:
                return False
        for (ax, ay), (cx, cy), w in self.segs:
            dx, dy = cx - ax, cy - ay
            l2 = dx * dx + dy * dy
            k = 0 if l2 == 0 else max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / l2))
            if math.hypot(x - ax - k * dx, y - ay - k * dy) < r + w:
                return False
        return True

    def seg_ok(self, a, c, r, net=None):
        # sampled: fine enough for these short stubs. The first 0.3 mm is inside the pad row
        n = max(2, int(math.hypot(c[0] - a[0], c[1] - a[1]) / 0.1))
        return all(self.ok(a[0] + (c[0] - a[0]) * i / n, a[1] + (c[1] - a[1]) * i / n, r, net) or i < 3 for i in range(n + 1))

    def add(self, x, y):
        self.segs.append(((x, y), (x, y), 0.3))


def fence(bd, free):
    """Via fence along the landing lines, as on the fixture, and ground around the crossing."""
    for sy in (-1, 1):
        y = LAND0 - 1.0
        while y < VOID_Y - 1.5:
            for x in (-(MS_W / 2 + MS_GAP + 0.8), MS_W / 2 + MS_GAP + 0.8):
                bd.via(x, sy * y, 'GND')
            y += 2.0
        for x in (-3.0, 3.0):
            bd.via(x, sy * (VIA_Y + 2.2), 'GND', 0.6, 0.3)


def ground_vias(bd, free):
    """QFN ground pins tie inward to the exposed pad, whose vias are already there. Other SMD ground pads get a via."""
    for ref, fp in bd.fps.items():
        ep = [p for p in fp.Pads() if p.GetNetname() == 'GND' and p.GetBoundingBox().GetWidth() > FromMM(2)
              and p.GetBoundingBox().GetHeight() > FromMM(2) and p.IsOnLayer(pcbnew.B_Cu) and p.GetAttribute() != pcbnew.PAD_ATTRIB_PTH]
        for p in fp.Pads():
            if p.GetNetname() != 'GND' or not p.IsOnLayer(pcbnew.B_Cu) or p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                continue
            px, py = mm(p.GetPosition())
            if p in ep or any(p.GetNumber() == e.GetNumber() for e in ep):
                continue
            if ep:
                cx, cy = mm(ep[0].GetPosition())
                bb = ep[0].GetBoundingBox()
                hw, hh = bb.GetWidth() / 2e6 - 0.1, bb.GetHeight() / 2e6 - 0.1
                ex, ey = (cx + max(-hw, min(hw, px - cx)), cy + max(-hh, min(hh, py - cy)))
                bd.track((px, py), (ex, ey), 0.2, 'GND')
                continue
            done = False
            for r in (0.9, 1.1, 1.3, 1.6, 2.0, 2.5, 3.0, 3.5):
                for k in range(16):
                    x, y = px + r * math.cos(k * math.pi / 8), py + r * math.sin(k * math.pi / 8)
                    if free.ok(x, y, 0.5) and (r <= 1.1 or free.seg_ok((px, py), (x, y), 0.25, 'GND')):
                        if r > 1.1:
                            bd.track((px, py), (x, y), 0.2, 'GND')
                        bd.via(x, y, 'GND', 0.6, 0.3)
                        free.add(x, y)
                        done = True
                        break
                if done:
                    break
            if not done and ref != 'J5':     # J5 sits in its own B.Cu pour
                print('no ground via for', ref, p.GetNumber())


def stitch(bd, free):
    """GND vias tying floor, In2 and B.Cu together on a 10 mm grid, wherever there is room."""
    x = X0 + 5
    while x < X1 - 3:
        y = -Y1 + 5
        while y < Y1 - 3:
            inside = abs(x) < 9.5 and abs(y) > LAND0 - 8
            # off the pads: one on U3 pins 1-2 left them short of solder on the first JLC run
            if not inside and free.ok(x, y, 0.65, on_pads=False):
                bd.via(x, y, 'GND')
            y += 10.0
        x += 10.0


def build():
    bd = B()
    bd.outline(rounded(X0, -Y1, X1, Y1, 4.0))
    for x, y in TEM_PLATE_HOLES + FEET:
        bd.hole(x, y)

    # ---- fixed parts and RF chains ----
    for ref, (x, y, rot, side) in FIXED.items():
        bd.place(ref, x, y, rot, side)
    tx_end, tx_net = rf_chain(bd, -1, TX_SERIES, TX_SHUNT, 'CELL_P1')
    rx_end, rx_net = rf_chain(bd, 1, RX_SERIES, RX_SHUNT, 'CELL_P2')

    # the 3 mm landing lines on the floor, and the crossing to B.Cu
    for sy, net in ((-1, 'CELL_P1'), (1, 'CELL_P2')):
        bd.track((0, sy * LAND0), (0, sy * PAD_Y), MS_W, net, pcbnew.F_Cu)
        bd.via(0, sy * VIA_Y, net)
        y_lo, y_hi = LAND0, ramp_tip_y(min(TEM_H)) + 0.4
        bd.shape(pcbnew.F_Mask, rect(-MS_W / 2, min(sy * y_lo, sy * y_hi), MS_W / 2, max(sy * y_lo, sy * y_hi)), fill=True)
        for h in TEM_H:
            yl = sy * ramp_tip_y(h)
            bd.shape(pcbnew.F_SilkS, [(MS_W / 2 + 1.6, yl), (MS_W / 2 + 4.0, yl)], w=0.2, closed=False)
            bd.text('h%g' % h, MS_W / 2 + 7.0, yl, 1.2)
        # In1/In2 cut away under the line so that it sees B.Cu, as on the fixture
        y0, y1 = sorted((sy * (LAND0 - 6), sy * VOID_Y))
        bd.rule_area(rect(-9, y0, 9, y1), [pcbnew.In1_Cu, pcbnew.In2_Cu], vias=False)
        # no routing on B.Cu under it: its reference has to stay whole
        y0, y1 = sorted((sy * (LAND0 - 6), sy * (VIA_Y - 0.7)))
        bd.rule_area(rect(-9, y0, 9, y1), [pcbnew.B_Cu], vias=False, pour=False)

    # source output: C3 -> RFOUTA+; receive: C21 -> INHI. Both stay clear of the small parts placed next
    x12, y12 = bd.padxy('U2', '12')
    bd.poly([(tx_end, -VIA_Y), (x12, -VIA_Y), (x12, y12)], W50, tx_net)
    x14, y14 = bd.padxy('U3', '14')
    bd.poly([(rx_end, VIA_Y), (x14, VIA_Y), (x14, y14)], W50, rx_net)
    for x, y, c, d in ((tx_end, -VIA_Y, x12, y12), (rx_end, VIA_Y, x14, y14)):
        bd.boxes.append((min(x, c) - 0.6, y - 0.6, max(x, c) + 0.6, y + 0.6))
        bd.boxes.append((c - 0.6, min(y, d) - 0.6, c + 0.6, max(y, d) + 0.6))

    # ---- small parts next to what they serve ----
    for ref, target in NEAR.items():
        near_place(bd, ref, target)

    missing = set(bd.comps) - set(bd.fps)
    if missing:
        raise SystemExit('no placement for: %s' % sorted(missing))

    # ---- silk ----
    gf_like_test_area(bd)
    bd.shape(pcbnew.F_SilkS, rect(-TEM['w'] / 2, -TEM['length'] / 2, TEM['w'] / 2, TEM['length'] / 2), w=0.15)
    # U4 has no exposed pad, and its two ground pins sit either side of a signal: join them under the body
    ux, uy = mm(bd.fps['U4'].GetPosition())
    bd.via(ux, uy, 'GND', 0.6, 0.3)
    for num in ('1', '3'):
        px, py = bd.padxy('U4', num)
        bd.poly([(px, py), (ux, py), (ux, uy)], 0.2, 'GND')    # straight in first: pin 2 is between them
    # thermal and RF ground under the chips: placed now so that the router has to go around them
    for ref in ('U2', 'U3'):
        cx, cy = mm(bd.fps[ref].GetPosition())
        for dx in (-0.8, 0.8):
            for dy in (-0.8, 0.8):
                bd.via(cx + dx, cy + dy, 'GND', 0.6, 0.3)
    rail_fanout(bd)
    bd.text('OPEN TEM CELL - rev 0.2 CONCEPT', 0, -26, 2.4)
    bd.text('not validated', 0, -22, 1.8)
    bd.text('slide wallet in flat, from this side', -16, 12, 1.6)
    bd.text(gf.REPO, 0, 58, 1.6)
    bd.text('LCD 2.0in ST7789', 102, -2, 2.0)
    bd.shape(pcbnew.F_SilkS, rect(85, -34, 120, 34), w=0.15)
    bd.text('GREEN', 92, -52, 1.6)
    bd.text('RED', 108, -52, 1.6)
    bd.text('START', 100, -74, 1.6)
    bd.text('Pico 2: micro-USB and BOOTSEL here', 100, 16, 1.4, pcbnew.B_SilkS, mirror=True)
    bd.text('SOURCE - fit shield can on this frame', 32, -71, 1.4, pcbnew.B_SilkS, mirror=True)
    bd.text('DETECTOR - fit shield can on this frame', 32, 71, 1.4, pcbnew.B_SilkS, mirror=True)
    bd.text('J4: spare GPIO / ADC / RUN', 86, 76, 1.4, pcbnew.B_SilkS, mirror=True)
    return bd


def gf_like_test_area(bd):
    layer = pcbnew.F_SilkS
    bd.shape(layer, rect(-40, -40, 40, 40), w=0.3)
    for sx in (-1, 1):
        for sy in (-1, 1):
            for k in range(1, 4):
                v = 10 * k
                bd.shape(layer, [(sx * 40, sy * v), (sx * 38, sy * v)], w=0.2, closed=False)
                bd.shape(layer, [(sx * v, sy * 40), (sx * v, sy * 38)], w=0.2, closed=False)
    bd.shape(layer, [(-3, 0), (3, 0)], w=0.2, closed=False)
    bd.shape(layer, [(0, -3), (0, 3)], w=0.2, closed=False)
    bd.text('80 x 80 mm test area', 0, -36, 2.0, layer)


def rail_fanout(bd):
    """+3V3A stays inside the source block as a pour on In1: each pad gets its own via and the router skips the net."""
    free = Free(bd)
    ux, uy = mm(bd.fps['U2'].GetPosition())
    vias = []
    for ref, fp in bd.fps.items():
        for p in fp.Pads():
            net = p.GetNetname()
            if net.lstrip('/') != '+3V3A':
                continue
            px, py = mm(p.GetPosition())
            away = math.atan2(py - uy, px - ux) if ref == 'U2' else None
            done = False
            for r in (1.0, 1.2, 1.5, 1.8, 2.2, 2.6, 3.0, 3.5, 4.0):
                for k in range(24):
                    a = (away + (k % 2 * 2 - 1) * (k // 2) * math.pi / 12) if away is not None else k * math.pi / 12
                    x, y = px + r * math.cos(a), py + r * math.sin(a)
                    if free.ok(x, y, 0.5, net) and free.seg_ok((px, py), (x, y), 0.25, net):
                        bd.track((px, py), (x, y), 0.2, '+3V3A')
                        bd.via(x, y, '+3V3A', 0.6, 0.3)
                        vias.append((x, y))
                        free.add(x, y)
                        done = True
                        break
                if done:
                    break
            if not done:
                raise SystemExit('no rail via for %s %s' % (ref, p.GetNumber()))
    # a ring on In1 around U2 with a straight link to every via: the pour alone gets cut up by signals
    r = 5.0
    ring = [(ux - r, uy - r), (ux + r, uy - r), (ux + r, uy + r), (ux - r, uy + r), (ux - r, uy - r)]
    bd.poly(ring, 0.4, '+3V3A', pcbnew.In1_Cu)
    for x, y in vias:
        rx, ry = max(ux - r, min(ux + r, x)), max(uy - r, min(uy + r, y))
        if abs(x - ux) < r and abs(y - uy) < r:     # inside: go to the nearest side
            if r - abs(x - ux) < r - abs(y - uy):
                rx = ux + (r if x > ux else -r)
            else:
                ry = uy + (r if y > uy else -r)
        bd.track((x, y), (rx, ry), 0.4, '+3V3A', pcbnew.In1_Cu)


FRAME = (-10.5, 59.5, 72.5, 107.0)


def frame_rings():
    x0, x1, ya, yb = FRAME
    for sy in (-1, 1):
        y0, y1 = sorted((sy * ya, sy * yb))
        yield y0, y1, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def shield_frames(bd, free):
    """Bare GND ring on B.Cu for a soldered or clipped shield around each RF block, stitched to the planes."""
    x0, x1, _, _ = FRAME
    for y0, y1, ring in frame_rings():
        for a, c in zip(ring, ring[1:]):
            bd.track(a, c, 1.2, 'GND')
            n = int(max(abs(c[0] - a[0]), abs(c[1] - a[1])) // 5)
            for i in range(n):      # the next side starts where this one ends
                x, y = a[0] + (c[0] - a[0]) * i / max(n, 1), a[1] + (c[1] - a[1]) * i / max(n, 1)
                if abs(y) > 105 and abs(x) < 5:     # the landing line and the SMA pad are on the floor here
                    continue
                if free.ok(x, y, 0.5):
                    bd.via(x, y, 'GND', 0.6, 0.3)
        bd.shape(pcbnew.B_Mask, rect(x0 - 0.6, y0 - 0.6, x1 + 0.6, y0 + 0.6), fill=True)
        bd.shape(pcbnew.B_Mask, rect(x0 - 0.6, y1 - 0.6, x1 + 0.6, y1 + 0.6), fill=True)
        bd.shape(pcbnew.B_Mask, rect(x0 - 0.6, y0, x0 + 0.6, y1), fill=True)
        bd.shape(pcbnew.B_Mask, rect(x1 - 0.6, y0, x1 + 0.6, y1), fill=True)


def route_keepouts(bd):
    """Only for the router: the frames and the fence must find free copper afterwards."""
    before = set(z.m_Uuid.AsString() for z in bd.b.Zones())
    for y0, y1, ring in frame_rings():
        for (ax, ay), (cx, cy) in zip(ring, ring[1:]):
            bd.rule_area(rect(min(ax, cx) - 1.1, min(ay, cy) - 1.1, max(ax, cx) + 1.1, max(ay, cy) + 1.1), [pcbnew.B_Cu], vias=True, pour=False)
    for sy in (-1, 1):
        y0, y1 = sorted((sy * (LAND0 - 7), sy * (VIA_Y - 0.7)))
        bd.rule_area(rect(-9.5, y0, 9.5, y1), [pcbnew.In1_Cu, pcbnew.B_Cu], vias=True, pour=False)
    return [z for z in bd.b.Zones() if z.m_Uuid.AsString() not in before]


def route(bd):
    # the router isn't deterministic: LID_PCB_OUT lets several attempts run side by side
    base = os.path.splitext(os.environ.get('LID_PCB_OUT', os.path.join(PRJ, NAME + '.kicad_pcb')))[0]
    dsn, ses = base + '.dsn', base + '.ses'
    temp = route_keepouts(bd)
    # GND and +3V3A come from pours. Everything hand-drawn so far is locked and stays in the file
    plane = ('GND', '+3V3A', '/+3V3A')
    pads = [(pad, pad.GetNetCode()) for fp in bd.b.GetFootprints() for pad in fp.Pads() if pad.GetNetname() in plane]
    for pad, _ in pads:
        pad.SetNetCode(0)
    if not pcbnew.ExportSpecctraDSN(bd.b, dsn):
        raise SystemExit('DSN export failed')
    # the floor and In2 stay whole: the router may only use In1 and B.Cu
    t = open(dsn).read()
    t, n = re.subn(r'(\(layer (?:F\.Cu|In2\.Cu)\s*\(type )\w+', r'\1power', t)
    if n != 2:
        raise SystemExit('expected to retype 2 layers, did %d' % n)
    open(dsn, 'w').write(t)
    jar = os.environ.get('FREEROUTING_JAR', 'freerouting.jar')
    subprocess.run(['java', '-Xmx8g', '-jar', jar, '-de', dsn, '-do', ses, '-mp', os.environ.get('FREEROUTING_PASSES', '40')]
                   + os.environ.get('FREEROUTING_EXTRA', '').split(), check=True, timeout=3000)
    if not pcbnew.ImportSpecctraSES(bd.b, ses):
        raise SystemExit('SES import failed')
    for pad, code in pads:
        pad.SetNetCode(code)
    for z in temp:
        bd.b.Remove(z)
    os.unlink(dsn)
    os.unlink(ses)


def pours(bd):
    outline = rounded(X0, -Y1, X1, Y1, 4.0)
    bd.zone([pcbnew.F_Cu], outline, 'GND', clearance=MS_GAP)
    bd.zone([pcbnew.In2_Cu], outline, 'GND', clearance=0.3)
    bd.zone([pcbnew.B_Cu], outline, 'GND', clearance=0.3)
    # the analog rail: everything on it is inside the source block
    bd.zone([pcbnew.In1_Cu], rect(12.0, -106.0, 58.0, -74.0), '+3V3A', clearance=0.3)


def fill(path):
    b = pcbnew.LoadBoard(path)
    b.BuildConnectivity()
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    # a GND pour island with no way down gets a via of its own
    hold = type('Hold', (), {'b': b})()
    free = Free(hold)
    added = 0
    vias = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == 'GND']
    pads = [p for fp in b.GetFootprints() for p in fp.Pads() if p.GetNetname() == 'GND' and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
    for z in list(b.Zones()):
        if z.GetIsRuleArea() or z.GetNetname() != 'GND':
            continue
        for layer in z.GetLayerSet().Seq():
            polys = z.GetFilledPolysList(layer)
            for i in range(polys.OutlineCount()):
                if any(polys.Contains(v.GetPosition(), i) for v in vias) or any(polys.Contains(p.GetPosition(), i) for p in pads):
                    continue
                bb = polys.Outline(i).BBox()
                done = False
                for x in range(bb.GetLeft(), bb.GetRight(), 50000):
                    for y in range(bb.GetTop(), bb.GetBottom(), 50000):
                        if polys.Contains(VECTOR2I(x, y), i) and free.ok(x / 1e6 - OX, y / 1e6 - OY, 0.46):
                            v = pcbnew.PCB_VIA(b)
                            v.SetPosition(VECTOR2I(x, y))
                            v.SetDrill(FromMM(0.3))
                            v.SetWidth(pcbnew.F_Cu, FromMM(0.6))
                            v.SetNet(z.GetNet())
                            b.Add(v)
                            vias.append(v)
                            free.add(x / 1e6 - OX, y / 1e6 - OY)
                            added += 1
                            done = True
                            break
                    if done:
                        break
                if not done:
                    print('GND island with no room for a via on', b.GetLayerName(layer), bb.GetCenter().x / 1e6 - OX, bb.GetCenter().y / 1e6 - OY)
    if added:
        print('island vias', added)
        b.BuildConnectivity()
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(path)


def main():
    if sys.argv[1:2] == ['--fill']:
        fill(sys.argv[2])
        return
    bd = build()
    path = os.environ.get('LID_PCB_OUT', os.path.join(PRJ, NAME + '.kicad_pcb'))
    if '--no-route' not in sys.argv:
        route(bd)
    free = Free(bd)
    fence(bd, free)
    ground_vias(bd, free)
    shield_frames(bd, free)
    stitch(bd, free)
    # the router works to 0.15 mm and rounds a hair under it on diagonals
    bd.b.GetDesignSettings().m_NetSettings.GetDefaultNetclass().SetClearance(FromMM(0.14))
    pours(bd)
    bd.b.Save(path)
    subprocess.run([sys.executable, os.path.abspath(__file__), '--fill', path], check=True)
    print('wrote', path)


def jlc_files(fab):
    """JLC assembles everything except the Pico and the LCD header, which are hand-soldered (see ORDER.md).
    Its BOM check also needs every designator written out: kicad-cli groups them as C3-C6."""
    hand = {'J3', 'U1'}

    def expand(refs):
        out = []
        for part in refs.split(','):
            m = re.fullmatch(r'([A-Z]+)(\d+)-[A-Z]*(\d+)', part.strip())
            if m:
                out += ['%s%d' % (m.group(1), n) for n in range(int(m.group(2)), int(m.group(3)) + 1)]
            else:
                out.append(part.strip())
        return out
    # exact LCSC parts, so JLC has nothing to ask about. Checked against its listings, see docs/rev02_integrated.md
    parts = {'0': ('0603WAF0000T5E', 'C21189'), '100': ('0603WAF1000T5E', 'C22775'), '68': ('0603WAF680JT5E', 'C27592'),
             '49.9': ('0603WAF499JT5E', 'C23185'), '5.1k': ('0603WAF5101T5E', 'C23186'), '510': ('0603WAF5100T5E', 'C23193'),
             '330': ('RC0603FR-07330RL', 'C105881'), '33': ('0603WAF330JT5E', 'C23140'), '150': ('0603WAF1500T5E', 'C22808'),
             '39': ('0603WAF390JT5E', 'C23154'), '499': ('RC0603FR-07499RL', 'C137714'), '1k': ('0603WAF1001T5E', 'C21190'),
             '100k': ('0603WAF1003T5E', 'C25803'), '4.7k': ('0603WAF4701T5E', 'C23162'), '10k': ('0603WAF1002T5E', 'C25804'),
             '47': ('0603WAF470JT5E', 'C23182'), '100p': ('CC0603JRNPO0BN101', 'C107033'), '220p': ('GCM1885C2A221JA16D', 'C388907'),
             '680p': ('CC0603JRNPO9BN681', 'C107055'), '1n': ('CL10C102JB8NNNC', 'C163508'), '1.5n': ('CGA0603C0G152J500JT', 'C36911403'),
             '10n': ('0603B103K500NT', 'C57112'), '15n': ('CC0603KRX7R9BB153', 'C107076'), '100n': ('CC0603KRX7R9BB104', 'C14663'),
             '4.7u': ('CL21A475KBQNNNE', 'C98192'), '10u': ('CL21A106KAYNNNE', 'C15850'), '600R': ('GZ1608D601TF', 'C1002'),
             'green': ('333-2SYGD/S530-E2-L', 'C99697'), 'red': ('333-2SURD/S530-A3', 'C87271'), 'Start': ('TS665CJ', 'C393938'),
             'ADF4351BCPZ': ('ADF4351BCPZ', 'C654681'), 'AD8318ACPZ-REEL7': ('AD8318ACPZ-REEL7', 'C578694'),
             'ADS1115IDGSR': ('ADS1115IDGSR', 'C37593'), 'AP2112K-3.3TRG1': ('AP2112K-3.3TRG1', 'C51118'),
             'OT322525MJBA4SL': ('OT322525MJBA4SL', 'C669088'), 'U.FL-R-SMT-1(80)': ('U.FL-R-SMT-1(80)', 'C88374')}
    for name in ('bom_jlc.csv', 'cpl_jlc.csv'):
        path = os.path.join(fab, name)
        rows = list(csv.DictReader(open(path)))
        with open(path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            for r in rows:
                refs = [x for x in expand(r['Designator']) if x not in hand]
                if refs:
                    r['Designator'] = ','.join(refs)
                    if 'Comment' in r:
                        r['Comment'], r['LCSC Part #'] = parts[r['Comment']]
                    w.writerow(r)


# JLC's footprint library uses other zero orientations and origins than KiCad for these (checked in its preview)
JLC_ROT = {'U2': 90, 'U3': 90, 'U4': 90, 'U5': 90, 'J5': 90, 'Y1': 180, 'D1': 180}
JLC_CENTRE = {'J5', 'SW1', 'D1', 'D2'}        # placed by the centre of its pads, not the footprint origin


def jlc_cpl_fix(fab, pcb):
    b = pcbnew.LoadBoard(pcb)
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    path = os.path.join(fab, 'cpl_jlc.csv')
    rows = list(csv.DictReader(open(path)))
    for r in rows:
        ref = r['Designator']
        if ref in JLC_ROT:
            r['Rotation'] = '%.6f' % ((float(r['Rotation']) + JLC_ROT[ref]) % 360)
        if ref in JLC_CENTRE:
            fp = fps[ref]
            boxes = [pd.GetBoundingBox() for pd in fp.Pads()]
            cx = (min(x.GetLeft() for x in boxes) + max(x.GetRight() for x in boxes)) / 2
            cy = (min(x.GetTop() for x in boxes) + max(x.GetBottom() for x in boxes)) / 2
            o = fp.GetPosition()
            # the placement file has y up from the drill origin
            r['Mid X'] = '%.6fmm' % (float(r['Mid X'][:-2]) + (cx - o.x) / 1e6)
            r['Mid Y'] = '%.6fmm' % (float(r['Mid Y'][:-2]) - (cy - o.y) / 1e6)
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def outputs():
    """Fab package and renders, using the same steps as the detector board."""
    import make_outputs as mo
    mo.PRJ, mo.NAME, mo.PCB, mo.SCH, mo.FAB = PRJ, NAME, os.path.join(PRJ, NAME + '.kicad_pcb'), os.path.join(PRJ, NAME + '.kicad_sch'), os.path.join(PRJ, 'fab')
    os.makedirs(mo.FAB, exist_ok=True)
    mo.gerbers()
    mo.bom()
    mo.cpl()
    mo.schematic_pdf()
    jlc_files(mo.FAB)
    jlc_cpl_fix(mo.FAB, mo.PCB)
    mo.cli('pcb', 'drc', '--schematic-parity', '--severity-error', '--severity-warning', '-o', os.path.join(mo.FAB, 'drc_report.txt'), mo.PCB)
    mo.cli('sch', 'erc', '--severity-error', '--severity-warning', '-o', os.path.join(mo.FAB, 'erc_report.txt'), mo.SCH)
    img = os.path.join(ROOT, 'docs', 'img')
    common = ['--quality', 'high', '--background', 'opaque', '-w', '1600', '-h', '1600']
    mo.cli('pcb', 'render', *common, '--side', 'top', '-o', os.path.join(img, 'integrated_top.png'), mo.PCB)
    mo.cli('pcb', 'render', *common, '--side', 'bottom', '-o', os.path.join(img, 'integrated_bottom.png'), mo.PCB)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--outputs']:
        outputs()
    else:
        main()
