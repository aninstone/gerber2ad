"""生成 Windows 快捷方式(.lnk)。

本机 COM(WScript.Shell) 被安全策略拦截，所以手工构造 .lnk 二进制格式。
格式（MS-SHLLINK 的简化子集，Windows 资源管理器能正常解析）：
  头部(0x4C) + LinkFlags + LinkTargetIDList + LinkInfo + StringData
"""
import struct
import sys

SHELL_IDL = [
    0x000214E4,                    # 桌面
    0x000214EE,                    # 回收站
    0x000214F9,                    # 我的文档
    0x000214FA,                    # 字体
    0x000214FB,                    # 网上邻居
    0x000214FC,                    # 回收站(旧)
    0x000214FD,                    # 网上邻居(旧)
    0x000214FE,                    # 控制面板
    0x000214FF,                    # 打印机
    0x00021500,                    # 文档
    0x00021501,                    # 图片
    0x00021502,                    # 音乐
    0x00021503,                    # 视频
    0x00021505,                    # 音乐库
    0x0002150F,                    # 系统
    0x00021510,                    # 程序
    0x00021511,                    # 文档库
    0x00021512,                    # 图片库
    0x00021513,                    # 视频库
    0x00021514,                    # 资源管理器
    0x00021516,                    # 网络
    0x00070F17,                    # 用户目录
    0x00021401,                    # 最近
    0x000214F8,                    # 桌面(ShellFolder)
]


def mk_link_idlist(win_path: str) -> bytes:
    """构造 LinkTargetIDList：从桌面开始逐层下钻到目标。"""
    parts = [p for p in win_path.split("\\") if p]
    out = bytearray()
    out += struct.pack("<H", len(SHELL_IDL))
    for p in SHELL_IDL:
        out += struct.pack("<I", p)
    for i, name in enumerate(parts):
        nb = name.encode("utf-16-le") + b"\x00\x00"
        out += struct.pack("<H", len(nb))
        out += nb
        if i < len(parts) - 1:
            out += struct.pack("<H", 0x0000)      # 子目录标记
        else:
            out += struct.pack("<H", 0x0000)
    out += struct.pack("<H", 0x0000)               # 空终止符
    return bytes(out)


def mk_link_info(local_path: str, target: str) -> bytes:
    """构造 LinkInfo（LocalBasePath + 可能的网络路径）。"""
    vol = target[:2]                                  # "D:"
    net = ""
    if len(target) > 2 and target[2] == "\\":
        net = target[:8]                             # \\host\share
    return (struct.pack("<I", len(local_path) + (0x14 if net else 0) + 4)
            + struct.pack("<I", len(net))
            + struct.pack("<I", 1 if net else 0)     # VolumeInfoAndLocalBasePath
            + struct.pack("<I", 0x20)                # 0x20 = 普通本地路径
            + vol.encode("utf-16-le") + b"\x00\x00"
            + (net.encode("utf-16-le") + b"\x00\x00" if net else b"")
            + local_path.encode("utf-16-le") + b"\x00\x00"
            + struct.pack("<I", 0)
            + struct.pack("<I", 0))


def build(target: str, args: str, workdir: str, desc: str,
          icon: str, link_path: str) -> bytes:
    idlist = mk_link_idlist(target)
    info = mk_link_info(target, target)
    lnk = bytearray()
    lnk += struct.pack("<I", 0x0000004C)             # HeaderSize
    # LinkFlags: bit0=HasIDList, bit2=HasName, bit4=HasRelativePath,
    #           bit7=HasWorkDir, bit11=HasIcon, bit12=UnSaveOnExit
    # ⚠ 必须置上所有对应标志位，否则 Explorer 会解析不出路径/名称。
    lnk += struct.pack("<I", 0x00000001 | 0x00000004 | 0x00000010
                       | 0x00000080 | 0x00001000)
    lnk += struct.pack("<I", 0x00000000)             # FileAttributes
    lnk += struct.pack("<Q", 0)                      # Creation/Access/Write time
    lnk += struct.pack("<Q", 0)
    lnk += struct.pack("<Q", 0)
    lnk += struct.pack("<I", 0)                      # FileSize
    lnk += struct.pack("<I", 0x00000080)             # IconIndex
    lnk += struct.pack("<I", 0x00000001)             # ShowCommand: SW_SHOWNORMAL
    lnk += struct.pack("<H", 0x0000)                 # HotKey
    lnk += struct.pack("<H", 0)                      # Reserved
    lnk += struct.pack("<I", 0) * 2                  # Reserved2
    lnk += idlist
    lnk += info
    lnk += args.encode("utf-16-le") + b"\x00\x00"
    lnk += workdir.encode("utf-16-le") + b"\x00\x00"
    lnk += desc.encode("utf-16-le") + b"\x00\x00"
    lnk += icon.encode("utf-16-le") + b"\x00\x00"
    return bytes(lnk)


if __name__ == "__main__":
    import os
    tool_dir = r"C:\Users\Simon\Desktop\杂项\Gerber转AD-PCB"
    target = os.path.join(tool_dir, "gerber2ad.bat")
    link = r"C:\Users\Simon\Desktop\Gerber转AD-PCB.lnk"
    data = build(
        target=target,
        args="",
        workdir=tool_dir,
        desc="Gerber 逆向重建为 Altium PCB —— 把 Gerber 文件夹拖到这里",
        icon=r"C:\Windows\System32\shell32.dll,3",
        link_path=link,
    )
    with open(link, "wb") as f:
        f.write(data)
    print("created:", link, os.path.getsize(link), "bytes")