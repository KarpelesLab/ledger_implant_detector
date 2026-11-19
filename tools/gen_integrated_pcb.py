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
RX_SERIES = [('R20', 6.0), ('R22', 13.0)]          # C21 and its 50 ohm shunt R24 sit at INHI (rf_terminations())
RX_SHUNT = [('R21', 8.5), ('R23', 15.5)]
# hand-routed: anything the router adds on them is removed
RF_NETS = ('CELL_P1', 'CELL_P2', 'TX_A', 'TX_B', 'TX_C', 'RX_A', 'RX_B', 'DET_HI', 'RFA_P',
           'RFA_N', 'RFA_T', 'RFB_P', 'RFB_N', 'RFB_T', 'RFB_OUT', 'DET_LO')     # see rf_terminations()

# fixed placement: ref -> (x, y, rot, side)
FIXED = {
    'J1': (0, -PAD_Y, 90, 'F'), 'J2': (0, PAD_Y, 270, 'F'),
    'U2': (32.0, -95.0, 0, 'B'), 'U3': (27.0, 96.5, 0, 'B'), 'U4': (46.0, 92.0, 0, 'B'),
    'U5': (52.0, -82.0, 0, 'B'), 'Y1': (32.8, -82.5, 180, 'B'),      # REFOUT faces REFIN, straight below it
    'U1': (127.5, 8.89, 90, 'B'),       # Pico 2: pin 1 and the micro-USB at the +x edge
    # J3: pin 1 (GND) at +x. Rev 0.2 had it at -x, so the module had to sit turned round, off the board edge
    'J3': (111.28, 32.0, 270, 'F'), 'D1': (92.0, -45.0, 0, 'F'), 'D2': (108.0, -45.0, 0, 'F'),
    'SW1': (97.0, -66.0, 0, 'F'),
    'J4': (86.0, 60.0, 90, 'B'),
    'TP1': (40.0, 80.0, 0, 'B'), 'TP3': (46.0, -76.0, 0, 'B'),       # TP2 (VTUNE) sits with the loop filter
    'TP4': (52.0, -76.0, 0, 'B'), 'TP5': (46.0, 80.0, 0, 'B'), 'TP6': (52.0, 80.0, 0, 'B'),
}
# small parts placed next to the pad they serve: ref -> (target ref, target pad)
# (the parts around U2 and U3 are placed by hand: see support_parts())
NEAR = {
    'R31': ('U3', '6'),
    'R27': ('U4', '4'), 'C28': ('U4', '4'), 'C29': ('U4', '5'), 'R29': ('U4', '6'), 'R30': ('U4', '6'),
    'C30': ('U4', '6'), 'FB4': ('U4', '8'), 'C31': ('U4', '8'),
    'C32': ('U5', '1'), 'C33': ('U5', '5'),
    'C34': ('U1', '36'), 'R32': ('U1', '1'), 'R33': ('U1', '2'), 'R34': ('U1', '6'),
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
        tb.SetRevision('0.3')
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
        if ref in self.fps:
            raise SystemExit('%s placed twice' % ref)
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
        fp.Reference().SetTextSize(VECTOR2I(FromMM(1.0), FromMM(1.0)))      # JLC minimum 1.0 / 0.15 mm
        fp.Reference().SetTextThickness(FromMM(0.15))
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
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)   # see thermals(): RF grounds stay solid
        z.SetThermalReliefGap(FromMM(THERMAL_GAP))
        z.SetThermalReliefSpokeWidth(FromMM(THERMAL_SPOKE))
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


def place_at(bd, ref, x, y, vertical, pad_net, at):
    """2-pad part centred on (x, y), along y if vertical, with its pad on pad_net nearest the point `at`."""
    fp = bd.place(ref, x, y, 90 if vertical else 0)
    pads = list(fp.Pads())
    mine = [p for p in pads if p.GetNetname().lstrip('/') == pad_net][0]
    other = pads[1] if mine is pads[0] else pads[0]
    d = lambda p: math.hypot(mm(p.GetPosition())[0] - at[0], mm(p.GetPosition())[1] - at[1])
    if d(mine) > d(other):
        fp.SetOrientationDegrees(270 if vertical else 180)
    return fp


def hand(bd, pts, net, w=0.2):
    """A locked track, also kept as boxes so that near_place() leaves it alone."""
    bd.poly(pts, w, net)
    for (ax, ay), (cx, cy) in zip(pts, pts[1:]):
        bd.boxes.append((min(ax, cx) - w / 2 - 0.3, min(ay, cy) - w / 2 - 0.3, max(ax, cx) + w / 2 + 0.3, max(ay, cy) + w / 2 + 0.3))


