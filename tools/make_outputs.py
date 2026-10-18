#!/usr/bin/env python3
"""Produce fabrication outputs + renders for the detector board.

hardware/detector/fab/
    gerbers/            Gerber X2 + Excellon drill (zip for upload)
    bom.csv             full BOM (grouped, with MPNs)
    bom_jlc.csv         JLCPCB assembly BOM (Comment, Designator, Footprint, LCSC)
    cpl_jlc.csv         JLCPCB pick-and-place (top side only; electrodes/loop are copper)
    schematic.pdf
docs/img/               3D renders + electrode map
"""
import csv
import io
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRJ = os.path.join(ROOT, 'hardware', 'detector')
NAME = 'implant_detector'
PCB = os.path.join(PRJ, NAME + '.kicad_pcb')
SCH = os.path.join(PRJ, NAME + '.kicad_sch')
FAB = os.path.join(PRJ, 'fab')
IMG = os.path.join(ROOT, 'docs', 'img')

ENV = dict(os.environ)
if 'LID_KICAD_CFG' in os.environ:
    ENV['XDG_CONFIG_HOME'] = os.environ['LID_KICAD_CFG']


def cli(*args):
    r = subprocess.run(['kicad-cli'] + list(args), env=ENV, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit('kicad-cli failed: %s' % ' '.join(args))
    return r.stdout


def gerbers():
    g = os.path.join(FAB, 'gerbers')
    shutil.rmtree(g, ignore_errors=True)
    os.makedirs(g)
    layers = 'F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts'
    cli('pcb', 'export', 'gerbers', '-l', layers, '--subtract-soldermask', '--use-drill-file-origin',
        '-o', g + '/', PCB)
    cli('pcb', 'export', 'drill', '--format', 'excellon', '--excellon-separate-th', '--generate-map',
        '--map-format', 'gerberx2', '-o', g + '/', PCB)
    z = os.path.join(FAB, NAME + '_gerbers.zip')
    with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(g)):
            zf.write(os.path.join(g, f), f)


def bom():
    fields = 'Reference,Value,Footprint,MPN,Manufacturer,LCSC,${QUANTITY},${DNP}'
    out = cli('sch', 'export', 'bom', '--fields', fields,
              '--labels', 'Designator,Value,Footprint,MPN,Manufacturer,LCSC,Qty,DNP',
              '--group-by', 'Value,Footprint,MPN', '--sort-field', 'Reference', '--exclude-dnp',
              '-o', os.path.join(FAB, 'bom.csv'), SCH)
    rows = list(csv.DictReader(open(os.path.join(FAB, 'bom.csv'))))
    with open(os.path.join(FAB, 'bom_jlc.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Comment', 'Designator', 'Footprint', 'LCSC Part #'])
        for r in rows:
            comment = r['MPN'] or r['Value']
            w.writerow([comment, r['Designator'], r['Footprint'].split(':')[-1], r['LCSC']])


def cpl():
    tmp = os.path.join(FAB, 'pos.csv')
    cli('pcb', 'export', 'pos', '--format', 'csv', '--units', 'mm', '--side', 'both',
        '--exclude-dnp', '--use-drill-file-origin', '-o', tmp, PCB)
    rows = list(csv.DictReader(open(tmp)))
    os.unlink(tmp)
    with open(os.path.join(FAB, 'cpl_jlc.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation'])
        for r in rows:
            w.writerow([r['Ref'], r['PosX'] + 'mm', r['PosY'] + 'mm',
                        'Top' if r['Side'] == 'top' else 'Bottom', r['Rot']])


def schematic_pdf():
    cli('sch', 'export', 'pdf', '-o', os.path.join(FAB, 'schematic.pdf'), SCH)


def renders():
    os.makedirs(IMG, exist_ok=True)
    common = ['--quality', 'high', '--background', 'opaque', '-w', '1800', '-h', '900']
    cli('pcb', 'render', *common, '--side', 'top', '-o', os.path.join(IMG, 'render_top.png'), PCB)
    cli('pcb', 'render', *common, '--side', 'bottom', '-o', os.path.join(IMG, 'render_bottom.png'), PCB)
    cli('pcb', 'render', '--quality', 'high', '--background', 'opaque', '-w', '1800', '-h', '1100',
        '--perspective', '--rotate', '-50,0,-25', '--zoom', '0.85', '-o', os.path.join(IMG, 'render_iso.png'), PCB)
    cli('pcb', 'render', '--quality', 'high', '--background', 'opaque', '-w', '1800', '-h', '1100',
        '--perspective', '--rotate', '-130,0,-25', '--zoom', '0.85', '-o', os.path.join(IMG, 'render_iso_bottom.png'), PCB)
    # 2D electrode map: bottom copper + bottom silk, seen from the bottom (mirrored)
    svg = os.path.join(IMG, 'electrodes.svg')
    cli('pcb', 'export', 'svg', '--mode-single', '-l', 'B.Cu,B.SilkS,Edge.Cuts', '--mirror', '--fit-page-to-board',
        '--exclude-drawing-sheet', '-o', svg, PCB)
    subprocess.run(['rsvg-convert', '-w', '1800', '-b', 'white', svg, '-o', os.path.join(IMG, 'electrodes.png')], check=True)
    os.unlink(svg)


if __name__ == '__main__':
    os.makedirs(FAB, exist_ok=True)
    what = sys.argv[1:] or ['gerbers', 'bom', 'cpl', 'pdf', 'renders']
    for w in what:
        {'gerbers': gerbers, 'bom': bom, 'cpl': cpl, 'pdf': schematic_pdf, 'renders': renders}[w]()
        print('done', w)
