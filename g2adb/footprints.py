"""焊盘聚类 -> 元件(封装)还原。

Gerber 里元件已经被"打散"成孤立的焊盘 Flash。本模块按几何规律把它们
重新组装成元件：

  1. 近邻聚类：焊盘间距小于阈值(默认 0.9mm)视为同一候选元件
     —— 覆盖 0402/0603/SOT-23/SOIC/QFP/排针/DIP 等常见封装
  2. 排列分析：对每个候选做 共线/等距/双列 检测，推断封装类型并命名
  3. 引脚编号：单排左->右，双列逆时针(pin1=左上)，其余按 (-y, x)

依据（KiCad 官方 Altium importer 源码 altium_parser_pcb.cpp / altium_pcb.cpp）：
  * Pad 的 COMPONENT = 所属元件在 Components6 流中的 **0-based 出现序号**
  * COMPONENT = 0 之外才有意义；自由图元不写该字段（等价 0）
  * Component 属性含 SOURCEDESIGNATOR（位号）与 PATTERN（封装名）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Component:
    pads: list = field(default_factory=list)     # Pad 列表(引用主列表的元素)
    x: float = 0.0                               # 原点 mm
    y: float = 0.0
    pattern: str = ""                            # 封装名
    designator: str = ""                         # 位号
    layer: str = "TOP"
    pin_names: dict = field(default_factory=dict)  # pad 索引 -> "1"/"2"/...


def _r(p):
    """焊盘等效半径(mm)：外接半径近似。"""
    return max(p.w, p.h) / 2.0


def _bbox(pads):
    xs = [p.x for p in pads]
    ys = [p.y for p in pads]
    return min(xs), min(ys), max(xs), max(ys)


def _line_fit_resid(pts):
    """最小二乘拟合直线，返回最大点线残差(mm)。"""
    n = len(pts)
    if n < 3:
        return 0.0
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    syy = sum((p[1] - my) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    # 主方向
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    c, s = math.cos(theta), math.sin(theta)
    return max(abs(-(p[0] - mx) * s + (p[1] - my) * c) for p in pts)


def _pitches_along(pads, axis):
    """沿 axis('x'/'y') 排序后的相邻间距列表。"""
    v = sorted((p.x if axis == "x" else p.y) for p in pads)
    return [b - a for a, b in zip(v, v[1:])]


def _uniform(dists, rel=0.10):
    """间距是否等距（标准差/均值 < rel）。"""
    if len(dists) < 2:
        return True
    m = sum(dists) / len(dists)
    if m <= 0:
        return False
    var = sum((d - m) ** 2 for d in dists) / len(dists)
    return math.sqrt(var) / m <= rel


# ---------------------------------------------------------------- 聚类
def group_components(pads, mech_holes, tol_gap=0.9, max_span=45.0):
    """把焊盘聚合成元件。

    pads     : 主焊盘列表(model.Pad)，通孔+SMD 混合
    mech_holes: 机械孔列表（不参与聚类）
    tol_gap  : 焊盘边缘间隙 < 该值(mm)则视为同一元件
    max_span : 候选元件包围盒长边超过该值(mm)则放弃（防止把铜皮/大阵列误判）
    返回 (components, free_pad_flags)
      free_pad_flags: 与 pads 等长的 bool 列表，True=不属于任何元件
    """
    n = len(pads)
    free = [True] * n

    # 机械孔中心集合（圆孔极易与排针焊盘重叠，跳过即可——机械孔不在 pads 里）
    hole_xy = [(h.x, h.y) for h in mech_holes]

    # 空间网格加速
    cell = 3.0
    buckets = {}
    for i, p in enumerate(pads):
        gx, gy = int(p.x // cell), int(p.y // cell)
        buckets.setdefault((gx, gy), []).append(i)

    dsu = list(range(n))

    def find(a):
        while dsu[a] != a:
            dsu[a] = dsu[dsu[a]]
            a = dsu[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            dsu[rb] = ra

    for (gx, gy), ids in buckets.items():
        cand = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cand += buckets.get((gx + dx, gy + dy), [])
        for a in ids:
            for b in cand:
                if b <= a:
                    continue
                pa, pb = pads[a], pads[b]
                d = math.hypot(pa.x - pb.x, pa.y - pb.y)
                if d <= _r(pa) + _r(pb) + tol_gap:
                    union(a, b)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    comps = []
    for root, members in groups.items():
        mem = sorted(members)
        grp = [pads[i] for i in mem]
        x0, y0, x1, y1 = _bbox(grp)
        span = max(x1 - x0, y1 - y0)

        # 单焊盘 / 超大聚合 / 含机械孔的大铜圈：保持自由
        if len(mem) < 2 or span > max_span:
            continue

        pts = [(p.x, p.y) for p in grp]
        resid = _line_fit_resid(pts)

        if resid < 0.15:
            # ---- 单排（排针/排阻/条形连接器）
            kind = "row"
        else:
            # ---- 双列检测：按主轴排序后分两半，各半共线
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            wide = (x1 - x0) >= (y1 - y0)
            if wide:
                half_a = [p for p in grp if p.x <= mx]
                half_b = [p for p in grp if p.x > mx]
            else:
                half_a = [p for p in grp if p.y <= my]
                half_b = [p for p in grp if p.y > my]
            ok = (len(half_a) == len(half_b) and len(half_a) >= 2
                  and _line_fit_resid([(p.x, p.y) for p in half_a]) < 0.15
                  and _line_fit_resid([(p.x, p.y) for p in half_b]) < 0.15)
            kind = "dual" if ok else "blob"

        # ---- 引脚编号
        pins = {}
        if kind == "row":
            axis = "x" if (x1 - x0) >= (y1 - y0) else "y"
            order = sorted(range(len(grp)),
                           key=lambda k: (grp[k].x if axis == "x" else grp[k].y))
            for no, k in enumerate(order, 1):
                pins[mem[k]] = str(no)
        elif kind == "dual":
            # 逆时针：pin1 = 左上(或右上，视列方向)，先上列左->右，再下列右->左
            wide = (x1 - x0) >= (y1 - y0)
            if wide:
                top = sorted([i for i in mem if pads[i].y >= my],
                             key=lambda i: pads[i].x)
                bot = sorted([i for i in mem if pads[i].y < my],
                             key=lambda i: -pads[i].x)
            else:
                top = sorted([i for i in mem if pads[i].x >= mx],
                             key=lambda i: -pads[i].y)
                bot = sorted([i for i in mem if pads[i].x < mx],
                             key=lambda i: pads[i].y)
            no = 1
            for i in top + bot:
                pins[i] = str(no)
                no += 1
        else:
            order = sorted(range(len(grp)), key=lambda k: (-grp[k].y, grp[k].x))
            for no, k in enumerate(order, 1):
                pins[mem[k]] = str(no)

        # ---- 封装命名
        pattern = _pattern_name(kind, grp)

        c = Component(pads=mem, x=(x0 + x1) / 2, y=(y0 + y1) / 2,
                      pattern=pattern, layer="TOP", pin_names=pins)
        comps.append(c)
        for i in mem:
            free[i] = False

    return comps, free


def _pattern_name(kind, grp):
    """按排列推断封装名（尽力而为，猜不出就给通用名）。"""
    n = len(grp)
    x0, y0, x1, y1 = _bbox(grp)

    if kind == "row":
        axis = "x" if (x1 - x0) >= (y1 - y0) else "y"
        pits = _pitches_along(grp, axis)
        pitch = sum(pits) / len(pits) if pits else 0
        if 2.3 <= pitch <= 2.8:
            return f"HDR-1x{n}"
        if 1.1 <= pitch <= 1.5:
            return f"HDR-1x{n}-1.27"
        if 0.7 <= pitch <= 1.0:
            return f"HDR-1x{n}-0.8"
        return f"ROW-{n}"

    if kind == "dual":
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        wide = (x1 - x0) >= (y1 - y0)
        if wide:
            rows = sorted(set(round(p.y, 3) for p in grp))
            cols = _pitches_along([p for p in grp if p.y >= my], "x")
        else:
            cols = sorted(set(round(p.x, 3) for p in grp))
            rows = _pitches_along([p for p in grp if p.x >= my], "y")
        pitch = (sum(cols) / len(cols)) if cols else 0
        npin = n // 2
        if 2.3 <= pitch <= 2.8:
            return f"DIP-{n}"
        if 1.1 <= pitch <= 1.45:
            return f"SOIC-{n}"
        if 0.75 <= pitch <= 0.9:
            return f"SSOP-{n}"
        if 0.55 <= pitch <= 0.7:
            return f"TSSOP-{n}"
        return f"DUAL-{npin}x2"

    # blob：两焊盘小件 / QFP / BGA 等
    if n == 2:
        return "SMD-2"
    if n <= 5:
        return f"SMD-{n}"
    return f"COMP-{n}"
