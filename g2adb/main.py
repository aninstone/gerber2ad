"""
gerber2adb 主程序：Gerber + Excellon -> Altium Designer ASCII PcbDoc

用法:
  python -m g2adb.main <gerber目录或zip> -o out.PcbDoc
"""
from __future__ import annotations

import argparse
import glob
import math
import os
import re
import sys
import tempfile
import zipfile

from . import parse as P
from . import footprints as F
from .adwrite import AdAsciiWriter
from .model import Arc, Drill, Flash, Pad, Region, Track
from .nets import DSU, dist_point_seg, seg_touches_pad, pad_touches_pad, TOL

COPPER = ("TOP", "BOTTOM")


def extract(zip_path, dest):
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)
    return dest


def collect(src, keep_drill_drawing=False):
    """扫描目录 -> ({层名: 文件路径}, [钻孔文件])

    兼容各厂命名：
      * 立创  Gerbers_TopLayer.GTL / Drill_PTH_Through.DRL
      * Altium  XXX.GTL / XXX-RoundHoles.TXT
      * KiCad   XXX-F_Cu.gbr / XXX-PTH.drl

    铜层的 TOP/内层/BOTTOM 归属按 Altium 的 `Layer_Physical_Order` 属性判定
    （这是唯一可靠依据：4 层板的 .G1 其实是内层，不是顶铜）。
    """
    files = []
    for p in sorted(glob.glob(os.path.join(src, "**", "*"), recursive=True)):
        if not os.path.isfile(p):
            continue
        low = os.path.basename(p).lower()
        if low.endswith((".rep", ".rul", ".l2p", ".l2p1", ".apr_lib",
                         ".extrep", ".drr", ".ldp", ".rpt", ".eos", ".txt")):
            # .txt 可能是钻孔，交由 is_drill_file 判断
            if not P.is_drill_file(p):
                continue
        files.append(p)

    gmap, drills = {}, []
    for p in files:
        if P.is_drill_file(p):
            drills.append(p)
            continue
        lay = P.detect_layer(p)
        if lay:
            # 钻孔图/钻孔示意层动辄上万条线，且对 PCB 还原无实质用处，默认跳过
            if lay == "DRILLDRAWING" and not keep_drill_drawing:
                continue
            gmap[lay] = p

    # --- 铜层校正：按 Layer_Physical_Order 重新分配 TOP / MIDn / BOTTOM
    copper_files = []
    for p in files:
        o = P.layer_physical_order(p)
        if o is not None and P.is_copper_file(p):
            copper_files.append((o, p))
    if copper_files:
        copper_files.sort(key=lambda t: t[0])
        # 删除此前按后缀误判的占位层（_ORDERn / 顶底铜）
        for lay in list(gmap):
            if lay.startswith("_ORDER"):
                del gmap[lay]
            elif lay in ("TOP", "BOTTOM"):
                del gmap[lay]
        n = len(copper_files)
        for idx, (_order, p) in enumerate(copper_files):
            if idx == 0:
                name = "TOP"
            elif idx == n - 1:
                name = "BOTTOM"
            else:
                name = f"MID{idx}"
            gmap[name] = p
    return gmap, drills


def re_gerber(low: str) -> bool:
    return low.endswith((".gtl", ".gbl", ".gto", ".gbo", ".gts", ".gbs",
                         ".gtp", ".gbp", ".gko", ".gdl", ".gdd", ".gm1", ".g1",
                         ".g2", ".g3", ".ger"))


def copper_layers(gmap):
    """实际存在的铜层(含内层)，按 TOP->MID->BOTTOM 排序。"""
    def key(l):
        if l == "TOP":
            return (0, 0)
        if l == "BOTTOM":
            return (2, 0)
        m = re.match(r"MID(\d+)$", l)
        return (1, int(m.group(1))) if m else (1, 999)
    return sorted([l for l in gmap if l == "TOP" or l == "BOTTOM"
                   or re.match(r"MID\d+$", l)], key=key)


