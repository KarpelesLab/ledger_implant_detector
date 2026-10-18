#!/usr/bin/env python3
"""Generate hardware/detector/implant_detector.kicad_pcb from the schematic netlist.

Board coordinates below are in mm relative to the board origin (top-left of the
main body, nose extends towards -X). Viewed from the top (component) side.

    stage 1 (default): place footprints, outline, zones, keepouts, RF line
    then: freerouting (tools/route.sh) and `--finish` to fill zones.
"""
import math
import os
import subprocess
import sys

import pcbnew
from pcbnew import FromMM, VECTOR2I

import sexpr
from sexpr import find, find1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRJ = os.path.join(ROOT, 'hardware', 'detector')
NAME = 'implant_detector'
PCB = os.path.join(PRJ, NAME + '.kicad_pcb')
FPLIB = {'lid': os.path.join(ROOT, 'hardware', 'lib', 'lid.pretty')}
KIFP = '/usr/share/kicad/footprints'

OX, OY = 100.0, 80.0  # board origin on the drawing sheet

# ---- geometry ---------------------------------------------------------------
BODY_X0, BODY_X1, BODY_Y0, BODY_Y1 = 12.0, 122.0, 0.0, 40.0
NOSE_Y0, NOSE_Y1, NOSE_CX = 12.0, 28.0, 8.0   # semicircular nose, radius 8
LOOP_C = (6.0, 20.0)
EL_SIZE, EL_PITCH, EL_X0 = 14.0, 17.0, 15.0
EL_ROWS_Y0 = (4.0, 24.0)
CHIP = {'U1': (30.5, 21.0), 'U2': (64.5, 21.0)}
HANDLE_X0 = 83.0

# electrode -> (chip, channel, quadrant (sx, sy) relative to the chip)
ELECTRODES = {1: ('U1', 0), 5: ('U1', 1), 6: ('U1', 2), 2: ('U1', 3),
              3: ('U2', 0), 7: ('U2', 1), 8: ('U2', 2), 4: ('U2', 3)}


def el_rect(e):
    c, r = (e - 1) % 4, (e - 1) // 4
    x0 = EL_X0 + c * EL_PITCH
    y0 = EL_ROWS_Y0[r]
    return x0, y0, x0 + EL_SIZE, y0 + EL_SIZE


def el_center(e):
    x0, y0, x1, y1 = el_rect(e)
    return (x0 + x1) / 2, (y0 + y1) / 2


# Fixed placement: ref -> (x, y, rot, side)
PLACE = {
    # handle: power / USB / RF connector
    'J4': (119.9, 4.8, 0, 'F'),
    'J1': (118.3, 24.0, 90, 'F'),
    'U5': (110.5, 24.0, 0, 'F'),
    'R1': (111.5, 19.0, 0, 'F'),
    'R2': (111.5, 29.0, 0, 'F'),
    'U4': (111.0, 34.0, 0, 'F'),
    'C9': (107.5, 34.0, 90, 'F'),
    'C10': (114.5, 34.0, 90, 'F'),
    # MCU
    'U3': (103.0, 13.0, 0, 'F'),
    'C11': (108.0, 13.0, 90, 'F'),
    'C12': (97.3, 11.4, 0, 'F'),
    'C13': (97.3, 15.6, 0, 'F'),
    'C14': (97.3, 8.2, 0, 'F'),
    'R3': (97.3, 6.2, 0, 'F'),
    'R7': (95.0, 20.0, 90, 'F'),
    'R8': (96.6, 20.0, 90, 'F'),
    'R9': (98.2, 20.0, 90, 'F'),
    'R10': (99.8, 20.0, 90, 'F'),
    'R11': (101.4, 20.0, 90, 'F'),
    # UI
    'BZ1': (89.0, 11.5, 0, 'F'),
    'R6': (89.0, 19.5, 0, 'F'),
    'D1': (85.8, 23.0, 0, 'F'),
    'R4': (89.4, 23.0, 0, 'F'),
    'D2': (85.8, 26.0, 0, 'F'),
    'R5': (89.4, 26.0, 0, 'F'),
    'J3': (96.5, 26.0, 0, 'F'),
    'SW1': (87.5, 33.0, 0, 'F'),
    'SW2': (93.5, 33.0, 0, 'F'),
    'J2': (101.0, 36.5, 0, 'F'),
    'H1': (84.5, 37.5, 0, 'F'),
    'H2': (119.5, 36.5, 0, 'F'),
    # head: clock between the converters
    'Y1': (47.5, 21.0, 0, 'F'),
    'C19': (47.5, 17.6, 0, 'F'),
    'R12': (47.5, 24.4, 0, 'F'),
    # RF loop at the nose (pads facing -Y)
    'AE1': (LOOP_C[0], LOOP_C[1], 90, 'F'),
}


