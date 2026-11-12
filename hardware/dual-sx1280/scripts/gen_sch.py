"""Generate kicad/dual_sx1280.kicad_sch (KiCad 7) from design.py.

Style: every symbol pin gets either a net label, a power symbol, or a
no-connect flag exactly on its connection point, so the schematic netlist is
guaranteed to equal design.NETS (checked afterwards by check_netlist.py).
"""
import os, re, uuid
from design import PARTS, NETS, NO_CONNECT, PROJECT, pin_to_net

HERE = os.path.dirname(os.path.abspath(__file__))
KDIR = os.path.join(HERE, "..", "kicad")
SYSLIB = "/usr/share/kicad/symbols"

FONT = "(effects (font (size 1.27 1.27)))"
G = 1.27


def U():
    return str(uuid.uuid4())


def snap(v):
    return round(round(v / G) * G, 4)


def extract(lib, name):
    path = os.path.join(KDIR, "dual_sx1280.kicad_sym") if lib == "dual_sx1280" \
        else os.path.join(SYSLIB, lib + ".kicad_sym")
    t = open(path).read()
    i = t.index(f'(symbol "{name}"')
    d = 0
    for j in range(i, len(t)):
        if t[j] == "(":
            d += 1
        elif t[j] == ")":
            d -= 1
            if d == 0:
                break
    blk = t[i:j + 1]
    assert "(extends" not in blk, f"{lib}:{name} is a derived symbol"
    return blk


PIN_RE = re.compile(r'\(pin (\w+) (\w+)\s*\(at ([-\d.]+) ([-\d.]+) (\d+)\)\s*\(length [\d.]+\)(?:\s*hide)?'
                    r'\s*\(name "([^"]*)".*?\(number "([^"]*)"', re.S)


def pins_of(blk):
    return {m.group(7): (float(m.group(3)), float(m.group(4)), int(m.group(5)), m.group(6))
            for m in PIN_RE.finditer(blk)}


# outward direction of a pin (screen angle: 0 right, 90 up, 180 left, 270 down)
def outward(rot):
    return (rot + 180) % 360


# ---------------------------------------------------------------------------
# Schematic placement (A3 sheet, mm). Only cosmetic: connectivity is by labels.
# ---------------------------------------------------------------------------
SCH_POS = {
    # radio A block
    "U1": (63.5, 76.2), "J1": (127.0, 60.96), "C9": (114.3, 96.52), "C10": (127.0, 96.52),
    "JP1": (152.4, 76.2),
    # radio B block
    "U2": (63.5, 182.88), "J2": (127.0, 167.64), "C11": (114.3, 203.2), "C12": (127.0, 203.2),
    "JP2": (152.4, 182.88),
    # MCU
    "U3": (215.9, 134.62),
    "C3": (264.16, 88.9), "C4": (276.86, 88.9), "C5": (289.56, 88.9), "C6": (302.26, 88.9), "C7": (314.96, 88.9),
    "C8": (167.64, 96.52), "R1": (167.64, 116.84),
    # power + host
    "J3": (309.88, 48.26), "U4": (350.52, 48.26), "C1": (335.28, 63.5), "C2": (368.3, 63.5),
    # LEDs
    "R2": (284.48, 152.4), "D1": (297.18, 157.48), "R3": (284.48, 177.8), "D2": (297.18, 182.88),
    # test pads
    "TP1": (335.28, 132.08), "TP2": (347.98, 132.08), "TP3": (360.68, 132.08),
    "TP4": (335.28, 152.4), "TP5": (347.98, 152.4), "TP6": (360.68, 152.4),
}

NOTES = [
    ((25.4, 22.86), "Dual SX1280 (2x NiceRF LoRa1280) + STM32F103CBU6  -  ultra-compact 20 x 32 mm, 4-layer, double-sided", 2.0),
    ((25.4, 30.48), "Radio A (top side) on SPI1, radio B (bottom side) on SPI2. Each radio: own NSS/BUSY/DIO1/NRESET, own U.FL.", 1.5),
    ((25.4, 35.56), "JP1/JP2: default 1-2 bridged = pin14 to GND (LoRa1280). Cut 1-2 and bridge 2-3 ONLY for LoRa1280-T (TCXO) modules.", 1.5),
    ((25.4, 40.64), "Host: J3 JST-SH 1.0mm  1=+5V 2=TX(PA9) 3=RX(PA10) 4=GND. USART1 is also the STM32 ROM bootloader (BOOT0 pad TP6).", 1.5),
    ((40.64, 50.8), "RADIO A  (SPI1, top)", 2.0),
    ((40.64, 157.48), "RADIO B  (SPI2, bottom)", 2.0),
    ((198.12, 76.2), "MCU  STM32F103CBU6 (UFQFPN48, pin-compatible with the 48-pin STM32F103C8T6 family)", 1.5),
    ((297.18, 30.48), "POWER: 5V in -> AP2112K-3.3 (600 mA)", 2.0),
    ((327.66, 119.38), "SWD / BOOT pads (bottom)", 1.5),
    ((269.24, 139.7), "STATUS LEDs", 1.5),
]


