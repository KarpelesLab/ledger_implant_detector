#!/usr/bin/env python3
"""Generate the RF test-fixture kit (rev 0.1, concept) under hardware/fixtures/.

All boards: 2-layer FR4 1.6 mm, no components except edge-mount SMA jacks.
Coordinates in mm, origin at the centre of the 80 x 80 mm test area, y down
(KiCad), viewed from the top.

    slot      coplanar-strip "slot" line, wallet lies flat over a 90 mm slot
    tem_base  open TEM cell: ground plane, SMA launches, landing pads
    tem_plate open TEM cell: septum plate (on M3 spacers of length h)
    tem_ramp  open TEM cell: tapered ramp, septum edge -> landing pad (2 needed)
    carrier   copper-free plate that holds the wallet at a set height (slot)

    python3 tools/gen_fixtures.py            # all boards
    python3 tools/gen_fixtures.py slot ...
"""
import json
import math
import os
import sys

import pcbnew
from pcbnew import FromMM, VECTOR2I

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'hardware', 'fixtures')
KIFP = '/usr/share/kicad/footprints'
SMA_FP = ('Connector_Coaxial', 'SMA_Samtec_SMA-J-P-H-ST-EM1_EdgeMount')
OX, OY = 150.0, 150.0
REV = 'rev 0.1 CONCEPT - not validated'
REPO = 'github.com/KarpelesLab/ledger_implant_detector'

# ---- shared geometry (mirrors sim/fixtures_fdtd.py) --------------------------------
SLOT = dict(gap=90.0, strip=25.0, straight=45.0, taper_end=95.0, tip_w=10.0, board=(75.0, 100.0))
SLOT_CARRIER_HOLES = [(sx * 57.5, sy * 50.0) for sx in (-1, 1) for sy in (-1, 1)]
SLOT_FEET = [(sx * 69.0, sy * 94.0) for sx in (-1, 1) for sy in (-1, 1)]

TEM = dict(w=100.0, length=100.0, ramp_len=55.0, tip_w=3.0, base=(70.0, 108.0))
TEM_PLATE_HOLES = [(sx * 45.0, sy * 40.0) for sx in (-1, 1) for sy in (-1, 1)]
TEM_FEET = [(sx * 64.0, sy * 102.0) for sx in (-1, 1) for sy in (-1, 1)]
TEM_H = (15.0, 20.0, 25.0, 30.0)
MS_W, MS_GAP = 3.0, 1.0          # 50 ohm landing line on 1.6 mm FR4 (grounded coplanar, wide gaps)


def air_strip_z0(w, h):
    """Wide strip at height h over a ground plane, in air (Hammerstad, w/h > 1)."""
    u = w / h
    return 376.73 / (u + 1.393 + 0.667 * math.log(u + 1.444))


# ---- pcbnew helpers -------------------------------------------------------------


def P(x, y):
    return VECTOR2I(FromMM(OX + x), FromMM(OY + y))


