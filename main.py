"""Peeklate 進入點：熱鍵觸發截圖翻譯，結果顯示在 always-on-top 視窗。"""

import argparse
import queue
import threading

import config
from capture import grab_chat_region
from translator import translate_new_lines
from ui import TranslationWindow

_results: queue.Queue = queue.Queue()
_busy = threading.Event()


def _worker(image_path: str | None) -> None:
    try:
        if image_path:
            with open(image_path, "rb") as f:
                png = f.read()
        else:
            png = grab_chat_region()
        _results.put(("ok", translate_new_lines(png)))
    except Exception as e:  # API、截圖等任何失敗都回報到 UI
        _results.put(("error", e))
    finally:
        _busy.clear()


def main() -> None:
    parser = argparse.ArgumentParser(description="遊戲隊友聊天翻譯小工具")
    parser.add_argument("--image", help="開發用：跳過截圖，直接翻譯這張圖片檔")
    args = parser.parse_args()

    def trigger() -> None:
        if _busy.is_set():  # 前一次翻譯還在跑就忽略這次觸發
            return
        _busy.set()
        window.set_status("翻譯中…")
        threading.Thread(target=_worker, args=(args.image,), daemon=True).start()

    window = TranslationWindow(on_translate=trigger, show_original=config.SHOW_ORIGINAL)

    def poll() -> None:
        try:
            status, payload = _results.get_nowait()
        except queue.Empty:
            pass
        else:
            if status == "error":
                window.set_status(f"錯誤：{payload}")
            elif payload:
                for line in payload:
                    window.append_line(line.original, line.translation)
                window.set_status(f"就緒（新增 {len(payload)} 則）")
            else:
                window.set_status("就緒（沒有新訊息）")
        window.after(100, poll)

    # macOS 上 keyboard 需要輔助使用權限，失敗就只靠視窗按鈕觸發
    try:
        import keyboard

        keyboard.add_hotkey(config.HOTKEY, trigger)
        window.set_status(f"就緒（熱鍵 {config.HOTKEY.upper()}）")
    except Exception as e:
        window.set_status(f"熱鍵註冊失敗，請用「翻譯」按鈕（{e}）")

    window.after(100, poll)
    window.mainloop()


if __name__ == "__main__":
    main()
