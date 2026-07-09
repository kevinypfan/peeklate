"""Antigravity CLI backend：透過本機已登入的 `agy` 指令跑推論。

Google 在 2026-06-18 停止 Gemini CLI 服務個人帳號，個人免費額度移到
Antigravity（安裝：curl -fsSL https://antigravity.google/cli/install.sh | bash，
執行一次 `agy` 完成 Google 帳號登入）。額度掛在 Antigravity 方案上，跟
GOOGLE_API_KEY 的 API 池互相獨立。

agy 是 agentic CLI，print 模式（-p）輸出純文字、沒有直接附圖的旗標：圖片要
寫進暫存目錄、在 prompt 裡明確要求它用 view/read 工具開啟該絕對路徑。兩個
實測踩過的坑，改動前先讀：
- prompt 必須指明完整路徑並「禁止搜尋」——模型一旦選了 file-search 工具，
  print 模式下 search 永遠等不到結果，會空轉到 timeout。
- 不要加 --dangerously-skip-permissions：讀檔工具本來就免核准即可執行，而
  聊天內容是陌生玩家打的不可信文字，不能給自動核准 shell 的權限
  （prompt injection）。
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

# 熱鍵觸發時程式可能從 GUI 環境啟動，PATH 不一定有 ~/.local/bin，找不到就用預設安裝路徑
_AGY = shutil.which("agy") or str(Path.home() / ".local" / "bin" / "agy")

_MAX_RETRIES = 3  # 首次失敗後最多再試幾次（與 translator 的 API 路徑一致）
_BACKOFF_BASE = 2.0
_MAX_BACKOFF = 30.0

# agy 沒有結構化的錯誤輸出，用訊息內容判斷是否值得重試
_RETRYABLE_PAT = re.compile(
    r"rate.?limit|quota|resource.?exhausted|overload|unavailable|too many requests"
    r"|timeout waiting|\b429\b|\b50[0234]\b",
    re.IGNORECASE,
)


class AntigravityCliError(RuntimeError):
    """CLI 呼叫失敗（找不到指令、額度用盡、逾時…）。retryable 供重試迴圈判斷。"""

    def __init__(self, msg: str, retryable: bool = False):
        super().__init__(msg)
        self.retryable = retryable


class AntigravityCliParseError(AntigravityCliError):
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
    """跑一次 agy print 模式，回傳 stdout 文字。失敗一律拋 AntigravityCliError。"""
    cmd = [_AGY, "-p", prompt, "--model", model]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.ANTIGRAVITY_CLI_TIMEOUT,
            cwd=cwd,
        )
    except FileNotFoundError:
        raise AntigravityCliError(
            "找不到 agy 指令；請先安裝 Antigravity CLI"
            "（curl -fsSL https://antigravity.google/cli/install.sh | bash）"
            "並執行一次 `agy` 完成 Google 帳號登入"
        ) from None
    except subprocess.TimeoutExpired:
        raise AntigravityCliError(
            f"agy 超過 {config.ANTIGRAVITY_CLI_TIMEOUT}s 沒回應", retryable=True
        ) from None
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        detail = (proc.stderr.strip() or out or "（無輸出）")[:300]
        # exit 0 卻沒輸出視為暫時性問題；非零 exit 依錯誤訊息判斷（auth 錯誤
        # 之類重試也沒用，直接拋）
        empty_ok = proc.returncode == 0 and not out
        raise AntigravityCliError(
            f"agy 失敗（exit {proc.returncode}）：{detail}",
            retryable=bool(_RETRYABLE_PAT.search(detail)) or empty_ok,
        )
    return out


def run(
    model: str,
    instructions: str,
    user_text: str = "",
    image_png: bytes | None = None,
    output_type: Any = str,
    label: str = "agy",
    on_status: Callable[[str], None] | None = None,
) -> Any:
    """呼叫 agy 並把回應驗證成 output_type。

    可重試的失敗（限流、逾時、輸出解析不了）沿用 translator 的節奏退避重試；
    解析失敗重試時會把錯誤訊息附回 prompt 讓模型修正。永遠在只放了這次截圖
    的暫存目錄裡執行，agy 的檔案工具能看到的就只有這張圖。
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
            img_path = tmp / "capture.png"
            img_path.write_bytes(image_png)
            prefix = (
                f"Use your file view/read tool to open {img_path} — an image"
                " file that already exists. Do NOT use any search tool.\n\n"
            )
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
            except AntigravityCliError as e:
                if e.retryable and attempt < _MAX_RETRIES:
                    wait = min(_BACKOFF_BASE * (2**attempt), _MAX_BACKOFF)
                    log.warning(
                        "%s（agy:%s）失敗，%.0fs 後重試（第 %d/%d 次）：%s",
                        label, model, wait, attempt + 1, _MAX_RETRIES, e,
                    )
                    if on_status:
                        on_status(
                            f"{label}：{e}，{wait:.0f} 秒後重試"
                            f"（第 {attempt + 1}/{_MAX_RETRIES} 次）…"
                        )
                    time.sleep(wait)
                    continue
                log.error("%s（agy:%s）失敗：%s", label, model, e)
                raise
            try:
                out = adapter.validate_json(_extract_json(resp))
            except Exception as e:
                parse_err = str(e)[:200]
                if attempt < _MAX_RETRIES:
                    log.warning(
                        "%s（agy:%s）輸出解析失敗，重試：%s", label, model, parse_err
                    )
                    if on_status:
                        on_status(f"{label}：輸出解析失敗，重試中…")
                    continue
                raise AntigravityCliParseError(
                    f"輸出無法解析為預期格式：{parse_err}"
                ) from e
            log.info(
                "%s（agy:%s）成功，耗時 %.1fs", label, model, time.monotonic() - t0
            )
            return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
