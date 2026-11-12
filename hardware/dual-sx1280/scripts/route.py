"""Grid-based A* autorouter for the dual-SX1280 board (KiCad 7 pcbnew + numpy).

    /usr/bin/python3.12 route.py      # reads/writes kicad/dual_sx1280.kicad_pcb

Why a custom router: the session could not run an external autorouter, and the
board is small enough (31 nets) for a maze router. Clearances are enforced with
exact distance fields (pads/tracks/vias) and the result is verified by KiCad's
own DRC (drc.py).

Strategy
  1. GND fan-out: every GND pad gets a short stub + via to the In1 GND plane
     (QFN exposed pad gets via-in-pad thermal vias).
  2. Signal nets (0.15 mm), then +3V3 / +5V (0.3 mm, fallback 0.2 mm) on
     F.Cu / In2.Cu / B.Cu with vias. Rip-up-and-retry with a new net order on failure.
  3. GND stitching vias wherever they fit, then zone fill.
"""
import os, sys, math, heapq, time, random
import numpy as np
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from design import NETS, BOARD_W, BOARD_H, PCB_ORIGIN, PROJECT, RF_NETS, POWER_NETS

KDIR = os.path.abspath(os.path.join(HERE, "..", "kicad"))
PCB = os.path.join(KDIR, PROJECT + ".kicad_pcb")
OX, OY = PCB_ORIGIN