def rf_terminations(bd, rx_end):
    """The parts on the ADF4351 outputs and the AD8318 input, placed and wired by hand next to the pins.

    Rev 0.2 left them to near_place() and the router: the margin kept around each chip pushed them
    7-14 mm away, and the router wired RFOUTA- through 45 mm to its pull-up and termination and
    INLO through 22 mm to its decoupling. Both stubs resonate in the band (a 12-15 dB notch at
    1.4 GHz on the built boards, bench-tested 2026-11-17). Here every one of those nets is a few
    mm long and fully drawn, so the router has nothing left to do on them.

    Source, below U2's pin row (pins 12-15 face the board edge): RFOUTA+ is the 50 ohm line to C3,
    drawn in build(). Its pull-up R5 hangs to its left. RFOUTA-, RFOUTB+ and RFOUTB- leave
    straight down and turn right at three depths, the deepest first, so nothing crosses: RFOUTA-
    gets C4 right below its turn, with R6 (pull-up, C36 at its supply end) and R7 (its 50 ohm
    termination) beside it; RFOUTB+ gets R8 and C5 to J5; RFOUTB- gets R9, C6 and R10.
    Detector: the 50 ohm line ends at R24, C21 stands on it right below INHI.
    """
    W = 0.2
    x12, y12 = bd.padxy('U2', '12')
    x13, x14, x15 = (bd.padxy('U2', n)[0] for n in ('13', '14', '15'))
    # turn depths: RFOUTA-, RFOUTB+, RFOUTB-. The band above LC holds the VVCO decoupling (support_parts())
    LA, LB, LC = y12 - 3.46, y12 - 2.61, y12 - 2.01
    # RFOUTA+ pull-up, left of the 50 ohm line
    place_at(bd, 'R5', x12 - 1.125, LA - 0.9, False, 'RFA_P', (x12, LA - 0.9))
    hand(bd, [bd.padxy('R5', [p.GetNumber() for p in bd.fps['R5'].Pads() if p.GetNetname().lstrip('/') == 'RFA_P'][0]), (x12, LA - 0.9)], 'RFA_P')
    # RFOUTA-: C4 straight below the pin's turn (0.5 mm clear of the RFOUTA+ line), R6 to +3V3A beside
    # its top pad with C36 (100p) at R6's supply end, R7 to GND beside its bottom pad
    xa, ya = x13 + 0.65, LA - 0.4
    place_at(bd, 'C4', xa, ya - 0.775, True, 'RFA_N', (xa, LA))
    place_at(bd, 'R6', xa + 2.26, ya, False, 'RFA_N', (x13, ya))
    place_at(bd, 'R7', xa + 2.26, ya - 1.55, False, 'RFA_T', (x13, ya - 1.55))
    place_at(bd, 'C36', xa + 5.22, ya, False, '+3V3A', (x13, ya))
    r6a, r6s = at_net(bd, 'R6', 'RFA_N'), at_net(bd, 'R6', '+3V3A')
    c36 = at_net(bd, 'C36', '+3V3A')
    hand(bd, [(x13, y12), (x13, ya), r6a], 'RFA_N', W)
    hand(bd, [at_net(bd, 'C4', 'RFA_T'), at_net(bd, 'R7', 'RFA_T')], 'RFA_T', W)
    hand(bd, [r6s, c36], '+3V3A', 0.3)
    bd.via(xa + 4.0, ya - 0.9, '+3V3A', 0.6, 0.3)
    bd.track(c36, (xa + 4.0, ya - 0.9), 0.3, '+3V3A')
    gx, gy = at_net(bd, 'C36', 'GND')
    bd.via(gx, gy - 0.9, 'GND', 0.6, 0.3)
    bd.track((gx, gy), (gx, gy - 0.9), 0.3, 'GND')
    # RFOUTB+: down at xb, R8 to +3V3A on the way, C5 and J5 at the bottom
    xb, yb = x13 + 11.05, LA - 3.4
    hand(bd, [(x14, y12), (x14, LB), (xb, LB), (xb, yb)], 'RFB_P', W)
    place_at(bd, 'R8', xb + 1.075, LA - 1.2, False, 'RFB_P', (xb, LA - 1.2))
    place_at(bd, 'C5', xb + 1.7, yb, False, 'RFB_P', (xb, yb))
    r8 = [mm(p.GetPosition()) for p in bd.fps['R8'].Pads() if p.GetNetname().lstrip('/') == 'RFB_P'][0]
    hand(bd, [(xb, r8[1]), r8], 'RFB_P', W)
    c5a = [mm(p.GetPosition()) for p in bd.fps['C5'].Pads() if p.GetNetname().lstrip('/') == 'RFB_P'][0]
    c5b = [mm(p.GetPosition()) for p in bd.fps['C5'].Pads() if p.GetNetname().lstrip('/') == 'RFB_OUT'][0]
    hand(bd, [(xb, yb), c5a], 'RFB_P', W)
    jx = c5b[0] + 3.3
    for rot in (0, 180):
        fp = bd.place('J5', jx, yb, rot, 'B')
        if bd.padxy('J5', '1')[0] < jx:
            break
        bd.b.Remove(fp)
        bd.boxes.pop()
        del bd.fps['J5']
    hand(bd, [c5b, bd.padxy('J5', '1')], 'RFB_OUT', W)
    # RFOUTB-: R9 to +3V3A, then C6 and R10 to GND
    xc = xb + 4.2
    place_at(bd, 'R9', xc, LC - 0.825, True, 'RFB_N', (xc, LC))
    place_at(bd, 'C6', xc + 2.4, LC, False, 'RFB_N', (xc, LC))
    place_at(bd, 'R10', xc + 4.8, LC - 0.825, True, 'RFB_T', (xc + 4.8, LC))
    c6a = [mm(p.GetPosition()) for p in bd.fps['C6'].Pads() if p.GetNetname().lstrip('/') == 'RFB_N'][0]
    c6b = [mm(p.GetPosition()) for p in bd.fps['C6'].Pads() if p.GetNetname().lstrip('/') == 'RFB_T'][0]
    hand(bd, [(x15, y12), (x15, LC), c6a], 'RFB_N', W)
    hand(bd, [c6b, (xc + 4.8, LC)], 'RFB_T', W)
    # ground ends: a via right next to each, before the router takes the room
    for ref, dx, dy in (('R7', 0, -1.0), ('R10', 0, -1.0)):
        gx, gy = [mm(p.GetPosition()) for p in bd.fps[ref].Pads() if p.GetNetname() == 'GND'][0]
        bd.via(gx + dx, gy + dy, 'GND', 0.6, 0.3)

    # Detector input: the 50 ohm line (RX_B) runs along the chain to R24, its 50 ohm shunt; C21 stands
    # on it right below INHI, so the open line past the shunt is only C21 and 2.5 mm of DET_HI
    x14d, y14d = bd.padxy('U3', '14')
    cx21 = x14d + 0.9
    place_at(bd, 'C21', cx21, y14d + 2.5, True, 'RX_B', (cx21, VIA_Y))        # clear of U3's courtyard
    place_at(bd, 'R24', cx21 + 2.25, VIA_Y, False, 'RX_B', (cx21, VIA_Y))
    c21i, c21o = at_net(bd, 'C21', 'RX_B'), at_net(bd, 'C21', 'DET_HI')
    hand(bd, [(rx_end, VIA_Y), at_net(bd, 'R24', 'RX_B')], 'RX_B', W50)
    hand(bd, [(cx21, VIA_Y), c21i], 'RX_B', W50)
    hand(bd, [(x14d, y14d), (x14d, c21o[1]), c21o], 'DET_HI', W50)
    gx, gy = at_net(bd, 'R24', 'GND')
    bd.via(gx + 0.9, gy, 'GND', 0.6, 0.3)
    # Detector: INLO (pin 15) is left of the INHI line (pin 14). C22 sits straight below it; ENBL/VPOS
    # (pin 16) steps out sideways first, to its 100 pF C25.
    x14d, y14d = bd.padxy('U3', '14')
    x15d, _ = bd.padxy('U3', '15')
    x16d, _ = bd.padxy('U3', '16')
    cx = x14d - 0.175 - 0.3 - 0.475                         # clear of the INHI line
    place_at(bd, 'C22', cx, y14d + 2.385, True, 'DET_LO', (cx, y14d))
    c22 = [mm(p.GetPosition()) for p in bd.fps['C22'].Pads() if p.GetNetname().lstrip('/') == 'DET_LO'][0]
    hand(bd, [(x15d, y14d), (x15d, c22[1])], 'DET_LO', W)
    ys = y14d + 0.56
    place_at(bd, 'C25', x16d - 3.2, ys, False, '+5VA', (x16d, ys))
    c25 = [mm(p.GetPosition()) for p in bd.fps['C25'].Pads() if p.GetNetname().lstrip('/') == '+5VA'][0]
    hand(bd, [(x16d, y14d), (x16d, ys), c25], '+5VA', 0.3)
    for ref, dx, dy in (('C22', -1.1, 0), ('C25', -1.0, 0)):
        gx, gy = [mm(p.GetPosition()) for p in bd.fps[ref].Pads() if p.GetNetname() == 'GND'][0]
        bd.via(gx + dx, gy + dy, 'GND', 0.6, 0.3)


