"""Generate kicad/dual_sx1280.kicad_pcb (KiCad 7) from design.py.

Run with the system python that has the KiCad bindings:
    /usr/bin/python3 gen_pcb.py            # placement + zones + RF traces (unrouted)
Routing is done afterwards by route.sh (Freerouting via Specctra DSN/SES).

Stack-up (JLCPCB JLC04101H-7628 style, 1.0 mm, 4 layers):
  F.Cu   : radio A, MCU, LDO, LEDs, U.FL A, GND pour
  In1.Cu : solid GND plane (reference for F.Cu RF trace)
  In2.Cu : routing + GND pour, kept clear under the radio-B RF path
  B.Cu   : radio B, U.FL B, JST-SH host connector, SWD pads, GND pour
"""
import os, sys
import pcbnew
from pcbnew import VECTOR2I, FromMM

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from design import PARTS, NETS, BOARD_W, BOARD_H, PCB_ORIGIN, PROJECT, RF_NETS, POWER_NETS, pin_to_net

HERE = os.path.dirname(os.path.abspath(__file__))
KDIR = os.path.abspath(os.path.join(HERE, "..", "kicad"))
SYSFP = "/usr/share/kicad/footprints"
OX, OY = PCB_ORIGIN

TRACK = 0.15
CLEAR = 0.15
VIA_D, VIA_DRILL = 0.45, 0.25
PWR_TRACK = 0.3
RF_TRACK = 0.35


def P(x, y):
    return VECTOR2I(FromMM(OX + x), FromMM(OY + y))


def load_fp(spec):
    lib, name = spec.split(":")
    path = os.path.join(KDIR, "dual_sx1280.pretty") if lib == "dual_sx1280" else os.path.join(SYSFP, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    assert fp is not None, spec
    fp.SetFPIDAsString(spec)
    return fp


def rect_poly(x1, y1, x2, y2):
    chain = pcbnew.SHAPE_LINE_CHAIN()
    for (x, y) in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]:
        chain.Append(P(x, y))
    chain.SetClosed(True)
    return chain


def add_zone(board, net, layer, x1, y1, x2, y2, prio=0, clearance=0.2, min_w=0.2):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(net)
    z.Outline().AddOutline(rect_poly(x1, y1, x2, y2))
    z.SetAssignedPriority(prio)
    z.SetLocalClearance(FromMM(clearance))
    z.SetMinThickness(FromMM(min_w))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(FromMM(0.2))
    z.SetThermalReliefSpokeWidth(FromMM(0.25))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    board.Add(z)
    return z


def add_keepout(board, layers, x1, y1, x2, y2, tracks=True, vias=False, pads=False, pours=False, name=""):
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    ls = pcbnew.LSET()
    for l in layers:
        ls.AddLayer(l)
    z.SetLayerSet(ls)
    z.Outline().AddOutline(rect_poly(x1, y1, x2, y2))
    z.SetDoNotAllowTracks(tracks)
    z.SetDoNotAllowVias(vias)
    z.SetDoNotAllowPads(pads)
    z.SetDoNotAllowCopperPour(pours)
    z.SetDoNotAllowFootprints(False)
    if name:
        z.SetZoneName(name)
    board.Add(z)
    return z


def add_track(board, net, layer, pts, width):
    for (a, b) in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(P(*a))
        t.SetEnd(P(*b))
        t.SetWidth(FromMM(width))
        t.SetLayer(layer)
        t.SetNet(net)
        t.SetLocked(True)
        board.Add(t)


def pad_xy(fp, num):
    for p in fp.Pads():
        if p.GetNumber() == num:
            pos = p.GetPosition()
            return (pcbnew.ToMM(pos.x) - OX, pcbnew.ToMM(pos.y) - OY)
    raise KeyError(num)


