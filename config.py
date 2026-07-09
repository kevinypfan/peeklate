"""Peeklate 設定 — 所有可調整項目集中在這裡。"""

# 聊天框截圖區域（螢幕絕對座標，單位 px）。
# 執行 `python capture.py` 會截這塊區域存成 region_preview.png，反覆調整直到剛好框住聊天框。
# 多螢幕時座標是跨螢幕的虛擬桌面座標：主螢幕左上角為 (0, 0)。
CHAT_REGION = {"left": 59, "top": 867, "width": 696, "height": 330}

# 全域熱鍵（keyboard 套件格式，例如 "f9"、"ctrl+shift+t"）
HOTKEY = "f9"

# 兩段式管線各用一個模型，前綴決定 backend、且各自吃不同的免費額度池：
# - "google:<model>" — Gemini API（pydantic-ai，需要 GOOGLE_API_KEY）。
#   各模型有自己的免費池，例如 gemini-3.1-flash-lite 500/天、gemma 系列 1500/天。
# - "cli:<model>" — 本機的 gemini CLI（需先 npm install -g @google/gemini-cli
#   並執行一次 `gemini` 登入 Google 帳號）。個人帳號免費 1000 次/天、60 次/分，
#   單一池不分模型，跟 API key 的額度互相獨立。
# 預設：OCR（每次觸發必跑的瓶頸段）走 CLI 的 1000/天池；翻譯留在 API（有
# structured output 的 schema 保證，且只在有新訊息時才呼叫）。
# 這樣每天可觸發 ~1000 次，代價是 CLI 每次呼叫多 ~3-5 秒啟動開銷。
# 注意：API 沒有 "gemini-3.1-flash"（純 flash）這個名字，會 404；lite 才有。
OCR_MODEL = "cli:gemini-2.5-flash"
TRANSLATE_MODEL = "google:gemini-3.5-flash"

# gemini CLI 單次呼叫的逾時秒數（含 ~2.5s 啟動時間；逾時會自動重試）
GEMINI_CLI_TIMEOUT = 60

# 譯文上方是否附原文（灰色小字）
SHOW_ORIGINAL = True

# 視窗、字型、配色（覺得字小、視窗小就把數字調大）。
WINDOW_SIZE = "520x640"  # 初始視窗大小 "寬x高"（之後仍可手動拖拉）
# 字型：Windows 繁中建議微軟正黑體；找不到會自動 fallback。
FONT_FAMILY = "Microsoft JhengHei UI"
FONT_SIZE_TRANS = 17  # 譯文字級
FONT_SIZE_ORIG = 13  # 原文字級（灰色小字）
COLOR_BG = "#141414"  # 背景（近黑）
COLOR_SPEAKER = "#e0af68"  # 發話者 ID（琥珀色，一眼看出誰說的）
COLOR_TRANS = "#f5f5f5"  # 譯文（近白）
COLOR_ORIG = "#9db4c0"  # 原文（帶點藍的灰，跟白色譯文區隔又夠亮好讀）

# 只翻這些玩家說的話（聊天行 `[頻道] 玩家ID> 訊息` 中的玩家ID，比對不分大小寫、
# 允許部分符合）。空清單 = 不指定玩家，改用下面的頻道過濾。
# UI 視窗的「只看」輸入框非空時會蓋過這裡的設定。
PLAYER_NAMES: list[str] = []

# 沒有指定玩家時，只翻頻道標籤（方括號內文字）含這些字樣的訊息。
# 依遊戲實際顯示調整；例如全境封鎖2繁中介面的隊伍頻道。
# 設為空清單 [] = 不做頻道過濾，翻聊天框裡的全部訊息。
GROUP_CHANNEL_TAGS = []

# 術語表路徑（執行 build_glossary.py 產生；檔案不存在也能跑，只是專有名詞
# 翻譯品質較普通）
GLOSSARY_PATH = "glossary.json"

