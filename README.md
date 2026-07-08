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

## 調整

所有設定都在 `config.py`：截圖區域、熱鍵、模型（`MODEL`，Pydantic AI 格式，換供應商只改字串）、是否顯示英文原文（`SHOW_ORIGINAL`）、頻道過濾描述（`CHANNEL_HINT`——如果過濾不準，調整裡面的頻道與顏色敘述）。

## 換別的遊戲

1. 改 `config.py` 的 `GAME_NAME` 為該遊戲名稱。
2. 改 `CHANNEL_HINT`，描述要保留哪個頻道的訊息（頻道名稱、文字顏色等特徵）、要忽略哪些。
3. 重跑 `python pick_region.py` 框選新遊戲的聊天框位置。

來源語言不限英文——模型讀得懂的語言都能翻，`original` 會照抄原文供去重。

## 開發測試（不開遊戲）

```bash
python main.py --image sample.png   # 直接翻譯現成截圖檔
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
