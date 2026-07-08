"""Peeklate 顯示模組:always-on-top 小視窗,顯示聊天譯文。"""
import tkinter as tk

BG = "#111111"        # 近黑背景
FG_TRANS = "#ffffff"  # 譯文:白色
FG_ORIG = "#888888"   # 原文:灰色


class TranslationWindow:
    """置頂小視窗,可自行拖到副螢幕。main.py 依此介面串接。"""

    def __init__(self, on_translate, show_original=True):
        self.show_original = show_original
        self.root = tk.Tk()
        self.root.title("Peeklate")
        self.root.geometry("420x480")
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)

        # 顯示區:唯讀 Text + scrollbar
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(
            body, state="disabled", wrap="word", bg=BG, fg=FG_TRANS,
            bd=0, highlightthickness=0, padx=8, pady=8,
        )
        sb = tk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        # 兩種樣式:原文小灰字、譯文大白字
        self.text.tag_configure("orig", foreground=FG_ORIG, font=("TkDefaultFont", 10))
        self.text.tag_configure("trans", foreground=FG_TRANS, font=("TkDefaultFont", 13))

        # 底部列:狀態 Label(左)+ 翻譯按鈕(右)
        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(fill="x", side="bottom")
        self.status = tk.Label(bottom, text="就緒", fg=FG_ORIG, bg=BG, anchor="w")
        self.status.pack(side="left", padx=8, pady=4)
        tk.Button(bottom, text="翻譯", command=on_translate).pack(side="right", padx=8, pady=4)

    def append_line(self, original: str, translation: str) -> None:
        """新增一則訊息:可選的原文小字 + 譯文,之後留一空行並捲到底。"""
        self.text.configure(state="normal")
        if self.show_original:
            self.text.insert("end", original + "\n", "orig")
        self.text.insert("end", translation + "\n\n", "trans")
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
    # 單獨目視測試:塞兩則假訊息,按「翻譯」再 append 一則
    win = TranslationWindow(
        on_translate=lambda: win.append_line("test message from button", "按鈕觸發的測試訊息")
    )
    win.append_line("anyone doing the summit today?", "今天有人要打高峰大廈嗎?")
    win.append_line("lfg countdown, need 2 more dps", "倒數行動找隊友,還缺兩個輸出")
    win.set_status("Demo 模式")
    win.mainloop()
