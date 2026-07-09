"""Gemini CLI backend：透過本機已登入的 `gemini` 指令跑推論。

走 Gemini Code Assist 個人帳號的免費額度（1000 次/天、60 次/分），跟 API key
的額度池互相獨立。CLI 沒有 schema 強制輸出，所以在 prompt 尾端附上 JSON
Schema 指示、拿回文字後本地用 pydantic 驗證；圖片經由 `@檔名` 語法附帶——
必須是不含空格的路徑，否則 CLI 會靜默略過、模型看不到圖，因此一律寫到
mkdtemp 出來的暫存目錄並以該目錄為 cwd。
"""

import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from pydantic import TypeAdapter

import config

log = logging.getLogger(__name__)

_MAX_RETRIES = 3  # 首次失敗後最多再試幾次（與 translator 的 API 路徑一致）
_BACKOFF_BASE = 2.0
_MAX_BACKOFF = 30.0

# CLI 的 error 欄沒有結構化的 HTTP status，用訊息內容判斷是否值得重試
_RETRYABLE_PAT = re.compile(
    r"rate.?limit|quota|resource.?exhausted|overload|unavailable|too many requests"
    r"|\b429\b|\b50[0234]\b",
    re.IGNORECASE,
)


class GeminiCliError(RuntimeError):
    """CLI 呼叫失敗（找不到指令、額度用盡、逾時…）。retryable 供重試迴圈判斷。"""

    def __init__(self, msg: str, retryable: bool = False):
        super().__init__(msg)
        self.retryable = retryable


class GeminiCliParseError(GeminiCliError):
    """模型回了文字但無法解析成預期的 JSON 格式（重試後仍失敗）。"""


def _json_instruction(adapter: TypeAdapter) -> str:
    schema = json.dumps(adapter.json_schema(), ensure_ascii=False)
    return (
        "\n\nRespond with ONLY a raw JSON value that matches this JSON Schema"
        " (no code fences, no commentary, no extra text):\n" + schema
    )


def _extract_json(text: str) -> str:
    """剝掉 code fence 與前後雜訊，取出第一個 JSON 值的範圍。"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not starts:
        return text
    start = min(starts)
    end = max(text.rfind("]"), text.rfind("}"))
    return text[start : end + 1] if end > start else text[start:]


def _invoke(model: str, prompt: str, cwd: str) -> str:
    """跑一次 CLI，回傳模型的文字回應。失敗一律拋 GeminiCliError。"""
    cmd = ["gemini", prompt, "-m", model, "-o", "json", "-e", "none"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.GEMINI_CLI_TIMEOUT,
            cwd=cwd,
        )
    except FileNotFoundError:
        raise GeminiCliError(
            "找不到 gemini 指令；請先 `npm install -g @google/gemini-cli`，"
            "並執行一次 `gemini` 完成 Google 帳號登入"
        ) from None
    except subprocess.TimeoutExpired:
        raise GeminiCliError(
            f"gemini CLI 超過 {config.GEMINI_CLI_TIMEOUT}s 沒回應", retryable=True
        ) from None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        detail = proc.stderr.strip()[:300] or proc.stdout.strip()[:300]
        raise GeminiCliError(
            f"gemini CLI 輸出不是 JSON（exit {proc.returncode}）：{detail}",
            retryable=True,  # 可能是暫時性 crash，值得再試
        ) from None
    if payload.get("error"):
        msg = str(payload["error"])[:500]
        raise GeminiCliError(msg, retryable=bool(_RETRYABLE_PAT.search(msg)))
    resp = payload.get("response")
    if not resp:
        raise GeminiCliError("gemini CLI 回應為空", retryable=True)
    return resp


def run(
    model: str,
    instructions: str,
    user_text: str = "",
    image_png: bytes | None = None,
    output_type: Any = str,
    label: str = "gemini CLI",
    on_status: Callable[[str], None] | None = None,
) -> Any:
    """呼叫 gemini CLI 並把回應驗證成 output_type。

    可重試的失敗（限流、逾時、輸出解析不了）沿用 translator 的節奏退避重試；
    解析失敗重試時會把錯誤訊息附回 prompt 讓模型修正。永遠在暫存目錄裡執行，
    避免 CLI 把專案目錄當 workspace 掃描。
    """
    adapter = (
        output_type
        if isinstance(output_type, TypeAdapter)
        else TypeAdapter(output_type)
    )
    tmp = Path(tempfile.mkdtemp(prefix="peeklate_"))
    try:
        prefix = ""
        if image_png is not None:
            (tmp / "capture.png").write_bytes(image_png)
            prefix = "@capture.png\n\n"
        base_prompt = prefix + instructions
        if user_text:
            base_prompt += "\n\n" + user_text
        base_prompt += _json_instruction(adapter)

        parse_err = ""
        for attempt in range(_MAX_RETRIES + 1):
            prompt = base_prompt
            if parse_err:
                prompt += (
                    f"\n\nYour previous reply was not valid ({parse_err})."
                    " Output ONLY the JSON value."
                )
            t0 = time.monotonic()
            try:
                resp = _invoke(model, prompt, cwd=str(tmp))
            except GeminiCliError as e:
                if e.retryable and attempt < _MAX_RETRIES:
                    wait = min(_BACKOFF_BASE * (2**attempt), _MAX_BACKOFF)
                    log.warning(
                        "%s（cli:%s）失敗，%.0fs 後重試（第 %d/%d 次）：%s",
                        label, model, wait, attempt + 1, _MAX_RETRIES, e,
                    )
                    if on_status:
                        on_status(
                            f"{label}：{e}，{wait:.0f} 秒後重試"
                            f"（第 {attempt + 1}/{_MAX_RETRIES} 次）…"
                        )
                    time.sleep(wait)
                    continue
                log.error("%s（cli:%s）失敗：%s", label, model, e)
                raise
            try:
                out = adapter.validate_json(_extract_json(resp))
            except Exception as e:
                parse_err = str(e)[:200]
                if attempt < _MAX_RETRIES:
                    log.warning(
                        "%s（cli:%s）輸出解析失敗，重試：%s", label, model, parse_err
                    )
                    if on_status:
                        on_status(f"{label}：輸出解析失敗，重試中…")
                    continue
                raise GeminiCliParseError(
                    f"輸出無法解析為預期格式：{parse_err}"
                ) from e
            log.info(
                "%s（cli:%s）成功，耗時 %.1fs", label, model, time.monotonic() - t0
            )
            return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