def at_net(bd, ref, net):
    """Position of the pad of `ref` on `net`."""
    return [mm(p.GetPosition()) for p in bd.fps[ref].Pads() if p.GetNetname().lstrip('/') == net][0]


# pads whose rail via is drawn by hand in support_parts(): rail_fanout() leaves them alone
RAIL_HAND = {('U2', '10'), ('U2', '28'), ('U2', '32'), ('C17', '1'), ('C18', '1'), ('C19', '1'),
             ('Y1', '1'), ('Y1', '4'), ('C20', '1'), ('U3', '3'), ('U3', '4'), ('U3', '9'), ('U3', '16'), ('C24', '1'), ('C26', '1'), ('C27', '1'), ('C25', '1'),
             ('R6', '1'), ('R6', '2'), ('C36', '1')}


def support_parts(bd):
    """Decoupling, bias and loop filter parts of U2 and U3, each next to its pin and wired by hand.

    Rev 0.2/0.3 placed them with near_place(), which keeps a 2.8 mm margin round the chips for the
    router: they landed 9-35 mm away (C15 on VVCO 35 mm, C10 on TEMP 29 mm, a 43 mm VTUNE through
    TP2), and the router threaded other nets between their pads and along the RF lines.

    U2 right side, pins 17-24: VVCO runs out along one line, C16 (100p), C15 (100n) and FB2 hang
    off it into the band above the RFOUT turns. TEMP, RSET and VREF each have a part in the first
    column, VCOM passes between them to C11 in the second. VTUNE drops to In1 right at pin 20 and
    runs under the chip, between the exposed pad vias, to the loop filter on the left.
    U2 left side: VP (pin 6) runs out to C14 and FB3; CP (pin 7) is a short spine with C7, R12 (+C8)
    and R13 (+C9) hanging off it. U2 top row: pins 28 and 32 drop to In1 (+3V3A) next to the pin,
    C18 and C19 sit just inside.
    U3: +5VA is a pour on In1 (pours()); every supply pin has its 100n/100p within 2 mm.
    """
    W = 0.2
    p = lambda n: bd.padxy('U2', n)
    # ---- U2 right: VVCO ----
    yv = -96.95
    for ref, x in (('C16', 35.9), ('C15', 37.45)):
        place_at(bd, ref, x, yv - 0.825, True, 'VVCO', (x, yv))
    place_at(bd, 'FB2', 40.2, yv - 0.15, False, 'VVCO', (35.0, yv))
    fb2 = at_net(bd, 'FB2', 'VVCO')
    hand(bd, [p('16'), p('17')], 'VVCO', W)
    hand(bd, [p('17'), (34.95, yv), (fb2[0], yv)], 'VVCO', 0.25)
    gx = (at_net(bd, 'C16', 'GND')[0] + at_net(bd, 'C15', 'GND')[0]) / 2
    bd.via(gx, at_net(bd, 'C16', 'GND')[1], 'GND', 0.6, 0.3)          # shared by both, between the pads
    # ---- U2 right: first column ----
    X1 = 37.3
    place_at(bd, 'C10', X1, -95.42, False, 'SYN_TEMP', p('19'))
    place_at(bd, 'R11', X1, -93.87, False, 'SYN_RSET', p('22'))
    place_at(bd, 'C12', X1, -92.3, False, 'SYN_VREF', p('24'))
    c10, r11, c12 = at_net(bd, 'C10', 'SYN_TEMP'), at_net(bd, 'R11', 'SYN_RSET'), at_net(bd, 'C12', 'SYN_VREF')
    hand(bd, [p('19'), (c10[0] - 0.5, p('19')[1]), (c10[0], c10[1] - 0.2)], 'SYN_TEMP', W)
    hand(bd, [p('22'), (r11[0] - 0.5, p('22')[1]), (r11[0], r11[1] - 0.25)], 'SYN_RSET', W)
    hand(bd, [p('24'), (35.0, -92.7), c12], 'SYN_VREF', W)
    for ref, y in (('C10', -95.42), ('R11', -93.87), ('C12', -92.3)):
        bd.via(39.1, y, 'GND', 0.6, 0.3)
        bd.track(at_net(bd, ref, 'GND'), (39.1, y), 0.3, 'GND')
    # ---- U2 right: VCOM between the rows, to the second column ----
    X2 = 40.9
    place_at(bd, 'C11', X2, -93.1, False, 'SYN_VCOM', (35.0, -93.1))
    place_at(bd, 'C13', X2, -91.5, False, 'SYN_VCOM', (35.0, -91.5))
    c11, c13 = at_net(bd, 'C11', 'SYN_VCOM'), at_net(bd, 'C13', 'SYN_VCOM')
    hand(bd, [p('23'), (35.05, p('23')[1]), (35.55, -93.1), c11], 'SYN_VCOM', W)
    hand(bd, [c11, c13], 'SYN_VCOM', W)
    for ref in ('C11', 'C13'):
        gx, gy = at_net(bd, ref, 'GND')
        bd.via(gx + 0.95, gy, 'GND', 0.6, 0.3)
    # ---- VTUNE: down to In1 at pin 20, under U2 between the exposed pad vias ----
    vt_r = (35.4, -95.05)
    hand(bd, [p('20'), vt_r], 'SYN_VT', W)
    bd.via(*vt_r, 'SYN_VT', 0.6, 0.3)
    yu = -95.575                          # between the EP via rows (see build())
    # ---- U2 left: VP ----
    yp = p('6')[1]
    place_at(bd, 'C14', 24.6, yp - 0.825, True, 'VP', (24.6, yp))
    place_at(bd, 'FB3', 22.2, yp, False, 'VP', (24.6, yp))
    hand(bd, [p('6'), (24.6, yp), at_net(bd, 'FB3', 'VP')], 'VP', 0.25)
    gx, gy = at_net(bd, 'C14', 'GND')
    bd.via(gx, gy - 1.0, 'GND', 0.6, 0.3)
    # ---- U2 left: charge pump spine and loop filter ----
    xs = 27.95
    for ref, y, net in (('C7', -97.75, 'SYN_CP'), ('R12', -99.35, 'SYN_CP'), ('R13', -100.95, 'SYN_CP')):
        place_at(bd, ref, xs - (0.775 if ref[0] == 'C' else 0.825), y, False, net, (xs, y))
    place_at(bd, 'C8', 24.075, -99.35, False, 'SYN_LF', (xs, -99.35))
    place_at(bd, 'C9', 24.075, -100.95, False, 'SYN_VT', (xs, -100.95))
    hand(bd, [p('7'), (28.8, p('7')[1]), (xs, p('7')[1] - 0.5), (xs, -100.95)], 'SYN_CP', W)
    hand(bd, [at_net(bd, 'R12', 'SYN_LF'), at_net(bd, 'C8', 'SYN_LF')], 'SYN_LF', W)
    hand(bd, [at_net(bd, 'R13', 'SYN_VT'), at_net(bd, 'C9', 'SYN_VT')], 'SYN_VT', W)
    vt_l = (25.57, -100.15)                  # on the board side of R13/C9: RFA_P runs just below them
    bd.track(((at_net(bd, 'R13', 'SYN_VT')[0] + at_net(bd, 'C9', 'SYN_VT')[0]) / 2, -100.95), vt_l, W, 'SYN_VT')
    bd.via(*vt_l, 'SYN_VT', 0.6, 0.3)
    bd.poly([vt_l, (28.6, -99.3), (28.6, -96.1), (29.1, yu), (34.6, yu), vt_r], W, 'SYN_VT', pcbnew.In1_Cu)
    for ref, dx, dy in (('C7', 0, 1.0), ('C8', 0, 1.0), ('C9', -1.0, 0)):
        gx, gy = at_net(bd, ref, 'GND')
        bd.via(gx + dx, gy + dy, 'GND', 0.6, 0.3)
    # TP2: VTUNE test pad, fed on In1 from the loop filter via (its own via is inside the pad)
    bd.place('TP2', 21.2, -98.2, 0, 'B')
    bd.via(21.2, -98.2, 'SYN_VT', 0.6, 0.3)
    bd.poly([vt_l, (21.2, -98.2)], W, 'SYN_VT', pcbnew.In1_Cu)
    # ---- U2 bottom row: pin 10 (+3V3A) drops to In1 next to the pin, C17 just below ----
    p10 = p('10')
    place_at(bd, 'C17', 30.2, -99.6, False, '+3V3A', p10)
    c17 = at_net(bd, 'C17', '+3V3A')
    bd.via(30.6, -98.6, '+3V3A', 0.6, 0.3)
    hand(bd, [p10, (30.6, -98.6), c17], '+3V3A', W)
    gx, gy = at_net(bd, 'C17', 'GND')
    bd.via(gx, gy + 1.0, 'GND', 0.6, 0.3)
    # ---- U2 top row: pins 28 and 32 to In1, C18/C19 just inside ----
    for pin, ref, x in (('28', 'C18', 32.5), ('32', 'C19', 30.25)):
        px, py = p(pin)
        bd.via(x, -91.35, '+3V3A', 0.6, 0.3)
        place_at(bd, ref, x, -89.675, True, '+3V3A', (x, -91.35))
        hand(bd, [(px, py), (x, -91.35), at_net(bd, ref, '+3V3A')], '+3V3A', W)
        gx, gy = at_net(bd, ref, 'GND')
        bd.via(gx, gy + 1.0, 'GND', 0.6, 0.3)
    # ---- REFIN: R14 at the oscillator's output ----
    yx, yy = bd.padxy('Y1', '3')
    place_at(bd, 'R14', yx, yy - 2.6, True, 'REF_OUT', (yx, yy))      # clear of Y1's courtyard
    hand(bd, [(yx, yy), at_net(bd, 'R14', 'REF_OUT')], 'REF_OUT', W)
    # Y1's supply: one via between its two rail pins, C20 beside it, and a locked In1 track up to pin
    # 28's via, so the digital lines leaving U2 on In1 can't cut it off from the rest of the pour
    yv = ((bd.padxy('Y1', '1')[1] + bd.padxy('Y1', '4')[1]) / 2)
    rv = (bd.padxy('Y1', '1')[0] + 1.2, yv)
    hand(bd, [bd.padxy('Y1', '1'), rv, bd.padxy('Y1', '4')], '+3V3A', W)
    bd.via(*rv, '+3V3A', 0.6, 0.3)
    place_at(bd, 'C20', rv[0] + 1.8, yv, False, '+3V3A', rv)
    hand(bd, [rv, at_net(bd, 'C20', '+3V3A')], '+3V3A', W)
    gx, gy = at_net(bd, 'C20', 'GND')
    bd.via(gx + 1.0, gy, 'GND', 0.6, 0.3)
    # Y1's own ground via, right below its ground pad (rev 0.3 had only C20's, 6 mm away)
    gx, gy = at_net(bd, 'Y1', 'GND')
    bd.via(gx, gy + 1.15, 'GND', 0.6, 0.3)
    bd.track((gx, gy), (gx, gy + 1.15), 0.3, 'GND')
    bd.poly([rv, (rv[0], -90.6), (33.25, -91.35), (32.5, -91.35)], 0.4, '+3V3A', pcbnew.In1_Cu)
    r14 = at_net(bd, 'R14', 'SYN_REF')
    hand(bd, [p('29'), (p('29')[0], r14[1] + 0.6), r14], 'SYN_REF', W)
    # ---- digital pins: fanned out by hand to vias clear of the decoupling, the router takes them on
    # In1 from there. Left side: CLK, DATA, LE, CE; top row between and beside C18/C19: MUX, PDBRF, LD
    for pin, pts in (('1', [(29.0, -93.25), (27.6, -92.4)]), ('2', [(28.6, -93.75), (27.6, -93.4)]),
                     ('3', [(26.8, -94.25)]), ('4', [(28.4, -94.75), (27.8, -94.95)]),
                     ('30', [(31.25, -88.4), (31.05, -88.0)]), ('26', [(33.25, -86.6)]),
                     ('25', [(33.75, -88.2), (34.3, -87.6)])):
        net = bd.padnet('U2', pin).lstrip('/')
        hand(bd, [p(pin)] + pts, net, W)
        bd.via(*pts[-1], net, 0.6, 0.3)

    # ---- U3 ----
    q = lambda n: bd.padxy('U3', n)
    # left: pins 3-4 (+5VA) to C24, via to the In1 pour
    place_at(bd, 'C24', 22.7, 95.85, False, '+5VA', q('3'))
    c24 = at_net(bd, 'C24', '+5VA')
    for pin in ('3', '4'):
        hand(bd, [q(pin), (24.5, q(pin)[1]), c24], '+5VA', W)
    bd.via(c24[0], 94.75, '+5VA', 0.6, 0.3)
    bd.track(c24, (c24[0], 94.75), W, '+5VA')
    # interior row: CLPF to C23, OUT/SET joined by R26
    place_at(bd, 'C23', 24.0, 93.3, False, 'DET_CLPF', q('5'))
    c23 = at_net(bd, 'C23', 'DET_CLPF')
    hand(bd, [q('5'), (q('5')[0], 93.95), (25.4, c23[1]), c23], 'DET_CLPF', W)
    place_at(bd, 'R26', 27.0, 91.6, False, 'DET_OUT', q('6'))
    r26o, r26s = at_net(bd, 'R26', 'DET_OUT'), at_net(bd, 'R26', 'DET_SET')
    hand(bd, [q('6'), (q('6')[0], 93.5), (r26o[0], r26o[1] + 0.3)], 'DET_OUT', W)
    hand(bd, [q('7'), (q('7')[0], 93.5), (r26s[0], r26s[1] + 0.3)], 'DET_SET', W)
    # right: pin 9 (+5VA) to C27 (100p) and C26 (100n), pin 10 to R25
    XR = 31.2
    place_at(bd, 'C27', XR, 95.2, False, '+5VA', q('9'))
    place_at(bd, 'C26', XR, 93.65, False, '+5VA', q('9'))
    place_at(bd, 'R25', XR, 96.75, False, 'DET_TADJ', q('10'))
    c27, c26, r25 = at_net(bd, 'C27', '+5VA'), at_net(bd, 'C26', '+5VA'), at_net(bd, 'R25', 'DET_TADJ')
    hand(bd, [q('9'), (29.6, q('9')[1]), c27, c26], '+5VA', W)
    bd.via(29.4, 93.3, '+5VA', 0.6, 0.3)
    bd.track(c26, (29.4, 93.3), W, '+5VA')
    hand(bd, [q('10'), (29.6, q('10')[1]), (r25[0], r25[1] - 0.25)], 'DET_TADJ', W)
    for ref in ('C26', 'C27', 'R25'):
        gx, gy = at_net(bd, ref, 'GND')
        bd.via(gx + 0.95, gy, 'GND', 0.6, 0.3)
    for ref in ('C24', 'C23'):
        gx, gy = at_net(bd, ref, 'GND')
        bd.via(gx - 1.0, gy, 'GND', 0.6, 0.3)
    # edge row: TEMP out sideways to R28, clear of the INHI line
    place_at(bd, 'R28', XR, 99.0, False, 'DET_TEMP', q('13'))
    r28 = at_net(bd, 'R28', 'DET_TEMP')
    hand(bd, [q('13'), (q('13')[0], 98.95), (28.5, r28[1]), r28], 'DET_TEMP', W)
    c25 = at_net(bd, 'C25', '+5VA')
    bd.via(c25[0], c25[1] - 1.1, '+5VA', 0.6, 0.3)
    bd.track(c25, (c25[0], c25[1] - 1.1), W, '+5VA')
    # FB1 where VBUS enters the can, so VBUS stays outside it; the In1 pour carries +5VA to U3,
    # with the 10 uF bulk C35 at the chip
    place_at(bd, 'FB1', 49.0, 75.6, False, '+5VA', (40.0, 75.6))
    place_at(bd, 'C35', 18.5, 93.2, False, '+5VA', (25.0, 93.2))


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

    def __init__(self, bd, skip_gnd=True):
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
            if t.GetNetname() == 'GND' and skip_gnd:
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
        # round the crossing via: the return current has to change layers right next to it
        for x, y in ((-3.0, VIA_Y + 2.2), (3.0, VIA_Y + 2.2), (-3.3, VIA_Y), (-2.6, VIA_Y - 1.3), (2.6, VIA_Y - 1.3)):
            bd.via(x, sy * y, 'GND', 0.6, 0.3)


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
            if not ep and any(t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == 'GND'
                              and math.hypot(*(u - w for u, w in zip(mm(t.GetPosition()), (px, py)))) < 1.3
                              for t in bd.b.GetTracks()):
                continue                    # already has one (drawn with the part)
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
    ep_paste(bd, 'U2', 1.22, 1.01)       # 0.1 mm clear of the via rings, 50 % of the pad
    ep_paste(bd, 'U3', 0.82, 0.765)      # out to the pad edge, 0.05 mm clear of the via rings, 49 %
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

    # source output: C3 -> RFOUTA+. The receive line to C21/R24 at INHI is drawn in rf_terminations()
    x12, y12 = bd.padxy('U2', '12')
    bd.poly([(tx_end, -VIA_Y), (x12, -VIA_Y), (x12, y12)], W50, tx_net)
    x14, y14 = bd.padxy('U3', '14')
    for x, y, c, d in ((tx_end, -VIA_Y, x12, y12), (rx_end, VIA_Y, x14, y14)):
        bd.boxes.append((min(x, c) - 0.6, y - 0.6, max(x, c) + 3.5, y + 0.6))
        bd.boxes.append((c - 0.6, min(y, d) - 0.6, c + 0.6, max(y, d) + 0.6))

    rf_terminations(bd, rx_end)
    support_parts(bd)

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
    # thermal and RF ground under the chips, in the gaps between the paste windows (ep_paste()), so
    # that they don't wick the solder away. VTUNE runs on In1 between them under U2 (support_parts())
    for ref, a in (('U2', 1.15), ('U3', 0.85)):
        cx, cy = mm(bd.fps[ref].GetPosition())
        for dx, dy in ((0, 0), (-a, 0), (a, 0), (0, -a), (0, a)):
            bd.via(cx + dx, cy + dy, 'GND', 0.6, 0.3)
    rail_fanout(bd)
    bd.text('OPEN TEM CELL - rev 0.3 CONCEPT', 0, -26, 2.4)
    bd.text('not validated', 0, -22, 1.8)
    bd.text('slide wallet in flat, from this side', -16, 12, 1.6)
    bd.text(gf.REPO, 0, 58, 1.6)
    bd.text('LCD 2.0in ST7789', 102, -2, 2.0)
    # test points: what each one carries, on the underside next to the pad
    for ref, label, dx, dy in (('TP1', 'DET', 0, 3.0), ('TP5', '5VA', 0, 3.0), ('TP6', 'ADC3', 0, 3.0), ('TP2', 'VT', -2.2, 0),
                               ('TP3', 'MUX', 0, 2.05), ('TP4', '3V3A', 0, 2.05)):    # source side: under the frame ring
        tx, ty = mm(bd.fps[ref].GetPosition())
        bd.text(label, tx + dx, ty + dy, 1.0, pcbnew.B_SilkS, mirror=True)
    bd.shape(pcbnew.F_SilkS, rect(85, -34, 120, 34), w=0.15)
    bd.text('GREEN', 92, -52, 1.6)
    bd.text('RED', 108, -52, 1.6)
    bd.text('START', 100, -74, 1.6)
    bd.text('Pico 2: micro-USB and BOOTSEL here', 100, 22.5, 1.4, pcbnew.B_SilkS, mirror=True)
    bd.text('SOURCE - fit shield can on this frame', 32, -71, 1.4, pcbnew.B_SilkS, mirror=True)
    bd.text('DETECTOR - fit shield can on this frame', 32, 71, 1.4, pcbnew.B_SilkS, mirror=True)
    bd.text('J4: spare GPIO / ADC / RUN', 86, 76, 1.4, pcbnew.B_SilkS, mirror=True)
    return bd


