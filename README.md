# gerber2ad — Gerber 逆向重建为 Altium Designer PCB

把 **Gerber + 钻孔文件** 逆向重建为 **Altium Designer 可编辑 PCB (.PcbDoc)**。

## 为什么不用现成工具

| 方案 | 问题 |
|---|---|
| 立创EDA标准版「Gerber→PCB」 | 实测只还原 **73 个对象 / 8 条走线**，绝大部分走线丢失，且无网络 |
| KiCad GerbView 导入 | 能还原图形，但得到一堆无网络、无封装的 `gr_line`，AD 里无法直接用 |
| 本工具 | **全部走线 + 焊盘 + 铺铜 + 推断网络**保留，直接输出 AD ASCII PcbDoc |

## 快速开始

### Windows（最简单）

1. 双击 **`setup-env.bat`** —— 一次性安装 Python 环境
2. 把 Gerber 文件夹（或 `.zip`）**拖到 `gerber2ad.bat` 上**
3. 输出在 `out\` 目录，用 AD 打开

### 命令行

```bash
python -m pip install gerbonara
python -m g2adb.main <gerber目录或zip> -o out.PcbDoc --template AD_template.PcbDoc
```

| 参数 | 说明 |
|---|---|
| `--template F` | 必需。AD ASCII PcbDoc 模板（见"为什么必须用模板"） |
| `--tol 0.02` | 几何连接容差(mm)，越小越严格 |
| `--no-nets` | 跳过网络推断，只还原纯几何 |
| `--drill-drawing` | 保留钻孔图层（默认跳过，文件大且无用） |

## 兼容性

已在以下两类差异极大的样本上实测通过：

| 样本 | 来源 | 层数 | 铜层单位 | 焊盘 | 铺铜 | 网络 |
|---|---|---|---|---|---|---|
| Arduino PC8 V6 | 立创EDA v6.5 | 2 | **mm** | 89 | 无 | 41 |
| L16S1K MainBoard | **Altium AD23** | **4** | **inch** | 2878 | **1633 个 Region** | 252 |

自动兼容的差异：

- **单位**：Gerber 的 `%MOIN*%`(英寸) 与 `%MOMM*%`(毫米)，钻孔文件同理
- **文件命名**：立创 `Gerber_TopLayer.GTL` / Altium `XXX.GTL` / KiCad `XXX-F_Cu.gbr`
- **层数**：2 层到 N 层，内层按 Altium 的 `Layer_Physical_Order` 判定
- **钻孔**：`Drill_PTH_Through.DRL` / `XXX-RoundHoles.TXT` / `*.xln`，含 G85 槽孔
- **铺铜**：Gerber Region（`G36/G37`）→ AD Polygon
- **光圈**：圆/矩形/腰圆/宏光圈(ApertureMacroInstance)

## 工作原理

### 1. 图元还原（不丢任何一根线）
逐条解析 `Line / Arc / Flash / Region`，1:1 输出为 AD 的 `Track / Arc / Pad / Polygon`。
走线宽度直接取自 Gerber 光圈(aperture)。

### 2. 焊盘还原（铜 + 钻孔 配对）
Gerber 的铜层 Flash 与 Excellon 钻孔是分离的，按位置配对：
- **孔 + 有铜** → 通孔焊盘，外形取各铜层对应 Flash 的**较大者**
- **孔 + 无铜** → NPTH 机械孔，输出到 Mechanical 层而非铜层
- **无孔铜** → SMD 焊盘
- **G85 槽孔** → 槽形焊盘

### 3. 网络重建（本工具的核心）
源文件通常**不含 IPC-356 网表**，Gerber 本身也不含网络信息。故用几何连通性推断：

| 判据 | 说明 |
|---|---|
| 焊盘铜面重叠 | 同层或通孔跨层 |
| 走线端点重合 | 同层 |
| T 型搭接 | 一条线端点落在另一条线段上 |
| 线端/线身落入焊盘铜面 | 按**焊盘铜面**判定（非钻孔），符合实际制程 |

通孔焊盘自动桥接所有铜层。网格空间索引加速，避免 O(n²)。
实测：4 层板 2878 焊盘 → 252 个网络。

### 4. 板框
Gerber 板框的**圆弧端点是切点、直边端点是倒角后顶点，两者不重合**
（差一个圆角半径），直接串接会断链。故取所有 KEEPOUT 图元端点求**凸包**
（Andrew monotone chain），圆弧额外采样 6 点贴合圆角。天然闭合。

实测：立创板 55.20×47.88mm，与原文件标注完全一致。

## 为什么必须用模板

AD ASCII 需要大量样板记录才能正常工作：82 个层声明、8 个 Class、
52 条 DRC Rule、以及 Board 记录里的 `SHEET*` / `PLANE1..16NETNAME`。
从零拼这些字段极易出错，因此本工具采用
**"经 AD 验证可打开的模板 + 追加图元"** 策略：只替换 `FILENAME` 和板框顶点。

仓库内 `AD_template.PcbDoc` 来自 [pcb2paf](https://github.com/hamid-rostami/pcb2paf)
（唯一从零生成且经 AD 验证可打开的开源实现）。

## AD ASCII 格式的坑

这是本项目最花时间的部分。以下每一条都实际导致过 AD 打开失败：

| # | 坑 | 正确做法 |
|---|---|---|
| 1 | `\|KIND=` / `\|ORIGINX=` 单独成行 | **必须与 `\|RECORD=Board` 同行**。AD 按行扫描，每行须是完整记录 |
| 2 | `VERSION=5.01` | 合法值是 **`5.00`** |
| 3 | 用 `\|RECORD=LayerStack` | **不存在此记录类型**。层栈用 Board 内 `LAYERnNAME`/`LAYERnPREV`/`LAYERnNEXT`（n=1..82） |
| 4 | 层名写 `TOP` | Board 里是 **`Top Layer`（带空格）**；图元里才是 `LAYER=TOP`（无空格），两套并存 |
| 5 | Pad 用 `COMPONENT=-1` | **Pad 没有 `COMPONENT=` 字段**（非法）。靠 `NAME=` |
| 6 | Pad 缺字段 | 必需 `PADMODE=0` + `PADXOFFSET0..31`/`PADYOFFSET0..31` 共 64 个 |
| 7 | Arc 用 `CX/CY/SA/EA` | 应为 **`LOCATION.X`/`LOCATION.Y` + `RADIUS`/`STARTANGLE`/`ENDANGLE`** |
| 8 | 铜皮用 `RECORD=Region` | 应为 **`RECORD=Polygon`**，顶点同为 `KINDn`/`VXn`/`VYn` 族 |
| 9 | 多边形不闭合 | **首尾顶点必须重复** |
| 10 | Track 缺 `SUBPOLYINDEX` | 补 `SUBPOLYINDEX=0`；建议带 `INDEXFORSAVE=n` |

> **为什么"立创EDA能开、AD报错"**：立创解析器只做 `|KEY=VALUE` 全局扫描，很宽容；
> AD 是严格按行解析 Record 的。上面第 1 条就是最初失败的直接原因。

## 已知限制

1. **网络名是推断的**（`Net1`/`Net4`…）。Gerber 不含此信息，需对照原理图重命名。
2. **无元件封装**。Gerber 不含元件边界/位号，需按丝印手工建封装。
3. **丝印文字是矢量线段**，不是可编辑 Text。外观 100% 保真，但改字需删线重画。
4. **铺铜作为实心 Polygon 输出**（`POUROVER=TRUE`），未按网络分区。
5. **无 DRC 规则定制**，沿用模板默认规则。

## 参考

- 官方规范：<http://www.eurointech.ru/products/Altium/Protel99SE_PCB_ASCII_File_Format.pdf>（36 页）
- 解析库：[gerbonara](https://gerbolyze.gitlab.io/gerbonara)
- 模板来源：[pcb2paf](https://github.com/hamid-rostami/pcb2paf)
- ⚠ KiCad 没有 Altium PCB ASCII 导出器（`altium_pcb.cpp` 只做二进制 CFB 导入）

## 文件结构

```
g2adb/
  model.py     # 图元数据结构 (Pad/Track/Arc/Region/Drill)
  parse.py     # Gerber + Excellon 解析、单位归一化、层识别
  nets.py      # 几何判定 + 并查集
  adwrite.py   # AD ASCII PcbDoc 输出（模板基底）
  main.py      # 主流程：解析→焊盘→网络→输出
gerber2ad.bat  # Windows 一键转换
setup-env.bat  # 环境安装
render.py      # 把 PcbDoc 渲染成 PNG，自检还原质量
AD_template.PcbDoc  # 经 AD 验证可打开的模板
```

## License

MIT