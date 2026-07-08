"""翻譯模組：兩段式管線。

第一段 Gemini vision 只讀字（頻道/發話者/原文），過濾、去重、術語比對都在
本地做，只有真正要翻的新訊息才進第二段的純文字翻譯——沒有新訊息時省下
第二次 API 呼叫。

API key 由 pydantic-ai 的 Google provider 自動從 GOOGLE_API_KEY 環境變數讀取。
"""

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.exceptions import ModelHTTPError

import config

log = logging.getLogger(__name__)


class OcrLine(BaseModel):
    channel: str  # 方括號內的頻道文字
    speaker: str  # 玩家 ID
    text: str  # 訊息原文（逐字）


class ChatLine(BaseModel):
    original: str  # 「玩家ID: 原文」
    translation: str  # 繁體中文譯文


class NumberedTranslation(BaseModel):
    id: int
    translation: str


class TermCandidate(BaseModel):
    """翻譯時模型發現、但術語表沒收錄的遊戲術語，記下來供人工審核。"""

    en: str  # 英文/縮寫短名
    zh: str  # 模型猜的中文譯法


class TranslationResult(BaseModel):
    translations: list[NumberedTranslation]
    new_terms: list[TermCandidate]  # 可能為空


# 這些是伺服器端暫時性錯誤（模型過載、限流等），值得自動重試；
# 其他錯誤（如 API key 錯的 401/403）重試也沒用，直接往外拋。
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3  # 首次失敗後最多再試幾次
_BACKOFF_BASE = 2.0  # 退避秒數：2、4、8…
_MAX_BACKOFF = 30.0  # 單次等待上限（避免熱鍵按下後卡太久）

# Agent 惰性建構：建構時就會讀 API key，延後到第一次翻譯才發生，
# 沒設 key 時錯誤會顯示在 UI 狀態列而不是啟動時直接 crash。
_ocr_agent: Agent | None = None
_translate_agent: Agent | None = None  # 含候選詞的完整輸出
_translate_simple_agent: Agent | None = None  # 只翻譯，備援用

# 已見過的訊息（去重用），key 為「玩家ID: 原文」
_seen: set[str] = set()

# 合併後的術語表（slang 覆蓋 glossary，key 一律小寫）。
# 記錄來源檔的 mtime，檔案一改就重載，改完 slang.json 不用重開程式。
_terms: dict[str, str] | None = None
_terms_mtimes: tuple[float, float] = (0.0, 0.0)


def _retry_after(err: ModelHTTPError, attempt: int) -> float:
    """該等幾秒再重試。

    429 限流時 Gemini 會在回應裡給建議秒數（retryDelay / "retry in Ns"），
    優先照它；否則用指數退避。都會夾在 _MAX_BACKOFF 以內。
    """
    m = re.search(r"retry(?:Delay)?[\"': in]+([\d.]+)s", str(err.body))
    server = float(m.group(1)) if m else 0.0
    return min(max(server, _BACKOFF_BASE * (2**attempt)), _MAX_BACKOFF)


