"""
Altium Designer ASCII PCB (.PcbDoc) 输出 —— 模板基底方案。

**关键设计依据（实测 + 官方 Protel99SE ASCII 规范）**

AD 的 ASCII 解析器**按行扫描**，每行必须是一个完整的 `|RECORD=...` 记录：
1. `|KIND=Protel_Advanced_PCB`、`|VERSION=`、`|ORIGINX=` 等**必须与 `|RECORD=Board` 同行**。
   拆成多行会让 AD 在读 Board 头时直接判非法 —— 这是"立创EDA能开、AD报错"的根因。
2. `VERSION` 合法值是 `5.00`（不是 5.01）。
3. **不存在 `RECORD=LayerStack`**。层栈由 Board 记录内的 `LAYERnNAME`/`LAYERnPREV`/
   `LAYERnNEXT` 字段族声明（n=1..82），且**层名带空格**（`Top Layer`）；
   而图元记录里的 `LAYER=TOP` 用无空格大写。两套命名并存。
4. Pad **没有** `COMPONENT=` 字段（非法）；组件归属靠 `NAME=`(引脚号)。
   另有必需的 `PADMODE` 与 `PADXOFFSET0..31`/`PADYOFFSET0..31` 共 64 个字段。
5. Track 需 `SUBPOLYINDEX=0`；各图元建议带 `INDEXFORSAVE=n`。
6. Arc 用 `LOCATION.X`/`LOCATION.Y` + `RADIUS`/`STARTANGLE`/`ENDANGLE`，
   **不是** CX/CY。
7. 板框是多边形顶点 `KINDn`/`VXn`/`VYn`/`CXn`/`CYn`/`SAn`/`EAn`/`Rn`，
   写在 `RECORD=Board` 内，**首尾顶点重复**表示闭合。
8. 铜皮用 `RECORD=Polygon`（同样用 KINDn/VXn 顶点族），不是 `RECORD=Region`。

因此本模块采取 **"模板基底 + 追加图元"** 策略：
以一个经 AD 验证可打开的模板为基底，替换 FILENAME / 板框顶点 / 图层名，
再按 AD 的原生语法追加 Pad / Track / Arc / Polygon 记录。
这样自动继承全部 82 层声明、8 个 Class、52 条 DRC 规则与 SHEET 参数。
"""
from __future__ import annotations

import math
import re

MM_PER_MIL = 0.0254

# AD 图元记录里的层名（无空格大写）
LAYER_NAME = {
    "TOP": "TOP",
    "BOTTOM": "BOTTOM",
    "MULTILAYER": "MULTILAYER",
    "TOPOVERLAY": "TOPOVERLAY",
    "BOTTOMOVERLAY": "BOTTOMOVERLAY",
    "TOPMASK": "TOPMASK",
    "BOTTOMMASK": "BOTTOMMASK",
    "TOPPASTE": "TOPPASTE",
    "BOTTOMPASTE": "BOTTOMPASTE",
    "KEEPOUT": "KEEPOUT",
    "MECHANICAL1": "MECHANICAL1",
    "DRILLDRAWING": "DRILLDRAWING",
}

# 内层：MID1..MID30 -> AD 的 Mid-Layer 1..30 (MIDLAYER1..)
for _i in range(1, 31):
    LAYER_NAME[f"MID{_i}"] = f"MIDLAYER{_i}"


def m(v_mm: float, nd: int = 4) -> str:
    """mm -> 'NNNNmil'（AD 要求带 mil 后缀）"""
    x = v_mm / MM_PER_MIL
    s = f"{x:.{nd}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("", "-", "-0"):
        s = "0"
    return s + "mil"


