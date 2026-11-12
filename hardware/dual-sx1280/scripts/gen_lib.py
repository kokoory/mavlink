"""Generate the project-local KiCad 7 symbol + footprint libraries.

  kicad/dual_sx1280.kicad_sym          LoRa1280 module, AP2112K-3.3 (flattened)
  kicad/dual_sx1280.pretty/*.kicad_mod NiceRF_LoRa1280_16x16mm

LoRa1280 pinout (NiceRF LoRa128X datasheet Rev 2.2, cross-checked with the
TinyGS NiceRF-1280 mikroBUS board):
   1 DIO2   2 DIO3   3 VCC   4 GND   5 MISO   6 MOSI   7 SCK   8 NSS
   9 ANT   10 GND   11 GND  12 GND  13 NRESET 14 GND (TCXOEN on LoRa1280-T)
  15 BUSY  16 DIO1
Module: 16 x 16 x 2.1 mm, 2.0 mm pitch castellated pads (RFM9xW-style).
"""
import os, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "kicad")

F = '(effects (font (size 1.27 1.27)))'
FH = '(effects (font (size 1.27 1.27)) hide)'


def pin(ptype, x, y, rot, name, num, length=2.54, hidden=False):
    h = " hide" if hidden else ""
    return (f'      (pin {ptype} line (at {x} {y} {rot}) (length {length}){h}\n'
            f'        (name "{name}" {F})\n        (number "{num}" {F}))\n')


def lora1280():
    left = [("1", "DIO2", "bidirectional"), ("2", "DIO3", "bidirectional"),
            ("3", "VCC", "power_in"), ("4", "GND", "power_in"),
            ("5", "MISO", "output"), ("6", "MOSI", "input"),
            ("7", "SCK", "input"), ("8", "NSS", "input")]
    right = [("16", "DIO1", "output"), ("15", "BUSY", "output"),
             ("14", "GND/TCXOEN", "passive"), ("13", "NRESET", "input"),
             ("12", "GND", "power_in"), ("11", "GND", "power_in"),
             ("10", "GND", "power_in"), ("9", "ANT", "bidirectional")]
    pins = ""
    for i, (n, name, t) in enumerate(left):
        pins += pin(t, -12.7, 8.89 - 2.54 * i, 0, name, n)
    for i, (n, name, t) in enumerate(right):
        pins += pin(t, 12.7, 8.89 - 2.54 * i, 180, name, n)
    return f'''  (symbol "LoRa1280" (in_bom yes) (on_board yes)
    (property "Reference" "U" (at -10.16 12.7 0) (effects (font (size 1.27 1.27)) (justify left)))
    (property "Value" "LoRa1280" (at -10.16 -11.43 0) (effects (font (size 1.27 1.27)) (justify left)))
    (property "Footprint" "dual_sx1280:NiceRF_LoRa1280_16x16mm" (at 0 0 0) {FH})
    (property "Datasheet" "https://www.nicerf.com/lora-module/lora-module-lora128x.html" (at 0 0 0) {FH})
    (property "ki_keywords" "SX1280 LoRa 2.4GHz ranging NiceRF" (at 0 0 0) {FH})
    (property "ki_description" "NiceRF LoRa1280 2.4 GHz SX1280 LoRa/FLRC/ranging module, 16x16 mm, SPI. Pin 14 = GND (LoRa1280) or TCXOEN (LoRa1280-T)" (at 0 0 0) {FH})
    (symbol "LoRa1280_0_1"
      (rectangle (start -10.16 10.16) (end 10.16 -10.16) (stroke (width 0.254) (type default)) (fill (type background)))
    )
    (symbol "LoRa1280_1_1"
{pins}    )
  )
'''


def ap2112():
    pins = (pin("power_in", -7.62, 2.54, 0, "VIN", "1") +
            pin("input", -7.62, 0, 0, "EN", "3") +
            pin("power_in", 0, -7.62, 90, "GND", "2") +
            pin("power_out", 7.62, 2.54, 180, "VOUT", "5") +
            pin("no_connect", 7.62, 0, 180, "NC", "4"))
    return f'''  (symbol "AP2112K-3.3" (pin_names (offset 0.254)) (in_bom yes) (on_board yes)
    (property "Reference" "U" (at -5.08 6.35 0) (effects (font (size 1.27 1.27)) (justify left)))
    (property "Value" "AP2112K-3.3" (at 0 6.35 0) (effects (font (size 1.27 1.27)) (justify left)))
    (property "Footprint" "Package_TO_SOT_SMD:SOT-23-5" (at 0 0 0) {FH})
    (property "Datasheet" "https://www.diodes.com/assets/Datasheets/AP2112.pdf" (at 0 0 0) {FH})
    (property "ki_description" "600mA LDO, 3.3V fixed, enable, SOT-23-5" (at 0 0 0) {FH})
    (symbol "AP2112K-3.3_0_1"
      (rectangle (start -5.08 5.08) (end 5.08 -5.08) (stroke (width 0.254) (type default)) (fill (type background)))
    )
    (symbol "AP2112K-3.3_1_1"
{pins}    )
  )
'''