class Board:
    def __init__(self, name, title, ignore=()):
        self.name = name
        self.ignore = ignore          # DRC checks that flag the design intent (written to the .kicad_pro)
        self.b = pcbnew.BOARD()
        self.nets = {}
        b = self.b
        b.SetCopperLayerCount(2)
        d = b.GetDesignSettings()
        d.SetBoardThickness(FromMM(1.6))
        d.m_TrackMinWidth = FromMM(0.2)
        d.m_MinClearance = FromMM(0.2)
        d.m_ViasMinSize = FromMM(0.6)
        d.m_MinThroughDrill = FromMM(0.3)
        d.m_CopperEdgeClearance = FromMM(0.3)
        d.m_HoleClearance = FromMM(0.3)
        d.m_HoleToHoleMin = FromMM(0.3)
        d.m_ViasMinAnnularWidth = FromMM(0.13)
        nc = d.m_NetSettings.GetDefaultNetclass()
        nc.SetClearance(FromMM(0.3))
        nc.SetViaDiameter(FromMM(0.8))
        nc.SetViaDrill(FromMM(0.4))
        tb = b.GetTitleBlock()
        tb.SetTitle(title)
        tb.SetRevision('0.1 (concept)')
        tb.SetCompany(REPO)

    def net(self, name):
        if name not in self.nets:
            n = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(n)
            self.nets[name] = n
        return self.nets[name]

    def shape(self, layer, pts, w=0.1, closed=True, fill=False):
        if fill:
            s = pcbnew.PCB_SHAPE(self.b, pcbnew.SHAPE_T_POLY)
            s.SetPolyPoints([P(*p) for p in pts])
            s.SetFilled(True)
            s.SetLayer(layer)
            s.SetWidth(FromMM(0))
            self.b.Add(s)
            return
        seq = list(pts) + ([pts[0]] if closed else [])
        for a, c in zip(seq, seq[1:]):
            s = pcbnew.PCB_SHAPE(self.b, pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(P(*a))
            s.SetEnd(P(*c))
            s.SetLayer(layer)
            s.SetWidth(FromMM(w))
            self.b.Add(s)

    def outline(self, pts):
        self.shape(pcbnew.Edge_Cuts, pts, w=0.05)

    def text(self, s, x, y, size=2.0, layer=pcbnew.F_SilkS, angle=0, thick=None, just=None):
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText(s)
        t.SetPosition(P(x, y))
        t.SetLayer(layer)
        t.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
        t.SetTextThickness(FromMM(thick or max(0.15, size * 0.15)))
        if angle:
            t.SetTextAngleDegrees(angle)
        if layer in (pcbnew.B_SilkS, pcbnew.B_Cu):
            t.SetMirrored(True)
        if just == 'left':
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        self.b.Add(t)

    def zone(self, layers, pts, net, priority=0, clearance=0.3, thermal=False):
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
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL if thermal else pcbnew.ZONE_CONNECTION_FULL)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        self.b.Add(z)
        return z

    def keepout(self, pts, layers=(pcbnew.F_Cu, pcbnew.B_Cu)):
        z = pcbnew.ZONE(self.b)
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(l)
        z.SetLayerSet(ls)
        o = z.Outline()
        o.NewOutline()
        for x, y in pts:
            o.Append(FromMM(OX + x), FromMM(OY + y))
        z.SetIsRuleArea(True)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowPads(False)
        self.b.Add(z)

    def via(self, x, y, net, d=0.8, drill=0.4):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(P(x, y))
        v.SetWidth(FromMM(d))
        v.SetDrill(FromMM(drill))
        v.SetNet(self.net(net))
        self.b.Add(v)

    def track(self, a, c, w, net, layer=pcbnew.F_Cu):
        t = pcbnew.PCB_TRACK(self.b)
        t.SetStart(P(*a))
        t.SetEnd(P(*c))
        t.SetWidth(FromMM(w))
        t.SetLayer(layer)
        t.SetNet(self.net(net))
        self.b.Add(t)

    def footprint(self, lib, name, ref, x, y, rot=0, nets=None, value=''):
        fp = pcbnew.FootprintLoad(os.path.join(KIFP, lib + '.pretty'), name)
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(value or name)
        fp.Value().SetVisible(False)
        self.b.Add(fp)
        fp.SetPosition(P(x, y))
        fp.SetOrientationDegrees(rot)
        for p in fp.Pads():
            if nets and p.GetNumber() in nets:
                p.SetNet(self.net(nets[p.GetNumber()]))
        return fp

    def hole(self, ref, x, y):
        fp = self.footprint('MountingHole', 'MountingHole_3.2mm_M3', ref, x, y)
        fp.Reference().SetVisible(False)
        return fp

    def sma(self, ref, x, y, outward, sig, gnd='GND'):
        """Edge SMA whose centre pad sits at (x, y); `outward` = direction (dx, dy) of the board edge."""
        # footprint: board edge at local x = -2.6, body towards -x
        rot = {(-1, 0): 0, (0, 1): 90, (1, 0): 180, (0, -1): 270}[outward]
        fp = self.footprint(SMA_FP[0], SMA_FP[1], ref, x, y, rot, nets={'1': sig, '2': gnd},
                            value='SMA edge jack (Samtec SMA-J-P-H-ST-EM1)')
        fp.Reference().SetVisible(False)
        return fp

    def save(self):
        d = os.path.join(OUT, self.name)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, self.name + '.kicad_pcb')
        self.b.Save(path)
        pro = {'meta': {'filename': self.name + '.kicad_pro', 'version': 1},
               'board': {'design_settings': {'rule_severities': {k: 'ignore' for k in self.ignore}}}}
        with open(os.path.join(d, self.name + '.kicad_pro'), 'w') as f:
            json.dump(pro, f, indent=2)
        print('wrote', path)
        return path


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def rounded(x0, y0, x1, y1, r=3.0, n=6):
    pts = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def circle(cx, cy, r, n=24):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def test_area(bd, layer=pcbnew.F_SilkS, label=True):
    bd.shape(layer, rect(-40, -40, 40, 40), w=0.3)
    for sx in (-1, 1):
        for sy in (-1, 1):   # corner ticks every 10 mm
            for k in range(1, 4):
                v = 10 * k
                bd.shape(layer, [(sx * 40, sy * v), (sx * 38, sy * v)], w=0.2, closed=False)
                bd.shape(layer, [(sx * v, sy * 40), (sx * v, sy * 38)], w=0.2, closed=False)
    bd.shape(layer, [(-3, 0), (3, 0)], w=0.2, closed=False)
    bd.shape(layer, [(0, -3), (0, 3)], w=0.2, closed=False)
    if label:
        bd.text('80 x 80 mm test area', 0, -36, 2.0, layer)


