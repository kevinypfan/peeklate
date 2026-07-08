"""集中設定 logging：同時輸出到終端機與專案目錄下的 peeklate.log。

各模組用 logging.getLogger(__name__) 取得 logger 即可，進入點呼叫一次
configure() 設定輸出。
"""

import logging
import sys
from pathlib import Path

LOG_PATH = Path(__file__).parent / "peeklate.log"

# 第三方套件在 DEBUG 下會非常吵（httpx 每個請求、google genai 內部…），
# 非 --debug 時壓到 WARNING，只留我們自己的訊息。
_NOISY = ["httpx", "httpcore", "google", "google_genai", "pydantic_ai", "openai"]

_configured = False


def configure(debug: bool = False) -> None:
    """設定 root logger；重複呼叫只生效第一次。"""
    global _configured
    if _configured:
        return
    _configured = True

    level = logging.DEBUG if debug else logging.INFO
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s", datefmt="%H:%M:%S"
    )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)

    # 檔案保留完整歷史，方便事後回看（每次啟動附加，不清空）
    file = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers[:] = [console, file]

    if not debug:
        for name in _NOISY:
            logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("peeklate").info(
        "logging 啟動（level=%s，檔案=%s）", logging.getLevelName(level), LOG_PATH
    )
