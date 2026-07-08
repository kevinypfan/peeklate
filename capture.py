"""截圖模組 — 抓取 config.CHAT_REGION 指定的聊天框區域。"""

import logging
from datetime import datetime
from pathlib import Path

import mss
import mss.tools

import config

log = logging.getLogger(__name__)


def grab_chat_region() -> bytes:
    """截取聊天框區域，回傳 PNG bytes（不落地）。

    mss 非跨執行緒安全，因此每次呼叫都在函式內建立實例，
    讓 worker thread 可以安全呼叫。
    """
    with mss.MSS() as sct:
        shot = sct.grab(config.CHAT_REGION)
        return mss.tools.to_png(shot.rgb, shot.size)


def save_capture(png_bytes: bytes) -> Path | None:
    """config.SAVE_CAPTURES 開啟時，把截圖存到 CAPTURE_DIR，回傳路徑；否則 None。"""
    if not config.SAVE_CAPTURES:
        return None
    out_dir = Path(__file__).parent / config.CAPTURE_DIR
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"capture_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
    path.write_bytes(png_bytes)
    log.info("已存截圖 %s", path)
    return path


if __name__ == "__main__":
    # 校準模式：存一張區域預覽圖並開啟，方便反覆調整 CHAT_REGION
    import os
    import subprocess
    import sys

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "region_preview.png")
    with open(path, "wb") as f:
        f.write(grab_chat_region())

    print(f"已存檔：{path}")
    print(f"截圖區域：{config.CHAT_REGION}")

    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", path])
    else:
        subprocess.run(["xdg-open", path])
