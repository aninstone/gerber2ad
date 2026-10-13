"""把生成的 PcbDoc 渲染成 PNG，与原 Gerber 视觉对比，验证还原质量。"""
import math
import re
import sys

MM_PER_MIL = 0.0254


def parse_pcb(path):
    pads, tracks, nets, outline = [], [], {}, []
    for ln in open(path, encoding="utf-8"):
        if not ln.startswith("|"):
            continue
        d = dict(re.findall(r"\|([A-Z0-9_]+)=([^|]*)", ln))
        rec = d.get("RECORD")
        f = lambda k: float(d[k][:-3]) * MM_PER_MIL if d.get(k, "").endswith("mil") else 0.0
        if rec == "Pad":
            pads.append(dict(
                x=f("X"), y=f("Y"), w=f("XSIZE"), h=f("YSIZE"),
                hole=f("HOLESIZE"), layer=d.get("LAYER", ""),
                shape=d.get("SHAPE", ""), net=int(d.get("NET", 0) or 0)))
        elif rec == "Track":
            tracks.append(dict(x1=f("X1"), y1=f("Y1"), x2=f("X2"), y2=f("Y2"),
                               w=f("WIDTH"), layer=d.get("LAYER", ""),
                               net=int(d.get("NET", 0) or 0)))
        elif rec == "Net":
            nets[int(d.get("ID", 0))] = d.get("NAME", "")
        elif rec == "Arc":
            cx, cy, r = f("CENTERX"), f("CENTERY"), f("RADIUS")
            sa, ea = math.radians(float(d.get("STARTANGLE", 0))), math.radians(float(d.get("ENDANGLE", 0)))
            n = 24
            for i in range(n + 1):
                t = sa + (ea - sa) * i / n
                outline.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return pads, tracks, nets, outline


COLORS = {
    "TOP": (200, 30, 30), "BOTTOM": (30, 90, 200), "MULTILAYER": (180, 40, 160),
    "TOPOVERLAY": (235, 235, 235), "TOPMASK": (40, 150, 90),
    "KEEPOUT": (255, 200, 0), "MECHANICAL1": (255, 200, 0),
}


def render(path, out_png, layers=None, size=1400):
    pads, tracks, nets, outline = parse_pcb(path)
    prims = pads + tracks
    if layers:
        prims = [p for p in prims if p.get("layer") in layers]
    xs, ys = [], []
    for p in prims:
        if "x" in p:
            xs += [p["x"] - p["w"] / 2, p["x"] + p["w"] / 2]
            ys += [p["y"] - p["h"] / 2, p["y"] + p["h"] / 2]
        else:
            xs += [p["x1"], p["x2"]]
            ys += [p["y1"], p["y2"]]
    if not xs:
        print("无图元")
        return
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pad = 20
    sc = min((size - 2 * pad) / max(x1 - x0, 1e-6), (size - 2 * pad) / max(y1 - y0, 1e-6))
    W = H = size

    px = [[(18, 18, 22) for _ in range(W)] for _ in range(H)]

    def put(x, y, c):
        xi, yi = int(x), int(y)
        if 0 <= xi < W and 0 <= yi < H:
            px[yi][xi] = c

    def T(x, y):
        return (pad + (x - x0) * sc, H - pad - (y - y0) * sc)

    def dot(x, y, r, c):
        cx, cy = x, y
        rr = max(int(r), 0)
        for dy in range(-rr, rr + 1):
            for dx in range(-rr, rr + 1):
                if dx * dx + dy * dy <= rr * rr:
                    put(cx + dx, cy + dy, c)

    for p in tracks:
        c = COLORS.get(p["layer"], (120, 120, 120))
        a = T(p["x1"], p["y1"]); b = T(p["x2"], p["y2"])
        steps = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
        r = max(p["w"] * sc / 2, 0.6)
        for i in range(steps + 1):
            t = i / max(steps, 1)
            dot(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, r, c)

    for p in pads:
        c = COLORS.get(p["layer"], (150, 150, 150))
        cx, cy = T(p["x"], p["y"])
        hw, hh = p["w"] * sc / 2, p["h"] * sc / 2
        if p["shape"] == "ROUND":
            rr = max(int(min(hw, hh)), 1)
            for dy in range(-rr, rr + 1):
                for dx in range(-rr, rr + 1):
                    if dx * dx + dy * dy <= rr * rr:
                        put(int(cx + dx), int(cy + dy), c)
        else:
            for dy in range(int(-hh), int(hh) + 1):
                for dx in range(int(-hw), int(hw) + 1):
                    put(int(cx + dx), int(cy + dy), c)
        if p["hole"] > 0:
            hr = max(int(p["hole"] * sc / 2), 1)
            for dy in range(-hr, hr + 1):
                for dx in range(-hr, hr + 1):
                    if dx * dx + dy * dy <= hr * hr:
                        put(int(cx + dx), int(cy + dy), (18, 18, 22))

    try:
        from PIL import Image
        buf = bytearray(W * H * 3)
        for yy in range(H):
            row = px[yy]
            base = yy * W * 3
            for xx in range(W):
                r, g, b = row[xx]
                o = base + xx * 3
                buf[o] = r
                buf[o + 1] = g
                buf[o + 2] = b
        img = Image.frombytes("RGB", (W, H), bytes(buf))
        img.save(out_png)
        print(f"已渲染 {out_png}  ({W}x{H})  pads={len(pads)} tracks={len(tracks)} nets={len(nets)}")
        print(f"  板尺寸: {(x1-x0)/MM_PER_MIL:.1f} x {(y1-y0)/MM_PER_MIL:.1f} mil "
              f"= {(x1-x0):.1f} x {(y1-y0):.1f} mm")
    except ImportError:
        print("无 PIL")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "out/Arduino_PCB_V6.PcbDoc"
    out = sys.argv[2] if len(sys.argv) > 2 else "out/preview.png"
    lay = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None
    render(src, out, lay)
