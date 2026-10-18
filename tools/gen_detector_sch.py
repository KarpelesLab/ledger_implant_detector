#!/usr/bin/env python3
"""Generate hardware/detector/implant_detector.kicad_sch."""
import json
import os

from schgen import Schematic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRJ = os.path.join(ROOT, 'hardware', 'detector')
NAME = 'implant_detector'

R0603 = 'Resistor_SMD:R_0603_1608Metric'
C0603 = 'Capacitor_SMD:C_0603_1608Metric'
C0805 = 'Capacitor_SMD:C_0805_2012Metric'

# electrode index (1..8) -> (converter ref, channel). Row 0 = E1..E4, row 1 = E5..E8,
# columns 1-2 on U1, columns 3-4 on U2. Each converter sits in the middle of its 2x2
# cluster, rotated 180 deg (IN0/IN1 face west, IN2/IN3 face south):
# CH0 = NW, CH1 = SW, CH2 = SE, CH3 = NE electrode.
ELECTRODES = {1: ('U1', 0), 5: ('U1', 1), 6: ('U1', 2), 2: ('U1', 3),
              3: ('U2', 0), 7: ('U2', 1), 8: ('U2', 2), 4: ('U2', 3)}


def gen():
    sch = Schematic(NAME, 'Ledger Implant Detector (CONCEPT)', '0.1',
                    {'lid': os.path.join(ROOT, 'hardware', 'lib', 'lid.kicad_sym')},
                    comments=('CONCEPT DESIGN - NOT YET BUILT OR VALIDATED',
                              'https://github.com/KarpelesLab/ledger_implant_detector'))

    def R(ref, val, x, y, a, b, **kw):
        sch.add(ref, 'Device:R', val, x, y, {'1': a, '2': b}, rot=90, footprint=R0603, **kw)

    def C(ref, val, x, y, a, b, fp=C0603, **kw):
        sch.add(ref, 'Device:C', val, x, y, {'1': a, '2': b}, rot=90, footprint=fp, **kw)

    # ---------------- USB / power ----------------
    sch.text('USB-C (sink, USB 2.0 FS) + ESD + 3.3 V LDO', 20, 20, 2)
    sch.add('J1', 'Connector:USB_C_Receptacle_USB2.0_16P', 'USB-C', 35, 60, {
        'A1': 'GND', 'A12': 'GND', 'B1': 'GND', 'B12': 'GND', 'SH': 'GND',
        'A4': 'VBUS', 'A9': 'VBUS', 'B4': 'VBUS', 'B9': 'VBUS',
        'A5': 'CC1', 'B5': 'CC2', 'A6': 'USB_DP', 'B6': 'USB_DP', 'A7': 'USB_DM', 'B7': 'USB_DM',
        'A8': None, 'B8': None},
        footprint='Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12',
        fields={'MPN': 'TYPE-C-31-M-12', 'Manufacturer': 'Korean Hroparts Elec', 'LCSC': 'C165948'})
    R('R1', '5.1k', 35, 100, 'CC1', 'GND')
    R('R2', '5.1k', 35, 110, 'CC2', 'GND')
    sch.add('U5', 'Power_Protection:USBLC6-2SC6', 'USBLC6-2SC6', 95, 40, {
        '1': 'USB_DP', '6': 'USB_DP', '3': 'USB_DM', '4': 'USB_DM', '2': 'GND', '5': 'VBUS'},
        fields={'MPN': 'USBLC6-2SC6', 'Manufacturer': 'STMicroelectronics'})
    sch.add('U4', 'Regulator_Linear:AP2112K-3.3', 'AP2112K-3.3', 95, 72, {
        '1': 'VBUS', '3': 'VBUS', '2': 'GND', '4': None, '5': '+3V3'},
        fields={'MPN': 'AP2112K-3.3TRG1', 'Manufacturer': 'Diodes Inc'})
    C('C9', '4.7u', 80, 100, 'VBUS', 'GND', fields={'Voltage': '10V', 'Dielectric': 'X5R'})
    C('C10', '4.7u', 110, 100, '+3V3', 'GND', fields={'Voltage': '10V', 'Dielectric': 'X5R'})
    sch.pwr_flag('VBUS', 115, 28)
    sch.pwr_flag('GND', 125, 28)

    # ---------------- MCU ----------------
    sch.text('MCU: STM32F042F6P6 (crystal-less USB, ROM DFU via BOOT0)', 20, 135, 2)
    sch.add('U3', 'MCU_ST_STM32F0:STM32F042F6Px', 'STM32F042F6P6', 75, 190, {
        '1': 'BOOT0', '2': 'I2C_SDA', '3': 'I2C_SCL', '4': 'NRST', '5': '+3V3',
        '6': 'FDC1_INT', '7': 'FDC2_INT', '8': 'FDC_SD', '9': 'LED_G', '10': 'LED_R',
        '11': 'BTN', '12': 'BUZZ', '13': None, '14': None, '15': 'GND', '16': '+3V3',
        '17': 'USB_DM', '18': 'USB_DP', '19': 'SWDIO', '20': 'SWCLK'},
        fields={'MPN': 'STM32F042F6P6', 'Manufacturer': 'STMicroelectronics'})
    C('C11', '100n', 25, 160, '+3V3', 'GND')
    C('C12', '100n', 25, 170, '+3V3', 'GND')
    C('C13', '4.7u', 25, 180, '+3V3', 'GND', fields={'Voltage': '10V', 'Dielectric': 'X5R'})
    C('C14', '100n', 25, 225, 'NRST', 'GND')
    R('R3', '10k', 25, 235, 'BOOT0', 'GND')
    sch.add('SW2', 'Switch:SW_Push', 'BOOT', 25, 247, {'1': '+3V3', '2': 'BOOT0'},
            footprint='Button_Switch_SMD:SW_SPST_PTS810', fields={'MPN': 'PTS810 SJM 250 SMTR LFS', 'Manufacturer': 'C&K'})
    sch.add('SW1', 'Switch:SW_Push', 'CAL', 25, 259, {'1': 'BTN', '2': 'GND'},
            footprint='Button_Switch_SMD:SW_SPST_PTS810', fields={'MPN': 'PTS810 SJM 250 SMTR LFS', 'Manufacturer': 'C&K'})

    sch.text('User interface / connectors', 135, 20, 2)
    R('R4', '1k', 140, 32, 'LED_G', 'LED_G_A')
    sch.add('D1', 'Device:LED', 'GREEN', 175, 32, {'1': 'GND', '2': 'LED_G_A'}, rot=180,
            footprint='LED_SMD:LED_0603_1608Metric', fields={'MPN': '19-217/GHC-YR1S2/3T', 'Manufacturer': 'Everlight'})
    R('R5', '1k', 140, 44, 'LED_R', 'LED_R_A')
    sch.add('D2', 'Device:LED', 'RED', 175, 44, {'1': 'GND', '2': 'LED_R_A'}, rot=180,
            footprint='LED_SMD:LED_0603_1608Metric', fields={'MPN': '19-217/R6C-AL1M2VY/3T', 'Manufacturer': 'Everlight'})
    R('R6', '100', 140, 58, 'BUZZ', 'BUZZ_P')
    sch.add('BZ1', 'Device:Buzzer', 'PKLCS1212E4001', 175, 60, {'1': 'BUZZ_P', '2': 'GND'},
            footprint='Buzzer_Beeper:Buzzer_Murata_PKLCS1212E', fields={'MPN': 'PKLCS1212E4001-R1', 'Manufacturer': 'Murata'})
    sch.add('J2', 'Connector_Generic_MountingPin:Conn_01x04_MountingPin', 'Qwiic', 160, 90, {
        '1': 'GND', '2': '+3V3', '3': 'I2C_SDA', '4': 'I2C_SCL', 'MP': 'GND'},
        footprint='Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal',
        fields={'MPN': 'SM04B-SRSS-TB(LF)(SN)', 'Manufacturer': 'JST'})
    sch.add('J3', 'Connector_Generic:Conn_02x03_Odd_Even', 'SWD (TC2030)', 160, 125, {
        '1': '+3V3', '2': 'SWDIO', '3': 'NRST', '4': 'SWCLK', '5': 'GND', '6': None},
        footprint='Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical', in_bom=False)

    # ---------------- I2C / control pull-ups ----------------
    sch.text('Bus pull-ups', 135, 150, 2)
    R('R7', '4.7k', 160, 165, '+3V3', 'I2C_SDA')
    R('R8', '4.7k', 160, 175, '+3V3', 'I2C_SCL')
    R('R9', '10k', 160, 185, '+3V3', 'FDC1_INT')
    R('R10', '10k', 160, 195, '+3V3', 'FDC2_INT')
    R('R11', '100k', 160, 205, 'FDC_SD', 'GND')

    # ---------------- clock ----------------
    sch.text('40 MHz reference (shared)', 225, 200, 2)
    sch.add('Y1', 'Oscillator:ASE-xxxMHz', '40MHz', 245, 220, {'1': '+3V3', '2': 'GND', '3': 'CLK40_RAW', '4': '+3V3'},
            fields={'MPN': 'ASE-40.000MHZ-LC-T', 'Manufacturer': 'Abracon'})
    R('R12', '33', 285, 220, 'CLK40_RAW', 'CLK40')
    C('C19', '100n', 245, 245, '+3V3', 'GND')

    # ---------------- FDC2214 x2 + tanks + electrodes ----------------
    sch.text('Capacitance-to-digital: 2x FDC2214, single-ended sensors, 18uH || 33pF tanks', 225, 20, 2)
    for i, (ref, addr, x0) in enumerate((('U1', 'GND', 60), ('U2', '+3V3', 145))):
        chans = sorted((ch, e) for e, (u, ch) in ELECTRODES.items() if u == ref)
        nets = {'1': 'I2C_SCL', '2': 'I2C_SDA', '3': 'CLK40', '4': addr, '5': 'FDC%d_INT' % (i + 1),
                '6': 'FDC_SD', '7': '+3V3', '8': 'GND', '17': 'GND'}
        for ch, e in chans:
            nets[str(9 + 2 * ch)] = 'SNS%d' % e
            nets[str(10 + 2 * ch)] = 'SNS%dB' % e
        sch.add(ref, 'lid:FDC2214', 'FDC2214', 330, x0, nets,
                fields={'MPN': 'FDC2214RGHR', 'Manufacturer': 'Texas Instruments',
                        'I2C': '0x2A' if addr == 'GND' else '0x2B'})
        cd = 15 + 2 * i
        C('C%d' % cd, '100n', 372, x0 - 10, '+3V3', 'GND')
        C('C%d' % (cd + 1), '1u', 372, x0, '+3V3', 'GND')
        for k, (ch, e) in enumerate(chans):
            yy = x0 - 21 + k * 14
            sch.add('L%d' % e, 'Device:L', '18u', 258, yy, {'1': 'SNS%d' % e, '2': 'SNS%dB' % e}, rot=90,
                    footprint='Inductor_SMD:L_1210_3225Metric',
                    fields={'MPN': 'CMH322522-180KL', 'Manufacturer': 'Bourns'})
            C('C%d' % e, '33p', 285, yy, 'SNS%d' % e, 'SNS%dB' % e,
              fields={'Tolerance': '1%', 'Dielectric': 'C0G', 'MPN': 'GRM1885C1H330FA01D', 'Manufacturer': 'Murata'})
            sch.add('E%d' % e, 'lid:Electrode', 'Electrode', 238, yy, {'1': 'SNS%d' % e}, rot=270,
                    in_bom=False, val_pos=(238, yy + 6))

    # ---------------- RF near-field loop ----------------
    sch.text('Near-field H-loop at the tip, for an external VNA (NanoVNA etc.)', 310, 200, 2)
    sch.text('50 ohm microstrip on F.Cu over In1 GND (w = 0.35 mm, JLC04161H-7628)', 310, 206, 1.27)
    sch.add('J4', 'Connector:Conn_Coaxial', 'SMA', 330, 222, {'1': 'RF_PROBE', '2': 'GND'},
            footprint='Connector_Coaxial:SMA_Samtec_SMA-J-P-H-ST-EM1_EdgeMount',
            fields={'MPN': 'SMA-J-P-H-ST-EM1', 'Manufacturer': 'Samtec'})
    sch.add('AE1', 'lid:NearField_Loop', 'Loop D8mm', 365, 222, {'1': 'RF_PROBE', '2': 'GND'}, in_bom=False)

    # ---------------- mechanical ----------------
    for k, h in enumerate(('H1', 'H2')):
        sch.add(h, 'Mechanical:MountingHole', 'M2', 330 + 15 * k, 250, {},
                footprint='MountingHole:MountingHole_2.2mm_M2', in_bom=False)

    sch.text('CONCEPT rev 0.1 - not yet fabricated or validated. See README.md.', 225, 255, 2.5)

    bad = sch.check_overlaps()
    if bad:
        print('WARNING overlapping blocks:', bad)
    os.makedirs(PRJ, exist_ok=True)
    sch.save(os.path.join(PRJ, NAME + '.kicad_sch'))


def project_files():
    pro = os.path.join(PRJ, NAME + '.kicad_pro')
    if not os.path.exists(pro):
        with open(pro, 'w') as f:
            json.dump({'meta': {'filename': NAME + '.kicad_pro', 'version': 3},
                       'sheets': [], 'boards': [], 'text_variables': {}}, f, indent=2)
    with open(os.path.join(PRJ, 'sym-lib-table'), 'w') as f:
        f.write('(sym_lib_table\n  (version 7)\n  (lib (name "lid")(type "KiCad")(uri "${KIPRJMOD}/../lib/lid.kicad_sym")(options "")(descr "Ledger implant detector project library"))\n)\n')
    with open(os.path.join(PRJ, 'fp-lib-table'), 'w') as f:
        f.write('(fp_lib_table\n  (version 7)\n  (lib (name "lid")(type "KiCad")(uri "${KIPRJMOD}/../lib/lid.pretty")(options "")(descr "Ledger implant detector project footprints"))\n)\n')


if __name__ == '__main__':
    gen()
    project_files()