def _run_with_retry(agent: Agent, prompt, label: str):
    model = agent.model.model_name
    for attempt in range(_MAX_RETRIES + 1):
        try:
            t0 = time.monotonic()
            result = agent.run_sync(prompt)
            log.info("%s（%s）成功，耗時 %.1fs", label, model, time.monotonic() - t0)
            return result
        except ModelHTTPError as e:
            if e.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                wait = _retry_after(e, attempt)
                log.warning(
                    "%s（%s）HTTP %s，%.0fs 後重試（第 %d/%d 次）",
                    label, model, e.status_code, wait, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(wait)
                continue
            log.error("%s（%s）失敗：HTTP %s %s", label, model, e.status_code, e.body)
            raise


def _get_ocr_agent() -> Agent:
    global _ocr_agent
    if _ocr_agent is None:
        _ocr_agent = Agent(
            config.OCR_MODEL,
            instructions=config.OCR_PROMPT,
            output_type=list[OcrLine],
        )
    return _ocr_agent


def _get_translate_agent() -> Agent:
    global _translate_agent
    if _translate_agent is None:
        _translate_agent = Agent(
            config.TRANSLATE_MODEL,
            instructions=config.TRANSLATE_PROMPT,
            output_type=TranslationResult,
        )
    return _translate_agent


def _get_simple_translate_agent() -> Agent:
    """備援：只輸出翻譯、不含候選詞。完整 schema 在弱模型上偶爾 parse 失敗，
    退回這個較簡單的 schema，保證翻譯不會整個掛掉。"""
    global _translate_simple_agent
    if _translate_simple_agent is None:
        _translate_simple_agent = Agent(
            config.TRANSLATE_MODEL,
            instructions=config.TRANSLATE_PROMPT,
            output_type=list[NumberedTranslation],
        )
    return _translate_simple_agent


def _load_json(path_str: str) -> dict[str, str]:
    path = Path(__file__).parent / path_str
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        log.info("術語表載入 %d 條（%s）", len(data), path.name)
        return data
    except FileNotFoundError:
        log.warning("找不到術語表 %s", path)
        return {}


def _mtime(path_str: str) -> float:
    try:
        return (Path(__file__).parent / path_str).stat().st_mtime
    except OSError:
        return 0.0


def _load_terms() -> dict[str, str]:
    """合併 glossary 與 slang，key 一律轉小寫；slang 覆蓋 glossary 的同名詞。

    來源檔一有變動就重載，改完 slang.json 下次翻譯即生效、不用重開程式。
    """
    global _terms, _terms_mtimes
    mtimes = (_mtime(config.GLOSSARY_PATH), _mtime(config.SLANG_PATH))
    if _terms is None or mtimes != _terms_mtimes:
        merged: dict[str, str] = {}
        for en, zh in _load_json(config.GLOSSARY_PATH).items():
            merged[en.lower()] = zh
        for en, zh in _load_json(config.SLANG_PATH).items():
            merged[en.lower()] = zh  # slang 優先
        _terms = merged
        _terms_mtimes = mtimes
    return _terms


def _log_candidates(candidates: list[TermCandidate]) -> None:
    """把術語表沒有的候選詞 append 到 slang_candidates.jsonl（去重）。

    只記錄、不寫進 slang.json；由 review_candidates.py 人工審核後才補入。
    """
    if not candidates:
        return
    path = Path(__file__).parent / config.CANDIDATES_PATH
    known = set(_load_terms())  # 已在術語表裡的（小寫）
    seen = set()  # 已記過的候選（小寫）
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(line)["en"].lower())
            except (json.JSONDecodeError, KeyError):
                continue
    fresh = []
    for c in candidates:
        key = c.en.lower().strip()
        if not key or key in known or key in seen:
            continue
        seen.add(key)
        fresh.append(c)
    if not fresh:
        return
    ts = datetime.now().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as f:
        for c in fresh:
            f.write(
                json.dumps(
                    {"en": c.en, "zh": c.zh, "ts": ts}, ensure_ascii=False
                )
                + "\n"
            )
    log.info("記錄 %d 個候選術語 → %s：%s", len(fresh), path.name,
             [c.en for c in fresh])


def _match_terms(texts: list[str], limit: int = 20) -> dict[str, str]:
    """找出訊息中出現的術語（大小寫不敏感、長詞優先），最多 limit 條。

    用 ASCII 詞邊界比對：短縮寫（esc）不會誤中 rescue，而 CJK 相鄰
    （打striker）仍算邊界、照樣命中。
    """
    joined = "\n".join(texts)
    hits: dict[str, str] = {}
    for en, zh in sorted(_load_terms().items(), key=lambda kv: -len(kv[0])):
        pat = rf"(?<![A-Za-z0-9]){re.escape(en)}(?![A-Za-z0-9])"
        if re.search(pat, joined, re.IGNORECASE):
            hits[en] = zh
            if len(hits) >= limit:
                break
    return hits


