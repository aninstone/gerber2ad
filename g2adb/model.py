"""
gerber2adb — Gerber/Excellon 逆向重建为 Altium Designer ASCII PCB (.PcbDoc)

坐标约定
--------
Gerber 与 AD ASCII PcbDoc 均为左下原点、Y 向上，故为 1:1 线性映射，无需翻转。
Gerber 单位 mm；AD ASCII 用 mil 后缀。1 mm = 39.3700787 mil。
"""
from __future__ import annotations

from dataclasses import dataclass, field

MM_PER_MIL = 0.0254


def mm2mil(v: float) -> float:
    return v / MM_PER_MIL


def fmt(v: float, nd: int = 4) -> str:
    s = f"{v:.{nd}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("", "-0", "-") else s


def fmtmil(v_mm: float, nd: int = 4) -> str:
    return f"{fmt(mm2mil(v_mm), nd)}mil"


@dataclass
class Flash:
    layer: str
    x: float
    y: float
    w: float
    h: float
    shape: str = "ROUND"


@dataclass
class Track:
    layer: str
    x1: float
    y1: float
    x2: float
    y2: float
    width: float
    net: int = -1


@dataclass
class Arc:
    layer: str
    x1: float
    y1: float
    x2: float
    y2: float
    cx: float | None
    cy: float | None
    width: float
    ccw: bool = True
    net: int = -1


@dataclass
class Region:
    layer: str
    pts: list
    net: int = -1


@dataclass
class Drill:
    x: float
    y: float
    d: float
    plated: bool = True
    slot: tuple | None = None      # (x1,y1,x2,y2) 槽孔


@dataclass
class Pad:
    x: float
    y: float
    w: float
    h: float
    shape: str = "ROUND"
    hole: float = 0.0
    layer: str = "MULTILAYER"
    net: int = -1
    slot: tuple | None = None
    is_via: bool = False
    plated: bool = True
    # 运行时辅助
    _w_line: float = 0.0
    _pads: list = None


@dataclass
class Text:
    layer: str
    x: float
    y: float
    height: float
    text: str
    width: float = 0.0
    rotation: float = 0.0
    net: int = -1
