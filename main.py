"""Peeklate 進入點：熱鍵觸發截圖翻譯，結果顯示在 always-on-top 視窗。"""

import argparse
import logging
import queue
import threading
from collections import deque

import config
import logsetup
from capture import grab_chat_region, save_capture
from translator import compose_reply, translate_new_lines
from ui import TranslationWindow

log = logging.getLogger("peeklate.main")

_results: queue.Queue = queue.Queue()
_busy = threading.Event()  # 翻譯單線
_compose_busy = threading.Event()  # 回覆生成單線（與翻譯互不阻擋）
# 最近翻譯到的隊友對話，供生成回覆時當情境。只在 poll（主執行緒）寫入。
_recent: deque = deque(maxlen=config.COMPOSE_CONTEXT_LINES)


def _worker(image_path: str | None, player_names: list[str]) -> None:
    try:
        if image_path:
            log.info("讀取圖片檔 %s", image_path)
            with open(image_path, "rb") as f:
                png = f.read()
        else:
            png = grab_chat_region()
            log.info("截圖完成（%d bytes，區域 %s）", len(png), config.CHAT_REGION)
            save_capture(png)  # SAVE_CAPTURES 開啟時才會落地
        _results.put((
            "ok",
            translate_new_lines(
                png,
                player_names,
                # 限流重試等待時把進度顯示到狀態列，不然看起來像當機
                on_status=lambda msg: _results.put(("status", msg)),
            ),
        ))
    except Exception as e:  # API、截圖等任何失敗都回報到 UI
        log.exception("翻譯失敗")  # 完整 traceback 進 log
        _results.put(("error", e))
    finally:
        _busy.clear()


def _compose_worker(text: str, context: list) -> None:
    try:
        options = compose_reply(
            text,
            context,
            on_status=lambda msg: _results.put(("status", msg)),
        )
        _results.put(("reply", options))
    except Exception as e:
        log.exception("回覆生成失敗")
        _results.put(("error", e))
    finally:
        _compose_busy.clear()


def main() -> None:
    parser = argparse.ArgumentParser(description="遊戲隊友聊天翻譯小工具")
    parser.add_argument("--image", help="開發用：跳過截圖，直接翻譯這張圖片檔")
    parser.add_argument(
        "--debug", action="store_true", help="輸出更詳細的 log（含每則 OCR 內容）"
    )
    args = parser.parse_args()
    logsetup.configure(args.debug)

    def trigger() -> None:
        if _busy.is_set():  # 前一次翻譯還在跑就忽略這次觸發
            log.debug("上一次翻譯還在跑，忽略這次觸發")
            return
        _busy.set()
        players = window.get_player_names()
        log.info("觸發翻譯（只看 %s）", players or "全部")
        window.set_status("翻譯中…")
        threading.Thread(
            target=_worker, args=(args.image, players), daemon=True
        ).start()

    def compose_trigger() -> None:
        if _compose_busy.is_set():  # 前一次還在生成就忽略
            log.debug("上一次回覆還在生成，忽略這次觸發")
            return
        text = window.get_reply_text()
        if not text:
            window.set_status("先在「想回」輸入框打要說的話")
            return
        _compose_busy.set()
        context = list(_recent)  # 快照，避免跨執行緒讀 deque
        log.info("觸發回覆生成（帶 %d 則情境）", len(context))
        window.set_status("生成回覆中…")
        threading.Thread(
            target=_compose_worker, args=(text, context), daemon=True
        ).start()

    window = TranslationWindow(
        on_translate=trigger,
        on_compose=compose_trigger,
        show_original=config.SHOW_ORIGINAL,
        default_players=", ".join(config.PLAYER_NAMES),
    )

    def poll() -> None:
        try:
            status, payload = _results.get_nowait()
        except queue.Empty:
            pass
        else:
            if status == "status":
                window.set_status(payload)
            elif status == "error":
                window.set_status(f"錯誤：{payload}")
            elif status == "reply":
                window.show_replies(payload)
                window.clear_reply_input()
                window.set_status(f"回覆建議已生成（{len(payload)} 種，點一下複製）")
            elif payload:
                for line in payload:
                    window.append_line(line.speaker, line.original, line.translation)
                    _recent.append(line)  # 累積情境給回覆生成用
                window.set_status(f"就緒（新增 {len(payload)} 則）")
            else:
                window.set_status("就緒（沒有新訊息）")
                log.info("沒有新訊息可顯示")
        window.after(100, poll)

    # macOS 上 keyboard 需要輔助使用權限，失敗就只靠視窗按鈕觸發
    try:
        import keyboard

        # 熱鍵回呼在 keyboard 的執行緒;trigger 會讀 tk 輸入框,排回主執行緒跑
        keyboard.add_hotkey(config.HOTKEY, lambda: window.after(0, trigger))
        log.info("熱鍵 %s 註冊成功", config.HOTKEY.upper())
        window.set_status(f"就緒（熱鍵 {config.HOTKEY.upper()}）")
    except Exception as e:
        log.warning("熱鍵註冊失敗：%s", e)
        window.set_status(f"熱鍵註冊失敗，請用「翻譯」按鈕（{e}）")

    log.info("Peeklate 啟動完成，等待觸發")

    window.after(100, poll)
    window.mainloop()


if __name__ == "__main__":
    main()
