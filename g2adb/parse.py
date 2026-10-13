"""Gerber / Excellon 解析 -> 统一图元几何(基于实测 gerbonara 1.6.3 API)。"""
from __future__ import annotations

import math
import os
import re
import warnings

from gerbonara import ExcellonFile, GerberFile

warnings.filterwarnings("ignore")

from .model import Arc, Drill, Flash, Region, Track

# AD 输出层名
AD_LAYER = {
    "TOP": "TOP", "BOTTOM": "BOTTOM",
    "TOPOVERLAY": "TOPOVERLAY", "BOTTOMOVERLAY": "BOTTOMOVERLAY",
    "TOPMASK": "TOPMASK", "BOTTOMMASK": "BOTTOMMASK",
    "TOPPASTE": "TOPPASTE", "BOTTOMPASTE": "BOTTOMPASTE",
    "KEEPOUT": "KEEPOUT", "MECHANICAL1": "MECHANICAL1",
    "DRILLDRAWING": "DRILLDRAWING",
}

# 内层(G1..G30) -> MID1..MID30
MID_LAYERS = {f"MID{i}": f"MID{i}" for i in range(1, 31)}
AD_LAYER.update(MID_LAYERS)
LAYER_ORDER = ["TOP", "BOTTOM"] + [f"MID{i}" for i in range(1, 31)] + [
    "TOPOVERLAY", "BOTTOMOVERLAY", "TOPMASK", "BOTTOMMASK",
    "TOPPASTE", "BOTTOMPASTE", "KEEPOUT", "MECHANICAL1", "DRILLDRAWING"]


def detect_layer(path: str):
    """通用层识别：兼容立创/Altium/KiCad 等各家的文件命名。

    优先级：
      1. **文件头里的 TF.FileFunction / FileFunction 注释**（最可靠，Gerber X2 标准）
      2. TF.GenerationSoftware 旁的长文件名（立创用 Gerbers_TopLayer.GTL 这种）
      3. 标准后缀 GTL/GBL/G1..G30/GTO/...（Altium/KiCad 用）
    """
    base = os.path.basename(path)
    low = base.lower()

    # --- 1) 读文件头，找 FileFunction（Gerber X2）
    try:
        with open(path, encoding="latin-1") as f:
            head = f.read(4096)
    except Exception:
        head = ""

    m = re.search(r"FileFunction\s*,\s*(\w+)\s*,\s*(\w*)", head, re.I)
    if m:
        cat, sub = m.group(1).lower(), (m.group(2) or "").lower()
        if cat == "copper":
            if sub in ("top", "ltop"):
                return "TOP"
            if sub in ("bot", "lbot", "bottom"):
                return "BOTTOM"
            mm = re.match(r"(\d+)", sub)
            if mm:
                return f"MID{mm.group(1)}"
        elif cat == "legend":
            return "TOPOVERLAY" if sub in ("top", "ltop", "") else "BOTTOMOVERLAY"
        elif cat == "soldermask":
            return "TOPMASK" if sub in ("top", "ltop", "") else "BOTTOMMASK"
        elif cat == "paste":
            return "TOPPASTE" if sub in ("top", "ltop", "") else "BOTTOMPASTE"
        elif cat == "profile":
            return "KEEPOUT"
        elif cat in ("drill", "plated", "nonplated"):
            return None

    # --- 2) 立创风格的长文件名（Gerber_TopLayer.GTL / ARDUINO-PCB_V6.GTL 等）
    for key, name in (
        ("topsilkscreen", "TOPOVERLAY"), ("bottomsilkscreen", "BOTTOMOVERLAY"),
        ("topsoldermask", "TOPMASK"), ("bottomsoldermask", "BOTTOMMASK"),
        ("toppastemask", "TOPPASTE"), ("bottompastemask", "BOTTOMPASTE"),
        ("boardoutline", "KEEPOUT"), ("documentlayer", "MECHANICAL1"),
        ("drilldrawing", "DRILLDRAWING"),
        ("toplayer", "TOP"), ("bottomlayer", "BOTTOM"),
    ):
        if key in low:
            return name

    # --- 3) 标准后缀（Altium / KiCad / 嘉立创通用）
    m = re.search(r"\.g(\d+|tl|bl|to|bo|ts|bs|tp|bs|p|ko|gm\d+|m\d+|d\d+"
                  r"|gg\d+|g\d+)\s*$", low)
    ext = None
    if m:
        e = m.group(1)
        if e == "tl":
            ext = "TOP"
        elif e == "bl":
            ext = "BOTTOM"
        elif e == "to":
            ext = "TOPOVERLAY"
        elif e == "bo":
            ext = "BOTTOMOVERLAY"
        elif e == "ts":
            ext = "TOPMASK"
        elif e == "bs":
            ext = "BOTTOMMASK"
        elif e == "tp":
            ext = "TOPPASTE"
        elif e == "p":
            ext = "BOTTOMPASTE"
        elif e == "ko":
            ext = "KEEPOUT"
        elif e.startswith("m") and e[1:].isdigit():
            ext = "MECHANICAL1"
        elif e.startswith("d") and e[1:].isdigit():
            ext = "DRILLDRAWING"
        elif e.startswith("gg"):
            return None                      # 钻孔图(仅示意，不还原)
        elif e.isdigit():
            # ⚠ G1/G2 **不一定是** TOP/BOTTOM —— 多层板里它们常是内层。
            # 交由 Layer_Physical_Order 决定；这里先标为"待定"。
            ext = f"_ORDER{e}"

    # --- 4) 用 Layer_Physical_Order(Altium 写入) 判定铜层物理顺序
    mo = re.search(r"Layer_Physical_Order\s*=\s*(\d+)", head)
    if mo:
        order = int(mo.group(1))
        cu = copper_by_order(order)
        if cu:
            return cu

    return ext