def head_placement():
    for ref, (cx, cy) in CHIP.items():
        PLACE[ref] = (cx, cy, 180, 'F')
        d = 15 if ref == 'U1' else 17
        # decoupling in the gap north of the chip, between the two north feed-throughs
        PLACE['C%d' % d] = (cx - 0.4, cy - 4.5, 90, 'F')        # 100n next to VDD
        PLACE['C%d' % (d + 1)] = (cx - 0.4, cy - 7.7, 90, 'F')  # 1u
    for e, (chip, ch) in ELECTRODES.items():
        cx, cy = CHIP[chip]
        ex, ey = el_center(e)
        sx = 1 if ex > cx else -1
        sy = 1 if ey > cy else -1
        PLACE['E%d' % e] = (ex, ey, 0, 'B')  # rotation fixed up later so the feed via faces the chip
        # the NE tank (CH3) is flipped so its pre-routed nets don't cross, see preroute_ne()
        rot = 180 if ch == 3 else 0
        PLACE['L%d' % e] = (cx + sx * 6.0, cy + sy * 5.5, rot, 'F')
        PLACE['C%d' % e] = (cx + sx * 6.0, cy + sy * 8.3, rot, 'F')


head_placement()

# ---- netlist ---------------------------------------------------------------


def netlist():
    out = os.path.join(PRJ, NAME + '.net')
    subprocess.run(['kicad-cli', 'sch', 'export', 'netlist', '--format', 'kicadsexpr', '-o', out,
                    os.path.join(PRJ, NAME + '.kicad_sch')], check=True, capture_output=True,
                   env=dict(os.environ, **({'XDG_CONFIG_HOME': os.environ['LID_KICAD_CFG']} if 'LID_KICAD_CFG' in os.environ else {})))
    t = sexpr.parse(open(out).read())
    os.unlink(out)
    comps = {}
    for c in find(find1(t, 'components'), 'comp'):
        ref = find1(c, 'ref')[1]
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
        comps[ref] = {'value': find1(c, 'value')[1], 'footprint': find1(c, 'footprint')[1],
                      'tstamp': find1(c, 'tstamps')[1], 'fields': fields}
    nets = {}
    for n in find(find1(t, 'nets'), 'net'):
        name = find1(n, 'name')[1]
        nets[name] = [(find1(nd, 'ref')[1], find1(nd, 'pin')[1]) for nd in find(n, 'node')]
    return comps, nets


# ---- helpers -----------------------------------------------------------------


def P(x, y):
    return VECTOR2I(FromMM(OX + x), FromMM(OY + y))


def load_fp(libid):
    nick, name = libid.split(':', 1)
    path = FPLIB.get(nick, os.path.join(KIFP, nick + '.pretty'))
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise RuntimeError('footprint not found: ' + libid)
    fp.SetFPID(pcbnew.LIB_ID(nick, name))
    return fp


def seg(board, layer, a, b, w=0.05):
    s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(P(*a))
    s.SetEnd(P(*b))
    s.SetLayer(layer)
    s.SetWidth(FromMM(w))
    board.Add(s)


def arc(board, layer, start, mid, end, w=0.05):
    s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
    s.SetArcGeometry(P(*start), P(*mid), P(*end))
    s.SetLayer(layer)
    s.SetWidth(FromMM(w))
    board.Add(s)


def outline_pts(step_deg=10):
    """Closed polygon approximating the board outline (for zones)."""
    r = 2.0
    pts = []

    def corner(cx, cy, a0, a1):
        for k in range(0, 91, 15):
            a = math.radians(a0 + (a1 - a0) * k / 90)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    corner(BODY_X1 - r, BODY_Y0 + r, -90, 0)
    corner(BODY_X1 - r, BODY_Y1 - r, 0, 90)
    corner(BODY_X0 + r, BODY_Y1 - r, 90, 180)
    pts.append((BODY_X0, NOSE_Y1))
    for a in range(90, 271, step_deg):
        pts.append((NOSE_CX + 8 * math.cos(math.radians(a)), 20 + 8 * math.sin(math.radians(a))))
    pts.append((BODY_X0, NOSE_Y0))
    corner(BODY_X0 + r, BODY_Y0 + r, 180, 270)
    return pts


def draw_outline(board):
    L = pcbnew.Edge_Cuts
    r = 2.0
    x0, x1, y0, y1 = BODY_X0, BODY_X1, BODY_Y0, BODY_Y1
    k = r * (1 - math.sqrt(0.5))
    seg(board, L, (x0 + r, y0), (x1 - r, y0))
    arc(board, L, (x1 - r, y0), (x1 - k, y0 + k), (x1, y0 + r))
    seg(board, L, (x1, y0 + r), (x1, y1 - r))
    arc(board, L, (x1, y1 - r), (x1 - k, y1 - k), (x1 - r, y1))
    seg(board, L, (x1 - r, y1), (x0 + r, y1))
    arc(board, L, (x0 + r, y1), (x0 + k, y1 - k), (x0, y1 - r))
    seg(board, L, (x0, y1 - r), (x0, NOSE_Y1))
    seg(board, L, (x0, NOSE_Y1), (NOSE_CX, NOSE_Y1))
    arc(board, L, (NOSE_CX, NOSE_Y1), (NOSE_CX - 8, 20), (NOSE_CX, NOSE_Y0))
    seg(board, L, (NOSE_CX, NOSE_Y0), (x0, NOSE_Y0))
    seg(board, L, (x0, NOSE_Y0), (x0, y0 + r))
    arc(board, L, (x0, y0 + r), (x0 + k, y0 + k), (x0 + r, y0))


