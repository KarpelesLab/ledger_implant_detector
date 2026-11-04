#!/usr/bin/env python3
"""Generate the project library (hardware/lib): symbols + footprints."""
import copy
import math
import os

import sexpr
from sexpr import Sym, find, find1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, 'hardware', 'lib')
KISYM = '/usr/share/kicad/symbols'


def load_symbol(lib, name):
    tree = sexpr.parse(open(os.path.join(KISYM, lib + '.kicad_sym')).read())
    for s in find(tree, 'symbol'):
        if s[1] == name:
            return s
    raise KeyError(name)


def set_prop(sym, key, value, hide=None):
    for p in find(sym, 'property'):
        if p[1] == key:
            p[2] = value
            return p
    p = [Sym('property'), key, value, [Sym('at'), 0, 0, 0],
         [Sym('effects'), [Sym('font'), [Sym('size'), 1.27, 1.27]], [Sym('hide'), Sym('yes')]]]
    idx = max(i for i, x in enumerate(sym) if isinstance(x, list) and x[0] == Sym('property')) + 1
    sym.insert(idx, p)
    return p


def rename_units(sym, old, new):
    for sub in find(sym, 'symbol'):
        sub[1] = sub[1].replace(old + '_', new + '_', 1)


def fdc2214():
    s = copy.deepcopy(load_symbol('Sensor_Proximity', 'LDC1314'))
    s[1] = 'FDC2214'
    rename_units(s, 'LDC1314', 'FDC2214')
    set_prop(s, 'Value', 'FDC2214')
    set_prop(s, 'Footprint', 'Package_DFN_QFN:WQFN-16-1EP_4x4mm_P0.5mm_EP2.6x2.6mm')
    set_prop(s, 'Datasheet', 'https://www.ti.com/lit/ds/symlink/fdc2214.pdf')
    set_prop(s, 'Description', 'Capacitance-to-digital converter, 4-channel 28-bit, resonant LC sensor, WQFN-16 (RGH). '
             'Pin-compatible with LDC1614; symbol derived from KiCad LDC1314.')
    set_prop(s, 'ki_keywords', 'capacitance sensor FDC proximity')
    return s


def pin(num, name, x, y, ang, etype='passive', length=2.54):
    return [Sym('pin'), Sym(etype), Sym('line'), [Sym('at'), x, y, ang], [Sym('length'), length],
            [Sym('name'), name, [Sym('effects'), [Sym('font'), [Sym('size'), 1.27, 1.27]]]],
            [Sym('number'), num, [Sym('effects'), [Sym('font'), [Sym('size'), 1.27, 1.27]]]]]


def prop(key, val, x=0, y=0, hide=False):
    eff = [Sym('effects'), [Sym('font'), [Sym('size'), 1.27, 1.27]]]
    if hide:
        eff.append([Sym('hide'), Sym('yes')])
    return [Sym('property'), key, val, [Sym('at'), x, y, 0], eff]


def stroke(w=0.254):
    return [Sym('stroke'), [Sym('width'), w], [Sym('type'), Sym('default')]]


def fill(t='none'):
    return [Sym('fill'), [Sym('type'), Sym(t)]]


def simple_symbol(name, ref, desc, fp, graphics, pins, in_bom=True, hide_pin_names=True, hide_pin_numbers=True):
    s = [Sym('symbol'), name]
    if hide_pin_numbers:
        s.append([Sym('pin_numbers'), [Sym('hide'), Sym('yes')]])
    if hide_pin_names:
        s.append([Sym('pin_names'), [Sym('offset'), 0], [Sym('hide'), Sym('yes')]])
    s += [[Sym('exclude_from_sim'), Sym('yes')], [Sym('in_bom'), Sym('yes' if in_bom else 'no')],
          [Sym('on_board'), Sym('yes')],
          prop('Reference', ref, 0, 3.81), prop('Value', name, 0, 5.715),
          prop('Footprint', fp, hide=True), prop('Datasheet', '', hide=True),
          prop('Description', desc, hide=True),
          [Sym('symbol'), name + '_0_1'] + graphics,
          [Sym('symbol'), name + '_1_1'] + pins]
    return s


