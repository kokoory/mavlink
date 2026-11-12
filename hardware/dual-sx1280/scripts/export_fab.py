"""Export fabrication + assembly outputs to ../fab and preview images to ../docs.

    python3 export_fab.py
Outputs
  fab/gerbers/*            Gerber X2 (4 copper, mask, paste, silk, edge) + Excellon drill
  fab/dual_sx1280_gerbers.zip
  fab/bom_jlcpcb.csv       Comment,Designator,Footprint,LCSC  (assembled parts only)
  fab/cpl_jlcpcb.csv       Designator,Mid X,Mid Y,Layer,Rotation
  fab/bom_full.csv         every part incl. hand-soldered modules / not-assembled pads
  docs/pcb_*.png           layer previews
"""
import csv, os, subprocess, sys, zipfile, shutil, glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from design import PARTS, PROJECT, BOARD_W, BOARD_H

ROOT = os.path.abspath(os.path.join(HERE, ".."))
PCB = os.path.join(ROOT, "kicad", PROJECT + ".kicad_pcb")
FAB = os.path.join(ROOT, "fab")
GDIR = os.path.join(FAB, "gerbers")
DOCS = os.path.join(ROOT, "docs")

LAYERS = "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"


def run(*a):
    r = subprocess.run(a, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit(f"failed: {' '.join(a)}")
    return r.stdout


def main():
    shutil.rmtree(GDIR, ignore_errors=True)
    os.makedirs(GDIR)
    run("kicad-cli", "pcb", "export", "gerbers", "-l", LAYERS, "--subtract-soldermask", "-o", GDIR + "/", PCB)
    run("kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
        "--generate-map", "--map-format", "pdf", "-u", "mm", "-o", GDIR + "/", PCB)
    zpath = os.path.join(FAB, PROJECT + "_gerbers.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(glob.glob(GDIR + "/*")):
            if not f.endswith(".pdf"):
                z.write(f, os.path.basename(f))

    # position file -> JLC CPL
    pos = os.path.join(FAB, "pos_raw.csv")
    run("kicad-cli", "pcb", "export", "pos", "--side", "both", "--format", "csv", "--units", "mm", "-o", pos, PCB)
    rows = list(csv.DictReader(open(pos)))
    with open(os.path.join(FAB, "cpl_jlcpcb.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in rows:
            ref = r["Ref"]
            if PARTS.get(ref, {}).get("dnp_asm") or ref.startswith("TP") or ref.startswith("JP"):
                continue
            w.writerow([ref, r["PosX"] + "mm", r["PosY"] + "mm", "Top" if r["Side"] == "top" else "Bottom", r["Rot"]])
    os.remove(pos)

    # BOMs
    groups = {}
    for ref, p in PARTS.items():
        key = (p["value"].split(" (")[0], p["footprint"].split(":")[1], p.get("lcsc", ""), p.get("mpn", ""))
        groups.setdefault(key, []).append(ref)
    with open(os.path.join(FAB, "bom_full.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Qty", "Designators", "Value", "Footprint", "MPN", "LCSC", "Assembly"])
        for (val, fp, lcsc, mpn), refs in sorted(groups.items(), key=lambda kv: kv[1][0]):
            asm = "hand-solder" if PARTS[refs[0]].get("dnp_asm") else (
                "not a part (pad)" if refs[0].startswith(("TP", "JP")) else "SMT")
            w.writerow([len(refs), " ".join(sorted(refs)), val, fp, mpn, lcsc, asm])
    with open(os.path.join(FAB, "bom_jlcpcb.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC"])
        for (val, fp, lcsc, mpn), refs in sorted(groups.items(), key=lambda kv: kv[1][0]):
            if PARTS[refs[0]].get("dnp_asm") or refs[0].startswith(("TP", "JP")):
                continue
            w.writerow([val, ",".join(sorted(refs)), fp, lcsc])

    # previews
    os.makedirs(DOCS, exist_ok=True)
    tmp = os.path.join(FAB, "_svg")
    os.makedirs(tmp, exist_ok=True)
    views = {
        "pcb_top": "F.Cu,F.SilkS,F.Mask,Edge.Cuts",
        "pcb_in1_gnd": "In1.Cu,Edge.Cuts",
        "pcb_in2": "In2.Cu,Edge.Cuts",
        "pcb_bottom": "B.Cu,B.SilkS,B.Mask,Edge.Cuts",
    }
    pngs = []
    for name, layers in views.items():
        svg = os.path.join(tmp, name + ".svg")
        extra = ["--mirror"] if name == "pcb_bottom" else []
        run("kicad-cli", "pcb", "export", "svg", "--layers", layers, "--exclude-drawing-sheet",
            "--page-size-mode", "2", *extra, "-o", svg, PCB)
        png = os.path.join(DOCS, name + ".png")
        run("rsvg-convert", "-z", "8", "-b", "white", "-o", png, svg)
        pngs.append(png)
    run("convert", *pngs, "-trim", "-bordercolor", "white", "-border", "20", "+append",
        "-resize", "2000x", os.path.join(DOCS, "pcb_layers.png"))
    shutil.rmtree(tmp)
    run("kicad-cli", "sch", "export", "pdf", "-o", os.path.join(DOCS, "schematic.pdf"),
        os.path.join(ROOT, "kicad", PROJECT + ".kicad_sch"))
    run("pdftoppm", "-png", "-r", "110", "-singlefile", os.path.join(DOCS, "schematic.pdf"), os.path.join(DOCS, "schematic"))
    print("exported to", FAB, "and", DOCS)


if __name__ == "__main__":
    main()