def zone(board, layers, pts, net=None, rule=None, priority=0, name=None, clearance=None, min_width=0.2):
    z = pcbnew.ZONE(board)
    ls = pcbnew.LSET()
    for l in layers:
        ls.AddLayer(l)
    z.SetLayerSet(ls)
    o = z.Outline()
    o.NewOutline()
    for x, y in pts:
        o.Append(FromMM(OX + x), FromMM(OY + y))
    if rule:
        z.SetIsRuleArea(True)
        z.SetDoNotAllowTracks('tracks' in rule)
        z.SetDoNotAllowVias('vias' in rule)
        z.SetDoNotAllowZoneFills('pour' in rule)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
    else:
        z.SetNet(net)
        z.SetAssignedPriority(priority)
        z.SetMinThickness(FromMM(min_width))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(FromMM(0.3))
        z.SetThermalReliefSpokeWidth(FromMM(0.3))
        if clearance is not None:
            z.SetLocalClearance(FromMM(clearance))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    if name:
        z.SetZoneName(name)
    board.Add(z)
    return z


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def circle_pts(cx, cy, r, a0=0, a1=360, step=10):
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(a0, a1, step)]


def text(board, s, x, y, layer, size=1.0, thick=0.15, angle=0, mirror=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetPosition(P(x, y))
    t.SetLayer(layer)
    t.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
    t.SetTextThickness(FromMM(thick))
    if angle:
        t.SetTextAngleDegrees(angle)
    if mirror:
        t.SetMirrored(True)
    board.Add(t)


# ---- design rules / net classes -------------------------------------------------


def setup_rules(board):
    board.SetCopperLayerCount(4)
    board.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)
    bds = board.GetDesignSettings()
    bds.SetBoardThickness(FromMM(1.6))
    # drill / placement origin at the bottom-left corner of the board's bounding box
    bds.SetAuxOrigin(P(0, BODY_Y1))
    bds.SetGridOrigin(P(0, BODY_Y1))
    bds.m_TrackMinWidth = FromMM(0.15)
    bds.m_MinClearance = FromMM(0.15)
    bds.m_ViasMinSize = FromMM(0.5)
    bds.m_MinThroughDrill = FromMM(0.3)
    bds.m_CopperEdgeClearance = FromMM(0.3)
    bds.m_HoleClearance = FromMM(0.25)
    bds.m_HoleToHoleMin = FromMM(0.25)
    bds.m_ViasMinAnnularWidth = FromMM(0.13)
    bds.m_MinSilkTextHeight = FromMM(0.8)
    ns = bds.m_NetSettings
    d = ns.GetDefaultNetclass()
    d.SetClearance(FromMM(0.15))
    d.SetTrackWidth(FromMM(0.2))
    d.SetViaDiameter(FromMM(0.6))
    d.SetViaDrill(FromMM(0.3))

    def cls(name, clr, w, via=0.6, drill=0.3):
        nc = pcbnew.NETCLASS(name)
        nc.SetClearance(FromMM(clr))
        nc.SetTrackWidth(FromMM(w))
        nc.SetViaDiameter(FromMM(via))
        nc.SetViaDrill(FromMM(drill))
        ns.SetNetclass(name, nc)
    cls('Power', 0.15, 0.3)
    cls('Sense', 0.2, 0.2)
    cls('RF', 0.5, 0.35)
    for pat, c in (('GND', 'Power'), ('+3V3', 'Power'), ('VBUS', 'Power'),
                   ('/SNS*', 'Sense'), ('/RF_PROBE', 'RF')):
        ns.SetNetclassPatternAssignment(pat, c)


# ---- main ----------------------------------------------------------------------


