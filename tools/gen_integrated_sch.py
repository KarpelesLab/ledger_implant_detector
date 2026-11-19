#!/usr/bin/env python3
"""Generate hardware/integrated/integrated.kicad_sch: the rev 0.3 integrated TEM cell detector.

See docs/rev02_integrated.md. "Room for hacks" parts are marked DNP or are 0 ohm links.
"""
import json
import os

from schgen import Schematic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRJ = os.path.join(ROOT, 'hardware', 'integrated')
NAME = 'integrated'

R0603 = 'Resistor_SMD:R_0603_1608Metric'
C0603 = 'Capacitor_SMD:C_0603_1608Metric'
C0805 = 'Capacitor_SMD:C_0805_2012Metric'
L0603 = 'Inductor_SMD:L_0603_1608Metric'
SMA = 'Connector_Coaxial:SMA_Samtec_SMA-J-P-H-ST-EM1_EdgeMount'
TP = 'TestPoint:TestPoint_Pad_D1.5mm'


def gen():
    sch = Schematic(NAME, 'Ledger Implant Detector: integrated TEM cell (CONCEPT)', '0.3',
                    {'lid': os.path.join(ROOT, 'hardware', 'lib', 'lid.kicad_sym')}, paper='A1',
                    comments=('CONCEPT DESIGN - NOT YET BUILT OR VALIDATED',
                              'https://github.com/KarpelesLab/ledger_implant_detector'))

    column = {}

    def slot(x, y):
        # small parts stack in columns; never closer than the symbol height
        y = max(y, column.get(x, 0))
        column[x] = y + 11
        return y

    def R(ref, val, x, y, a, b, **kw):
        sch.add(ref, 'Device:R', val, x, slot(x, y), {'1': a, '2': b}, rot=90, footprint=R0603, **kw)

    def C(ref, val, x, y, a, b, fp=C0603, **kw):
        sch.add(ref, 'Device:C', val, x, slot(x, y), {'1': a, '2': b}, rot=90, footprint=fp, **kw)

    def dnp(ref, kind, x, y, a, b):
        (R if kind == 'R' else C)(ref, 'DNP', x, y, a, b, in_bom=False)

    # ---- cell ports (SMA is not fitted in normal use: fit it and remove the link to use the cell with a VNA) ----
    sch.text('Cell ports. J1/J2 not fitted; fit J + remove R1/R20 to drive the cell from a VNA', 20, 15, 2)
    sch.add('J1', 'Connector:Conn_Coaxial', 'DNP', 30, 35, {'1': 'CELL_P1', '2': 'GND'}, footprint=SMA, in_bom=False)
    sch.add('J2', 'Connector:Conn_Coaxial', 'DNP', 55, 35, {'1': 'CELL_P2', '2': 'GND'}, footprint=SMA, in_bom=False)

    # ---- source ----
    sch.text('Source output: link, optional low-pass (not fitted), 10 dB pad, DC block, ADF4351 output network', 20, 55, 2)
    R('R1', '0', 30, 65, 'CELL_P1', 'TX_A')
    dnp('C1', 'C', 30, 72, 'TX_A', 'GND')
    R('L1', '0', 30, 79, 'TX_A', 'TX_B')
    dnp('C2', 'C', 30, 86, 'TX_B', 'GND')
    R('R2', '100', 30, 93, 'TX_B', 'GND')
    R('R3', '68', 30, 100, 'TX_B', 'TX_C')
    R('R4', '100', 30, 107, 'TX_C', 'GND')
    C('C3', '100p', 30, 114, 'TX_C', 'RFA_P', fields={'Dielectric': 'C0G'})
    R('R5', '49.9', 60, 65, 'RFA_P', '+3V3A')
    R('R6', '49.9', 60, 72, 'RFA_N', '+3V3A')
    C('C4', '100p', 60, 79, 'RFA_N', 'RFA_T', fields={'Dielectric': 'C0G'})
    R('R7', '49.9', 60, 86, 'RFA_T', 'GND')
    R('R8', '49.9', 60, 93, 'RFB_P', '+3V3A')
    R('R9', '49.9', 60, 100, 'RFB_N', '+3V3A')
    C('C5', '100p', 60, 107, 'RFB_P', 'RFB_OUT', fields={'Dielectric': 'C0G'})
    C('C6', '100p', 60, 114, 'RFB_N', 'RFB_T', fields={'Dielectric': 'C0G'})
    R('R10', '49.9', 60, 121, 'RFB_T', 'GND')
    sch.add('J5', 'Connector:Conn_Coaxial', 'U.FL', 95, 100, {'1': 'RFB_OUT', '2': 'GND'},
            footprint='Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical', fields={'MPN': 'U.FL-R-SMT-1(80)', 'LCSC': 'C88374'})

    # ---- synthesizer ----
    sch.text('ADF4351 synthesizer. Phase noise does not matter here: only amplitude is measured', 110, 15, 2)
    sch.add('U2', 'lid:ADF4351', 'ADF4351', 165, 60, {
        '1': 'SYN_CLK', '2': 'SYN_DATA', '3': 'SYN_LE', '4': 'SYN_CE', '26': 'SYN_PDBRF', '25': 'SYN_LD', '30': 'SYN_MUX',
        '29': 'SYN_REF', '5': None, '7': 'SYN_CP', '20': 'SYN_VT', '22': 'SYN_RSET', '19': 'SYN_TEMP', '23': 'SYN_VCOM',
        '24': 'SYN_VREF', '6': 'VP', '10': '+3V3A', '16': 'VVCO', '17': 'VVCO', '28': '+3V3A', '32': '+3V3A',
        '12': 'RFA_P', '13': 'RFA_N', '14': 'RFB_P', '15': 'RFB_N', '8': 'GND', '9': 'GND', '11': 'GND', '18': 'GND',
        '21': 'GND', '27': 'GND', '31': 'GND', '33': 'GND'}, fields={'MPN': 'ADF4351BCPZ', 'Manufacturer': 'Analog Devices'})
    R('R11', '5.1k', 120, 110, 'SYN_RSET', 'GND')
    # third-order passive loop filter: ~63 kHz, 50 deg at Kv 40 MHz/V, Icp 2.5 mA, N 124 (see docs/rev02_integrated.md)
    C('C7', '1.5n', 120, 117, 'SYN_CP', 'GND', fields={'Dielectric': 'C0G'})
    C('C8', '15n', 120, 124, 'SYN_LF', 'GND', fields={'Dielectric': 'X7R'})
    R('R12', '510', 120, 131, 'SYN_CP', 'SYN_LF')
    R('R13', '330', 120, 138, 'SYN_CP', 'SYN_VT')
    C('C9', '680p', 120, 145, 'SYN_VT', 'GND', fields={'Dielectric': 'C0G'})
    for i, (net, val) in enumerate((('SYN_TEMP', '100n'), ('SYN_VCOM', '100n'), ('SYN_VREF', '100n'))):
        C('C%d' % (10 + i), val, 150, 110 + 7 * i, net, 'GND')
    dnp('C13', 'C', 150, 131, 'SYN_VCOM', 'GND')
    for i, (net, val) in enumerate((('VP', '100n'), ('VVCO', '100n'), ('VVCO', '100p'), ('+3V3A', '100n'), ('+3V3A', '100n'), ('+3V3A', '100p'))):
        C('C%d' % (14 + i), val, 180, 110 + 7 * i, net, 'GND')
    sch.add('FB2', 'Device:FerriteBead', '600R', 205, 110, {'1': '+3V3A', '2': 'VVCO'}, rot=90, footprint=L0603)
    sch.add('FB3', 'Device:FerriteBead', '600R', 205, 125, {'1': '+3V3A', '2': 'VP'}, rot=90, footprint=L0603)
    sch.add('Y1', 'Oscillator:ASE-xxxMHz', '25 MHz', 225, 40, {'1': '+3V3A', '2': 'GND', '3': 'REF_OUT', '4': '+3V3A'},
            footprint='Oscillator:Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm', fields={'MPN': 'OT322525MJBA4SL', 'Manufacturer': 'YXC', 'LCSC': 'C669088'})
    R('R14', '33', 225, 65, 'REF_OUT', 'SYN_REF')
    C('C20', '100n', 225, 76, '+3V3A', 'GND')

    # ---- detector ----
    sch.text('Receive: link, 6 dB pad, AD8318 log detector in measurement mode, ADS1115', 240, 15, 2)
    R('R20', '0', 275, 30, 'CELL_P2', 'RX_A')
    R('R21', '150', 275, 37, 'RX_A', 'GND')
    R('R22', '39', 275, 44, 'RX_A', 'RX_B')
    R('R23', '150', 275, 51, 'RX_B', 'GND')
    R('R24', '49.9', 275, 58, 'RX_B', 'GND')
    C('C21', '1n', 275, 65, 'RX_B', 'DET_HI', fields={'Dielectric': 'C0G'})
    C('C22', '1n', 275, 72, 'DET_LO', 'GND', fields={'Dielectric': 'C0G'})
    sch.add('U3', 'lid:AD8318', 'AD8318', 330, 45, {
        '14': 'DET_HI', '15': 'DET_LO', '16': '+5VA', '10': 'DET_TADJ', '5': 'DET_CLPF', '13': 'DET_TEMP',
        '3': '+5VA', '4': '+5VA', '9': '+5VA', '6': 'DET_OUT', '7': 'DET_SET', '8': 'GND',
        '1': 'GND', '2': 'GND', '11': 'GND', '12': 'GND', '17': 'GND'},
        fields={'MPN': 'AD8318ACPZ-REEL7', 'Manufacturer': 'Analog Devices'})
    R('R25', '499', 275, 79, 'DET_TADJ', 'GND')
    C('C23', '220p', 275, 86, 'DET_CLPF', 'GND', fields={'Dielectric': 'C0G'})
    R('R26', '0', 275, 93, 'DET_OUT', 'DET_SET')
    for i, (val) in enumerate(('100n', '100p', '100n', '100p')):
        C('C%d' % (24 + i), val, 305, 85 + 7 * i, '+5VA', 'GND')
    # FB1 where VBUS enters the detector frame, its bulk cap C35 at U3: +5VA is a plane on In1 under the detector block (rev 0.3)
    sch.add('FB1', 'Device:FerriteBead', '600R', 330, 85, {'1': 'VBUS', '2': '+5VA'}, rot=90, footprint=L0603)
    C('C35', '10u', 305, 113, '+5VA', 'GND', fp=C0805, fields={'Voltage': '10V', 'Dielectric': 'X5R'})
    sch.add('U4', 'Analog_ADC:ADS1115IDGS', 'ADS1115', 345, 130, {
        '1': 'GND', '2': 'ADC_RDY', '3': 'GND', '4': 'ADC_0', '5': 'ADC_1', '6': 'ADC_2', '7': 'ADC_3', '8': 'ADC_VDD',
        '9': 'I2C_SDA', '10': 'I2C_SCL'}, footprint='Package_SO:TSSOP-10_3x3mm_P0.5mm',
        fields={'MPN': 'ADS1115IDGSR', 'Manufacturer': 'Texas Instruments'})
    R('R27', '1k', 275, 150, 'DET_OUT', 'ADC_0')
    C('C28', '10n', 275, 122, 'ADC_0', 'GND')
    R('R28', '1k', 275, 129, 'DET_TEMP', 'ADC_1')
    C('C29', '10n', 275, 136, 'ADC_1', 'GND')
    R('R29', '100k', 275, 143, '+5VA', 'ADC_2')
    R('R30', '100k', 275, 150, 'ADC_2', 'GND')
    C('C30', '100n', 275, 157, 'ADC_2', 'GND')
    sch.add('FB4', 'Device:FerriteBead', '600R', 310, 150, {'1': '+3V3', '2': 'ADC_VDD'}, rot=90, footprint=L0603)
    C('C31', '100n', 310, 165, 'ADC_VDD', 'GND')

    # ---- MCU ----
    sch.text('MCU: Raspberry Pi Pico 2 module. Micro-USB and BOOTSEL are on the module', 20, 190, 2)
    sch.add('U1', 'MCU_Module:RaspberryPi_Pico', 'Pico 2', 70, 245, {
        '1': 'I2C_SDA', '2': 'I2C_SCL', '3': 'GND', '4': 'SYN_CLK', '5': 'SYN_DATA', '6': 'ADC_RDY', '7': 'SYN_LE', '8': 'GND',
        '9': 'SYN_CE', '10': 'SYN_PDBRF', '11': 'SYN_LD', '12': 'SYN_MUX', '13': 'GND', '14': 'LCD_SCK', '15': 'LCD_SDA',
        '16': 'LCD_BL', '17': 'LCD_CS', '18': 'GND', '19': 'LCD_DC', '20': 'LCD_RST', '21': 'LED_G', '22': 'LED_R', '23': 'GND',
        '24': 'BTN', '25': 'GP19', '26': 'GP20', '27': 'GP21', '28': 'GND', '29': 'GP22', '30': 'RUN', '31': 'GP26',
        '32': 'GP27', '33': 'GND', '34': 'FAST_ADC', '35': None, '36': '+3V3', '37': None, '38': 'GND', '39': None, '40': 'VBUS'},
        footprint='Module:RaspberryPi_Pico_Common_THT', fields={'MPN': 'SC1631', 'Manufacturer': 'Raspberry Pi'})
    dnp('R31', 'R', 130, 205, 'DET_OUT', 'FAST_ADC')
    R('R32', '4.7k', 130, 212, 'I2C_SDA', '+3V3')
    R('R33', '4.7k', 130, 219, 'I2C_SCL', '+3V3')
    R('R34', '10k', 130, 226, 'ADC_RDY', '+3V3')
    # lock detect: MUXOUT and LD are both brought to the MCU

    # ---- analog supply ----
    sch.text('Analog 3.3 V, separate from the module supply', 165, 225, 2)
    sch.add('U5', 'Regulator_Linear:AP2112K-3.3', 'AP2112K-3.3', 190, 245, {'1': 'VBUS', '3': 'VBUS', '2': 'GND', '4': None, '5': '+3V3A'},
            fields={'MPN': 'AP2112K-3.3TRG1', 'Manufacturer': 'Diodes Inc'})
    C('C32', '4.7u', 165, 270, 'VBUS', 'GND', fp=C0805, fields={'Voltage': '10V', 'Dielectric': 'X5R'})
    C('C33', '10u', 215, 270, '+3V3A', 'GND', fp=C0805, fields={'Voltage': '10V', 'Dielectric': 'X5R'})
    C('C34', '100n', 215, 281, '+3V3', 'GND')
    sch.pwr_flag('+5VA', 348, 85)
    sch.pwr_flag('VP', 222, 125)
    sch.pwr_flag('VVCO', 222, 110)
    sch.pwr_flag('ADC_VDD', 318, 150)

    # ---- user interface: top side, beyond the cell ----
    sch.text('User interface (top side). Everything else is on the underside', 210, 205, 2)
    sch.add('J3', 'Connector_Generic:Conn_01x08', 'LCD 2.0in ST7789', 240, 245, {
        '1': 'GND', '2': '+3V3', '3': 'LCD_SCK', '4': 'LCD_SDA', '5': 'LCD_RST', '6': 'LCD_DC', '7': 'LCD_CS', '8': 'LCD_BL_R'},
        footprint='Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical')
    R('R35', '47', 262, 245, 'LCD_BL', 'LCD_BL_R')
    sch.add('D1', 'Device:LED', 'green', 295, 225, {'1': 'GND', '2': 'LED_G_A'}, rot=180, footprint='LED_THT:LED_D5.0mm')
    sch.add('D2', 'Device:LED', 'red', 295, 240, {'1': 'GND', '2': 'LED_R_A'}, rot=180, footprint='LED_THT:LED_D5.0mm')
    R('R36', '330', 320, 225, 'LED_G', 'LED_G_A')
    R('R37', '330', 320, 240, 'LED_R', 'LED_R_A')
    sch.add('SW1', 'Switch:SW_Push', 'Start', 295, 255, {'1': 'BTN', '2': 'GND'}, footprint='Button_Switch_THT:SW_PUSH_6mm')

    # ---- hacks ----
    sch.text('Room for hacks: spare GPIO, spare ADC input, test points', 340, 205, 2)
    sch.add('J4', 'Connector_Generic:Conn_01x12', 'DNP', 350, 235, {
        '1': 'GND', '2': '+3V3', '3': 'VBUS', '4': 'GP19', '5': 'GP20', '6': 'GP21', '7': 'GP22', '8': 'GP26', '9': 'GP27',
        '10': 'ADC_3', '11': 'RUN', '12': 'GND'},
        footprint='Connector_PinHeader_2.54mm:PinHeader_1x12_P2.54mm_Vertical', in_bom=False)
    for i, net in enumerate(('DET_OUT', 'SYN_VT', 'SYN_MUX', '+3V3A', '+5VA', 'ADC_3')):
        sch.add('TP%d' % (i + 1), 'Connector:TestPoint', net, 345 + 20 * (i % 3), 265 + 20 * (i // 3), {'1': net}, footprint=TP, in_bom=False)

    bad = sch.check_overlaps()
    if bad:
        print('WARNING overlapping blocks:', bad)
    os.makedirs(PRJ, exist_ok=True)
    sch.save(os.path.join(PRJ, NAME + '.kicad_sch'))


def project_files():
    pro = os.path.join(PRJ, NAME + '.kicad_pro')
    if not os.path.exists(pro):
        # the stock Pico and ITR8307 symbols call their ground pins power/emitter outputs, which ERC reports as shorts
        with open(pro, 'w') as f:
            json.dump({'meta': {'filename': NAME + '.kicad_pro', 'version': 3},
                       'erc': {'rule_severities': {'pin_to_pin': 'warning'}},
                       'sheets': [], 'boards': [], 'text_variables': {}}, f, indent=2)
    with open(os.path.join(PRJ, 'sym-lib-table'), 'w') as f:
        f.write('(sym_lib_table\n  (version 7)\n  (lib (name "lid")(type "KiCad")(uri "${KIPRJMOD}/../lib/lid.kicad_sym")(options "")(descr "Ledger implant detector project library"))\n)\n')
    with open(os.path.join(PRJ, 'fp-lib-table'), 'w') as f:
        f.write('(fp_lib_table\n  (version 7)\n  (lib (name "lid")(type "KiCad")(uri "${KIPRJMOD}/../lib/lid.pretty")(options "")(descr "Ledger implant detector project footprints"))\n)\n')


if __name__ == '__main__':
    os.makedirs(PRJ, exist_ok=True)
    gen()
    project_files()
