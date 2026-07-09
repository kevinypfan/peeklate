# Peeklate

遊戲隊友聊天翻譯小工具：按一下熱鍵 → 截聊天框 → Gemini vision 讀字＋過濾＋翻譯 → 繁中譯文顯示在副螢幕的 always-on-top 小視窗。

- 只翻你指定頻道的隊友訊息（預設設定以 **The Division 2 的 group 頻道**為例），忽略系統訊息與其他頻道
- 已翻過的行會記住，每次只顯示新增的訊息
- 手動觸發，不自動輪詢，省 API 額度
- 不限遊戲：任何聊天框位置固定的遊戲都能用，見下方「換別的遊戲」

## 前置需求

- Windows、遊戲以**無邊框視窗**執行（獨佔全螢幕會截到黑畫面）
- Python ≥ 3.10
- Gemini API key（免費層即可）：https://aistudio.google.com/apikey
- [Gemini CLI](https://github.com/google-gemini/gemini-cli)（預設的 OCR backend；`npm install -g @google/gemini-cli` 後執行一次 `gemini` 登入 Google 帳號）。不想裝的話把 `config.py` 的 `OCR_MODEL` 改回 `google:` 前綴即可，見下方「翻譯 backend」

## 安裝

```bash
# 有 uv：
uv sync

# 或用 pip：
pip install -e .
```

設定 API key（PowerShell）：

```powershell
$env:GOOGLE_API_KEY = "你的key"
```

## 校準聊天框區域（第一次使用必做）

1. 開遊戲，讓聊天框顯示在畫面上（先在聊天框打點字，避免它淡出）。
2. 執行 `python pick_region.py`，整個螢幕會蓋上一張當下截圖，**用滑鼠拖曳框出聊天框**，放開後座標自動寫回 `config.py`（Esc 取消；遊戲不在主螢幕時加 `--monitor 2`）。
3. 執行 `python capture.py` 會截 `CHAT_REGION` 區域並開啟 `region_preview.png`，確認框得剛好；要微調可直接改 `config.py` 的座標再重看。

## 使用

```bash
python main.py
```

1. 小視窗出現後拖到副螢幕。
2. 隊友聊天出現、看不懂時按 **F9**（可在 `config.py` 改 `HOTKEY`）。
3. 譯文出現在視窗裡；重按不會重複翻已經翻過的行。

視窗右下角的「翻譯」按鈕與熱鍵等效。

## 出問題怎麼查（log）

每次執行都會把管線每一步印到終端機，同時寫進專案目錄的 `peeklate.log`：讀到幾則、過濾後剩幾則、命中哪些術語、翻出什麼、API 有沒有 503/429 及重試等待幾秒。翻譯怪怪的、過濾不如預期時，看這裡最快。

```bash
python main.py --debug   # 額外印出每一則 OCR 的頻道/發話者/原文
```

不加 `--debug` 是 INFO 等級（各階段數量與結果）；加了是 DEBUG（連每則原文都印，並解除第三方套件的 log 靜音）。

想連「當下截到的畫面」也留下來對照，把 `config.py` 的 `SAVE_CAPTURES` 設成 `True`：之後每次翻譯都會把送去辨識的截圖存到 `captures/`（檔名帶時間戳，可跟 log 對照）。查完記得關掉，它不會自動清理。

## 只看某幾個人（過濾發話者）

視窗底部的「只看:」輸入框可填玩家 ID，只翻這些人說的話（**逗號分隔多人**，比對不分大小寫、部分符合即可）。留空則不指定玩家，改用頻道過濾。

- **有指定玩家**：翻他們在任何頻道說的話。
- **留空 + `GROUP_CHANNEL_TAGS` 有值**：只翻頻道標籤含這些字樣（預設隊伍/小隊/Group）的訊息，忽略系統訊息、其他頻道。
- **留空 + `GROUP_CHANNEL_TAGS = []`**：不做任何過濾，翻聊天框裡的全部訊息。

想每次開啟就預設某幾人，改 `config.py` 的 `PLAYER_NAMES`（清單）；視窗輸入框非空時會蓋過它。

## 遊戲術語表（提升專有名詞翻譯品質）

The Division 2 的道具/裝備/天賦/技能有官方中譯，直接讓模型翻常常對不上。本工具會在翻譯前，於本地把訊息裡出現的術語配上官方譯名一起餵給模型。

術語表 `glossary.json` 由社群整理的兩份資料庫自動建立：

```bash
uv run --env-file .env python build_glossary.py
```

會自動下載兩份 Google Sheets → 抽出各類名稱 → 用 Gemini 配對中英 → 本地驗證後輸出 `glossary.json`（約 340 條）。資料庫更新時重跑即可（`--refresh` 強制重新下載，`--extract-only` 只看抽取結果不呼叫 API）。

沒有 `glossary.json` 也能正常使用，只是專有名詞翻譯品質較普通。

### 縮寫與黑話（`slang.json`）

自動術語表只有官方全名，但隊友聊天滿是縮寫黑話（`esc`=戰鬥升級、`Potomac`=地圖、裸詞 `striker`=突襲者套裝）。這些試算表查不到，所以另外用一份手動維護的 `slang.json`（`{ "英文": "中文提示" }`）補齊，並**覆蓋**自動表的錯義（例如把 `striker` 從技能「前鋒」導正為套裝「突襲者」）。

這份表已內建一批常見詞，直接編輯即可增修——加地圖、模式、你們常用的縮寫都行。改完存檔即時生效（程式偵測到檔案變動會自動重載，不用重開）。比對用「ASCII 詞邊界」，所以短縮寫（如 `esc`）不會誤中 `rescue` 這種字。

譯文會把遊戲專有名詞附上英文短名，例如「突襲者（Striker）」「戰鬥升級（Escalation）」，方便對照英文介面。

### 自動累積待補術語（候選詞）

翻譯時，模型若遇到術語表**還沒收錄**的遊戲專有名詞，會把它（連同猜測的譯法）記到 `slang_candidates.jsonl`——只記錄、不會自動改動 `slang.json`，所以你的權威表不會被模型的猜測污染。

有空時跑審核工具，逐條決定要不要收進 `slang.json`：

```bash
uv run python review_candidates.py          # 逐條 y(收錄)/e(收錄並改譯法)/n(略過)/d(丟棄)/q(離開)
uv run python review_candidates.py --list    # 只列出目前累積了哪些候選
```

收錄的會寫進 `slang.json`（下次翻譯即生效），處理過的候選會從候選檔移除。這樣術語表會隨你實際玩的內容越補越準，又不必自己一直盯著。

> 備註：候選詞是翻譯時「順便」產出的（同一次呼叫，不額外花 API）。萬一模型輸出格式壞掉，程式會自動退回「只翻譯」模式——**翻譯本身永遠不會因為這個附加功能而失敗**。

## 運作方式（兩段式管線）

按一次熱鍵：
1. **Gemini vision 只讀字**——依 `[頻道] 玩家ID> 訊息` 格式抽出每則的頻道、發話者、原文（折行訊息會併回同一則）。
2. **本地過濾/去重/術語比對**——不花 API。
3. **Gemini 純文字翻譯**——只把這次新出現的行 + 命中的術語送去翻；沒有新訊息就跳過這步，省額度。

## 調整

所有設定都在 `config.py`：截圖區域、熱鍵、模型（兩段各一：`OCR_MODEL` 讀字、`TRANSLATE_MODEL` 翻譯）、是否顯示原文（`SHOW_ORIGINAL`）、預設發話者（`PLAYER_NAMES`）、群組頻道標籤（`GROUP_CHANNEL_TAGS`）、術語表路徑（`GLOSSARY_PATH`）。

### 翻譯 backend：API 或 gemini CLI

`OCR_MODEL` / `TRANSLATE_MODEL` 的前綴決定走哪個 backend，兩段可獨立切換，各吃不同的免費額度池：

| 前綴 | backend | 免費額度 | 特性 |
|---|---|---|---|
| `google:` | Gemini API（需 `GOOGLE_API_KEY`） | 各模型獨立池，如 3.1-flash-lite 500 次/天 | 快、有 structured output 保證 |
| `cli:` | 本機 gemini CLI（OAuth 登入） | 單一池 1000 次/天、60 次/分 | 額度多，但每次呼叫多 ~3-5 秒啟動時間 |

預設 OCR 走 `cli:gemini-2.5-flash`（每次觸發必跑的瓶頸段，吃大池）、翻譯走 `google:gemini-3.5-flash`（只在有新訊息時呼叫），每天可觸發約 **1000 次**。CLI 額度也用完時，把 OCR 改回 `google:gemini-3.1-flash-lite`（500 次/天）還能再撐。

> - API 沒有 `gemini-3.1-flash`（純 flash）這個名字，會回 404；只有帶 `-lite` 的版本。
> - 遇到 `429 ...quota` 是當天免費額度用完（API 用量到 [AI Studio](https://aistudio.google.com/) 查）；`503 ...high demand` 是伺服器暫時過載。兩個 backend 都會自動重試（API 429 會照伺服器指定秒數等待）。
> - CLI backend 回報「找不到 gemini 指令」= 還沒裝 CLI；輸出解析失敗時會自動附上錯誤重問、再不行退回只翻譯的簡單格式。

## 換別的遊戲

1. 改 `config.py` 的 `GAME_NAME` 為該遊戲名稱。
2. 改 `GROUP_CHANNEL_TAGS` 為該遊戲隊伍頻道的標籤文字（或直接用「只看某幾個人」）。
3. 重跑 `python pick_region.py` 框選新遊戲的聊天框位置。
4. 術語表是 The Division 2 專用；換遊戲請自備 `glossary.json`（`{ "英文": "中文" }`）或刪掉不用。

來源語言不限英文——模型讀得懂的語言都能翻。

## 開發測試（不開遊戲）

```bash
python main.py --image sample.png   # 直接翻譯現成截圖檔（可在「只看:」框試發話者過濾）
python ui.py                        # 單獨看視窗樣式
```

macOS 上若用 uv 管理的 Python 開視窗時報 `Can't find a usable init.tcl`，先設：

```bash
PYROOT=$(uv run python -c "import sys; print(sys.base_prefix)")
export TCL_LIBRARY=$PYROOT/lib/tcl8.6 TK_LIBRARY=$PYROOT/lib/tk8.6
```

（僅 macOS 開發環境需要；Windows 官方安裝版 Python 不受影響。）

## 隱私備註

免費層請求可能被 Google 用於改進模型；本工具只送出遊戲聊天截圖，無敏感內容。