def copper_by_order(order: int):
    """Layer_Physical_Order -> 铜层名。
    Altium 约定：1=Top, 2..N=内层, 最后=Bottom。
    2 层板时 order1=TOP, order2=BOTTOM。
    """
    if order == 1:
        return "TOP"
    # order>=2 暂按下标推断；真正的 Bottom 需要知道总层数，
    # 由 main.collect 的二次校正处理（见 resolve_copper_layers）
    return None


def layer_physical_order(path: str):
    """读取 Altium 写入的 Layer_Physical_Order（无则返回 None）。"""
    try:
        with open(path, encoding="latin-1") as f:
            head = f.read(4096)
    except Exception:
        return None
    m = re.search(r"Layer_Physical_Order\s*=\s*(\d+)", head)
    return int(m.group(1)) if m else None


def is_copper_file(path: str) -> bool:
    """判断是否是铜层光绘(Gerber X2 FileFunction 或数字后缀)。"""
    low = os.path.basename(path).lower()
    try:
        with open(path, encoding="latin-1") as f:
            head = f.read(4096)
    except Exception:
        head = ""
    if re.search(r"FileFunction\s*,\s*Copper", head, re.I):
        return True
    return bool(re.search(r"\.(g\d+|gtl|gbl|ger|gbr)\s*$", low))


def is_drill_file(path: str) -> bool:
    """判断是否为 Excellon 钻孔文件。"""
    low = os.path.basename(path).lower()
    if low.endswith((".drl", ".xln", ".exc")):
        return True
    if "hole" in low or "drill" in low or "npth" in low or "pth" in low:
        return True
    try:
        with open(path, encoding="latin-1") as f:
            return f.readline().strip().upper().startswith("M48")
    except Exception:
        return False


def _mm(v, default=0.0):
    """Length / float -> mm float"""
    if v is None:
        return default
    if hasattr(v, "to"):
        try:
            return v.to("mm").value
        except Exception:
            pass
    try:
        return float(v)
    except Exception:
        return default


def _unit_scale(unit) -> float:
    """把 gerbonara 的单位对象换算成 mm 的乘数。"""
    if unit is None:
        return 1.0
    s = str(unit).strip().lower()
    if s in ("mm", "millimeter"):
        return 1.0
    if s in ("in", "inch"):
        return 25.4
    # LengthUnit 枚举：尝试取其 to('mm') 的比例
    try:
        return float(unit.to("mm").value) / 1.0 if unit.to("mm").value else 1.0
    except Exception:
        pass
    for name, k in (("in", 25.4), ("mm", 1.0), ("cm", 10.0), ("mil", 0.0254)):
        if name in s:
            return k
    return 1.0


def aperture_geom(ap, scale=1.0):
    """返回 (w_mm, h_mm, shape)。实测 gerbonara 1.6.3：
    - CircleAperture: .diameter (float)
    - RectangleAperture / ObroundAperture: .w / .h (float)
    - ApertureMacroInstance: .bounding_box()
    """
    cn = type(ap).__name__

    if cn == "CircleAperture":
        d = _mm(getattr(ap, "diameter", None), 0.2)
        return d, d, "ROUND"

    if cn in ("RectangleAperture", "ObroundAperture"):
        w = _mm(getattr(ap, "w", None), 0.2)
        h = _mm(getattr(ap, "h", None), 0.2)
        shape = "RECTANGLE" if cn == "RectangleAperture" else "RECTANGLE"
        return w, h, shape

    if cn in ("RoundRectAperture", "RoundedRectAperture"):
        return (_mm(getattr(ap, "w", None), 0.2),
                _mm(getattr(ap, "h", None), 0.2), "RECTANGLE")

    if cn in ("PolygonAperture", "RegularPolygonAperture"):
        d = _mm(getattr(ap, "diameter", None), 0.2)
        return d, d, "ROUND"

    if cn == "ApertureMacroInstance":
        try:
            bb = ap.bounding_box()
            x0, y0 = _mm(bb[0][0]), _mm(bb[0][1])
            x1, y1 = _mm(bb[1][0]), _mm(bb[1][1])
            return abs(x1 - x0), abs(y1 - y0), "RECTANGLE"
        except Exception:
            return 0.2, 0.2, "RECTANGLE"

    # 兜底：任意带 w/h 的
    w = _mm(getattr(ap, "w", None), None)
    h = _mm(getattr(ap, "h", None), None)
    if w is not None and h is not None:
        return w, h, "RECTANGLE"
    d = _mm(getattr(ap, "diameter", None), 0.2)
    return d, d, "ROUND"