def main():
    p2n = pin_to_net()
    nc = set(NO_CONNECT)
    root_uuid = U()
    libs = {}
    out = []
    labels, powers, ncs = [], [], []
    glabels, pgroups, wires = [], {}, []
    used_power = set()

    for ref, part in PARTS.items():
        lib, name = part["symbol"].split(":")
        if part["symbol"] not in libs:
            libs[part["symbol"]] = extract(lib, name)
        blk = libs[part["symbol"]]
        pins = pins_of(blk)
        X, Y = SCH_POS[ref]
        X, Y = snap(X), snap(Y)
        props = [("Reference", ref, (X, Y - 2.54), False),
                 ("Value", part["value"], (X, Y + 2.54), False),
                 ("Footprint", part["footprint"], (X, Y), True),
                 ("Datasheet", "", (X, Y), True),
                 ("MPN", part.get("mpn", ""), (X, Y), True),
                 ("LCSC", part.get("lcsc", ""), (X, Y), True)]
        # nicer property placement for big parts
        if ref in ("U1", "U2"):
            props[0] = ("Reference", ref, (X - 10.16, Y - 12.7), False)
            props[1] = ("Value", part["value"], (X - 10.16, Y + 12.7), False)
        if ref == "U3":
            props[0] = ("Reference", ref, (X + 3.81, Y - 43.18), False)
            props[1] = ("Value", part["value"], (X + 3.81, Y + 43.18), False)
        if ref in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "R1", "R2", "R3"):
            props[0] = ("Reference", ref, (X + 2.54, Y - 1.27), False)
            props[1] = ("Value", part["value"], (X + 2.54, Y + 1.27), False)
        s = (f'  (symbol (lib_id "{part["symbol"]}") (at {X} {Y} 0) (unit 1)\n'
             f'    (in_bom yes) (on_board yes) (dnp no)\n    (uuid {U()})\n')
        for k, v, (px, py), hide in props:
            just = " (justify left)" if k in ("Reference", "Value") and ref.startswith(("C", "R")) else ""
            eff = f'(effects (font (size 1.27 1.27)){just}{" hide" if hide else ""})'
            s += f'    (property "{k}" "{v}" (at {px} {py} 0) {eff})\n'
        for num in pins:
            s += f'    (pin "{num}" (uuid {U()}))\n'
        s += (f'    (instances (project "{PROJECT}" (path "/{root_uuid}" (reference "{ref}") (unit 1))))\n'
              f'  )\n')
        out.append(s)

        # connections at every pin
        seen_pts = set()
        for num, (px, py, prot, pname) in pins.items():
            key = f"{ref}.{num}"
            ax, ay = snap(X + px), snap(Y - py)
            if key in nc:
                ncs.append((ax, ay))
                continue
            if key not in p2n:
                raise SystemExit(f"pin {key} ({pname}) is neither on a net nor marked NC")
            net = p2n[key]
            if (ax, ay, net) in seen_pts:      # stacked pins (e.g. STM32 VSS) share one connection
                continue
            seen_pts.add((ax, ay, net))
            od = outward(prot)
            if net in ("GND", "+3V3", "+5V"):
                if od in (0, 180):
                    glabels.append((net, ax, ay, od))   # side pins: global label (same global net)
                else:
                    pgroups.setdefault((ref, net, ay, od), []).append(ax)
            else:
                labels.append((net, ax, ay, od))

    # up/down power pins: chain same-net neighbours of one symbol with wires, one power symbol per group
    for (ref, net, ay, od), xs in pgroups.items():
        xs = sorted(set(xs))
        for a, b in zip(xs, xs[1:]):
            wires.append((a, ay, b, ay))
        used_power.add(net)
        if net == "GND":
            rot = 0 if od == 270 else 180
        else:
            rot = 0 if od == 90 else 180
        powers.append((net, xs[0], ay, rot))

    # every design pin must exist on a symbol
    all_pins = {f"{r}.{n}" for r, p in PARTS.items() for n in pins_of(libs[p["symbol"]])}
    for k in list(p2n) + list(nc):
        assert k in all_pins, f"{k} referenced in design.py but symbol has no such pin"

    # power flags: +5V and GND have no power_out driver
    pwr_flags = []
    for net in ("+5V", "GND"):
        for (n, ax, ay, rot) in powers:
            if n == net:
                pwr_flags.append((ax, ay))
                break
        else:
            raise SystemExit(f"no power symbol for {net} to hang a PWR_FLAG on")

    psyms = {"GND": extract("power", "GND"), "+3V3": extract("power", "+3V3"),
             "+5V": extract("power", "+5V"), "PWR_FLAG": extract("power", "PWR_FLAG")}

    def lib_entry(full, blk):
        lib, name = full.split(":")
        return blk.replace(f'(symbol "{name}"', f'(symbol "{full}"', 1)

    body = []
    body.append(f'(kicad_sch (version 20230121) (generator eeschema)\n\n  (uuid {root_uuid})\n\n  (paper "A3")\n\n')
    body.append('  (title_block\n    (title "Dual SX1280 ultra-compact radio (2x NiceRF LoRa1280)")\n'
                '    (date "2026-11-12")\n    (rev "0.1")\n'
                '    (comment 1 "Generated by hardware/dual-sx1280/scripts/gen_sch.py - edit design.py, not this file")\n'
                '    (comment 2 "Reference: NiceRF LoRa1280 series demo board (SX1280 ranging demo)")\n  )\n\n')
    body.append("  (lib_symbols\n")
    for full, blk in libs.items():
        body.append(lib_entry(full, blk) + "\n")
    for n in used_power | {"PWR_FLAG"}:
        body.append(lib_entry(f"power:{n}", psyms[n]) + "\n")
    body.append("  )\n\n")

    for (ax, ay) in ncs:
        body.append(f"  (no_connect (at {ax} {ay}) (uuid {U()}))\n")
    for (net, ax, ay, ang) in labels:
        just = {0: "left", 180: "right", 90: "left", 270: "right"}[ang]
        body.append(f'  (label "{net}" (at {ax} {ay} {ang}) (fields_autoplaced)\n'
                    f'    (effects (font (size 1.27 1.27)) (justify {just} bottom))\n    (uuid {U()})\n  )\n')
    for (net, ax, ay, ang) in glabels:
        just = "left" if ang == 0 else "right"
        body.append(f'  (global_label "{net}" (shape passive) (at {ax} {ay} {ang}) (fields_autoplaced)\n'
                    f'    (effects (font (size 1.27 1.27)) (justify {just}))\n    (uuid {U()})\n'
                    f'    (property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at {ax} {ay} 0) (effects (font (size 1.27 1.27)) hide))\n  )\n')
    for (x1, y1, x2, y2) in wires:
        body.append(f'  (wire (pts (xy {x1} {y1}) (xy {x2} {y2})) (stroke (width 0) (type default)) (uuid {U()}))\n')
    for (txt_pos, txt, size) in NOTES:
        body.append(f'  (text "{txt}" (at {txt_pos[0]} {txt_pos[1]} 0)\n'
                    f'    (effects (font (size {size} {size})) (justify left bottom))\n    (uuid {U()})\n  )\n')

    body.extend(out)

    pcount = 1
    for (net, ax, ay, rot) in powers:
        body.append(f'  (symbol (lib_id "power:{net}") (at {ax} {ay} {rot}) (unit 1)\n'
                    f'    (in_bom yes) (on_board yes) (dnp no)\n    (uuid {U()})\n'
                    f'    (property "Reference" "#PWR0{pcount:02d}" (at {ax} {ay} 0) (effects (font (size 1.27 1.27)) hide))\n'
                    f'    (property "Value" "{net}" (at {ax} {ay - 3.81 if net != "GND" else ay + 3.81} 0) (effects (font (size 1.0 1.0))))\n'
                    f'    (property "Footprint" "" (at {ax} {ay} 0) (effects (font (size 1.27 1.27)) hide))\n'
                    f'    (property "Datasheet" "" (at {ax} {ay} 0) (effects (font (size 1.27 1.27)) hide))\n'
                    f'    (pin "1" (uuid {U()}))\n'
                    f'    (instances (project "{PROJECT}" (path "/{root_uuid}" (reference "#PWR0{pcount:02d}") (unit 1))))\n  )\n')
        pcount += 1
    for i, (ax, ay) in enumerate(pwr_flags):
        body.append(f'  (symbol (lib_id "power:PWR_FLAG") (at {ax} {ay} 0) (unit 1)\n'
                    f'    (in_bom yes) (on_board yes) (dnp no)\n    (uuid {U()})\n'
                    f'    (property "Reference" "#FLG0{i + 1}" (at {ax} {ay} 0) (effects (font (size 1.27 1.27)) hide))\n'
                    f'    (property "Value" "PWR_FLAG" (at {ax + 1.27} {ay - 2.54} 0) (effects (font (size 1.0 1.0)) hide))\n'
                    f'    (property "Footprint" "" (at {ax} {ay} 0) (effects (font (size 1.27 1.27)) hide))\n'
                    f'    (property "Datasheet" "" (at {ax} {ay} 0) (effects (font (size 1.27 1.27)) hide))\n'
                    f'    (pin "1" (uuid {U()}))\n'
                    f'    (instances (project "{PROJECT}" (path "/{root_uuid}" (reference "#FLG0{i + 1}") (unit 1))))\n  )\n')

    body.append(f'\n  (sheet_instances\n    (path "/" (page "1"))\n  )\n)\n')
    with open(os.path.join(KDIR, f"{PROJECT}.kicad_sch"), "w") as f:
        f.write("".join(body))
    print(f"schematic: {len(PARTS)} symbols, {len(labels)} labels, {len(glabels)} global labels, {len(powers)} power syms, {len(ncs)} NC flags")


if __name__ == "__main__":
    main()
