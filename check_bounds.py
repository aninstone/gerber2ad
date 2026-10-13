"""检查生成的 PcbDoc：各铜层图元是否溢出板框。"""
import re
import sys
from collections import defaultdict

P = sys.argv[1] if len(sys.argv) > 1 else "out/ad4.PcbDoc"
ls = open(P, encoding="latin-1").read().splitlines()


def mil(v):
    v = v.strip()
    try:
        return float(v[:-3]) if v.endswith("mil") else float(v)
    except Exception:
        return 0.0


vx = re.findall(r"\|VX\d+=([^|]+)\|VY\d+=([^|]+)", ls[0])
bx = [mil(a) for a, b in vx]
by = [mil(b) for a, b in vx]
BX0, BX1 = min(bx), max(bx)
BY0, BY1 = min(by), max(by)
print(f"板框(mil): X[{BX0:.0f},{BX1:.0f}] Y[{BY0:.0f},{BY1:.0f}]"
      f"  = {(BX1-BX0)*0.0254:.1f} x {(BY1-BY0)*0.0254:.1f} mm")

bb = defaultdict(lambda: [1e18, -1e18, 1e18, -1e18])
cnt = defaultdict(int)
for ln in ls:
    if not re.search(r"RECORD=(Track|Arc|Pad|Polygon)", ln):
        continue
    lay = re.search(r"LAYER=(\w+)", ln)
    if not lay:
        continue
    L = lay.group(1)
    vals = [mil(v) for v in
            re.findall(r"[XY](?:1|2)?=(-?[\d.]+)mil", ln)]
    if not vals:
        continue
    xs, ys = vals[0::2], vals[1::2]
    if not xs or not ys:
        continue
    a, b, c, d = bb[L]
    bb[L] = [min(a, min(xs)), max(b, max(xs)),
             min(c, min(ys)), max(d, max(ys))]
    cnt[L] += 1

print()
print("各层图元范围 vs 板框:")
for L in ("TOP", "MIDLAYER1", "MIDLAYER2", "BOTTOM", "MULTILAYER"):
    if L not in bb:
        continue
    a, b, c, d = bb[L]
    out = []
    if a < BX0 - 1:
        out.append(f"左溢出 {BX0-a:.0f}mil")
    if b > BX1 + 1:
        out.append(f"右溢出 {b-BX1:.0f}mil")
    if c < BY0 - 1:
        out.append(f"下溢出 {BY0-c:.0f}mil")
    if d > BY1 + 1:
        out.append(f"上溢出 {d-BY1:.0f}mil")
    flag = "  ".join(out) if out else "OK 在板内"
    print(f"  {L:12s} n={cnt[L]:6d} X[{a:8.0f},{b:8.0f}] "
          f"Y[{c:8.0f},{d:8.0f}]  {flag}")

print()
pol = sum(1 for ln in ls if "RECORD=Polygon" in ln)
print(f"Polygon 总数: {pol}")
for ln in ls:
    if "RECORD=Polygon" in ln:
        print("  POUROVER:", re.search(r"POUROVER=(\w+)", ln).group(1),
              " POLYGONOUTLINE:", re.search(r"POLYGONOUTLINE=(\w+)", ln).group(1))
        break
names = re.findall(r"RECORD=Pad\|[^|]*\|NAME=([^|]*)\|", "\n".join(ls))
print(f"Pad NAME 分布: 空={names.count('')} 非空={len(names)-names.count('')}"
      f"  样例非空={ [x for x in names if x][:5] }")