def ep_paste(bd, ref, size, off):
    """Exposed pad paste as 4 windows (size, at +-off), leaving a cross free for the ground vias."""
    fp = bd.fps[ref]
    paste = [pd for pd in fp.Pads() if not pd.GetNumber()]
    for pd in paste[4:]:
        fp.Remove(pd)
    for pd, (sx, sy) in zip(paste[:4], ((-1, -1), (-1, 1), (1, -1), (1, 1))):
        pd.SetSize(VECTOR2I(FromMM(size), FromMM(size)))
        pd.SetFPRelativePosition(VECTOR2I(FromMM(sx * off), FromMM(sy * off)))


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
    """+3V3A (source block) and +5VA (detector block) are pours on In1: each pad gets its own via and the
    router skips both nets. Pads in RAIL_HAND already have one, drawn in support_parts()."""
    free = Free(bd, skip_gnd=False)
    for rail, chip in (('+3V3A', 'U2'), ('+5VA', 'U3')):
        ux, uy = mm(bd.fps[chip].GetPosition())
        for ref, fp in bd.fps.items():
            for p in fp.Pads():
                if p.GetNetname().lstrip('/') != rail or (ref, p.GetNumber()) in RAIL_HAND:
                    continue
                px, py = mm(p.GetPosition())
                away = math.atan2(py - uy, px - ux) if ref == chip else None
                done = False
                for r in (1.0, 1.2, 1.5, 1.8, 2.2, 2.6, 3.0, 3.5, 4.0):
                    for k in range(24):
                        a = (away + (k % 2 * 2 - 1) * (k // 2) * math.pi / 12) if away is not None else k * math.pi / 12
                        x, y = px + r * math.cos(a), py + r * math.sin(a)
                        if free.ok(x, y, 0.5, p.GetNetname()) and free.seg_ok((px, py), (x, y), 0.25, p.GetNetname()):
                            bd.track((px, py), (x, y), 0.2, rail)
                            bd.via(x, y, rail, 0.6, 0.3)
                            free.add(x, y)
                            done = True
                            break
                    if done:
                        break
                if not done:
                    raise SystemExit('no rail via for %s %s' % (ref, p.GetNumber()))


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
    # nothing between the two pads of a small part: rev 0.3 had signals threaded under C3, C5, C6, C21...
    for fp in bd.b.GetFootprints():
        pads = list(fp.Pads())
        if len(pads) != 2 or not fp.IsFlipped() or any(pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for pd in pads):
            continue
        a, c = (pd.GetBoundingBox() for pd in pads)
        box = lambda bb: (bb.GetLeft() / 1e6 - OX, bb.GetTop() / 1e6 - OY, bb.GetRight() / 1e6 - OX, bb.GetBottom() / 1e6 - OY)
        (ax0, ay0, ax1, ay1), (cx0, cy0, cx1, cy1) = box(a), box(c)
        # 0.2 mm off each pad: closer than the clearance, the router won't connect to the pad at all.
        # What is left (0.45 mm on a 0603) still leaves no room for a track between the pads
        if ax1 < cx0 or cx1 < ax0:          # side by side in x
            x0, x1 = (ax1, cx0) if ax1 < cx0 else (cx1, ax0)
            x0, x1 = x0 + 0.2, x1 - 0.2
            y0, y1 = max(ay0, cy0), min(ay1, cy1)
        else:
            y0, y1 = (ay1, cy0) if ay1 < cy0 else (cy1, ay0)
            y0, y1 = y0 + 0.2, y1 - 0.2
            x0, x1 = max(ax0, cx0), min(ax1, cx1)
        if x1 - x0 > 0.1 and y1 - y0 > 0.1:
            bd.rule_area(rect(x0, y0, x1, y1), [pcbnew.B_Cu], vias=True, pour=False)
    # the same through the pad gaps of the oscillator: the reference must not see a digital line
    fp = bd.fps['Y1']
    xs = sorted({round(mm(pd.GetPosition())[0], 3) for pd in fp.Pads()})
    ys = sorted({round(mm(pd.GetPosition())[1], 3) for pd in fp.Pads()})
    bb = fp.Pads()[0].GetBoundingBox()
    hw, hh = bb.GetWidth() / 2e6, bb.GetHeight() / 2e6
    cx, cy = (xs[0] + xs[-1]) / 2, (ys[0] + ys[-1]) / 2
    gx, gy = (xs[-1] - xs[0]) / 2 - hw - 0.2, (ys[-1] - ys[0]) / 2 - hh - 0.2
    if gx > 0.05:
        bd.rule_area(rect(cx - gx, ys[0] - hh, cx + gx, ys[-1] + hh), [pcbnew.B_Cu], vias=True, pour=False)
    if gy > 0.05:
        bd.rule_area(rect(xs[0] - hw, cy - gy, xs[-1] + hw, cy + gy), [pcbnew.B_Cu], vias=True, pour=False)
    # and round it: rev 0.3 had MUXOUT 0.16 mm from the REF_OUT pad, beside the whole part
    bd.rule_area(rect(xs[0] - hw - 1.5, ys[0] - hh - 1.5, xs[-1] + hw + 1.5, ys[-1] + hh + 1.5), [pcbnew.B_Cu], vias=True, pour=False)
    # No keepout along the 50 ohm chains: one covering their pads and the parts beside them stalls
    # Freerouting (about 12 connections left open every time). rf_neighbours() checks the result instead
    # In1 stays a whole rail pour under the chips and their decoupling: the router may not cut it up
    # there. Only that small: the digital lines to U2 have to reach it on In1
    ux, uy = mm(bd.fps['U2'].GetPosition())
    bd.rule_area(rect(ux - 3.0, uy - 3.5, ux + 6.0, uy + 3.0), [pcbnew.In1_Cu], vias=False, pour=False)
    ux, uy = mm(bd.fps['U3'].GetPosition())
    bd.rule_area(rect(ux - 5.0, uy - 3.5, ux + 5.0, uy + 3.0), [pcbnew.In1_Cu], vias=False, pour=False)
    return [z for z in bd.b.Zones() if z.m_Uuid.AsString() not in before]


def route(bd):
    # the router isn't deterministic: LID_PCB_OUT lets several attempts run side by side
    base = os.path.splitext(os.environ.get('LID_PCB_OUT', os.path.join(PRJ, NAME + '.kicad_pcb')))[0]
    dsn, ses = base + '.dsn', base + '.ses'
    temp = route_keepouts(bd)
    # GND and +3V3A come from pours. Everything hand-drawn so far is locked and stays in the file
    plane = ('GND', '+3V3A', '/+3V3A', '+5VA', '/+5VA')
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
    # The hand-drawn vias and tracks on the plane nets name nets with no pins left in the network.
    # Left like that, Freerouting loses its own wires when it writes the session; declared as one
    # net, it spends its passes joining them. Each gets a net of its own: an obstacle, nothing to join
    w0 = t.index('(wiring')
    known = set(re.findall(r'\(net ("[^"]*"|[^\s()]+)\s*\(pins', t))
    dummies = []

    def own(m):
        if m.group(1) in known:
            return m.group(0)
        dummies.append('PLANE_%d' % len(dummies))
        return '(net %s)' % dummies[-1]
    t = t[:w0] + re.sub(r'\(net ("[^"]*"|[^\s()]+)\)', own, t[w0:])
    t = t.replace('(network', '(network\n' + ''.join('    (net %s (pins))\n' % nm for nm in dummies), 1)
    open(dsn, 'w').write(t)
    jar = os.environ.get('FREEROUTING_JAR', 'freerouting.jar')
    subprocess.run(['java', '-Xmx8g', '-jar', jar, '-de', dsn, '-do', ses, '-mp', os.environ.get('FREEROUTING_PASSES', '40')]
                   + os.environ.get('FREEROUTING_EXTRA', '').split(), check=True, timeout=3000)
    if not pcbnew.ImportSpecctraSES(bd.b, ses):
        raise SystemExit('SES import failed')
    for pad, code in pads:
        pad.SetNetCode(code)
    for tr in list(bd.b.GetTracks()):          # nothing routed on the planes, nor on the dummy nets
        if not tr.IsLocked() and (tr.GetNetname() in plane or tr.GetNetCode() == 0 or tr.GetNetname().startswith('PLANE_')):
            bd.b.Remove(tr)
    for z in temp:
        bd.b.Remove(z)
    os.unlink(dsn)
    os.unlink(ses)


def rf_neighbours(bd, gap=1.0):
    """Router tracks on B.Cu running within `gap` mm of the hand-drawn RF lines (the 50 ohm chains and the
    U2/U3 RF pins): printed, so that a coupling path like rev 0.3's SYN_TEMP along RFOUTA+ shows up."""
    rf = [t for t in bd.b.GetTracks() if t.IsLocked() and t.Type() != pcbnew.PCB_VIA_T and t.GetLayer() == pcbnew.B_Cu
          and t.GetNetname().lstrip('/') in RF_NETS + ('RFA_P',)]
    near = {}
    for t in bd.b.GetTracks():
        if t.IsLocked() or t.Type() == pcbnew.PCB_VIA_T or t.GetLayer() != pcbnew.B_Cu or t.GetNetname() == 'GND':
            continue
        sa = pcbnew.SEG(t.GetStart(), t.GetEnd())
        for r in rf:
            d = sa.Distance(pcbnew.SEG(r.GetStart(), r.GetEnd())) / 1e6 - (t.GetWidth() + r.GetWidth()) / 2e6
            if d < gap:
                k = (t.GetNetname().lstrip('/'), r.GetNetname().lstrip('/'))
                near[k] = min(near.get(k, 9), d)
    for (a, b), d in sorted(near.items()):
        print('near RF: %s %.2f mm from %s' % (a, d, b))


def pours(bd):
    outline = rounded(X0, -Y1, X1, Y1, 4.0)
    bd.zone([pcbnew.F_Cu], outline, 'GND', clearance=MS_GAP)
    bd.zone([pcbnew.In2_Cu], outline, 'GND', clearance=0.3)
    bd.zone([pcbnew.B_Cu], outline, 'GND', clearance=0.3)
    # the analog rails: everything on each is inside its block
    bd.zone([pcbnew.In1_Cu], rect(12.0, -106.0, 58.0, -74.0), '+3V3A', clearance=0.3)
    bd.zone([pcbnew.In1_Cu], rect(12.0, 74.0, 58.0, 106.0), '+5VA', clearance=0.3)
    rf_pour_gap(bd)


RF_POUR_GAP = 0.5


def rf_pour_gap(bd):
    """The B.Cu ground pour stays 0.5 mm off the 50 ohm lines (0.3 mm made them grounded coplanar lines,
    a few ohm low). Stops 1.2 mm short of the IC pins, where the pour has to reach the ground pins."""
    pins = [mm(pd.GetPosition()) for r in ('U2', 'U3') for pd in bd.fps[r].Pads()]
    e = W50 / 2 + RF_POUR_GAP
    for t in bd.b.GetTracks():
        if t.GetClass() != 'PCB_TRACK' or t.GetLayer() != pcbnew.B_Cu or abs(t.GetWidth() / 1e6 - W50) > 0.01:
            continue
        (ax, ay), (cx, cy) = mm(t.GetStart()), mm(t.GetEnd())
        L = math.hypot(cx - ax, cy - ay)
        if L < 0.05:
            continue
        ux, uy = (cx - ax) / L, (cy - ay) / L
        near = lambda x, y: any(math.hypot(x - px, y - py) < 0.4 for px, py in pins)
        if near(ax, ay):
            ax, ay = ax + 1.2 * ux, ay + 1.2 * uy
        if near(cx, cy):
            cx, cy = cx - 1.2 * ux, cy - 1.2 * uy
        if (cx - ax) * ux + (cy - ay) * uy <= 0:
            continue
        nx, ny = -uy * e, ux * e
        ax, ay, cx, cy = ax - ux * e, ay - uy * e, cx + ux * e, cy + uy * e
        bd.rule_area([(ax + nx, ay + ny), (cx + nx, cy + ny), (cx - nx, cy - ny), (ax - nx, ay - ny)],
                     [pcbnew.B_Cu], tracks=False, vias=False, pour=True)


# Pads join the pours through 4 short spokes (easier to solder, and the paste isn't pulled away by
# the plane), except RF grounds: a spoke adds ~0.5-1 nH, which the RF ICs, the pad and termination
# shunts and their decoupling can't take.
THERMAL_GAP, THERMAL_SPOKE = 0.25, 0.3
SOLID_GND = {'U2', 'U3', 'J1', 'J2', 'J5', 'R2', 'R4', 'R7', 'R10', 'R21', 'R23', 'R24',
             'C10', 'C11', 'C12', 'C14', 'C15', 'C16', 'C17', 'C18', 'C19', 'C20', 'C22',
             'C24', 'C25', 'C26', 'C27', 'C36',
             'Y1', 'U5', 'C8', 'C28'}      # no room for 2 spokes between the tracks (DRC starved_thermal)
SOLID_PADS = {('U1', '23')}


def thermals(b):
    for z in b.Zones():
        if not z.GetIsRuleArea():
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
            z.SetThermalReliefGap(FromMM(THERMAL_GAP))
            z.SetThermalReliefSpokeWidth(FromMM(THERMAL_SPOKE))
    n = 0
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            if fp.GetReference() in SOLID_GND or (fp.GetReference(), pad.GetNumber()) in SOLID_PADS:
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
                n += 1
    return n


def apply_thermals(path):
    """Thermal reliefs on an existing board, without re-routing it."""
    b = pcbnew.LoadBoard(path)
    print('solid pads', thermals(b))
    b.BuildConnectivity()
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(path)


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
    unstarve(path)


def unstarve(path):
    """Thermal pads whose spokes the router blocked (DRC starved_thermal) go back to a solid connection."""
    import json
    rep = path + '.drc.json'
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-error', '-o', rep, path],
                   check=True, capture_output=True, env=KICAD_ENV)
    want = set()
    for v in json.load(open(rep)).get('violations', []):
        if v.get('type') != 'starved_thermal':
            continue
        for it in v.get('items', []):
            m = re.match(r'(?:PTH )?[Pp]ad (\S+) \[GND\] of (\S+)', it.get('description', ''))
            if m:
                want.add((m.group(2), m.group(1)))
    os.unlink(rep)
    if not want:
        return
    b = pcbnew.LoadBoard(path)
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            if (fp.GetReference(), pad.GetNumber()) in want:
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    b.BuildConnectivity()
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(path)
    print('solid (no room for spokes):', ' '.join('%s.%s' % w for w in sorted(want)))


def main():
    if sys.argv[1:2] == ['--fill']:
        fill(sys.argv[2])
        return
    if sys.argv[1:2] == ['--thermals']:
        apply_thermals(sys.argv[2])
        unstarve(sys.argv[2])
        return
    if sys.argv[1:2] == ['--unstarve']:
        unstarve(sys.argv[2])
        return
    bd = build()
    path = os.environ.get('LID_PCB_OUT', os.path.join(PRJ, NAME + '.kicad_pcb'))
    if '--no-route' not in sys.argv:
        route(bd)
        # the hand-drawn RF nets are complete: anything the router added on them is a redundant stub
        for t in list(bd.b.GetTracks()):
            if not t.IsLocked() and t.GetNetname().lstrip('/') in RF_NETS:
                bd.b.Remove(t)
        rf_neighbours(bd)
    free = Free(bd)
    fence(bd, free)
    ground_vias(bd, free)
    shield_frames(bd, free)
    stitch(bd, free)
    # the router works to 0.15 mm and rounds a hair under it on diagonals
    bd.b.GetDesignSettings().m_NetSettings.GetDefaultNetclass().SetClearance(FromMM(0.14))
    pours(bd)
    thermals(bd.b)
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