def build():
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    ds = board.GetDesignSettings()
    ds.SetBoardThickness(FromMM(1.0))
    ds.m_TrackMinWidth = FromMM(0.127)
    ds.m_MinClearance = FromMM(0.127)
    ds.m_ViasMinSize = FromMM(0.45)
    ds.m_MinThroughDrill = FromMM(0.25)
    ds.m_ViasMinAnnularWidth = FromMM(0.1)
    ds.m_CopperEdgeClearance = FromMM(0.3)
    ds.m_HoleClearance = FromMM(0.2)
    ds.m_HoleToHoleMin = FromMM(0.25)
    ds.m_SolderMaskMinWidth = FromMM(0.0)

    nc = ds.m_NetSettings.m_DefaultNetClass
    nc.SetClearance(FromMM(CLEAR)); nc.SetTrackWidth(FromMM(TRACK))
    nc.SetViaDiameter(FromMM(VIA_D)); nc.SetViaDrill(FromMM(VIA_DRILL))
    pwr = pcbnew.NETCLASS("Power")
    pwr.SetClearance(FromMM(CLEAR)); pwr.SetTrackWidth(FromMM(PWR_TRACK))
    pwr.SetViaDiameter(FromMM(0.5)); pwr.SetViaDrill(FromMM(0.25))
    rf = pcbnew.NETCLASS("RF")
    rf.SetClearance(FromMM(0.25)); rf.SetTrackWidth(FromMM(RF_TRACK))
    rf.SetViaDiameter(FromMM(VIA_D)); rf.SetViaDrill(FromMM(VIA_DRILL))
    ds.m_NetSettings.m_NetClasses["Power"] = pwr
    ds.m_NetSettings.m_NetClasses["RF"] = rf
    for n in POWER_NETS:
        ds.m_NetSettings.m_NetClassPatternAssignments.push_back(
            pcbnew.NET_SETTINGS.make_shared_matcher(n, "Power")) if hasattr(pcbnew.NET_SETTINGS, "make_shared_matcher") else None

    # nets
    nets = {}
    for name in NETS:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        nets[name] = ni
    p2n = pin_to_net()

    # outline
    for (a, b) in [((0, 0), (BOARD_W, 0)), ((BOARD_W, 0), (BOARD_W, BOARD_H)),
                   ((BOARD_W, BOARD_H), (0, BOARD_H)), ((0, BOARD_H), (0, 0))]:
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(P(*a)); s.SetEnd(P(*b))
        s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(FromMM(0.1))
        board.Add(s)

    fps = {}
    for ref, part in PARTS.items():
        fp = load_fp(part["footprint"])
        fp.SetReference(ref)
        fp.SetValue(part["value"])
        fp.SetPosition(P(*part["pos"]))
        fp.SetOrientationDegrees(part["rot"])
        board.Add(fp)
        if part["side"] == "B":
            fp.Flip(P(*part["pos"]), True)
        for k in ("mpn", "lcsc"):
            if part.get(k):
                fp.SetProperty(k.upper(), part[k])
        if part.get("dnp_asm"):
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        for pad in fp.Pads():
            key = f"{ref}.{pad.GetNumber()}"
            if key in p2n:
                pad.SetNet(nets[p2n[key]])
        fp.Reference().SetTextSize(VECTOR2I(FromMM(0.6), FromMM(0.6)))
        fp.Reference().SetTextThickness(FromMM(0.1))
        fp.Value().SetVisible(False)
        fps[ref] = fp

    return board, fps, nets


def report(fps):
    for ref, fp in fps.items():
        fp.BuildCourtyardCaches()
        bb = fp.GetCourtyard(pcbnew.F_CrtYd if not fp.IsFlipped() else pcbnew.B_CrtYd).BBox()
        x1, y1 = pcbnew.ToMM(bb.GetX()) - OX, pcbnew.ToMM(bb.GetY()) - OY
        print(f"{ref:4s} {'B' if fp.IsFlipped() else 'F'} crtyd x {x1:6.2f}..{x1 + pcbnew.ToMM(bb.GetWidth()):6.2f} "
              f"y {y1:6.2f}..{y1 + pcbnew.ToMM(bb.GetHeight()):6.2f}  "
              + " ".join(f"{p.GetNumber()}@({pcbnew.ToMM(p.GetPosition().x) - OX:.2f},{pcbnew.ToMM(p.GetPosition().y) - OY:.2f})"
                         for p in fp.Pads() if ref in ("J1", "J2", "J3") or p.GetNumber() in ("3", "9", "14")))