# --------------------------------------------------------------- 焊盘还原
def build_pads(flashes_by_layer, drills, copper, tol=0.08):
    """把 铜层Flash + 钻孔 合成真正的 Pad。

    - PTH 有孔 + 有铜 => 通孔焊盘(外形取各铜层对应 Flash 的较大者)
    - NPTH 无铜的孔 => 非金属化安装孔，按机械孔输出(不带铜)
    - 无孔铜 Flash => SMD 焊盘
    返回 (pads, mech_holes)
    """
    import math

    pads = []
    mech_holes = []
    consumed = set()      # (layer, index) 已被吸收进 Pad 的铜 Flash

    def find_flash(dr):
        """在所有铜层上找包含该孔的 Flash。返回 [(lay, i, f), ...]"""
        hit = []
        for lay in copper:
            for i, f in enumerate(flashes_by_layer.get(lay, [])):
                if (lay, i) in consumed:
                    continue
                if f.shape == "ROUND":
                    r = f.w / 2.0
                    if math.hypot(f.x - dr.x, f.y - dr.y) <= r + tol:
                        hit.append((lay, i, f))
                else:
                    if (abs(f.x - dr.x) <= f.w / 2 + tol and
                            abs(f.y - dr.y) <= f.h / 2 + tol):
                        hit.append((lay, i, f))
        return hit

    # 1) 处理所有孔
    for dr in drills:
        hits = find_flash(dr)

        if hits:
            # 取面积最大的铜面作为焊盘外形(顶底可能不同)
            lay, i, f = max(hits, key=lambda t: t[2].w * t[2].h)
            for (l2, i2, _f2) in hits:
                consumed.add((l2, i2))
            pads.append(Pad(x=dr.x, y=dr.y, w=f.w, h=f.h, shape=f.shape,
                            hole=dr.d, layer="MULTILAYER", plated=dr.plated,
                            slot=dr.slot))
        else:
            # 无铜的孔 => 机械孔(NPTH 安装孔 / 螺丝孔)
            mech_holes.append(Drill(dr.x, dr.y, dr.d, dr.plated, dr.slot))

    # 2) 剩余铜 Flash = SMD 焊盘
    for lay in copper:
        for i, f in enumerate(flashes_by_layer.get(lay, [])):
            if (lay, i) in consumed:
                continue
            pads.append(Pad(x=f.x, y=f.y, w=f.w, h=f.h, shape=f.shape,
                            hole=0.0, layer=lay))

    return pads, mech_holes


def mark_connected_tracks(pads, tracks, tol=TOL):
    """标注每条走线所连通的焊盘集合(用 DSU 节点)。"""
    for t in tracks:
        hits = []
        for k, p in enumerate(pads):
            if p.layer not in ("MULTILAYER", t.layer):
                continue
            p._w_line = t.width
            if seg_touches_pad(t.x1, t.y1, t.x2, t.y2, p, tol):
                hits.append(k)
        t._pads = hits
    return tracks