def keepout_holes(bd, holes, r=3.5):
    for x, y in holes:
        bd.keepout(circle(x, y, r))


# ---- slot (coplanar strips) -------------------------------------------------------


def slot_strip(sign):
    """Polygon of one strip (sign +1: signal side x > 0, -1: ground side), both tapers included."""
    c = SLOT
    g2, s, y1, y2, tw = c['gap'] / 2, c['strip'], c['straight'], c['taper_end'], c['tip_w']
    # inner edge at the tip: signal = left edge of the SMA centre pad, ground = inner edge of the ground pad
    tip_in = -0.635 if sign > 0 else 2.15
    tip_out = tw
    poly = [(g2, -y1), (tip_in, -y2), (tip_out, -y2), (g2 + s, -y1), (g2 + s, y1), (tip_out, y2), (tip_in, y2), (g2, y1)]
    if sign > 0:
        return poly
    return [(-x, y) for x, y in poly]


def build_slot():
    c = SLOT
    bx, by = c['board']
    bd = Board('slot', 'Implant detector RF fixture: slot line (coplanar strips)')
    bd.outline(rounded(-bx, -by, bx, by, 4.0))
    y2 = c['taper_end']
    pad_y = by - 2.6                          # SMA centre pad centre (board edge at local -2.6)
    bd.zone([pcbnew.F_Cu], slot_strip(+1), 'SIG')
    bd.zone([pcbnew.F_Cu], slot_strip(-1), 'GND')
    for sy, ref in ((1, 'J2'), (-1, 'J1')):
        yp = sy * pad_y
        bd.sma(ref, 0.0, yp, (0, sy), 'SIG')
        # signal neck from the taper tip to the centre pad
        bd.zone([pcbnew.F_Cu], rect(-0.635, min(sy * y2, yp), 0.635, max(sy * y2, yp)), 'SIG', priority=1)
        # ground: left pad joins the ground strip; right pad comes over through the bottom-side bridge
        bd.zone([pcbnew.F_Cu], rect(-3.5, min(sy * (y2 - 0.2), yp), -2.15, max(sy * (y2 - 0.2), yp)), 'GND',
                 priority=1)
        bd.zone([pcbnew.B_Cu], rect(-3.6, min(sy * (y2 - 1), sy * by), 3.6, max(sy * (y2 - 1), sy * by)), 'GND')
        for x in (-2.9, 2.9):
            for dy in (-1.0, 0.6):
                bd.via(x, yp + sy * dy, 'GND', 0.6, 0.3)
        bd.text('PORT %d' % (1 if sy < 0 else 2), 16, sy * (by - 5), 2.5)
    # holes: carrier spacers and feet (copper kept clear around them)
    for n, (x, y) in enumerate(SLOT_CARRIER_HOLES):
        bd.hole('H%d' % (n + 1), x, y)
    for n, (x, y) in enumerate(SLOT_FEET):
        bd.hole('H%d' % (n + 5), x, y)
    keepout_holes(bd, SLOT_CARRIER_HOLES + SLOT_FEET)
    test_area(bd)
    # field direction arrow across the slot
    bd.shape(pcbnew.F_SilkS, [(-30, 20), (30, 20)], w=0.3, closed=False)
    for sx in (-1, 1):
        bd.shape(pcbnew.F_SilkS, [(sx * 30, 20), (sx * 27, 18.5), (sx * 27, 21.5)], w=0.3)
    bd.text('E field across the slot', 0, 24, 2.0)
    bd.text('SLOT LINE FIXTURE', 0, -24, 3.0)
    bd.text(REV, 0, -19, 1.8)
    bd.text('wallet: back down, centred; test 0 and 90 deg', 0, 30, 1.6)
    bd.text('feet: >= 20 mm spacers in the corner holes', 0, 33, 1.6)
    notes = ['SLOT LINE FIXTURE - ' + REV, '',
             'NanoVNA: PORT 1 = CH0 (S11), PORT 2 = CH1 (S21)',
             'S11 only: 50 ohm load on the other port', '',
             'CARRIER HEIGHT z (wallet back above the copper):',
             'carrier lying on the board:   z = 1.6 mm',
             'carrier on L mm spacers:       z = L + 1.6 mm',
             'L = 5 / 10 / 15 / 20 mm  ->  z = 6.6 / 11.6 / 16.6 / 21.6 mm', '',
             'Stand the board on >= 20 mm feet (corner holes),',
             'away from metal, cables leaving straight out.', '',
             REPO]
    for k, s in enumerate(notes):
        bd.text(s, 0, -24 + 3.4 * k, 1.8, layer=pcbnew.B_SilkS)
    bd.text('SIG', 57.5, -60, 3.0)
    bd.text('GND', -57.5, -60, 3.0)
    return bd.save()