def write_symbols():
    with open(os.path.join(OUT, "dual_sx1280.kicad_sym"), "w") as f:
        f.write("(kicad_symbol_lib (version 20220914) (generator gen_lib)\n")
        f.write(lora1280())
        f.write(ap2112())
        f.write(")\n")


def tid():
    return str(uuid.uuid4())


def line(x1, y1, x2, y2, layer, w):
    return (f'  (fp_line (start {x1} {y1}) (end {x2} {y2}) '
            f'(stroke (width {w}) (type solid)) (layer "{layer}") (tstamp {tid()}))\n')


def write_module_fp():
    d = os.path.join(OUT, "dual_sx1280.pretty")
    os.makedirs(d, exist_ok=True)
    s = ('(footprint "NiceRF_LoRa1280_16x16mm" (version 20221018) (generator gen_lib)\n'
         '  (layer "F.Cu")\n'
         '  (descr "NiceRF LoRa1280/LoRa1281/LoRa1280-T SX1280 module, 16x16mm, 16 castellated pads, 2.0mm pitch. '
         'Pad geometry from KiCad HOPERF_RFM9XW_SMD (same outline/pitch).")\n'
         '  (tags "NiceRF LoRa1280 SX1280 2.4GHz")\n'
         '  (attr smd)\n'
         f'  (fp_text reference "REF**" (at 0 -9.3) (layer "F.SilkS") (effects (font (size 0.8 0.8) (thickness 0.12))) (tstamp {tid()}))\n'
         f'  (fp_text value "NiceRF_LoRa1280_16x16mm" (at 0 9.5) (layer "F.Fab") (effects (font (size 0.8 0.8) (thickness 0.12))) (tstamp {tid()}))\n'
         f'  (fp_text user "${{REFERENCE}}" (at 0 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))) (tstamp {tid()}))\n'
         f'  (fp_text user "ANT" (at 4.6 7) (layer "F.SilkS") (effects (font (size 0.7 0.7) (thickness 0.12))) (tstamp {tid()}))\n')
    # silkscreen corners (outside pads), pin-1 dot
    for (x1, y1, x2, y2) in [(-8.1, -8.1, 8.1, -8.1), (-8.1, 8.1, 8.1, 8.1),
                             (-8.1, -8.1, -8.1, -7.75), (8.1, -8.1, 8.1, -7.75),
                             (-8.1, 8.1, -8.1, 7.75), (8.1, 8.1, 8.1, 7.75)]:
        s += line(x1, y1, x2, y2, "F.SilkS", 0.12)
    s += (f'  (fp_circle (center -9.6 -7) (end -9.4 -7) (stroke (width 0.12) (type solid)) '
          f'(fill solid) (layer "F.SilkS") (tstamp {tid()}))\n')
    # fab outline
    for (x1, y1, x2, y2) in [(-7, -8, 8, -8), (8, -8, 8, 8), (8, 8, -8, 8), (-8, 8, -8, -7), (-8, -7, -7, -8)]:
        s += line(x1, y1, x2, y2, "F.Fab", 0.1)
    # courtyard
    for (x1, y1, x2, y2) in [(-9.25, -8.25, 9.25, -8.25), (9.25, -8.25, 9.25, 8.25),
                             (9.25, 8.25, -9.25, 8.25), (-9.25, 8.25, -9.25, -8.25)]:
        s += line(x1, y1, x2, y2, "F.CrtYd", 0.05)
    for i in range(8):
        y = -7 + 2 * i
        s += (f'  (pad "{i + 1}" smd roundrect (at -7.525 {y}) (size 2.95 1.27) '
              f'(layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.25) (tstamp {tid()}))\n')
    for i in range(8):
        y = 7 - 2 * i
        s += (f'  (pad "{i + 9}" smd roundrect (at 7.525 {y}) (size 2.95 1.27) '
              f'(layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.25) (tstamp {tid()}))\n')
    s += ('  (model "${KICAD7_3DMODEL_DIR}/RF_Module.3dshapes/HOPERF_RFM9XW_SMD.wrl"\n'
          '    (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))\n)\n')
    with open(os.path.join(d, "NiceRF_LoRa1280_16x16mm.kicad_mod"), "w") as f:
        f.write(s)


def write_lib_tables():
    with open(os.path.join(OUT, "sym-lib-table"), "w") as f:
        f.write('(sym_lib_table\n  (lib (name "dual_sx1280")(type "KiCad")(uri "${KIPRJMOD}/dual_sx1280.kicad_sym")(options "")(descr "Project symbols"))\n)\n')
    with open(os.path.join(OUT, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table\n  (lib (name "dual_sx1280")(type "KiCad")(uri "${KIPRJMOD}/dual_sx1280.pretty")(options "")(descr "Project footprints"))\n)\n')


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    write_symbols()
    write_module_fp()
    write_lib_tables()
    print("libraries written to", os.path.abspath(OUT))
