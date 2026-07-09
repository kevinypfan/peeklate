"""Peeklate 顯示模組:always-on-top 小視窗,顯示聊天譯文。"""
import tkinter as tk

import config

BG = config.COLOR_BG        # 近黑背景
FG_TRANS = config.COLOR_TRANS  # 譯文
FG_ORIG = config.COLOR_ORIG    # 原文（灰字）


class TranslationWindow:
    """置頂小視窗,可自行拖到副螢幕。main.py 依此介面串接。"""

    MAX_LINES = 600  # 顯示區保留的行數上限(約 200 則),掛整天也不會越跑越慢

    def __init__(self, on_translate, show_original=True, default_players=""):
        self.show_original = show_original
        self.root = tk.Tk()
        self.root.title("Peeklate")
        self.root.geometry(config.WINDOW_SIZE)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)

        fam = config.FONT_FAMILY
        ui_font = (fam, 11)  # 底部列（狀態/輸入框/按鈕）統一字型

        # 底部列先建、先 pack，確保永遠佔到位置（body 用 expand 會吃掉剩餘空間，
        # 若晚於 body pack 會被擠出視窗）。
        # 狀態 Label(左) + 只看誰輸入框 + 翻譯按鈕(右)
        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(fill="x", side="bottom")
        self.status = tk.Label(
            bottom, text="就緒", fg=FG_ORIG, bg=BG, anchor="w", font=ui_font
        )
        self.status.pack(side="left", padx=8, pady=4)
        tk.Button(
            bottom, text="翻譯", command=on_translate, font=ui_font
        ).pack(side="right", padx=8, pady=4)
        # 只翻這些玩家說的話(逗號分隔多人);留空 = 翻全部(照頻道過濾)
        self.players = tk.Entry(
            bottom, width=20, bg="#2a2a2a", fg=FG_TRANS,
            insertbackground=FG_TRANS, bd=0, font=ui_font,
        )
        self.players.insert(0, default_players)
        self.players.pack(side="right", pady=4)
        tk.Label(
            bottom, text="只看:", fg=FG_ORIG, bg=BG, font=ui_font
        ).pack(side="right", padx=(8, 2))

        # 顯示區:唯讀 Text + scrollbar（填滿底部列以外的空間）
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(
            body, state="disabled", wrap="word", bg=BG, fg=FG_TRANS,
            bd=0, highlightthickness=0, padx=12, pady=10,
            font=(fam, config.FONT_SIZE_TRANS),
        )
        sb = tk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        # 每則三行：發話者(琥珀色標題) / 原文(灰) / 譯文(白)。
        # spacing1 在發話者上方留空區隔各則、spacing2 放寬折行行距。
        self.text.tag_configure(
            "speaker", foreground=config.COLOR_SPEAKER,
            font=(fam, config.FONT_SIZE_ORIG, "bold"), spacing1=10,
        )
        self.text.tag_configure(
            "orig", foreground=FG_ORIG, font=(fam, config.FONT_SIZE_ORIG),
            spacing2=2,
        )
        self.text.tag_configure(
            "trans", foreground=FG_TRANS, font=(fam, config.FONT_SIZE_TRANS),
            spacing2=4,
        )

    def get_player_names(self) -> list[str]:
        """輸入框裡逗號分隔的玩家 ID 清單(去空白、濾空字串)。"""
        return [n.strip() for n in self.players.get().split(",") if n.strip()]

    def append_line(self, speaker: str, original: str, translation: str) -> None:
        """新增一則訊息:發話者標題 + 可選原文 + 譯文,並捲到底。"""
        self.text.configure(state="normal")
        self.text.insert("end", speaker + "\n", "speaker")
        if self.show_original:
            self.text.insert("end", original + "\n", "orig")
        self.text.insert("end", translation + "\n", "trans")
        overflow = int(self.text.index("end-1c").split(".")[0]) - self.MAX_LINES
        if overflow > 0:
            self.text.delete("1.0", f"{overflow + 1}.0")
        self.text.configure(state="disabled")
        self.text.see("end")

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def after(self, ms: int, fn) -> None:
        """代理到 root.after,供 main.py 輪詢 queue。"""
        self.root.after(ms, fn)

    def mainloop(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    # 單獨目視測試:塞幾則假訊息,按「翻譯」再 append 一則
    win = TranslationWindow(
        on_translate=lambda: win.append_line(
            "TestBtn", "test message from button", "按鈕觸發的測試訊息"
        )
    )
    win.append_line("Uno_ATS", "anyone doing the summit today?", "今天有人要打高峰大廈（Summit）嗎?")
    win.append_line(
        "R.azgriz", "lfg countdown, need 2 more dps", "倒數行動（Countdown）找隊友,還缺兩個輸出（DPS）"
    )
    win.set_status("Demo 模式")
    win.mainloop()