def translate_new_lines(png_bytes: bytes, player_names: list[str]) -> list[ChatLine]:
    """辨識截圖中的聊天訊息，過濾、去重後翻譯，只回傳這次新出現的行。

    player_names 非空 → 只留這些玩家說的話（不限頻道，部分符合即可）；
    空 → 只留頻道標籤符合 config.GROUP_CHANNEL_TAGS 的訊息。
    從 worker thread 呼叫（不在 asyncio event loop 內），故可直接用 run_sync。
    """
    log.info("開始翻譯：只看 %s", player_names or "（不指定，用頻道過濾）")
    result = _run_with_retry(
        _get_ocr_agent(),
        [BinaryContent(data=png_bytes, media_type="image/png")],
        "第一段 OCR 讀字",
    )
    ocr_lines = result.output
    log.info("OCR 讀到 %d 則：", len(ocr_lines))
    for l in ocr_lines:
        log.debug("  [%s] %s> %s", l.channel, l.speaker, l.text)

    if player_names:
        wanted = [n.lower() for n in player_names]
        lines = [
            l for l in ocr_lines if any(w in l.speaker.lower() for w in wanted)
        ]
        log.info("依發話者過濾後剩 %d 則（wanted=%s）", len(lines), wanted)
    elif config.GROUP_CHANNEL_TAGS:
        lines = [
            l
            for l in ocr_lines
            if any(tag in l.channel for tag in config.GROUP_CHANNEL_TAGS)
        ]
        log.info(
            "依頻道過濾後剩 %d 則（tags=%s）", len(lines), config.GROUP_CHANNEL_TAGS
        )
    else:
        lines = list(ocr_lines)
        log.info("未指定玩家、頻道標籤也為空 → 不過濾，全收 %d 則", len(lines))

    new_lines: list[OcrLine] = []
    for line in lines:
        key = f"{line.speaker}: {line.text.strip()}"
        if not line.text.strip() or key in _seen:
            continue
        _seen.add(key)
        new_lines.append(line)
    log.info("去重後有 %d 則新訊息（已見過 %d 則）", len(new_lines), len(_seen))
    if not new_lines:
        return []

    terms = _match_terms([l.text for l in new_lines])
    if terms:
        log.info("命中術語 %d 條：%s", len(terms), terms)
    prompt = "Messages:\n" + "\n".join(
        f"{i}. {l.text}" for i, l in enumerate(new_lines, 1)
    )
    if terms:
        prompt += "\n\nGlossary (game terms, EN -> 繁中):\n" + "\n".join(
            f"- {en} -> {zh}" for en, zh in terms.items()
        )

    # 完整輸出（翻譯 + 候選詞）；弱模型偶爾 parse 失敗，就退回只翻譯的簡單
    # schema，確保翻譯本身永遠不會因為候選詞這個附加功能而整批掛掉。
    try:
        result2 = _run_with_retry(_get_translate_agent(), prompt, "第二段 翻譯")
        translations = result2.output.translations
        _log_candidates(result2.output.new_terms)
    except ModelHTTPError:
        raise  # API 層錯誤（額度/過載）照舊往外拋，交給 UI 顯示
    except Exception as e:
        log.warning("完整翻譯輸出解析失敗，退回簡易翻譯（略過候選詞）：%s", e)
        result2 = _run_with_retry(
            _get_simple_translate_agent(), prompt, "第二段 翻譯（簡易備援）"
        )
        translations = result2.output
    by_id = {t.id: t.translation for t in translations}
    out = [
        ChatLine(
            original=f"{l.speaker}: {l.text}",
            translation=by_id.get(i, "（翻譯缺漏）"),
        )
        for i, l in enumerate(new_lines, 1)
    ]
    for c in out:
        log.info("譯：%s → %s", c.original, c.translation)
    return out