def overlaps(fps):
    """Courtyard overlap check per side (bbox based)."""
    boxes = []
    for ref, fp in fps.items():
        fp.BuildCourtyardCaches()
        layer = pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd
        bb = fp.GetCourtyard(layer).BBox()
        boxes.append((ref, fp.IsFlipped(), pcbnew.ToMM(bb.GetX()), pcbnew.ToMM(bb.GetY()),
                      pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom())))
    bad = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[1] != b[1]:
                continue
            if a[2] < b[4] - 1e-3 and b[2] < a[4] - 1e-3 and a[3] < b[5] - 1e-3 and b[3] < a[5] - 1e-3:
                bad.append((a[0], b[0]))
    return bad


PRO_TEMPLATE = {
    "board": {
        "design_settings": {
            "defaults": {"board_outline_line_width": 0.1, "copper_line_width": 0.2, "copper_text_size_h": 1.0,
                         "copper_text_size_v": 1.0, "copper_text_thickness": 0.15, "silk_line_width": 0.12,
                         "silk_text_size_h": 0.6, "silk_text_size_v": 0.6, "silk_text_thickness": 0.1},
            "rules": {"min_clearance": 0.127, "min_track_width": 0.127, "min_via_diameter": 0.45,
                      "min_through_hole_diameter": 0.25, "min_via_annular_width": 0.1,
                      "min_copper_edge_clearance": 0.3, "min_hole_clearance": 0.2, "min_hole_to_hole": 0.25,
                      "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1, "solder_mask_to_copper_clearance": 0.0,
                      "min_silk_clearance": 0.0, "min_text_height": 0.5, "min_text_thickness": 0.08,
                      "max_error": 0.005, "allow_blind_buried_vias": False, "allow_microvias": False,
                      "use_height_for_length_calcs": True},
            "rule_severities": {"starved_thermal": "warning", "silk_overlap": "ignore", "silk_over_copper": "ignore", "silk_edge_clearance": "ignore",
                                "text_height": "ignore", "text_thickness": "ignore",
                                "footprint_type_mismatch": "ignore", "lib_footprint_issues": "ignore",
                                "lib_footprint_mismatch": "ignore"},
            "track_widths": [0.0, 0.15, 0.2, 0.3, 0.35, 0.5],
            "via_dimensions": [{"diameter": 0.0, "drill": 0.0}, {"diameter": 0.45, "drill": 0.25},
                               {"diameter": 0.5, "drill": 0.25}],
            "diff_pair_dimensions": [],
        },
        "layer_presets": [], "viewports": [],
    },
    "net_settings": {
        "classes": [
            {"name": "Default", "clearance": 0.15, "track_width": 0.15, "via_diameter": 0.45, "via_drill": 0.25},
            {"name": "Power", "clearance": 0.15, "track_width": 0.3, "via_diameter": 0.5, "via_drill": 0.25},
            {"name": "RF", "clearance": 0.3, "track_width": 0.35, "via_diameter": 0.45, "via_drill": 0.25},
        ],
        "meta": {"version": 3},
        "netclass_patterns": [{"netclass": "Power", "pattern": n} for n in ("+3V3", "+5V", "GND")]
                             + [{"netclass": "RF", "pattern": n} for n in ("RF_A", "RF_B")],
    },
    "meta": {"filename": "dual_sx1280.kicad_pro", "version": 1},
    "pcbnew": {"last_paths": {}, "page_layout_descr_file": ""},
    "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
    "sheets": [["00000000-0000-0000-0000-000000000000", ""]],
    "text_variables": {},
}


