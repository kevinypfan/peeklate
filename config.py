"""Peeklate 設定 — 所有可調整項目集中在這裡。"""

# 聊天框截圖區域（螢幕絕對座標，單位 px）。
# 執行 `python capture.py` 會截這塊區域存成 region_preview.png，反覆調整直到剛好框住聊天框。
# 多螢幕時座標是跨螢幕的虛擬桌面座標：主螢幕左上角為 (0, 0)。
CHAT_REGION = {"left": 40, "top": 640, "width": 640, "height": 260}

# 全域熱鍵（keyboard 套件格式，例如 "f9"、"ctrl+shift+t"）
HOTKEY = "f9"

# Pydantic AI 模型字串；之後想換模型或供應商只需改這個字串
MODEL = "google:gemini-2.5-flash-lite"

# 譯文上方是否附英文原文（灰色小字）
SHOW_ORIGINAL = True

# ── 遊戲相關設定：換遊戲時改下面兩項，並重跑 python pick_region.py 框選聊天框 ──

# 遊戲名稱（讓模型知道截圖來自哪款遊戲，有助辨識介面）
GAME_NAME = "Tom Clancy's The Division 2"

# 告訴模型要保留哪些訊息（頻道、顏色等特徵）。過濾不準就調整這段描述。
CHANNEL_HINT = """\
Keep ONLY player messages from the GROUP / fireteam channel:
- Group channel lines are shown in a distinct color that differs from other channels
  (general/zone chat, clan chat) and from white/grey system messages.
- Ignore system or service messages (XP gains, loot, matchmaking or server notices),
  general/zone chat, and clan chat.\
"""

# ── 以下通常不用動：組合出丟給模型的完整指示 ──
PROMPT = f"""\
You are looking at a screenshot of the in-game chat box from {GAME_NAME}.

{CHANNEL_HINT}
- Strip the channel tag and the speaker's name; keep only the message content itself.

For each kept message, in top-to-bottom order, output:
- original: the exact English message text, copied verbatim
- translation: a natural Traditional Chinese (繁體中文) translation in a casual gamer tone

If there are no matching messages in the image, return an empty list.
"""