def parse_gerber_layer(path: str, layer: str):
    """解析单层 Gerber。返回 (tracks, arcs, flashes, regions)。"""
    g = GerberFile.open(path)
    tracks, arcs, flashes, regions = [], [], [], []

    # ⚠ 关键：gerbonara 返回的坐标与光圈尺寸**保留文件原始单位**
    # (立创导出是 mm，Altium/KiCad 多为 inch)。统一换算到 mm。
    s = _unit_scale(getattr(g, "unit", None))

    for o in g.objects:
        cn = type(o).__name__

        if cn == "Line":
            w, _, _ = aperture_geom(o.aperture)
            tracks.append(Track(layer, o.x1 * s, o.y1 * s,
                                o.x2 * s, o.y2 * s, w * s))

        elif cn == "Arc":
            w, _, _ = aperture_geom(o.aperture)
            sx, sy = o.x1 * s, o.y1 * s
            ex, ey = o.x2 * s, o.y2 * s
            # ⚠ gerbonara 实测：cx/cy 是**相对当前点的偏移量**(G02/G03 的 I/J)，
            # 不是绝对圆心。绝对圆心 = 起点 + 偏移。
            cx = sx + (getattr(o, "cx", 0.0) or 0.0) * s
            cy = sy + (getattr(o, "cy", 0.0) or 0.0) * s
            arcs.append(Arc(layer, sx, sy, ex, ey, cx, cy, w * s,
                            ccw=not getattr(o, "clockwise", True)))

        elif cn == "Flash":
            w, h, shape = aperture_geom(o.aperture)
            flashes.append(Flash(layer, o.x * s, o.y * s, w * s, h * s, shape))

        elif cn == "Region":
            try:
                # ⚠ gerbonara 实测：Region.outline 的元素是 **tuple(x, y)**，
                # 不是带 .x/.y 的对象（Line/Arc 才是对象）。
                pts = []
                for p in o.outline:
                    if isinstance(p, (tuple, list)):
                        pts.append((p[0] * s, p[1] * s))
                    else:
                        pts.append((p.x * s, p.y * s))
            except Exception:
                continue
            if len(pts) >= 3:
                # ⚠ 必须保留极性：LPD(True)=实心，LPC(False)=挖空。
                # 铺铜层里大量 LPC 区域是走线间隙/避空，
                # 当成实心画出来会把整个板铺满。
                dark = getattr(o, "polarity_dark", True)
                regions.append(Region(layer, pts, dark=dark))

    return tracks, arcs, flashes, regions


def parse_drill(path: str, plated: bool = True):
    """解析 Excellon 钻孔文件，返回 Drill 列表(含槽孔)，坐标统一为 mm。

    gerbonara 实测：Excellon Flash 用 .aperture(ExcellonTool) 承载孔径，
    槽孔(G85)在 gerbonara 1.6.3 中以 Line 形式存在。
    ExcellonFile 没有 .unit 属性，单位需从文件头的 MO 行读取。
    """
    e = ExcellonFile.open(path)
    s = _drill_unit_scale(path)

    drills = []
    slots = []
    for o in e.objects:
        cn = type(o).__name__
        if cn == "Flash":
            ap = getattr(o, "aperture", None)
            d = _mm(getattr(ap, "diameter", None), 0.3) * s if ap else 0.3
            pl = getattr(ap, "plated", plated) if ap else plated
            drills.append(Drill(o.x * s, o.y * s, d, pl))
        elif cn == "Line":
            # 槽孔(G85)：gerbonara 以 Line 表示，两端点 + 孔径
            ap = getattr(o, "aperture", None)
            d = _mm(getattr(ap, "diameter", None), 0.3) * s if ap else 0.3
            pl = getattr(ap, "plated", plated) if ap else plated
            slots.append(Drill((o.x1 * s + o.x2 * s) / 2,
                               (o.y1 * s + o.y2 * s) / 2, d, pl,
                               slot=(o.x1 * s, o.y1 * s, o.x2 * s, o.y2 * s)))
    return drills, slots


def _drill_unit_scale(path: str) -> float:
    """从 Excellon 文件头读单位(默认 INCH)。"""
    try:
        with open(path, encoding="latin-1") as f:
            head = f.read(2048)
    except Exception:
        return 25.4
    import re as _re
    m = _re.search(r"^\s*(INCH|METRIC|IN|MM)\s*,", head, _re.M | _re.I)
    if not m:
        m = _re.search(r"^\s*(INCH|METRIC|IN|MM)\s*$", head, _re.M | _re.I)
    if not m:
        return 25.4
    u = m.group(1).upper()
    return 1.0 if u in ("METRIC", "MM") else 25.4