RES = 0.05
CLR = 0.15
MARGIN = 0.02
EDGE = 0.3
VIA_D, VIA_DRILL = 0.45, 0.25
VIA_COST = 14.0          # in grid steps (0.7 mm)
INNER_COST = 1.1         # slight preference for outer layers
HW = 1.4                 # weighted A* (faster, slightly sub-optimal paths)
LAYERS = [pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
LNAME = {pcbnew.F_Cu: "F", pcbnew.In2_Cu: "In2", pcbnew.B_Cu: "B"}
NL = len(LAYERS)
NX, NY = int(round(BOARD_W / RES)), int(round(BOARD_H / RES))
XS = (np.arange(NX) + 0.5) * RES
YS = (np.arange(NY) + 0.5) * RES
GX, GY = np.meshgrid(XS, YS)           # (NY, NX)
EDGE_D = np.minimum(np.minimum(GX, BOARD_W - GX), np.minimum(GY, BOARD_H - GY))
NETNAMES = list(NETS)
NIDX = {n: i for i, n in enumerate(NETNAMES)}


def mm(v):
    return ToMM(v)


def P(x, y):
    return VECTOR2I(FromMM(OX + x), FromMM(OY + y))


# --------------------------------------------------------------------------- geometry fields
class World:
    def __init__(self):
        n = len(NETNAMES)
        self.d = np.full((NL, n, NY, NX), np.inf, np.float32)      # distance to copper of net
        self.padd = np.full((NL, n, NY, NX), np.inf, np.float32)   # distance to pads of net only
        self.track_block = np.zeros((NL, NY, NX), bool)
        self.track_keepouts = {li: [] for li in range(NL)}
        self.via_block = np.zeros((NY, NX), bool)
        self.vias = {i: [] for i in range(n)}                        # (x, y) per net

    @staticmethod
    def rect_dist(x1, y1, x2, y2):
        dx = np.maximum(np.maximum(x1 - GX, 0), GX - x2)
        dy = np.maximum(np.maximum(y1 - GY, 0), GY - y2)
        return np.hypot(dx, dy)

    @staticmethod
    def seg_dist(ax, ay, bx, by):
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        if L2 == 0:
            return np.hypot(GX - ax, GY - ay)
        t = np.clip(((GX - ax) * vx + (GY - ay) * vy) / L2, 0, 1)
        return np.hypot(GX - (ax + t * vx), GY - (ay + t * vy))

    def add(self, li, ni, dist, pad=False):
        np.minimum(self.d[li, ni], dist, out=self.d[li, ni])
        if pad:
            np.minimum(self.padd[li, ni], dist, out=self.padd[li, ni])

    def add_seg(self, li, ni, a, b, w):
        self.add(li, ni, self.seg_dist(a[0], a[1], b[0], b[1]) - w / 2)

    def add_via(self, ni, x, y):
        dist = np.hypot(GX - x, GY - y) - VIA_D / 2
        for li in range(NL):
            self.add(li, ni, dist)
        self.vias[ni].append((x, y))


def pad_geom(pad):
    """Return ('circle', cx, cy, r) or ('rect', x1, y1, x2, y2) in board-mm coords."""
    pos = pad.GetPosition()
    cx, cy = mm(pos.x) - OX, mm(pos.y) - OY
    if pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE:
        return ("circle", cx, cy, mm(pad.GetSize().x) / 2)
    bb = pad.GetBoundingBox()
    return ("rect", mm(bb.GetX()) - OX, mm(bb.GetY()) - OY, mm(bb.GetRight()) - OX, mm(bb.GetBottom()) - OY)


def geom_dist(g):
    if g[0] == "circle":
        return np.hypot(GX - g[1], GY - g[2]) - g[3]
    return World.rect_dist(*g[1:])


def keepout_rect(z):
    bb = z.GetBoundingBox()
    return (mm(bb.GetX()) - OX, mm(bb.GetY()) - OY, mm(bb.GetRight()) - OX, mm(bb.GetBottom()) - OY)


def cells_in(x1, y1, x2, y2):
    return (GX >= x1) & (GX <= x2) & (GY >= y1) & (GY <= y2)


# --------------------------------------------------------------------------- build world from board
def load_world(board):
    W = World()
    pads = {}       # net -> list of (pad, layers(list of li), geom)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            net = pad.GetNetname()
            g = pad_geom(pad)
            lis = [i for i, l in enumerate(LAYERS) if pad.IsOnLayer(l)]
            if not net:
                # unconnected pads are still obstacles: give them a pseudo-net? use nearest: treat as all nets' obstacle
                dist = geom_dist(g)
                for li in lis:
                    for ni in range(len(NETNAMES)):
                        pass
                W.__dict__.setdefault("nc_obst", []).append((lis, dist))
                continue
            ni = NIDX[net]
            dist = geom_dist(g)
            for li in lis:
                W.add(li, ni, dist, pad=True)
            pads.setdefault(net, []).append((pad, lis, g, fp.GetReference()))
    for t in board.GetTracks():
        ni = NIDX[t.GetNetname()]
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            W.add_via(ni, mm(p.x) - OX, mm(p.y) - OY)
        else:
            li = LAYERS.index(t.GetLayer())
            a, b = t.GetStart(), t.GetEnd()
            W.add_seg(li, ni, (mm(a.x) - OX, mm(a.y) - OY), (mm(b.x) - OX, mm(b.y) - OY), mm(t.GetWidth()))
    for z in board.Zones():
        if not z.GetIsRuleArea():
            continue
        r = keepout_rect(z)
        m = cells_in(*r)
        for li, l in enumerate(LAYERS):
            if z.IsOnLayer(l) and z.GetDoNotAllowTracks():
                W.track_block[li] |= m
                W.track_keepouts[li].append(World.rect_dist(*r))
        if z.GetDoNotAllowVias():
            # inflate by via radius so the via copper stays outside the area
            W.via_block |= cells_in(r[0] - VIA_D / 2, r[1] - VIA_D / 2, r[2] + VIA_D / 2, r[3] + VIA_D / 2)
    return W, pads


# --------------------------------------------------------------------------- legality masks
def masks_for(W, ni, w, ep_ok=False):
    hw = w / 2
    other = np.empty((NL, NY, NX), np.float32)
    for li in range(NL):
        tmp = W.d[li].copy()
        tmp[ni] = np.inf
        o = tmp.min(axis=0)
        for (lis, dist) in getattr(W, "nc_obst", []):
            if li in lis:
                o = np.minimum(o, dist)
        other[li] = o
    track_ok = (other >= CLR + hw + MARGIN) & (EDGE_D >= EDGE + hw)[None] & ~W.track_block
    for li in range(NL):
        for kd in W.track_keepouts[li]:
            track_ok[li] &= kd >= hw + 0.02
    via_ok = np.all(other >= CLR + VIA_D / 2 + MARGIN, axis=0) & (EDGE_D >= EDGE + VIA_D / 2) & ~W.via_block
    # no via-in-pad on own SMD pads (outer layers), except where allowed (EP)
    if not ep_ok:
        via_ok &= (W.padd[0, ni] >= VIA_D / 2 + 0.05) & (W.padd[2, ni] >= VIA_D / 2 + 0.05)
    # hole-to-hole spacing to own vias
    for (vx, vy) in W.vias[ni]:
        via_ok &= np.hypot(GX - vx, GY - vy) >= VIA_DRILL + 0.25 + 0.01
    via_ok &= track_ok.any(axis=0) | True
    # via must also be legal as copper on every routing layer for this net => covered by `other` check
    return track_ok, via_ok


# --------------------------------------------------------------------------- A*
DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
        (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]


def astar(track_ok, via_ok, sources, target_cells, target_bbox, max_expand=2_500_000, allow_via=True,
          goal_fn=None):
    """sources/target_cells: sets of (li, iy, ix). Returns list of (li, iy, ix) from source to target."""
    tok = [track_ok[li] for li in range(NL)]
    tx1, ty1, tx2, ty2 = target_bbox
    tlayers = {c[0] for c in target_cells} if target_cells else set(range(NL))

    def h(li, iy, ix):
        dx = max(tx1 - ix, 0, ix - tx2)
        dy = max(ty1 - iy, 0, iy - ty2)
        hh = max(dx, dy) + 0.4142 * min(dx, dy)
        if li not in tlayers:
            hh += VIA_COST
        return hh

    g = {}
    came = {}
    heap = []
    for s in sources:
        li, iy, ix = s
        g[s] = 0.0
        came[s] = None
        heapq.heappush(heap, (HW * h(*s), 0.0, s))
    exp = 0
    while heap:
        f, gc, cur = heapq.heappop(heap)
        if gc > g.get(cur, math.inf):
            continue
        if (goal_fn(cur) if goal_fn else cur in target_cells):
            path = []
            while cur is not None:
                path.append(cur)
                cur = came[cur]
            return path[::-1]
        exp += 1
        if exp > max_expand:
            return None
        li, iy, ix = cur
        lc = INNER_COST if LAYERS[li] == pcbnew.In2_Cu else 1.0
        for dx, dy, c in DIRS:
            nx, ny = ix + dx, iy + dy
            if not (0 <= nx < NX and 0 <= ny < NY):
                continue
            nb = (li, ny, nx)
            if not (tok[li][ny, nx] or nb in target_cells):
                continue
            if dx and dy and not (tok[li][iy, nx] and tok[li][ny, ix]):
                continue
            ng = gc + c * lc
            if ng < g.get(nb, math.inf):
                g[nb] = ng
                came[nb] = cur
                heapq.heappush(heap, (ng + HW * h(*nb), ng, nb))
        if allow_via and via_ok[iy, ix]:
            for l2 in range(NL):
                if l2 == li:
                    continue
                nb = (l2, iy, ix)
                if not (tok[l2][iy, ix] or nb in target_cells):
                    continue
                ng = gc + VIA_COST
                if ng < g.get(nb, math.inf):
                    g[nb] = ng
                    came[nb] = cur
                    heapq.heappush(heap, (ng + HW * h(*nb), ng, nb))
    return None


def cell_of(x, y):
    return int(min(max(y / RES - 0.5, 0), NY - 1) + 0.5), int(min(max(x / RES - 0.5, 0), NX - 1) + 0.5)


def pad_cells(pad_entry):
    pad, lis, g, ref = pad_entry
    inside = geom_dist(g) <= -0.0001 if g[0] == "rect" else geom_dist(g) <= 0
    # keep only cells comfortably inside the pad
    inside = geom_dist(g) <= -min(0.03, 0.0)
    iy, ix = np.nonzero(inside)
    if len(iy) == 0:
        cy, cx = cell_of((g[1] + g[3]) / 2, (g[2] + g[4]) / 2) if g[0] == "rect" else cell_of(g[1], g[2])
        iy, ix = np.array([cy]), np.array([cx])
    return {(li, int(y), int(x)) for li in lis for y, x in zip(iy, ix)}


def bbox_of(cells):
    ys = [c[1] for c in cells]
    xs = [c[2] for c in cells]
    return (min(xs), min(ys), max(xs), max(ys))


# --------------------------------------------------------------------------- path -> tracks
def path_to_items(path):
    """Return (segments[(li,(x,y),(x,y))], vias[(x,y)])."""
    segs, vias = [], []
    if len(path) < 2:
        return segs, vias

    def xy(c):
        return (float(XS[c[2]]), float(YS[c[1]]))
    start = path[0]
    prev = path[0]
    direction = None
    for c in path[1:]:
        if c[0] != prev[0]:
            if prev != start:
                segs.append((prev[0], xy(start), xy(prev)))
            vias.append(xy(c))
            start = c
            direction = None
        else:
            d = (c[1] - prev[1], c[2] - prev[2])
            if direction is not None and d != direction:
                segs.append((prev[0], xy(start), xy(prev)))
                start = prev
            direction = d
        prev = c
    if prev != start and prev[0] == start[0]:
        segs.append((prev[0], xy(start), xy(prev)))
    return segs, vias


class Router:
    def __init__(self, board):
        self.board = board
        self.W, self.pads = load_world(board)
        self.netinfo = {n: board.FindNet(n) for n in NETNAMES}
        self.items = []     # (kind, net, data)
        self.tree = {}      # net -> set of cells

    def commit(self, net, segs, vias, w, cells=()):
        ni = NIDX[net]
        for (li, a, b) in segs:
            self.W.add_seg(li, ni, a, b, w)
            self.items.append(("seg", net, (li, a, b, w)))
        for (x, y) in vias:
            self.W.add_via(ni, x, y)
            self.items.append(("via", net, (x, y)))
        self.tree.setdefault(net, set()).update(cells)

    # --- GND fan-out --------------------------------------------------------
    def gnd_fanout(self):
        net = "GND"
        ni = NIDX[net]
        fails = []
        for entry in self.pads[net]:
            pad, lis, g, ref = entry
            if ref == "U3":
                continue
            if not lis:
                continue
            track_ok, via_ok = masks_for(self.W, ni, 0.25)
            src = pad_cells(entry)
            pc = (g[1], g[2]) if g[0] == "circle" else ((g[1] + g[3]) / 2, (g[2] + g[4]) / 2)
            pd = geom_dist(g)

            def goal(c, via_ok=via_ok, pd=pd, li0=lis[0]):
                return c[0] == li0 and via_ok[c[1], c[2]] and pd[c[1], c[2]] >= VIA_D / 2 + 0.02
            path = astar(track_ok, via_ok, src, set(), bbox_of(src), max_expand=60000, allow_via=False,
                         goal_fn=goal)
            if path is None:
                fails.append(f"{ref}.{pad.GetNumber()}")
                continue
            segs, _ = path_to_items(path)
            end = path[-1]
            vx, vy = float(XS[end[2]]), float(YS[end[1]])
            self.commit(net, segs, [(vx, vy)], 0.25, set(path))
        return fails

    # --- QFN ground: VSS pins straight into the exposed pad, EP thermal vias ---
    def qfn_gnd(self):
        net = "GND"
        ni = NIDX[net]
        ep = [e for e in self.pads[net] if e[3] == "U3" and e[0].GetNumber() == "49"][0]
        g = ep[2]
        cx, cy = (g[1] + g[3]) / 2, (g[2] + g[4]) / 2
        self.commit(net, [], [(cx + dx, cy + dy) for dx in (-1.6, 0, 1.6) for dy in (-1.6, 0, 1.6)], 0.3)
        tree = pad_cells(ep)
        fails = []
        for e in self.pads[net]:
            if e[3] != "U3" or e is ep:
                continue
            track_ok, via_ok = masks_for(self.W, ni, 0.15)
            tgt = pad_cells(e)
            path = astar(track_ok, via_ok, tgt, tree, bbox_of(tree), max_expand=200000, allow_via=False)
            if path is None:
                fails.append(e[0].GetNumber())
                continue
            segs, _ = path_to_items(path)
            self.commit(net, segs, [], 0.15, set(path))
        return fails

    # --- QFN dog-bone fan-out: stub + via per used signal/power pin ----------
    def qfn_fanout(self, ref="U3", rows=(0.75, 1.35)):
        fp = [f for f in self.board.GetFootprints() if f.GetReference() == ref][0]
        c = fp.GetPosition()
        qx, qy = mm(c.x) - OX, mm(c.y) - OY
        done, skipped = 0, []
        side_pads = {}
        for pad in fp.Pads():
            net = pad.GetNetname()
            if not net or net == "GND":
                continue
            p = pad.GetPosition()
            px, py = mm(p.x) - OX, mm(p.y) - OY
            dx, dy = px - qx, py - qy
            if abs(dx) > abs(dy):
                d = (1 if dx > 0 else -1, 0)
            else:
                d = (0, 1 if dy > 0 else -1)
            side_pads.setdefault(d, []).append((pad, px, py, net))
        for d, lst in side_pads.items():
            lst.sort(key=lambda t: t[1] * abs(d[1]) + t[2] * abs(d[0]))
            for k, (pad, px, py, net) in enumerate(lst):
                ni = NIDX[net]
                g = pad_geom(pad)
                # outer end of the pad along d
                if d[0]:
                    edge = g[3] if d[0] > 0 else g[1]
                    base = (edge, py)
                else:
                    edge = g[4] if d[1] > 0 else g[2]
                    base = (px, edge)
                w = 0.25 if net in POWER_NETS else 0.15
                track_ok, via_ok = masks_for(self.W, ni, w)
                placed = False
                pin_no = int(pad.GetNumber())
                order = rows if pin_no % 2 else rows[::-1]
                for r in order:
                    vx, vy = base[0] + d[0] * r, base[1] + d[1] * r
                    iy, ix = cell_of(vx, vy)
                    vx, vy = float(XS[ix]), float(YS[iy])
                    if not via_ok[iy, ix]:
                        continue
                    # stub legality: sample along the stub on F.Cu
                    ok = True
                    n = 12
                    for t in range(1, n + 1):
                        sx = px + (vx - px) * t / n
                        sy = py + (vy - py) * t / n
                        jy, jx = cell_of(sx, sy)
                        if not track_ok[0, jy, jx] and geom_dist(g)[jy, jx] > 0:
                            ok = False
                            break
                    if not ok:
                        continue
                    stub_end = (vx, vy)
                    cells = {(li, iy, ix) for li in range(NL)}
                    self.commit(net, [(0, (px, py), stub_end)], [stub_end], w, cells)
                    placed = True
                    done += 1
                    break
                if not placed:
                    skipped.append(pad.GetNumber())
        return done, skipped

    # --- one multi-pin net ----------------------------------------------------
    def route_net(self, net, w):
        ni = NIDX[net]
        snap = (self.W.d[:, ni].copy(), list(self.W.vias[ni]), len(self.items), set(self.tree.get(net, set())))
        ok = self._route_net(net, w)
        if not ok:
            self.W.d[:, ni] = snap[0]
            self.W.vias[ni] = snap[1]
            del self.items[snap[2]:]
            self.tree[net] = snap[3]
        return ok

    def _route_net(self, net, w):
        ni = NIDX[net]
        entries = sorted(self.pads[net], key=lambda e: (e[3] != "U3", e[3]))
        if net in RF_NETS:
            return True
        tree = set(pad_cells(entries[0]))
        # existing copper of this net (e.g. fixed RF tracks) is part of the tree
        tree |= self.tree.get(net, set())
        remaining = entries[1:]
        staged = []
        while remaining:
            # nearest remaining pad to tree centroid
            tb = bbox_of(tree)
            tcx, tcy = (tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2

            def dist(e):
                c = pad_cells(e)
                b = bbox_of(c)
                return abs((b[0] + b[2]) / 2 - tcx) + abs((b[1] + b[3]) / 2 - tcy)
            remaining.sort(key=dist)
            e = remaining.pop(0)
            tgt = pad_cells(e)
            track_ok, via_ok = masks_for(self.W, ni, w)
            path = astar(track_ok, via_ok, tgt, tree, bbox_of(tree))
            if path is None:
                # undo staged items of this net
                return False
            segs, vias = path_to_items(path)
            self.commit(net, segs, vias, w, set(path))
            tree |= set(path) | tgt
            # vias occupy all layers
            for (vx, vy) in vias:
                iy, ix = cell_of(vx, vy)
                tree |= {(li, iy, ix) for li in range(NL)}
        return True

    def to_board(self):
        for kind, net, data in self.items:
            if kind == "seg":
                li, a, b, w = data
                t = pcbnew.PCB_TRACK(self.board)
                t.SetStart(P(*a)); t.SetEnd(P(*b))
                t.SetWidth(FromMM(w)); t.SetLayer(LAYERS[li])
                t.SetNet(self.netinfo[net])
                self.board.Add(t)
            else:
                x, y = data
                v = pcbnew.PCB_VIA(self.board)
                v.SetPosition(P(x, y))
                v.SetWidth(FromMM(VIA_D)); v.SetDrill(FromMM(VIA_DRILL))
                v.SetViaType(pcbnew.VIATYPE_THROUGH)
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetNet(self.netinfo[net])
                self.board.Add(v)

    def stitch(self, pitch=1.0):
        net = "GND"
        ni = NIDX[net]
        n = 0
        for y in np.arange(0.8, BOARD_H - 0.5, pitch):
            for x in np.arange(0.8, BOARD_W - 0.5, pitch):
                track_ok, via_ok = None, None
                iy, ix = cell_of(x, y)
                # cheap local check using current fields
                ok = True
                for li in range(NL):
                    tmp = self.W.d[li, :, iy, ix].copy()
                    tmp[ni] = np.inf
                    if tmp.min() < CLR + VIA_D / 2 + 0.05:
                        ok = False
                if not ok or EDGE_D[iy, ix] < EDGE + VIA_D / 2 + 0.05 or self.W.via_block[iy, ix]:
                    continue
                if self.W.padd[0, ni, iy, ix] < VIA_D / 2 + 0.05 or self.W.padd[2, ni, iy, ix] < VIA_D / 2 + 0.05:
                    continue
                if any(math.hypot(vx - XS[ix], vy - YS[iy]) < 0.8 for (vx, vy) in self.W.vias[ni]):
                    continue
                self.commit(net, [], [(float(XS[ix]), float(YS[iy]))], 0.3)
                n += 1
        return n


def main(seed=0, tries=10):
    # long radio nets first, short local nets afterwards
    order_signal = ["B_NSS", "B_SCK", "B_MISO", "B_MOSI", "B_BUSY", "B_DIO1", "B_NRESET",
                    "A_NSS", "A_SCK", "A_MISO", "A_MOSI", "A_BUSY", "A_DIO1", "A_NRESET",
                    "UART_TX", "UART_RX", "SWDIO", "SWCLK", "NRST", "BOOT0",
                    "LED_A", "LED_A_K", "LED_B", "LED_B_K", "A_TCXO", "B_TCXO"]
    assert set(order_signal) == {n for n in NETNAMES if n not in POWER_NETS and n not in RF_NETS}
    rnd = random.Random(seed)
    failed_first = []
    best = None
    for attempt in range(tries):
        board = pcbnew.LoadBoard(PCB)
        for t in list(board.GetTracks()):
            if not t.IsLocked():
                board.Remove(t)
        R = Router(board)
        t0 = time.time()
        qf = R.qfn_gnd()
        fo = R.qfn_fanout()
        fails = []
        # power first (wide), so signals flow around it
        for net in ("+3V3", "+5V"):
            if not (R.route_net(net, 0.25) or R.route_net(net, 0.2)):
                fails.append(net)
        rest = [n for n in order_signal if n not in failed_first]
        if attempt > 0:
            rnd.shuffle(rest)
        for net in failed_first + rest:
            if not R.route_net(net, 0.15):
                fails.append(net)
        gf = R.gnd_fanout() if not fails else []
        print(f"attempt {attempt}: fanout={fo} qfn_gnd_fail={qf} net fails={fails} "
              f"gnd fanout misses={gf} ({time.time() - t0:.1f}s)", flush=True)
        if os.environ.get("ROUTE_DEBUG"):
            R.to_board()
            board.Save(os.environ["ROUTE_DEBUG"])
            return 2
        if not fails and not qf:
            nst = R.stitch()
            print(f"stitching vias: {nst}")
            R.to_board()
            board.Save(PCB)
            return 0
        failed_first = [f for f in fails if f not in failed_first and f not in POWER_NETS] + failed_first
    return 1


if __name__ == "__main__":
    sys.exit(main())