# ---- open TEM cell ---------------------------------------------------------------


def ramp_proj(h):
    return math.sqrt(TEM['ramp_len'] ** 2 - h ** 2)


def build_tem_base():
    c = TEM
    bx, by = c['base']
    hl = c['length'] / 2
    # the landing lines end open on purpose: the ramp tip is soldered onto them
    bd = Board('tem_base', 'Implant detector RF fixture: open TEM cell, base', ignore=('track_dangling',))
    bd.outline(rounded(-bx, -by, bx, by, 4.0))
    land0 = hl + ramp_proj(max(TEM_H)) - 3.0
    pad_y = by - 2.6
    # full ground on both layers, landing lines cut out of F.Cu
    bd.zone([pcbnew.F_Cu, pcbnew.B_Cu], rect(-bx, -by, bx, by), 'GND', clearance=MS_GAP)
    for sy, ref in ((1, 'J2'), (-1, 'J1')):
        yp = sy * pad_y
        sig = 'P1' if sy < 0 else 'P2'
        bd.sma(ref, 0.0, yp, (0, sy), sig)
        bd.track((0, sy * land0), (0, yp), MS_W, sig)
        # bare copper where the ramp tip gets soldered
        y_lo, y_hi = land0, hl + ramp_proj(min(TEM_H)) + 0.4
        bd.shape(pcbnew.F_Mask, rect(-MS_W / 2, min(sy * y_lo, sy * y_hi), MS_W / 2, max(sy * y_lo, sy * y_hi)),
                 fill=True)
        # via fence along the landing line
        y = land0 - 1.0
        while y < pad_y - 3.5:
            for x in (-(MS_W / 2 + MS_GAP + 0.8), MS_W / 2 + MS_GAP + 0.8):
                bd.via(x, sy * y, 'GND')
            y += 2.0
        for x in (-2.9, 2.9):
            bd.via(x, yp - sy * 1.0, 'GND', 0.6, 0.3)
        # landing range marks: where the ramp tip lands for each spacer length
        for h in TEM_H:
            yl = sy * (hl + ramp_proj(h))
            bd.shape(pcbnew.F_SilkS, [(MS_W / 2 + 1.6, yl), (MS_W / 2 + 4.0, yl)], w=0.2, closed=False)
            bd.text('h%g' % h, MS_W / 2 + 7.0, yl, 1.2)
        bd.text('PORT %d' % (1 if sy < 0 else 2), -14, sy * (by - 6), 2.5)
    # stitching grid
    y = -by + 6
    while y <= by - 6:
        x = -bx + 6
        while x <= bx - 6:
            clear = all(math.hypot(x - hx, y - hy) > 6 for hx, hy in TEM_PLATE_HOLES + TEM_FEET)
            if clear and (abs(x) > 9 or abs(y) < land0 - 3):
                bd.via(x, y, 'GND')
            x += 10.0
        y += 10.0
    for n, (x, y) in enumerate(TEM_PLATE_HOLES):
        bd.hole('H%d' % (n + 1), x, y)
    for n, (x, y) in enumerate(TEM_FEET):
        bd.hole('H%d' % (n + 5), x, y)
    keepout_holes(bd, TEM_PLATE_HOLES + TEM_FEET)
    test_area(bd)
    bd.shape(pcbnew.F_SilkS, rect(-c['w'] / 2, -hl, c['w'] / 2, hl), w=0.15)
    bd.text('septum plate outline (100 x 100) on 4 x M3 spacers, length h', 0, -hl - 3, 1.6)
    bd.text('OPEN TEM CELL - BASE', 0, -24, 3.0)
    bd.text(REV, 0, -19, 1.8)
    lines = ['h (spacer)  Z0 of the cell', ]
    lines += ['%4.0f mm   %3.0f ohm%s' % (h, air_strip_z0(c['w'], h), '  <- 50 ohm' if h == 20 else '') for h in TEM_H]
    for k, s in enumerate(lines):
        bd.text(s, -33, 14 + 3.0 * k, 1.6, just='left')
    bd.text('wallet: flat, or standing on its long side (h >= 25)', 0, 31, 1.6)
    bd.text(REPO, 0, 66, 1.6)
    return bd.save()