class AdAsciiWriter:
    """基于模板输出 AD ASCII PcbDoc。"""

    def __init__(self, template_path: str, board_name: str = "PCB1"):
        self.tpl = template_path
        self.board_name = board_name
        self._idx = 0

    # ------------------------------------------------------------ 基底
    def load_template_lines(self) -> list:
        with open(self.tpl, encoding="latin-1") as f:
            return f.read().splitlines()

    def next_index(self) -> int:
        v = self._idx
        self._idx += 1
        return v

    # ------------------------------------------------------------ Board
    @staticmethod
    def rewrite_board(lines: list, filename: str, outline_pts=None) -> list:
        """替换模板首行的 FILENAME 与板框顶点。"""
        out = []
        for i, ln in enumerate(lines):
            if i == 0:
                ln = re.sub(r"\|FILENAME=[^|]*", "|FILENAME=" + filename,
                            ln, count=1)
                ln = re.sub(r"\|SNAPGRIDSIZE=[^|]*",
                            "|SNAPGRIDSIZE=1000.000000", ln)
                ln = re.sub(r"\|TRACKGRIDSIZE=[^|]*",
                            "|TRACKGRIDSIZE=1000.000000", ln)
                ln = re.sub(r"\|VIAGRIDSIZE=[^|]*",
                            "|VIAGRIDSIZE=1000.000000", ln)
                ln = re.sub(r"\|VISIBLEGRIDSIZE=[^|]*",
                            "|VISIBLEGRIDSIZE=10000.000", ln)
                ln = re.sub(r"\|BIGVISIBLEGRIDSIZE=[^|]*",
                            "|BIGVISIBLEGRIDSIZE=100000.000", ln)
                if outline_pts:
                    ln = AdAsciiWriter._set_outline(ln, outline_pts)
            out.append(ln)
        return out

    @staticmethod
    def _set_outline(ln: str, pts) -> str:
        """替换板框顶点为给定多边形(首尾闭合)。"""
        # 移除原有顶点字段(每个顶点是一个字段组)
        pat = (r"\|KIND\d+=[^|]*\|VX\d+=[^|]*\|VY\d+=[^|]*"
               r"\|CX\d+=[^|]*\|CY\d+=[^|]*"
               r"\|SA\d+=[^|]*\|EA\d+=[^|]*\|R\d+=[^|]*")
        ln = re.sub(pat, "", ln)

        p = list(pts)
        if p[0] != p[-1]:
            p = p + [p[0]]
        seg = []
        for i, (x, y) in enumerate(p):
            seg.append(f"|KIND{i}=0|VX{i}={m(x)}|VY{i}={m(y)}"
                       f"|CX{i}=0mil|CY{i}=0mil"
                       f"|SA{i}= 0.00000000000000E+0000"
                       f"|EA{i}= 0.00000000000000E+0000|R{i}=0mil")
        anchor = "|PLANE16NETNAME=(No Net)"
        if anchor in ln:
            return ln.replace(anchor, anchor + "".join(seg), 1)
        return ln + "".join(seg)

    # ------------------------------------------------------------ 图元
    def track(self, layer, x1, y1, x2, y2, width, net=0) -> str:
        L = LAYER_NAME.get(layer, layer)
        return (f"|RECORD=Track|INDEXFORSAVE={self.next_index()}"
                f"|SELECTION=FALSE|LAYER={L}|LOCKED=FALSE"
                f"|POLYGONOUTLINE=FALSE|USERROUTED=TRUE|UNIONINDEX=0"
                f"|X1={m(x1)}|Y1={m(y1)}|X2={m(x2)}|Y2={m(y2)}"
                f"|WIDTH={m(width)}|SUBPOLYINDEX=0|NET={net}")

    def arc(self, layer, cx, cy, radius, start_ang, end_ang, width, net=0) -> str:
        L = LAYER_NAME.get(layer, layer)
        return (f"|RECORD=Arc|INDEXFORSAVE={self.next_index()}"
                f"|SELECTION=FALSE|LAYER={L}|LOCKED=FALSE"
                f"|POLYGONOUTLINE=FALSE|USERROUTED=TRUE|UNIONINDEX=0"
                f"|LOCATION.X={m(cx)}|LOCATION.Y={m(cy)}"
                f"|RADIUS={m(radius)}|STARTANGLE={start_ang:.3f}"
                f"|ENDANGLE={end_ang:.3f}|WIDTH={m(width)}"
                f"|SUBPOLYINDEX=0|NET={net}")

    def pad(self, layer, x, y, w, h, shape="ROUND", hole=0.0,
            plated=True, net=0, name="") -> str:
        """Pad：严格按 AD 原生字段序列。"""
        L = LAYER_NAME.get(layer, layer)
        if hole > 0:
            L = "MULTILAYER"
        sh = {"ROUND": "ROUND", "RECTANGLE": "RECTANGLE",
              "OBLONG": "RECTANGLE", "OCTAGON": "OCTAGON"}.get(shape, "ROUND")
        s = (f"|RECORD=Pad|INDEXFORSAVE={self.next_index()}"
             f"|SELECTION=FALSE|LAYER={L}|LOCKED=FALSE"
             f"|POLYGONOUTLINE=FALSE|USERROUTED=TRUE|UNIONINDEX=0"
             f"|NAME={name or '0'}"
             f"|X={m(x)}|Y={m(y)}|XSIZE={m(w)}|YSIZE={m(h)}|SHAPE={sh}")
        if hole > 0:
            s += (f"|HOLESIZE={m(hole)}"
                  f"|ROTATION= 0.00000000000000E+0000"
                  f"|PLATED={'TRUE' if plated else 'FALSE'}"
                  f"|DAISYCHAIN=Load|CCSV=0|CPLV=0|CCWV=1|CENV=1"
                  f"|CAGV=1|CPEV=1|CSEV=1|CPCV=1|CPRV=1"
                  f"|CCW=10mil|CEN=4|CAG=10mil|CPE=0mil|CSE=4mil"
                  f"|CPC=20mil|CPR=20mil|PADMODE=0"
                  f"|SWAPID_PAD=|SWAPID_GATE=|&|0|SWAPPEDPADNAME=|GATEID=0"
                  f"|OVERRIDEWITHV6_6SHAPES=FALSE|DRILLTYPE=0|HOLETYPE=0"
                  f"|HOLEWIDTH={m(hole)}"
                  f"|HOLEROTATION= 0.00000000000000E+0000")
        else:
            s += (f"|ROTATION= 0.00000000000000E+0000"
                  f"|PLATED={'TRUE' if plated else 'FALSE'}|PADMODE=0")
        for i in range(32):
            s += f"|PADXOFFSET{i}=0mil|PADYOFFSET{i}=0mil"
        s += f"|PADJUMPERID=0|NET={net}"
        return s

    def net(self, net_id: int, name: str) -> str:
        return (f"|RECORD=Net|ID={net_id}|SELECTION=FALSE|NAME={name}"
                f"|VISIBLE=TRUE|COLOR=8421376")

    def polygon(self, layer, pts, net=0, pour=True) -> str:
        """铜皮/填充区：AD 用 RECORD=Polygon + KINDn/VXn 顶点族。"""
        L = LAYER_NAME.get(layer, layer)
        p = list(pts)
        if p[0] != p[-1]:
            p = p + [p[0]]
        seg = []
        for i, (x, y) in enumerate(p):
            seg.append(f"|KIND{i}=0|VX{i}={m(x)}|VY{i}={m(y)}"
                       f"|CX{i}=0mil|CY{i}=0mil"
                       f"|SA{i}= 0.00000000000000E+0000"
                       f"|EA{i}= 0.00000000000000E+0000|R{i}=0mil")
        return (f"|RECORD=Polygon|ID={self.next_index()}"
                f"|SELECTION=FALSE|LAYER={L}|LOCKED=FALSE"
                f"|POLYGONOUTLINE={'FALSE' if pour else 'TRUE'}"
                f"|USERROUTED=TRUE|PRIMITIVELOCK=TRUE|POLYGONTYPE=Polygon"
                f"|POUROVER=TRUE|REMOVEDEAD=TRUE"
                f"|GRIDSIZE=20mil|TRACKWIDTH=8mil|HATCHSTYLE=90Degree"
                f"|USEOCTAGONS=FALSE|MINPRIMLENGTH=3mil"
                f"|NET={net}" + "".join(seg))

    def text(self, layer, x, y, height, s, rot=0.0, mirror=False) -> str:
        L = LAYER_NAME.get(layer, layer)
        return (f"|RECORD=Text|INDEXFORSAVE={self.next_index()}"
                f"|SELECTION=FALSE|LAYER={L}|LOCKED=FALSE"
                f"|POLYGONOUTLINE=FALSE|USERROUTED=TRUE|UNIONINDEX=0"
                f"|TEXT={s}|X={m(x)}|Y={m(y)}|HEIGHT={m(height)}"
                f"|WIDTH={m(height * 0.8)}|ROTATION={rot:.3f}"
                f"|FONTNAME=Default|ISMIRRORED={'TRUE' if mirror else 'FALSE'}")