def build():
    comps, nets = netlist()
    board = pcbnew.BOARD()
    setup_rules(board)
    tb = board.GetTitleBlock()
    tb.SetTitle('Ledger Implant Detector (CONCEPT)')
    tb.SetRevision('0.1')
    tb.SetDate('2026-10-18')
    tb.SetComment(0, 'CONCEPT DESIGN - NOT YET BUILT OR VALIDATED')
    tb.SetComment(1, 'Stackup: JLC04161H-7628 (4L 1.6mm)')

    netinfo = {}
    for i, name in enumerate(sorted(nets), 1):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni
    pinnet = {}
    for name, nodes in nets.items():
        for ref, pin in nodes:
            pinnet[(ref, pin)] = name

    missing = set(comps) - set(PLACE)
    if missing:
        raise SystemExit('no placement for: %s' % sorted(missing))

    fps = {}
    for ref, c in sorted(comps.items()):
        fp = load_fp(c['footprint'])
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
        x, y, rot, side = PLACE[ref]
        board.Add(fp)
        fp.SetPosition(P(x, y))
        if side == 'B':
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            n = pinnet.get((ref, pad.GetNumber()))
            if n:
                pad.SetNet(netinfo[n])
        # passives: designators on the fab drawing only (no room on silk around the tanks);
        # parts that already have a silk label get none
        if ref in ('J1', 'J2', 'J4', 'AE1', 'H1', 'H2') or ref[0] == 'E':
            fp.Reference().SetVisible(False)
        elif ref[0] in 'RCL' and side == 'F':
            fp.Reference().SetLayer(pcbnew.F_Fab)
        else:
            fp.Reference().SetTextSize(VECTOR2I(FromMM(0.8), FromMM(0.8)))
            fp.Reference().SetTextThickness(FromMM(0.12))
        if ref == 'Y1':
            fp.Reference().SetPosition(P(x + 2.9, y))
            fp.Reference().SetTextAngleDegrees(90)
        fps[ref] = fp

    # orient each electrode so its feed-through sits at the corner nearest its converter
    for e, (chip, ch) in ELECTRODES.items():
        fp = fps['E%d' % e]
        cx, cy = CHIP[chip]
        best = None
        for rot in (0, 90, 180, 270):
            fp.SetOrientationDegrees(rot)
            th = [p for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH][0]
            px, py = pcbnew.ToMM(th.GetPosition().x) - OX, pcbnew.ToMM(th.GetPosition().y) - OY
            d = math.hypot(px - cx, py - cy)
            if best is None or d < best[0]:
                best = (d, rot)
        fp.SetOrientationDegrees(best[1])
        fp.Reference().SetLayer(pcbnew.B_SilkS)
        fp.Reference().SetVisible(False)

    draw_outline(board)
    outline = outline_pts()
    gnd = netinfo['GND']

    # In1 = solid GND shield / reference plane (the router fans GND out to it);
    # the other pours are added after routing, see add_pours()
    zone(board, [pcbnew.In1_Cu], outline, gnd, priority=0, name='GND_shield')

    # keep In2/B.Cu (the layers right above / at the electrodes) free of anything but the plates
    # (notched around the electrode's own feed-through so the router can reach it)
    for e in ELECTRODES:
        x0, y0, x1, y1 = el_rect(e)
        x0, y0, x1, y1 = x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 0.5
        th = [p for p in fps['E%d' % e].Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH][0].GetPosition()
        tx, ty = pcbnew.ToMM(th.x) - OX, pcbnew.ToMM(th.y) - OY
        n = 0.7  # notch half-size: room for the feed-through only, no foreign via fits
        # walk the rectangle corners, replacing the one nearest the feed-through by a notch
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        k = min(range(4), key=lambda i: math.hypot(corners[i][0] - tx, corners[i][1] - ty))
        pts = []
        for i, (cx_, cy_) in enumerate(corners):
            if i != k:
                pts.append((cx_, cy_))
                continue
            sxn = 1 if tx > cx_ else -1
            syn = 1 if ty > cy_ else -1
            nx, ny = tx + sxn * n, ty + syn * n
            prev = corners[i - 1]
            if prev[0] == cx_:  # coming along a vertical edge
                pts += [(cx_, ny), (nx, ny), (nx, cy_)]
            else:
                pts += [(nx, cy_), (nx, ny), (cx_, ny)]
        zone(board, [pcbnew.In2_Cu, pcbnew.B_Cu], pts, rule=('tracks', 'vias', 'pour'), name='EL%d_keepout' % e)
    # no inner-layer routing anywhere in the head except the via channel / gaps: allowed by default

    # nothing but the electrodes on the sensing face of the head
    zone(board, [pcbnew.B_Cu], rect(BODY_X0 - 12, -1, HANDLE_X0 - 0.5, BODY_Y1 + 1), rule=('tracks',), name='HEAD_bottom_no_tracks')

    # RF loop: no copper pour around the loop on any layer, except a wedge where its pads are
    lx, ly = LOOP_C
    wedge = circle_pts(lx, ly, 6.0, -45, 226, 10) + [(lx, ly - 1.5)]
    zone(board, [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu], wedge, rule=('pour', 'vias'), name='LOOP_keepout')

    # RF feed: 50 ohm microstrip on F.Cu over In1 (locked, routed by hand)
    feed = [p for p in fps['AE1'].Pads() if p.GetNumber() == '1'][0].GetPosition()
    fx, fy = pcbnew.ToMM(feed.x) - OX, pcbnew.ToMM(feed.y) - OY
    sma = [p for p in fps['J4'].Pads() if p.GetNumber() == '1'][0].GetPosition()
    sx, sy = pcbnew.ToMM(sma.x) - OX, pcbnew.ToMM(sma.y) - OY
    ry = 1.8
    path = [(fx, fy), (fx, 13.6), (12.8, 13.6), (13.6, 12.8), (13.6, ry + 1.5), (15.1, ry),
            (sx - 2.7 - (sy - ry), ry), (sx - 2.7, sy), (sx, sy)]
    for a, b in zip(path, path[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(P(*a))
        t.SetEnd(P(*b))
        t.SetWidth(FromMM(0.35))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(netinfo['/RF_PROBE'])
        t.SetLocked(True)
        board.Add(t)

    # silkscreen
    S = pcbnew.F_SilkS
    text(board, 'IMPLANT DETECTOR rev0.1 - CONCEPT, UNTESTED', 48.0, 39.0, pcbnew.B_SilkS, 0.8, 0.12, mirror=True)
    text(board, 'github.com/KarpelesLab/ledger_implant_detector', 48.0, 1.9, pcbnew.B_SilkS, 0.8, 0.12, mirror=True)
    text(board, 'LEDGER IMPLANT DETECTOR  rev0.1 CONCEPT', 48.0, 39.0, S, 0.8, 0.12)
    for e in ELECTRODES:
        ex, ey = el_center(e)
        text(board, 'E%d' % e, ex, ey, pcbnew.B_SilkS, 2.0, 0.3, mirror=True)
    text(board, 'RF', 115.0, 6.3, S, 0.8, 0.12)
    text(board, 'USB', 113.0, 24.0, S, 0.8, 0.12, angle=90)
    text(board, 'CAL', 87.5, 35.8, S, 0.8, 0.12)
    text(board, 'BOOT', 93.5, 35.8, S, 0.8, 0.12)
    text(board, 'LOOP', 6.0, 26.5, S, 0.8, 0.12)
    text(board, 'Qwiic', 101.0, 32.3, S, 0.8, 0.12)

    escape_digital(board)
    preroute_ne(board)
    preroute_north(board)
    preroute_bus(board)
    fanout(board)
    return board


# digital side of each converter (rot 180: pins 1-4 face +X): stub + via so these nets
# leave on In2 through the via channel and the F.Cu around the chip stays free for the tanks
DIGITAL_ESCAPE = {'4': [(2.6, -0.75), (3.0, -1.45)], '3': [(3.3, -0.25), (3.9, -0.6)],
                  '2': [(3.3, 0.25), (3.9, 0.6)], '1': [(2.6, 0.75), (3.0, 1.45)]}
PREROUTED = set()


# CH3 (pins 15 = IN3A, 16 = IN3B on the south side) serves the NE electrode, diagonally
# opposite the analog pins: B hugs the chip, A goes round the outside and loops back over
# the tank to the feed-through. Coordinates relative to the converter centre.
NE_B = [(0.75, 2.7), (4.6, 2.7), (4.6, -5.5), (4.6, -7.0), (5.225, -7.625), (5.225, -8.3)]
NE_A = [(0.25, 3.15), (5.9, 3.15), (5.9, -3.6), (6.6, -3.6), (7.4, -4.4), (7.4, -5.5), (7.4, -7.0),
        (6.775, -7.625), (6.775, -9.4), (3.0, -9.4), (2.4, -8.8), (2.4, -3.9)]


# north side (pins 5 INTB, 6 SD, 7 VDD): VDD to both decoupling caps (detouring east of
# the near cap's GND pad), SD / INTB escape north through the gap, past the CH3 loop
NORTH = {'7': [(-0.25, -3.0), (-0.4, -3.725), (0.45, -4.5), (0.45, -6.2), (-0.4, -6.925)],
         '7b': [(0.45, -6.2), (0.9, -6.65), (0.9, -10.2)],
         '6': [(0.25, -2.9), (0.95, -3.6), (0.95, -4.8), (1.4, -5.25), (1.4, -10.2)],
         '5': [(0.75, -2.5), (1.4, -3.15), (1.4, -4.6), (1.9, -5.1), (1.9, -10.2)]}


def preroute_north(board):
    for ref, (cx, cy) in CHIP.items():
        fp = board.FindFootprintByReference(ref)
        for num, pts in NORTH.items():
            pad = [p for p in fp.Pads() if p.GetNumber() == num[0]][0]
            prev = pad.GetPosition() if len(num) == 1 else P(cx + pts[0][0], cy + pts[0][1])
            for dx, dy in pts:
                if P(cx + dx, cy + dy) == prev:
                    continue
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(prev)
                t.SetEnd(P(cx + dx, cy + dy))
                t.SetWidth(FromMM(0.3 if num[0] == '7' else 0.2))
                t.SetLayer(pcbnew.F_Cu)
                t.SetNet(pad.GetNet())
                t.SetLocked(True)
                board.Add(t)
                prev = P(cx + dx, cy + dy)
            PREROUTED.add((ref, num[0]))


# the north escapes of both converters run east to the handle as a small bus over the
# top-row electrodes (F.Cu is free there; In1 shields), U1 on the upper rows, U2 below
BUS_END_X = 81.5
BUS_ROWS = {'U1': {'7b': 6.6, '6': 7.2, '5': 7.8}, 'U2': {'7b': 9.0, '6': 9.6, '5': 10.2}}


def preroute_bus(board):
    for ref, rows in BUS_ROWS.items():
        cx, cy = CHIP[ref]
        fp = board.FindFootprintByReference(ref)
        for key, row in rows.items():
            x0, y0 = cx + NORTH[key][-1][0], cy + NORTH[key][-1][1]
            net = [p for p in fp.Pads() if p.GetNumber() == key[0]][0].GetNet()
            for a, b in (((x0, y0), (x0, row)), ((x0, row), (BUS_END_X, row))):
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(P(*a))
                t.SetEnd(P(*b))
                t.SetWidth(FromMM(0.3 if key[0] == '7' else 0.2))
                t.SetLayer(pcbnew.F_Cu)
                t.SetNet(net)
                t.SetLocked(True)
                board.Add(t)


def preroute_ne(board):
    for ref, (cx, cy) in CHIP.items():
        fp = board.FindFootprintByReference(ref)
        for num, pts in (('16', NE_B), ('15', NE_A)):
            pad = [p for p in fp.Pads() if p.GetNumber() == num][0]
            prev = pad.GetPosition()
            for dx, dy in pts:
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(prev)
                t.SetEnd(P(cx + dx, cy + dy))
                t.SetWidth(FromMM(0.2))
                t.SetLayer(pcbnew.F_Cu)
                t.SetNet(pad.GetNet())
                t.SetLocked(True)
                board.Add(t)
                prev = P(cx + dx, cy + dy)
            PREROUTED.add((ref, num))


def escape_digital(board):
    for ref, (cx, cy) in CHIP.items():
        fp = board.FindFootprintByReference(ref)
        for num, pts in DIGITAL_ESCAPE.items():
            pad = [p for p in fp.Pads() if p.GetNumber() == num][0]
            net = pad.GetNet()
            prev = pad.GetPosition()
            for i, (dx, dy) in enumerate(pts):
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(prev)
                t.SetEnd(P(cx + dx, cy + dy))
                t.SetWidth(FromMM(0.2))
                t.SetLayer(pcbnew.F_Cu)
                t.SetNet(net)
                t.SetLocked(True)
                board.Add(t)
                prev = P(cx + dx, cy + dy)
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(prev)
            v.SetWidth(FromMM(0.6))
            v.SetDrill(FromMM(0.3))
            v.SetNet(net)
            v.SetLocked(True)
            board.Add(v)
            PREROUTED.add((ref, num))


def add_pours(board):
    gnd = board.FindNet('GND')
    zone(board, [pcbnew.F_Cu], outline_pts(), gnd, priority=0, name='GND_top')
    zone(board, [pcbnew.In2_Cu], rect(HANDLE_X0, 0.5, BODY_X1 - 0.5, BODY_Y1 - 0.5), gnd, name='GND_in2_handle')
    zone(board, [pcbnew.B_Cu], rect(HANDLE_X0, 0.5, BODY_X1 - 0.5, BODY_Y1 - 0.5), gnd, name='GND_bottom')


FREEROUTING = os.environ.get('FREEROUTING_JAR', 'freerouting.jar')


def route(board, passes=40):
    """Autoroute. GND pads are already fanned out to the In1 plane (see fanout())."""
    dsn = os.path.join(PRJ, NAME + '.dsn')
    ses = os.path.join(PRJ, NAME + '.ses')
    # hide from the router: the RF line (hand-placed) and the electrode plates (only the
    # feed-through is a valid target); restored after import
    hidden = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if (fp.GetReference().startswith('E') and pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD) or \
                    pad.GetNetname() == '/RF_PROBE':
                hidden.append((pad, pad.GetNetCode()))
    for t in board.GetTracks():
        if t.GetNetname() == '/RF_PROBE':
            hidden.append((t, t.GetNetCode()))
    for item, _ in hidden:
        item.SetNetCode(0)
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        raise SystemExit('DSN export failed')
    passes = int(os.environ.get('FREEROUTING_PASSES', passes))
    extra = os.environ.get('FREEROUTING_EXTRA', '').split()
    subprocess.run(['java', '-Xmx8g', '-jar', FREEROUTING, '-de', dsn, '-do', ses,
                    '-mp', str(passes)] + extra, check=True, timeout=3600)
    if not pcbnew.ImportSpecctraSES(board, ses):
        raise SystemExit('SES import failed')
    for item, code in hidden:
        item.SetNetCode(code)
    os.unlink(dsn)
    os.unlink(ses)


def _box_dist(px, py, box):
    x0, y0, x1, y1 = box
    dx = max(x0 - px, 0, px - x1)
    dy = max(y0 - py, 0, py - y1)
    return math.hypot(dx, dy)


def _seg_box_dist(a, b, box, step=0.05):
    n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
    return min(_box_dist(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n, box) for i in range(n + 1))


def _seg_point_dist(a, b, p):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _in_poly(x, y, poly):
    inside = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _poly_edge_dist(x, y, poly):
    best = 1e9
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        dx, dy = x1 - x0, y1 - y0
        t = max(0, min(1, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy or 1)))
        best = min(best, math.hypot(x - x0 - t * dx, y - y0 - t * dy))
    return best


def _mm(v):
    return pcbnew.ToMM(v)


def fanout(board):
    """Give every GND SMD pad a short stub + via down to the In1 GND plane."""
    gnd = board.FindNet('GND')
    outline = outline_pts()
    keepouts = []
    for z in board.Zones():
        if z.GetIsRuleArea() and z.GetDoNotAllowVias():
            o = z.Outline().Outline(0)
            keepouts.append([(_mm(o.CPoint(i).x) - OX, _mm(o.CPoint(i).y) - OY) for i in range(o.PointCount())])
    boxes = []  # (box, netcode, pad)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            bb = pad.GetBoundingBox()
            boxes.append(((_mm(bb.GetX()) - OX, _mm(bb.GetY()) - OY, _mm(bb.GetRight()) - OX, _mm(bb.GetBottom()) - OY),
                          pad.GetNetCode(), pad))
    rf = []
    for t in board.GetTracks():
        if t.GetNetname() == '/RF_PROBE':
            rf.append(((_mm(t.GetStart().x) - OX, _mm(t.GetStart().y) - OY), (_mm(t.GetEnd().x) - OX, _mm(t.GetEnd().y) - OY)))
    placed = []
    failed = []
    fixed = []
    for t in board.GetTracks():
        if t.GetNetCode() == gnd.GetNetCode():
            continue
        a_ = (_mm(t.GetStart().x) - OX, _mm(t.GetStart().y) - OY)
        b_ = (_mm(t.GetEnd().x) - OX, _mm(t.GetEnd().y) - OY)
        w = _mm(t.GetWidth()) if t.Type() == pcbnew.PCB_TRACE_T else 0.6
        fixed.append((a_, b_, w))

    def ok(vx, vy, px, py, own):
        if not _in_poly(vx, vy, outline) or _poly_edge_dist(vx, vy, outline) < 0.7:
            return False
        for k in keepouts:
            if _in_poly(vx, vy, k) or _poly_edge_dist(vx, vy, k) < 0.35:
                return False
        for box, net, pad in boxes:
            if pad is own:
                continue
            same = net == gnd.GetNetCode()
            if _box_dist(vx, vy, box) < (0.35 if same else 0.5):
                return False
            if not same and _seg_box_dist((px, py), (vx, vy), box) < 0.3:
                return False
        for qx, qy in placed:
            if math.hypot(vx - qx, vy - qy) < 0.9:
                return False
        for a, b, w in fixed:
            if _seg_point_dist(a, b, (vx, vy)) < 0.3 + 0.2 + w / 2:
                return False
        for a, b in rf:
            n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.1))
            for i in range(n + 1):
                if math.hypot(vx - a[0] - (b[0] - a[0]) * i / n, vy - a[1] - (b[1] - a[1]) * i / n) < 1.0:
                    return False
        return True

    for fp in board.GetFootprints():
        cx, cy = _mm(fp.GetPosition().x) - OX, _mm(fp.GetPosition().y) - OY
        for pad in fp.Pads():
            if pad.GetNetCode() != gnd.GetNetCode() or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            if (fp.GetReference(), pad.GetNumber()) in PREROUTED:
                continue
            if fp.GetReference() in CHIP and pad.GetNumber() == '17':
                # FDC2214 die-attach pad: 2x2 vias in the pad (DAP is a secondary ground, pin 8 is the real one)
                for dx in (-0.65, 0.65):
                    for dy in (-0.65, 0.65):
                        v = pcbnew.PCB_VIA(board)
                        v.SetPosition(VECTOR2I(pad.GetPosition().x + FromMM(dx), pad.GetPosition().y + FromMM(dy)))
                        v.SetWidth(FromMM(0.6))
                        v.SetDrill(FromMM(0.3))
                        v.SetNet(gnd)
                        v.SetLocked(True)
                        board.Add(v)
                continue
            px, py = _mm(pad.GetPosition().x) - OX, _mm(pad.GetPosition().y) - OY
            half = max(_mm(pad.GetSize().x), _mm(pad.GetSize().y)) / 2
            a0 = math.atan2(py - cy, px - cx) if (px, py) != (cx, cy) else -math.pi / 2
            found = None
            for d10 in range(int((half + 0.5) * 10), int((half + 2.4) * 10), 2):
                for k in (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6, 8, -8, 10, -10, 12):
                    a = a0 + math.radians(15 * k)
                    vx, vy = px + d10 / 10 * math.cos(a), py + d10 / 10 * math.sin(a)
                    if ok(vx, vy, px, py, pad):
                        found = (vx, vy)
                        break
                if found:
                    break
            if not found:
                failed.append('%s.%s' % (fp.GetReference(), pad.GetNumber()))
                continue
            vx, vy = found
            placed.append(found)
            w = min(0.3, _mm(pad.GetSize().x), _mm(pad.GetSize().y))
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pad.GetPosition())
            t.SetEnd(P(vx, vy))
            t.SetWidth(FromMM(w))
            t.SetLayer(pcbnew.F_Cu)
            t.SetNet(gnd)
            t.SetLocked(True)
            board.Add(t)
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(P(vx, vy))
            v.SetWidth(FromMM(0.6))
            v.SetDrill(FromMM(0.3))
            v.SetNet(gnd)
            v.SetLocked(True)
            board.Add(v)
    print('fanout: %d vias, failed: %s' % (len(placed), failed or 'none'), flush=True)