def build_tem_plate():
    c = TEM
    w2, hl = c['w'] / 2, c['length'] / 2
    bd = Board('tem_plate', 'Implant detector RF fixture: open TEM cell, septum plate', ignore=('isolated_copper',))
    bd.outline(rect(-w2, -hl, w2, hl))
    bd.zone([pcbnew.F_Cu, pcbnew.B_Cu], rect(-w2, -hl, w2, hl), 'SEPTUM', clearance=0.3)
    for n, (x, y) in enumerate(TEM_PLATE_HOLES):
        bd.hole('H%d' % (n + 1), x, y)
    keepout_holes(bd, TEM_PLATE_HOLES, 3.0)
    for y in [-hl + 10 + 8 * k for k in range(11)]:
        for x in [-w2 + 2 + 8 * k for k in range(13)]:
            if all(math.hypot(x - hx, y - hy) > 5 for hx, hy in TEM_PLATE_HOLES):
                bd.via(x, y, 'SEPTUM')
    # bare copper strips along the two ramp edges (solder / copper tape joint), both sides
    for sy in (-1, 1):
        for layer in (pcbnew.F_Mask, pcbnew.B_Mask):
            bd.shape(layer, rect(-w2, min(sy * hl, sy * (hl - 4)), w2, max(sy * hl, sy * (hl - 4))), fill=True)
    bd.text('TEM SEPTUM PLATE', 0, -10, 3.0)
    bd.text(REV, 0, -5, 1.8)
    bd.text('both sides are the same conductor', 0, 2, 1.6)
    bd.text('join the ramps along the bare edges', 0, 6, 1.6)
    bd.text('(copper tape + solder tacks, both faces)', 0, 9.5, 1.6)
    return bd.save()


def ramp_outline():
    c = TEM
    L, w2, t2 = c['ramp_len'], c['w'] / 2, c['tip_w'] / 2
    # y = 0 at the septum joint, +L at the tip; a 4 mm straight tab carries the tip onto the landing line
    return [(-w2, 0), (w2, 0), (t2, L), (t2, L + 4), (-t2, L + 4), (-t2, L)]