def electrode_symbol():
    g = [[Sym('rectangle'), [Sym('start'), -3.81, 1.016], [Sym('end'), 3.81, 0], stroke(), fill('outline')]]
    return simple_symbol('Electrode', 'E', 'Capacitive sensing electrode (PCB copper plate)',
                         'lid:Electrode_14x14mm', g, [pin('1', 'SENSE', 0, -2.54, 90)], in_bom=False)


def loop_symbol():
    g = [[Sym('circle'), [Sym('center'), 0, 0], [Sym('radius'), 2.54], stroke(), fill()]]
    pins = [pin('1', 'FEED', -5.08, 0, 0), pin('2', 'GND', 0, -5.08, 90)]
    return simple_symbol('NearField_Loop', 'AE', 'PCB near-field H-field loop (net-tie between feed and ground)',
                         'lid:NearField_Loop_D8mm', g, pins, in_bom=False)


def ic_symbol(name, ref, desc, fp, left, right):
    """Plain box; left/right = [(pin number, name), ...] top to bottom. All passive: the datasheet pin table is the source."""
    n = max(len(left), len(right))
    w = 12.7
    top = ((n + 1) // 2 + 1) * 2.54
    g = [[Sym('rectangle'), [Sym('start'), -w, top], [Sym('end'), w, top - 2.54 * (n + 1)], stroke(), fill('background')]]
    pins = []
    for side, x, ang in ((left, -w - 2.54, 0), (right, w + 2.54, 180)):
        for i, (num, label) in enumerate(side):
            pins.append(pin(num, label, x, top - 2.54 * (i + 1), ang))
    s = simple_symbol(name, ref, desc, fp, g, pins, hide_pin_names=False, hide_pin_numbers=False)
    return s


def adf4351_symbol():
    """Pin table: ADF4351 datasheet Rev. A, Table 5 (32-lead LFCSP, CP-32-7)."""
    return ic_symbol('ADF4351', 'U', 'Wideband PLL synthesizer with VCO, 35 MHz - 4.4 GHz, LFCSP-32',
                     'Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm',
                     [('1', 'CLK'), ('2', 'DATA'), ('3', 'LE'), ('4', 'CE'), ('26', 'PDBRF'), ('25', 'LD'), ('30', 'MUXOUT'),
                      ('29', 'REFIN'), ('5', 'SW'), ('7', 'CPOUT'), ('20', 'VTUNE'), ('22', 'RSET'), ('19', 'TEMP'),
                      ('23', 'VCOM'), ('24', 'VREF')],
                     [('6', 'VP'), ('10', 'AVDD'), ('16', 'VVCO'), ('17', 'VVCO'), ('28', 'DVDD'), ('32', 'SDVDD'),
                      ('12', 'RFOUTA+'), ('13', 'RFOUTA-'), ('14', 'RFOUTB+'), ('15', 'RFOUTB-'), ('8', 'CPGND'), ('9', 'AGND'),
                      ('11', 'AGNDVCO'), ('18', 'AGNDVCO'), ('21', 'AGNDVCO'), ('27', 'DGND'), ('31', 'SDGND'), ('33', 'EP')])


def ad8318_symbol():
    """Pin table: AD8318 datasheet Rev. B, Table 3 (16-lead LFCSP, CP-16-4)."""
    return ic_symbol('AD8318', 'U', 'Logarithmic detector/controller, 1 MHz - 8 GHz, 70 dB, -25 mV/dB, LFCSP-16',
                     'Package_CSP:Analog_LFCSP-16-1EP_4x4mm_P0.65mm_EP2.35x2.35mm',
                     [('14', 'INHI'), ('15', 'INLO'), ('16', 'ENBL'), ('10', 'TADJ'), ('5', 'CLPF'), ('13', 'TEMP')],
                     [('3', 'VPSI'), ('4', 'VPSI'), ('9', 'VPSO'), ('6', 'VOUT'), ('7', 'VSET'), ('8', 'CMOP'), ('1', 'CMIP'),
                      ('2', 'CMIP'), ('11', 'CMIP'), ('12', 'CMIP'), ('17', 'EP')])


def write_symbols():
    lib = [Sym('kicad_symbol_lib'), [Sym('version'), 20251024], [Sym('generator'), 'lid_gen'],
           [Sym('generator_version'), '10.0'], fdc2214(), electrode_symbol(), loop_symbol(),
           adf4351_symbol(), ad8318_symbol()]
    with open(os.path.join(LIB, 'lid.kicad_sym'), 'w') as f:
        f.write(sexpr.dump(lib) + '\n')


FP_HEAD = '''(footprint "{name}"
	(version 20241229)
	(generator "lid_gen")
	(generator_version "10.0")
	(layer "F.Cu")
	(descr "{descr}")
	(tags "{tags}")
	(property "Reference" "REF**" (at {rx} {ry} 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
	(property "Value" "{name}" (at 0 {vy} 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
	(property "Footprint" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))
	(property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))
	(property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))
'''


def electrode_fp():
    """14x14 mm plate on the footprint's copper side, mask-covered, with a
    plated feed-through at the -Y edge so the tank can be connected from the
    other side of the board. Place flipped (bottom) on the board."""
    s = FP_HEAD.format(name='Electrode_14x14mm', descr='Capacitive sensing electrode 14x14mm, solder-mask covered, with feed-through via pad',
                       tags='capacitive electrode sensor', rx=0, ry=0, vy=9)
    s += '\t(attr smd exclude_from_pos_files exclude_from_bom allow_soldermask_bridges)\n'
    s += '\t(fp_rect (start -7 -7) (end 7 7) (stroke (width 0.1) (type default)) (fill no) (layer "F.Fab"))\n'
    s += '\t(fp_rect (start -7.25 -7.25) (end 7.25 7.25) (stroke (width 0.05) (type default)) (fill no) (layer "F.CrtYd"))\n'
    s += '\t(pad "1" smd rect (at 0 0) (size 14 14) (layers "F.Cu") (zone_connect 0))\n'
    s += '\t(pad "1" thru_hole circle (at 6.1 6.1) (size 0.7 0.7) (drill 0.35) (layers "*.Cu") (remove_unused_layers no) (zone_connect 0))\n'
    s += ')\n'
    return s


def loop_fp():
    r = 4.0
    a = math.radians(20)
    sx, sy = r * math.cos(a), r * math.sin(a)
    s = FP_HEAD.format(name='NearField_Loop_D8mm', descr='Near-field H-field loop, 8mm centerline diameter, 0.5mm trace. Pad 1 feed, pad 2 ground (via)',
                       tags='near field probe loop H-field', rx=0, ry=-6, vy=6)
    s += '\t(attr smd exclude_from_pos_files exclude_from_bom)\n'
    s += '\t(net_tie_pad_groups "1,2")\n'
    s += '\t(fp_arc (start %.4f %.4f) (mid %.4f 0) (end %.4f %.4f) (stroke (width 0.5) (type solid)) (layer "F.Cu"))\n' % (sx, sy, -r, sx, -sy)
    s += '\t(fp_circle (center 0 0) (end 4.75 0) (stroke (width 0.1) (type default)) (fill no) (layer "F.Fab"))\n'
    s += '\t(fp_circle (center 0 0) (end 5 0) (stroke (width 0.05) (type default)) (fill no) (layer "F.CrtYd"))\n'
    s += '\t(pad "1" smd circle (at %.4f %.4f) (size 0.5 0.5) (layers "F.Cu"))\n' % (sx, sy)
    s += '\t(pad "2" thru_hole circle (at %.4f %.4f) (size 0.7 0.7) (drill 0.35) (layers "*.Cu") (remove_unused_layers no))\n' % (sx, -sy)
    s += ')\n'
    return s


def write_footprints():
    d = os.path.join(LIB, 'lid.pretty')
    os.makedirs(d, exist_ok=True)
    for name, body in (('Electrode_14x14mm', electrode_fp()), ('NearField_Loop_D8mm', loop_fp())):
        with open(os.path.join(d, name + '.kicad_mod'), 'w') as f:
            f.write(body)


if __name__ == '__main__':
    os.makedirs(LIB, exist_ok=True)
    write_symbols()
    write_footprints()
