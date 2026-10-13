"""几何连通性 -> 网络重建。

没有 IPC-356 时，Gerber 里不含任何网络信息。这里用纯几何手段重建：
  * 同层：图元之间发生"重叠/端点相接"即视为导通
  * 跨层：通孔焊盘 / 过孔把所在的所有铜层连起来
由此得到的连通分量即各网络(GND、VCC、各信号线)。

这是逆向 PCB 的核心难点，也是立创EDA标准版逆向导入缺失的部分。
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------- 基础几何
def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def dist_point_seg(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = _clamp(t, 0.0, 1.0)
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def seg_seg_dist(x1, y1, x2, y2, x3, y3, x4, y4) -> float:
    def cross(ax, ay, bx, by, cx, cy):
        return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

    d1 = cross(x1, y1, x2, y2, x3, y3)
    d2 = cross(x1, y1, x2, y2, x4, y4)
    d3 = cross(x3, y3, x4, y4, x1, y1)
    d4 = cross(x3, y3, x4, y4, x2, y2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return 0.0
    return min(
        dist_point_seg(x3, y3, x1, y1, x2, y2),
        dist_point_seg(x4, y4, x1, y1, x2, y2),
        dist_point_seg(x1, y1, x3, y3, x4, y4),
        dist_point_seg(x2, y2, x3, y3, x4, y4),
    )


def point_in_poly(px, py, pts) -> bool:
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            xint = (x2 - x1) * (py - y1) / (y2 - y1) + x1
            if px < xint:
                inside = not inside
    return inside


def poly_bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------- 并查集
class DSU:
    def __init__(self, n):
        self.p = list(range(n))
        self.r = [0] * n

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.r[ra] < self.r[rb]:
            ra, rb = rb, ra
        self.p[rb] = ra
        if self.r[ra] == self.r[rb]:
            self.r[ra] += 1


# ---------------------------------------------------------------- 连接判定
TOL = 0.02  # mm，几何容差


def seg_touches_pad(x1, y1, x2, y2, pad, tol=TOL) -> bool:
    """线段是否与(圆/矩形)焊盘导通。
    焊盘铜面 >= 钻孔，故按焊盘外形判定铜连接，符合实际制程。
    """
    hw, hh = pad.w / 2.0, pad.h / 2.0
    r = (hw + hh) / 2.0
    # 线段中点到焊盘中心的距离 <= 焊盘半径 + 半线宽
    half_w = (pad._w_line or 0.0) / 2.0
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    # 端点/中点采样更稳
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        px = x1 + (x2 - x1) * t
        py = y1 + (y2 - y1) * t
        if pad.shape == "ROUND":
            if math.hypot(px - pad.x, py - pad.y) <= r + half_w + tol:
                return True
        else:
            dx = abs(px - pad.x) - hw
            dy = abs(py - pad.y) - hh
            if dx <= half_w + tol and dy <= half_w + tol:
                return True
    return False


def pad_touches_pad(a, b, tol=TOL) -> bool:
    if a.shape == "ROUND" and b.shape == "ROUND":
        ra = (a.w + a.h) / 4.0
        rb = (b.w + b.h) / 4.0
        return math.hypot(a.x - b.x, a.y - b.y) <= ra + rb + tol
    # 矩形/混合：用 bbox 近似
    ax0, ay0, ax1, ay1 = a.x - a.w / 2, a.y - a.h / 2, a.x + a.w / 2, a.y + a.h / 2
    bx0, by0, bx1, by1 = b.x - b.w / 2, b.y - b.h / 2, b.x + b.w / 2, b.y + b.h / 2
    return not (ax0 - tol > bx1 or bx0 - tol > ax1 or ay0 - tol > by1 or by0 - tol > ay1)
