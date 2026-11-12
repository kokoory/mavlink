"""Fill zones, run KiCad DRC and the netlist cross-check on the routed board.

    /usr/bin/python3.12 drc.py [report_path]
Exit 0 only if DRC has 0 errors, 0 unconnected items and the PCB nets equal design.NETS.
"""
import os, re, sys, subprocess
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from design import PROJECT

KDIR = os.path.abspath(os.path.join(HERE, "..", "kicad"))
PCB = os.path.join(KDIR, PROJECT + ".kicad_pcb")
REPORT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "docs", "drc_report.txt")

board = pcbnew.LoadBoard(PCB)
filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
board.Save(PCB)

board = pcbnew.LoadBoard(PCB)
ok = pcbnew.WriteDRCReport(board, REPORT, pcbnew.EDA_UNITS_MILLIMETRES, True)
txt = open(REPORT).read()
viol = re.search(r"\*\* Found (\d+) DRC violations \*\*", txt)
unc = re.search(r"\*\* Found (\d+) unconnected pads \*\*", txt)
nv = int(viol.group(1)) if viol else -1
nu = int(unc.group(1)) if unc else -1
types = re.findall(r"^\[(\w+)\]: (.*)$", txt, re.M)
errors = [t for t in re.findall(r"^\[(\w+)\]: .*\n.*?; (error|warning)", txt, re.M)]
from collections import Counter
print("DRC violations:", nv, " unconnected:", nu)
for (k, sev), c in Counter(errors).most_common():
    print(f"  {c:4d}  {k} ({sev})")
r = subprocess.run([sys.executable, os.path.join(HERE, "check_netlist.py"), "pcb", PCB], capture_output=True, text=True)
print(r.stdout.strip())
n_err = sum(c for (k, sev), c in Counter(errors).items() if sev == "error")
sys.exit(0 if (n_err == 0 and nu == 0 and r.returncode == 0) else 1)
