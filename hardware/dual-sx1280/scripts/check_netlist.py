"""Compare a KiCad-exported netlist (kicadsexpr) or the routed PCB against design.py.

usage:  python3 check_netlist.py sch <file.net>
        /usr/bin/python3 check_netlist.py pcb <file.kicad_pcb>   (needs pcbnew)

Exit code 0 only if every design net matches exactly (same pin set) and no
extra connections exist. Pin-type sanity (multiple drivers etc.) is also
checked for the schematic.
"""
import re, sys
from design import NETS, NO_CONNECT, PARTS


def design_sets():
    return {n: set(p) for n, p in NETS.items()}


def parse_sch_net(path):
    t = open(path).read()
    nets = {}
    types = {}
    for m in re.finditer(r'\(net \(code "?\d+"?\) \(name "([^"]*)"\)(.*?)\)\s*(?=\(net \(code|\)\s*\)\s*$)', t, re.S):
        name = m.group(1).lstrip("/")
        pins = set()
        for nm in re.finditer(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)(?: \(pinfunction "[^"]*"\))?(?: \(pintype "([^"]+)"\))?', m.group(2)):
            ref, pin, ptype = nm.groups()
            if ref.startswith("#"):
                continue
            pins.add(f"{ref}.{pin}")
            types[f"{ref}.{pin}"] = ptype
        nets[name] = pins
    return nets, types


def parse_pcb(path):
    import pcbnew
    b = pcbnew.LoadBoard(path)
    nets = {}
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            n = pad.GetNetname()
            if not n or pad.GetNumber() == "":
                continue
            nets.setdefault(n.lstrip("/"), set()).add(f"{fp.GetReference()}.{pad.GetNumber()}")
    return nets, {}


def compare(actual, label):
    want = design_sets()
    ok = True
    # map actual nets to design nets by pin overlap
    for name, pins in want.items():
        cands = [a for a, ap in actual.items() if ap & pins]
        if len(cands) != 1:
            print(f"[FAIL] {label}: design net {name} spread over {cands}")
            ok = False
            continue
        a = cands[0]
        if actual[a] != pins:
            print(f"[FAIL] {label}: net {name}: missing {sorted(pins - actual[a])} extra {sorted(actual[a] - pins)}")
            ok = False
    allp = set().union(*want.values())
    for a, ap in actual.items():
        stray = ap - allp
        stray = {p for p in stray if p not in NO_CONNECT}
        if stray and len(ap) > 1:
            print(f"[FAIL] {label}: unexpected net {a}: {sorted(ap)}")
            ok = False
    for p in NO_CONNECT:
        for a, ap in actual.items():
            if p in ap and len(ap) > 1:
                print(f"[FAIL] {label}: NC pin {p} is connected on {a}")
                ok = False
    return ok


def pin_type_check(nets, types):
    ok = True
    for name, pins in nets.items():
        drivers = [p for p in pins if types.get(p) in ("output", "power_out")]
        if len(drivers) > 1:
            print(f"[FAIL] net {name}: multiple drivers {drivers}")
            ok = False
        pw_in = [p for p in pins if types.get(p) == "power_in"]
        if pw_in and not [p for p in pins if types.get(p) == "power_out"] and name not in ("GND", "+5V"):
            print(f"[WARN] net {name}: power_in pins without power_out driver")
    return ok


if __name__ == "__main__":
    kind, path = sys.argv[1], sys.argv[2]
    if kind == "sch":
        nets, types = parse_sch_net(path)
        ok = compare(nets, "schematic") & pin_type_check(nets, types)
        refs = {p.split(".")[0] for ps in nets.values() for p in ps}
        missing = set(PARTS) - refs
        if missing:
            print("[FAIL] parts missing from netlist:", missing)
            ok = False
    else:
        nets, _ = parse_pcb(path)
        ok = compare(nets, "pcb")
    print("RESULT:", "PASS" if ok else "FAIL", f"({len(NETS)} design nets)")
    sys.exit(0 if ok else 1)