def finish(board, fps, nets):
    W, H = BOARD_W, BOARD_H
    board.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)
    board.SetLayerName(pcbnew.In1_Cu, "In1.Cu")
    gnd = nets["GND"]
    # GND pours on every layer (In1 = solid plane)
    for layer, prio in ((pcbnew.F_Cu, 0), (pcbnew.In1_Cu, 0), (pcbnew.In2_Cu, 0), (pcbnew.B_Cu, 0)):
        add_zone(board, gnd, layer, 0, 0, W, H, prio=prio, clearance=0.2)
    # NOTE: tracks/vias under the module bodies are allowed (solder-masked tracks, tented vias).
    # This assumes the LoRa1280 underside has no exposed copper besides its castellated pads.
    # keep In2 solid GND under the bottom RF path (reference plane for RF_B on B.Cu)
    add_keepout(board, [pcbnew.In2_Cu], 0.0, 15.2, 5.4, 22.8, tracks=True, vias=True, name="rfB_ref")
    # no vias right next to the RF traces / U.FL signal pins
    add_keepout(board, [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu], 16.85, 15.8, 18.2, 19.6,
                tracks=False, vias=True, name="rfA_novia")
    add_keepout(board, [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu], 1.8, 15.8, 3.15, 19.6,
                tracks=False, vias=True, name="rfB_novia")
    # RF traces: module ANT pad -> U.FL centre pin, straight, 0.35 mm (~50 ohm CPWG over 0.21 mm prepreg)
    for net, ref, jref, layer in (("RF_A", "U1", "J1", pcbnew.F_Cu), ("RF_B", "U2", "J2", pcbnew.B_Cu)):
        a = pad_xy(fps[ref], "9")
        b = pad_xy(fps[jref], "1")
        add_track(board, nets[net], layer, [a, b], RF_TRACK)
    # silkscreen labels
    for (txt, x, y, layer, size) in (("ANT A", 15.1, 22.9, pcbnew.F_SilkS, 0.6),
                                    ("ANT B", 4.9, 22.9, pcbnew.B_SilkS, 0.6),
                                    ("5V TX RX G", 10.0, 26.0, pcbnew.B_SilkS, 0.5),
                                    ("SWD", 3.9, 26.0, pcbnew.B_SilkS, 0.5),
                                    ("SX1280x2 v0.1", 5.0, 32.2, pcbnew.B_SilkS, 0.5)):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(txt)
        t.SetPosition(P(x, y))
        t.SetLayer(layer)
        t.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
        t.SetTextThickness(FromMM(0.1))
        if layer == pcbnew.B_SilkS:
            t.SetMirrored(True)
        board.Add(t)


def write_project():
    """board.Save() rewrites the .kicad_pro; merge our rules + net class patterns into it afterwards."""
    import json
    path = os.path.join(KDIR, PROJECT + ".kicad_pro")
    d = json.load(open(path)) if os.path.exists(path) else {}
    for k, v in PRO_TEMPLATE.items():
        if k == "board":
            ds = d.setdefault("board", {}).setdefault("design_settings", {})
            for kk, vv in v["design_settings"].items():
                if isinstance(vv, dict):
                    ds.setdefault(kk, {}).update(vv)
                else:
                    ds[kk] = vv
        elif k == "net_settings":
            ns = d.setdefault("net_settings", {})
            classes = {c["name"]: c for c in ns.get("classes", [])}
            for c in v["classes"]:
                classes.setdefault(c["name"], {}).update(c)
            ns["classes"] = list(classes.values())
            ns["netclass_patterns"] = v["netclass_patterns"]
            ns["meta"] = v["meta"]
        else:
            d.setdefault(k, v)
    with open(path, "w") as f:
        json.dump(d, f, indent=2)


if __name__ == "__main__":
    board, fps, nets = build()
    bad = overlaps(fps)
    assert not bad, f"courtyard overlaps: {bad}"
    finish(board, fps, nets)
    out = os.path.join(KDIR, PROJECT + ".kicad_pcb")
    board.Save(out)
    write_project()
    print("saved", out)