def stitch_candidates():
    pts = []
    # electrode column gaps and the horizontal channel
    for gx in (EL_X0 + EL_SIZE + 1.5, EL_X0 + EL_PITCH + EL_SIZE + 1.5, EL_X0 + 2 * EL_PITCH + EL_SIZE + 1.5):
        pts += [(gx, y / 10) for y in range(40, 381, 25)]
    pts += [(x / 10, 19.2) for x in range(140, 830, 25)] + [(x / 10, 22.8) for x in range(140, 830, 25)]
    # along the RF microstrip (return path) and the bottom edge
    pts += [(x / 10, 3.0) for x in range(160, 1120, 25)]
    pts += [(x / 10, 39.1) for x in range(160, 830, 25) if not 270 <= x <= 690]  # gap under the silk legend
    pts += [(13.3, y / 10) for y in range(150, 381, 25)]
    # handle
    pts += [(x / 10, y / 10) for x in range(840, 1210, 25) for y in range(15, 391, 25)]
    return pts


def add_stitching(board):
    gnd = board.FindNet('GND')
    vias = []
    taken = [(_mm(v.GetPosition().x) - OX, _mm(v.GetPosition().y) - OY) for v in board.GetTracks()
             if v.Type() == pcbnew.PCB_VIA_T]
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.HasHole():
                taken.append((_mm(pad.GetPosition().x) - OX, _mm(pad.GetPosition().y) - OY))
    for x, y in stitch_candidates():
        if any(math.hypot(x - tx, y - ty) < 1.2 for tx, ty in taken):
            continue
        taken.append((x, y))
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(P(x, y))
        v.SetWidth(FromMM(0.6))
        v.SetDrill(FromMM(0.3))
        v.SetNet(gnd)
        board.Add(v)
        vias.append(v)
    return vias


