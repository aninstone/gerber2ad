"""模拟用户双击 bat 后，在窗口里拖拽/粘贴路径的场景。

生成 GBK 编码的输入文件喂给 cmd（真实 cmd 是 GBK 代码页）。
覆盖三种输入形态：
  1. 带引号的中文路径（从资源管理器"复制文件地址"粘贴）
  2. 不带引号的中文+空格路径（拖文件夹到 cmd 窗口自动填入）
  3. 拖 .zip 到 cmd 窗口
"""
import subprocess
import sys

BAT = r"C:\Users\Simon\Desktop\杂项\Gerber转AD-PCB\gerber2ad.bat"
OUT = r"D:\workbuddy\2026-10-13-15-00-34\gerber2pcb\sim_in.txt"

cases = {
    "quoted_zh":   r'"D:\WorkPRJ\工作同事\LTS 绕线机\LTS-Respooler-main\PCB Gerber Files\Manufacturing_Driver-Board_V1\Manufacturing_Driver-Board_V1\Gerber_Driver-Board_V1.zip"',
    "plain_zh":    r'D:\WorkPRJ\工作同事\LTS 绕线机\LTS-Respooler-main\PCB Gerber Files\Manufacturing_Driver-Board_V1\Manufacturing_Driver-Board_V1\Gerber_Driver-Board_V1.zip',
}

for name, path in cases.items():
    with open(OUT, "w", encoding="gbk") as f:
        f.write(path + "\r\n")
    r = subprocess.run(
        ["cmd", "/c", BAT],
        stdin=open(OUT, "rb"), capture_output=True, timeout=900,
    )
    out = r.stdout.decode("gbk", errors="replace")
    ok = "[DONE]" in out
    fail = "[FAILED]" in out
    print(f"### {name}: {'DONE' if ok else ('FAILED' if fail else '???')} "
          f"(exit={r.returncode})")
    # 打印关键行
    for ln in out.splitlines():
        if any(k in ln for k in ("Input :", "Output:", "已输出", "[DONE]",
                                 "[FAILED]", "[ERROR]", "Error", "Traceback")):
            print("   ", ln.strip())
    print()
