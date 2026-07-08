"""互動式框選 CHAT_REGION：全螢幕顯示當下截圖，拖曳框出聊天框，放開自動寫回 config.py。

用法：python pick_region.py [--monitor N]（N 從 1 起算，預設 1 = 主螢幕；Esc 取消）
"""

import argparse
import base64
import re
import sys
import tkinter as tk
from pathlib import Path

import mss
import mss.tools

CONFIG_PATH = Path(__file__).with_name("config.py")


def _write_config(region: dict) -> None:
    line = (f'CHAT_REGION = {{"left": {region["left"]}, "top": {region["top"]}, '
            f'"width": {region["width"]}, "height": {region["height"]}}}')
    text = CONFIG_PATH.read_text(encoding="utf-8")
    new, n = re.subn(r"^CHAT_REGION = \{.*\}$", line, text, count=1, flags=re.M)
    if n == 1:
        CONFIG_PATH.write_text(new, encoding="utf-8")
        print(f"已寫入 config.py：{line}")
        print("可執行 python capture.py 確認框選結果。")
    else:
        print("找不到 config.py 裡的 CHAT_REGION 行，請手動貼上：\n" + line)


def pick(monitor_index: int) -> None:
    if sys.platform == "win32":
        # 關掉 DPI 虛擬化，讓 tkinter 座標 = 實體像素 = mss 座標
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

    with mss.MSS() as sct:
        if monitor_index >= len(sct.monitors):
            sys.exit(f"沒有第 {monitor_index} 號螢幕（可用：1..{len(sct.monitors) - 1}）")
        mon = sct.monitors[monitor_index]
        shot = sct.grab(mon)
        png = mss.tools.to_png(shot.rgb, shot.size)

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")

    img = tk.PhotoImage(data=base64.b64encode(png))
    scale = max(1, round(shot.width / mon["width"]))  # Retina 等高 DPI 螢幕縮回邏輯像素
    if scale > 1:
        img = img.subsample(scale)

    canvas = tk.Canvas(root, width=mon["width"], height=mon["height"],
                       highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)
    canvas.create_image(0, 0, image=img, anchor="nw")
    canvas.create_text(mon["width"] // 2, 30, text="拖曳框選聊天框區域（Esc 取消）",
                       fill="#ff5555", font=("TkDefaultFont", 16, "bold"))

    state = {"x0": 0, "y0": 0, "rect": None}

    def press(e):
        state["x0"], state["y0"] = e.x, e.y
        state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#ff5555", width=2)

    def drag(e):
        canvas.coords(state["rect"], state["x0"], state["y0"], e.x, e.y)

    def release(e):
        w, h = abs(e.x - state["x0"]), abs(e.y - state["y0"])
        root.destroy()
        if w < 10 or h < 10:
            print("框選範圍太小，未更新。")
            return
        _write_config({
            "left": mon["left"] + min(state["x0"], e.x),
            "top": mon["top"] + min(state["y0"], e.y),
            "width": w,
            "height": h,
        })

    canvas.bind("<ButtonPress-1>", press)
    canvas.bind("<B1-Motion>", drag)
    canvas.bind("<ButtonRelease-1>", release)
    root.bind("<Escape>", lambda e: (root.destroy(), print("已取消。")))
    root.focus_force()
    root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="拖曳框選聊天框區域並寫回 config.py")
    parser.add_argument("--monitor", type=int, default=1, help="螢幕編號（1 = 主螢幕）")
    pick(parser.parse_args().monitor)