def drc_json(path):
    import json
    out = path + '.drc.json'
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-error', '-o', out, path],
                   check=True, capture_output=True,
                   env=dict(os.environ, **({'XDG_CONFIG_HOME': os.environ['LID_KICAD_CFG']} if 'LID_KICAD_CFG' in os.environ else {})))
    d = json.load(open(out))
    os.unlink(out)
    return d


def prune_stitching(board, vias):
    """Remove stitching vias involved in any DRC error (except 'unconnected')."""
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    d = drc_json(PCB)
    bad = set()
    for v in d.get('violations', []):
        for it in v.get('items', []):
            bad.add(it.get('uuid'))
    drop = [v for v in vias if v.m_Uuid.AsString() in bad]
    n = len(drop)
    keep = [v for v in vias if v.m_Uuid.AsString() not in bad]
    for v in drop:
        board.Delete(v)
    print('stitching: kept %d of %d vias' % (len(vias) - n, len(vias)), flush=True)
    return keep


def trim_dangling(board):
    """Delete track segments with a free end (e.g. pre-routed stubs the router bypassed)."""
    pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
    removed = 0
    while True:
        tracks = [t for t in board.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]
        vias = [v for v in board.GetTracks() if v.Type() == pcbnew.PCB_VIA_T]

        def connected(t, pt):
            for o in tracks:
                if o is not t and o.GetNetCode() == t.GetNetCode() and o.HitTest(pt, 1000):
                    return True
            for v in vias:
                if v.GetNetCode() == t.GetNetCode() and v.HitTest(pt, 1000):
                    return True
            for p in pads:
                if p.GetNetCode() == t.GetNetCode() and p.IsOnLayer(t.GetLayer()) and p.HitTest(pt, 1000):
                    return True
            return False
        changed = False
        for t in tracks:
            cs, ce = connected(t, t.GetStart()), connected(t, t.GetEnd())
            if cs and ce:
                continue
            if not cs and not ce:
                board.Delete(t)
                removed += 1
                changed = True
                break
            # one free end: shorten back to the farthest T-junction on the segment, if any
            keep = t.GetStart() if cs else t.GetEnd()
            juncs = [pt for o in tracks if o is not t and o.GetNetCode() == t.GetNetCode()
                     for pt in (o.GetStart(), o.GetEnd()) if t.HitTest(pt, 1000) and pt != keep]
            juncs += [v.GetPosition() for v in vias if v.GetNetCode() == t.GetNetCode()
                      and t.HitTest(v.GetPosition(), 1000) and v.GetPosition() != keep]
            if juncs:
                far = max(juncs, key=lambda pt: (pt - keep).EuclideanNorm())
                if cs:
                    t.SetEnd(far)
                else:
                    t.SetStart(far)
            else:
                board.Delete(t)
            removed += 1
            changed = True
            break
        if not changed:
            break
    print('trimmed %d dangling segments' % removed, flush=True)


def finish(board):
    # the router leaves a few zero-length stubs; Delete() (not Remove()) is safe from Python
    for t in [t for t in board.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and t.GetLength() < FromMM(0.002)]:
        board.Delete(t)
    trim_dangling(board)
    add_pours(board)
    vias = add_stitching(board)
    for _ in range(3):
        vias = prune_stitching(board, vias)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())


if __name__ == '__main__':
    if '--finish-only' not in sys.argv:
        b = build()
        if '--no-route' not in sys.argv:
            route(b)
        pcbnew.SaveBoard(PCB, b)
        print('saved', PCB, flush=True)
    if '--no-route' not in sys.argv and '--no-finish' not in sys.argv:
        # finish in a fresh process: reload from disk, then pour / stitch / fill
        if '--finish-only' in sys.argv:
            b = pcbnew.LoadBoard(PCB)
            finish(b)
            pcbnew.SaveBoard(PCB, b)
            print('finished', PCB, flush=True)
        else:
            subprocess.run([sys.executable, os.path.abspath(__file__), '--finish-only'], check=True)