# 手動維護的縮寫/黑話對照（地圖、模式、套裝縮寫…），補齊資料庫沒有的詞、
# 並覆蓋自動表的錯義。優先度高於 GLOSSARY_PATH，可自行增修（改完即時生效）。
SLANG_PATH = "slang.json"

# 翻譯時，模型遇到術語表沒有的遊戲術語會記到這裡（只記錄、不動 slang.json）。
# 用 `python review_candidates.py` 逐條審核後才補進 slang.json。
CANDIDATES_PATH = "slang_candidates.jsonl"

# debug 用：是否把每次送去翻譯的截圖存檔（帶時間戳，方便跟 log 對照，
# 確認截到的畫面對不對）。存到 CAPTURE_DIR 目錄；不會自動清理。
SAVE_CAPTURES = True
CAPTURE_DIR = "captures"

# ── 遊戲相關設定：換遊戲時改這項，並重跑 python pick_region.py 框選聊天框 ──

# 遊戲名稱（讓模型知道截圖來自哪款遊戲，有助辨識介面）
GAME_NAME = "Tom Clancy's The Division 2"

# ── 以下通常不用動：兩段式管線的模型指示 ──

# 第一段：vision 只讀字，不翻譯
OCR_PROMPT = f"""\
You are reading a screenshot of the in-game chat box from {GAME_NAME}.

Each chat line has the format: [channel] PlayerName> message
Extract every player message, in top-to-bottom order:
- channel: the text inside the square brackets, copied verbatim
- speaker: the player name between "]" and ">"
- text: the message content after ">", copied verbatim; do NOT translate it

Long messages wrap onto following lines without the "[channel] PlayerName>"
prefix; merge such continuation lines back into the same message.
Ignore anything that does not match this format (system or service messages).
If there are no matching lines, return an empty list.
"""

# 第二段：純文字翻譯
TRANSLATE_PROMPT = f"""\
You translate {GAME_NAME} fireteam (team/group) chat into natural Traditional
Chinese (繁體中文) with a casual gamer tone. This is teammate chat, so it is
full of abbreviations, shorthand and slang. Messages may be in any language
(English, Simplified Chinese, ...); translate every one of them.

Guidelines:
- Interpret gamer shorthand and expand abbreviations to their intended meaning
  (e.g. "esc" = the Escalation game mode, not "escape"; a bare gear-set name
  like "striker" means the gear set, not the same-named skill).
- When an item/skill name is ambiguous, prefer the sense that fits team play
  (gear set, weapon, game mode, map) over an obscure one.
- Keep translations concise and natural - one line, no lengthy explanation.
- For game-specific proper nouns (gear sets, maps, game modes, named items,
  exotics), append the English in full-width parentheses after the Chinese.
  Use the SHORT common name players actually type, not a long official title
  or description: 突襲者（Striker）NOT 突襲者（Striker's Battlegear gear set）;
  戰鬥升級（Escalation）NOT （Escalation mode）; 波托馬克活動中心（Potomac）
  NOT （Potomac Event Center）. Do NOT add parentheses for ordinary words.
  ONLY append English when it is in the glossary or you genuinely know the
  real in-game English name. If you are unsure, OMIT the parentheses - never
  invent or guess an English name.

The input is a numbered list of messages. Output two things:
- translations: for each message, its id and the Traditional Chinese translation.
- new_terms: game-specific proper nouns / abbreviations / slang you saw in the
  messages that were NOT in the provided glossary and that a translator could
  easily get wrong (gear sets, weapons, exotics, brands, maps, game modes,
  named items, activity abbreviations). For each give en (the short common
  English form players type) and zh (your best-guess Traditional Chinese).
  Skip ordinary words (hi, heal, thanks...) and anything already in the
  glossary. Return an empty list if there are none.

If a glossary of game terms is provided, treat it as authoritative for those
terms (the slang/shorthand entries especially), but still pick the sense that
fits the context.
"""