def infer_nets(pads, tracks, verbose=True):
    """几何连通 -> 网络编号。

    连通判据(全部基于真实制程规则)：
      1) 焊盘之间铜面重叠          -> 导通
      2) 走线之间端点重合 / T 型搭接 -> 导通
      3) 走线端点或中部落入焊盘铜面 -> 导通
      4) 通孔焊盘(MULTILAYER)连接顶底两层 -> 跨层导通
    返回 (pad_net, trk_net, net_names)；索引与入参一一对应。
    """
    np_, nt = len(pads), len(tracks)
    n = np_ + nt
    dsu = DSU(n)

    def ti(i):
        return np_ + i

    # ---- 1) 焊盘间重叠
    for i in range(np_):
        for j in range(i + 1, np_):
            a, b = pads[i], pads[j]
            if a.layer not in ("MULTILAYER", b.layer):
                continue
            if pad_touches_pad(a, b):
                dsu.union(i, j)

    # ---- 2) 走线-走线：共享端点 或 端点落在另一条线段上
    # 用网格加速
    cell = 1.0
    buckets = {}
    for idx, t in enumerate(tracks):
        key0 = (int(min(t.x1, t.x2) // cell), int(min(t.y1, t.y2) // cell))
        key1 = (int(max(t.x1, t.x2) // cell), int(max(t.y1, t.y2) // cell))
        for gx in range(key0[0], key1[0] + 1):
            for gy in range(key0[1], key1[1] + 1):
                buckets.setdefault((gx, gy), []).append(idx)

    seen_pairs = set()
    for cellkey, ids in buckets.items():
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                i, j = ids[a], ids[b]
                if (i, j) in seen_pairs:
                    continue
                seen_pairs.add((i, j))
                t, u = tracks[i], tracks[j]
                if t.layer != u.layer:
                    continue
                tol = (t.width + u.width) / 2 + TOL
                # 端点重合
                ep_t = [(t.x1, t.y1), (t.x2, t.y2)]
                ep_u = [(u.x1, u.y1), (u.x2, u.y2)]
                joined = False
                for (px, py) in ep_t:
                    for (qx, qy) in ep_u:
                        if abs(px - qx) <= tol and abs(py - qy) <= tol:
                            joined = True
                            break
                    if joined:
                        break
                # T 型：u 的端点落在 t 的线段上
                if not joined:
                    for (px, py) in ep_t:
                        if _pt_on_seg(px, py, u, tol):
                            joined = True
                            break
                if not joined:
                    for (px, py) in ep_u:
                        if _pt_on_seg(px, py, t, tol):
                            joined = True
                            break
                if joined:
                    dsu.union(ti(i), ti(j))

    # ---- 3) 走线-焊盘
    for idx, t in enumerate(tracks):
        for k, p in enumerate(pads):
            if p.layer not in ("MULTILAYER", t.layer):
                continue
            p._w_line = t.width
            if seg_touches_pad(t.x1, t.y1, t.x2, t.y2, p):
                dsu.union(ti(idx), k)

    # ---- 分组
    groups = {}
    for i in range(n):
        groups.setdefault(dsu.find(i), []).append(i)

    pad_net = {}
    trk_net = {}
    names = {}
    idx = 0
    for root in sorted(groups, key=lambda r: min(groups[r])):
        members = groups[root]
        if not any(i < np_ for i in members):
            continue          # 纯走线组(悬空)不建网络
        idx += 1
        for i in members:
            if i < np_:
                pad_net[i] = idx
            else:
                trk_net[i - np_] = idx
        names[idx] = f"Net{idx}"

    return pad_net, trk_net, names


def _pt_on_seg(px, py, t, tol):
    """点是否落在线段(含半宽)上。"""
    from .nets import dist_point_seg
    d = dist_point_seg(px, py, t.x1, t.y1, t.x2, t.y2)
    return d <= t.width / 2 + tol


def _arc_radius(a):
    import math
    cx = a.cx if a.cx is not None else (a.x1 + a.x2) / 2
    cy = a.cy if a.cy is not None else (a.y1 + a.y2) / 2
    return math.hypot(a.x1 - cx, a.y1 - cy)


def _ang(a, which):
    """圆弧起止角(度)。"""
    import math
    cx = a.cx if a.cx is not None else (a.x1 + a.x2) / 2
    cy = a.cy if a.cy is not None else (a.y1 + a.y2) / 2
    px, py = (a.x1, a.y1) if which == 0 else (a.x2, a.y2)
    return math.degrees(math.atan2(py - cy, px - cx)) % 360


def build_outline(tracks, arcs):
    """把 KEEPOUT(GKO) 层的线段/圆弧串成闭合多边形顶点序列。

    GKO 层就是板框。Gerber 里的板框通常由若干 Line + 圆角 Arc 组成，
    这里按端点首尾相接的方式串起来；圆弧用其端点(圆角对板框尺寸影响 <0.15mm)。
    """
    segs = [(t.x1, t.y1, t.x2, t.y2) for t in tracks if t.layer == "KEEPOUT"]
    # 圆弧：gerbonara 的 Arc 有 .x1/.y1/.x2/.y2(两端点)
    for a in arcs:
        if a.layer != "KEEPOUT":
            continue
        if getattr(a, "x1", None) is None or getattr(a, "x2", None) is None:
            continue
        segs.append((a.x1, a.y1, a.x2, a.y2))
    if not segs:
        return []
    pts = [(segs[0][0], segs[0][1])]
    cur = (segs[0][2], segs[0][3])
    used = [False] * len(segs)
    used[0] = True
    T = 0.05
    for _ in range(len(segs) * 2):
        found = False
        for i, s in enumerate(segs):
            if used[i]:
                continue
            x1, y1, x2, y2 = s
            if abs(x1 - cur[0]) <= T and abs(y1 - cur[1]) <= T:
                pts.append((x2, y2))
                cur = (x2, y2)
            elif abs(x2 - cur[0]) <= T and abs(y2 - cur[1]) <= T:
                pts.append((x1, y1))
                cur = (x1, y1)
            else:
                continue
            used[i] = True
            found = True
            break
        if not found:
            break
    return pts


def _convex_hull(points):
    """Andrew monotone chain 凸包。"""
    pts = sorted(set((round(x, 4), round(y, 4)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def build_outline(tracks, arcs):
    """生成板框闭合多边形。

    GKO 层即板框。直边与圆角圆弧的端点并不重合(Gerber 里圆弧两端是切点，
    直边端点是倒角后顶点，相差一个倒角半径)，直接串环会断链。
    这里取所有 KEEPOUT 图元的端点求**凸包**作为板框：
    对矩形板而言结果就是精确的外轮廓，误差 <= 圆角半径，且天然闭合。
    """
    pts = []
    for t in tracks:
        if t.layer == "KEEPOUT":
            pts += [(t.x1, t.y1), (t.x2, t.y2)]
    for a in arcs:
        if a.layer == "KEEPOUT" and getattr(a, "x1", None) is not None:
            pts += [(a.x1, a.y1), (a.x2, a.y2)]
            # 圆弧采样中间点，让圆角更贴合
            import math as _m
            cx, cy = a.cx, a.cy
            if cx is not None and cy is not None:
                r = _m.hypot(a.x1 - cx, a.y1 - cy)
                a0 = _m.atan2(a.y1 - cy, a.x1 - cx)
                a1 = _m.atan2(a.y2 - cy, a.x2 - cx)
                # 归一化到最近的方向
                if a.ccw:
                    while a1 < a0:
                        a1 += 2 * _m.pi
                else:
                    while a1 > a0:
                        a1 -= 2 * _m.pi
                for k in range(1, 6):
                    th = a0 + (a1 - a0) * k / 6.0
                    pts.append((cx + r * _m.cos(th), cy + r * _m.sin(th)))
    if not pts:
        return []
    return _convex_hull(pts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gerber/Excellon -> Altium ASCII PcbDoc")
    ap.add_argument("src", help="Gerber 目录或 .zip")
    ap.add_argument("-o", "--out", default="out.PcbDoc")
    ap.add_argument("--template", required=True,
                    help="经 AD 验证可打开的 ASCII PcbDoc 模板文件")
    ap.add_argument("--no-nets", action="store_true", help="跳过网络推断")
    ap.add_argument("--no-components", action="store_true",
                    help="跳过元件还原(焊盘保持自由)")
    ap.add_argument("--group-gap", type=float, default=0.9,
                    help="元件聚类间隙阈值 mm (默认 0.9)")
    ap.add_argument("--drill-drawing", action="store_true",
                    help="保留钻孔图/钻孔示意层(默认跳过，文件很大且无用)")
    ap.add_argument("--tol", type=float, default=TOL)
    args = ap.parse_args(argv)

    src = args.src
    if zipfile.is_zipfile(src):
        tmp = tempfile.mkdtemp(prefix="g2adb_")
        src = extract(src, tmp)

    gmap, drill_files = collect(src, keep_drill_drawing=args.drill_drawing)
    cu = copper_layers(gmap)
    print(f"识别到的层 (共 {len(gmap)}):")
    for k in sorted(gmap, key=lambda x: (x not in cu, x)):
        print(f"   {k:14s} <- {os.path.basename(gmap[k])}")
    print(f"铜层: {cu if cu else '(无)'}")
    print("钻孔文件:", [os.path.basename(d) for d in drill_files])

    # 解析
    tracks, arcs, flashes, regions = [], [], {}, {}
    for lay, path in gmap.items():
        try:
            t, a, f, r = P.parse_gerber_layer(path, lay)
        except Exception as e:
            print(f"   !! {lay} 解析失败: {type(e).__name__}: {e}")
            continue
        tracks += t
        arcs += a
        flashes[lay] = f
        regions[lay] = r
        print(f"   {lay:14s} track={len(t):4d} arc={len(a):3d} "
              f"flash={len(f):4d} region={len(r):4d}")

    drills = []
    for dp in drill_files:
        bn = os.path.basename(dp).lower()
        plated = "npth" in bn or "non_plated" in bn or "nonplated" in bn
        try:
            d, slots = P.parse_drill(dp, plated)
        except Exception as e:
            print(f"   !! {os.path.basename(dp)} 解析失败: "
                  f"{type(e).__name__}: {e}")
            continue
        drills += d + slots
        print(f"   {os.path.basename(dp):40s} 孔={len(d)} 槽={len(slots)}")

    if not gmap:
        raise SystemExit("未识别到任何 Gerber 层文件。"
                         "请确认目录里是 Gerber 光绘文件(.GTL/.GBL/.G1... 或 *-F_Cu.gbr)。")

    # 焊盘
    pads, mech_holes = build_pads(flashes, drills, cu, tol=max(args.tol, 0.08))
    print(f"\n焊盘还原: 共 {len(pads)} 个 "
          f"(通孔={sum(1 for p in pads if p.hole>0)}, "
          f"SMD={sum(1 for p in pads if p.hole<=0)}), "
          f"机械孔={len(mech_holes)}")

    # 铜层走线才参与网络推断
    cu_tracks = [t for t in tracks if t.layer in cu]
    mark_connected_tracks(pads, cu_tracks, args.tol)

    if args.no_nets:
        pad_net = {i: 0 for i in range(len(pads))}
        trk_net = {len(pads) + i: 0 for i in range(len(cu_tracks))}
        names = {}
    else:
        pad_net, trk_net, names = infer_nets(pads, cu_tracks)
        print(f"网络推断: 得到 {len(names)} 个网络")

    # 板框多边形(由 GKO 的线段+圆弧串成闭环)
    outline = build_outline(tracks, arcs)

    # 元件还原：焊盘聚类 -> Component（封装/位号/引脚号）
    comps = []
    free_pads = [True] * len(pads)
    if not args.no_components:
        comps, free_pads = F.group_components(pads, mech_holes,
                                              tol_gap=args.group_gap)
        kinds = {}
        for c in comps:
            kinds[c.pattern] = kinds.get(c.pattern, 0) + 1
        top = sorted(kinds.items(), key=lambda t: -t[1])[:8]
        print(f"元件还原: {len(comps)} 个元件 "
              f"(自由焊盘 {sum(free_pads)} 个)\n"
              f"   封装分布: " + ", ".join(f"{k}x{v}" for k, v in top))

    # 输出：模板基底 + 追加图元
    tpl = args.template
    if not os.path.isfile(tpl):
        raise SystemExit(f"找不到 AD ASCII 模板: {tpl}\n"
                         f"请用 --template 指定一个经 AD 验证可打开的 ASCII PcbDoc")
    w = AdAsciiWriter(tpl)
    lines = w.rewrite_board(w.load_template_lines(),
                            filename=os.path.basename(args.out),
                            outline_pts=outline,
                            copper=cu)

    # 网络
    for nid in sorted(names):
        lines.append(w.net(nid, names[nid]))

    # 元件记录：ID 从 1 起；Pad 的 COMPONENT 写相同值（0=自由焊盘）
    comp_of_pad = {}
    for ci, c in enumerate(comps):
        lines.append(w.component(c.x, c.y, c.pattern,
                                 f"REF{ci + 1}", ci))
        for pi in c.pads:
            comp_of_pad[pi] = (ci + 1, c.pin_names.get(pi, ""))

    # 焊盘(铜 + 机械孔)：归属元件的带 COMPONENT/NAME
    for i, p in enumerate(pads):
        ci, pin = comp_of_pad.get(i, (None, ""))
        lines.append(w.pad(p.layer, p.x, p.y, p.w, p.h, p.shape,
                           hole=p.hole, plated=p.plated,
                           net=pad_net.get(i, 0),
                           name=pin, comp=ci))
    for h in mech_holes:
        lines.append(w.pad("MECHANICAL1", h.x, h.y, h.d, h.d, "ROUND",
                           hole=h.d, plated=False, net=0))

    # 铜层走线
    for ti, t in enumerate(cu_tracks):
        lines.append(w.track(t.layer, t.x1, t.y1, t.x2, t.y2, t.width,
                             net=trk_net.get(ti, 0)))
    for a in arcs:
        if a.layer in cu:
            lines.append(w.arc(a.layer, a.cx, a.cy,
                               _arc_radius(a),
                               _ang(a, 0), _ang(a, 1), a.width))

    # 填充区(Gerber Region -> AD Polygon)
    # ⚠ 只输出 **实心(LPD)** 区域。Gerber 铺铜层里的 LPC(挖空)区域是
    # 走线间隙/避空区，画成实心会把整块板铺满(实测糊成一片)。
    # 另外 pour=False：Gerber 里已是"最终铜形"，不需要 AD 重新灌铜，
    # 开启 POUROVER 反而会让 AD 把相邻多边形并成一整块。
    n_dark = n_clear = 0
    for lay, regs in regions.items():
        for r in regs:
            if r.dark:
                n_dark += 1
                lines.append(w.polygon(lay, r.pts, pour=False))
            else:
                n_clear += 1
    print(f"铺铜区域: 实心 {n_dark} 个(已输出)  挖空 {n_clear} 个(按 Gerber 语义忽略)")

    # 丝印 / 阻焊 / 锡膏 / 机械 线
    for t in tracks:
        if t.layer not in cu:
            lines.append(w.track(t.layer, t.x1, t.y1, t.x2, t.y2, t.width))
    for a in arcs:
        if a.layer not in cu:
            lines.append(w.arc(a.layer, a.cx, a.cy, _arc_radius(a),
                               _ang(a, 0), _ang(a, 1), a.width))

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="latin-1", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n已输出: {args.out}")
    print(f"  记录行数 {len(lines)}   文件大小 {os.path.getsize(args.out)} 字节")
    print(f"  板框顶点 {len(outline)} 个   网络 {len(names)} 个")
    if not outline:
        print("  ⚠ 未找到板框层(GKO/GML)，AD 里板框可能需手工重画")


if __name__ == "__main__":
    main()