def build_tem_ramp():
    c = TEM
    bd = Board('tem_ramp', 'Implant detector RF fixture: open TEM cell, ramp (order 2+)', ignore=('isolated_copper',))
    pts = ramp_outline()
    bd.outline(pts)
    inset = [(x * 0.997, y) for x, y in pts]
    bd.zone([pcbnew.F_Cu, pcbnew.B_Cu], inset, 'SEPTUM', clearance=0.3)
    L = c['ramp_len']
    y = 8.0
    while y < L - 4:
        half = c['w'] / 2 + (c['tip_w'] / 2 - c['w'] / 2) * (y / L) - 2.0
        n = max(0, int(half // 8))
        for k in range(-n, n + 1):
            bd.via(8.0 * k, y, 'SEPTUM')
        y += 8.0
    for layer in (pcbnew.F_Mask, pcbnew.B_Mask):
        bd.shape(layer, rect(-c['w'] / 2, 0, c['w'] / 2, 4), fill=True)
        bd.shape(layer, rect(-c['tip_w'] / 2, L, c['tip_w'] / 2, L + 4), fill=True)
    bd.text('TEM RAMP', 0, 12, 3.0)
    bd.text(REV, 0, 17, 1.6)
    bd.text('wide edge -> septum, tip -> landing line', 0, 21, 1.4)
    bd.text('same tip landing marks: h15..h30', 0, 24, 1.4)
    return bd.save()


# ---- carrier -------------------------------------------------------------------------


def build_carrier():
    bd = Board('carrier', 'Implant detector RF fixture: wallet carrier plate (no copper)')
    bd.outline(rounded(-66, -58, 66, 58, 4.0))
    for n, (x, y) in enumerate(SLOT_CARRIER_HOLES):
        bd.hole('H%d' % (n + 1), x, y)
    test_area(bd)
    for k in range(-3, 4):   # 10 mm grid inside the area (silk only)
        if k:
            bd.shape(pcbnew.F_SilkS, [(10 * k, -40), (10 * k, 40)], w=0.1, closed=False)
            bd.shape(pcbnew.F_SilkS, [(-40, 10 * k), (40, 10 * k)], w=0.1, closed=False)
    bd.text('WALLET CARRIER (no copper)', 0, -50, 2.5)
    bd.text(REV, 0, -45.5, 1.5)
    bd.text('z = spacer length + 1.6 mm', 0, 45, 2.0)
    bd.text('0 deg: wallet length across the slot  |  90 deg: along it', 0, 49, 1.5)
    bd.text('SLOT FIXTURE: SIG side ->', 40, 53.5, 1.5)
    return bd.save()


BUILD = {'slot': build_slot, 'tem_base': build_tem_base, 'tem_plate': build_tem_plate,
         'tem_ramp': build_tem_ramp, 'carrier': build_carrier}

def fill(path):
    # zone filling segfaults on a board built in memory; it is fine on a freshly loaded one
    b = pcbnew.LoadBoard(path)
    b.BuildConnectivity()
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(path)


def outputs(name):
    """Gerbers + drill (zip for upload), DRC report, renders into docs/img/."""
    import shutil
    import subprocess
    import zipfile
    env = dict(os.environ)
    if 'LID_KICAD_CFG' in os.environ:
        env['XDG_CONFIG_HOME'] = os.environ['LID_KICAD_CFG']

    def cli(*a):
        r = subprocess.run(['kicad-cli'] + list(a), env=env, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(r.stdout + r.stderr)
    d = os.path.join(OUT, name)
    pcb = os.path.join(d, name + '.kicad_pcb')
    g = os.path.join(d, 'fab', 'gerbers')
    shutil.rmtree(g, ignore_errors=True)
    os.makedirs(g)
    cli('pcb', 'export', 'gerbers', '-l', 'F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts',
        '--subtract-soldermask', '-o', g + '/', pcb)
    cli('pcb', 'export', 'drill', '--format', 'excellon', '--excellon-separate-th', '-o', g + '/', pcb)
    with zipfile.ZipFile(os.path.join(d, 'fab', name + '_gerbers.zip'), 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(g)):
            zf.write(os.path.join(g, f), f)
    cli('pcb', 'drc', '--severity-error', '--severity-warning', '-o', os.path.join(d, 'fab', 'drc_report.txt'), pcb)
    img = os.path.join(ROOT, 'docs', 'img')
    os.makedirs(img, exist_ok=True)
    common = ['--quality', 'high', '--background', 'opaque', '-w', '1200', '-h', '1200']
    cli('pcb', 'render', *common, '--side', 'top', '-o', os.path.join(img, 'fixture_%s_top.png' % name), pcb)
    cli('pcb', 'render', *common, '--side', 'bottom', '-o', os.path.join(img, 'fixture_%s_bottom.png' % name), pcb)


if __name__ == '__main__':
    import subprocess
    if sys.argv[1:2] == ['--fill']:
        fill(sys.argv[2])
        sys.exit(0)
    if sys.argv[1:2] == ['--outputs']:
        for n in sys.argv[2:] or list(BUILD):
            outputs(n)
            print('outputs', n)
        sys.exit(0)
    for n in sys.argv[1:] or list(BUILD):
        path = BUILD[n]()
        subprocess.run([sys.executable, os.path.abspath(__file__), '--fill', path], check=True)
