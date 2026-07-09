"""所有 CLI backend 共用的執行器：暫存工作區、附圖、JSON schema、重試。

各家 agentic CLI 的差異只有四點，都收斂在 CliSpec 的兩個 callable 裡：
- 執行檔怎麼找、argv 怎麼組
- 答案文字要從哪裡撈（agy 是 stdout、claude 是 JSON envelope、codex 是 -o 檔）
- 失敗怎麼判定（三家的 exit code 都不可靠，詳見各 adapter）
- 圖片怎麼給（agy/claude 要在 prompt 裡叫模型自己開檔，codex 有 -i）

共用的部分（這裡）只寫一次，包含幾個踩過的坑：
- subprocess 一律指定 encoding="utf-8"：不指定會用 locale 編碼（Windows 繁中是
  cp950），CLI 一吐中文就在 reader thread 炸 UnicodeDecodeError，communicate()
  只回 None，錯誤現場離真正原因很遠。
- 模型的工作目錄（cwd）裡只放這次的截圖；log／輸出檔一律放在 cwd 外面的 side
  目錄，免得模型的檔案工具看到它們。
- 聊天內容是陌生玩家打的不可信文字，各 adapter 都必須用唯讀／禁止執行的姿態
  跑（prompt injection），細節見各自的 build_argv。
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import TypeAdapter

log = logging.getLogger(__name__)

_MAX_RETRIES = 3  # 首次失敗後最多再試幾次（與 translator 的 API 路徑一致）
_BACKOFF_BASE = 2.0
_MAX_BACKOFF = 30.0

# 跟 translator API 路徑的 _RETRYABLE_STATUS 同一套語意
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class CliError(RuntimeError):
    """CLI 呼叫失敗（找不到指令、額度用盡、逾時…）。retryable 供重試迴圈判斷。"""

    def __init__(self, msg: str, retryable: bool = False):
        super().__init__(msg)
        self.retryable = retryable


class CliParseError(CliError):
    """模型回了文字但無法解析成預期的 JSON 格式（重試後仍失敗）。"""


class CliQuotaError(CliError):
    """方案額度用盡；等額度重置或改用其他 backend 才有解，重試沒有意義。"""


@dataclass(frozen=True)
class CliCall:
    """單次呼叫的路徑與參數，adapter 只讀。"""

    model: str
    prompt: str
    cwd: Path  # CLI 的 workspace，裡面只有這次的截圖
    side: Path  # workspace 外的暫存區，放 log／輸出檔，模型看不到
    image: Path | None
    timeout: int


@dataclass(frozen=True)
class CliSpec:
    """一個 CLI backend 的全部差異。"""

    name: str
    binary: str
    not_found_hint: str
    timeout: int
    build_argv: Callable[[CliCall], list[str]]
    read_response: Callable[[subprocess.CompletedProcess, CliCall], str]
    # True：在 prompt 裡叫模型用讀檔工具開圖（agy／claude）
    # False：CLI 自己有附圖旗標（codex -i）
    image_via_prompt: bool = True


def json_instruction(adapter: TypeAdapter) -> str:
    """CLI 沒有原生 structured output，只能把 schema 塞進 prompt 要求它照抄。"""
    schema = json.dumps(adapter.json_schema(), ensure_ascii=False)
    return (
        "\n\nRespond with ONLY a raw JSON value that matches this JSON Schema"
        " (no code fences, no commentary, no extra text):\n" + schema
    )


def extract_json(text: str) -> str:
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


def _invoke(spec: CliSpec, call: CliCall) -> str:
    """跑一次 CLI，回傳答案文字。失敗一律拋 CliError（或其子類）。"""
    try:
        # encoding 一定要指定，理由見 module docstring
        # stdin 一定要關掉：codex 看到 stdin 不是 tty 就會把它當成 prompt 的一部分讀進去
        # （"Reading additional input from stdin..."），從 GUI／pipe 啟動時會吃到雜訊或卡住
        proc = subprocess.run(
            spec.build_argv(call),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            timeout=call.timeout + 10,  # subprocess 只當兜底硬牆
            cwd=str(call.cwd),
        )
    except FileNotFoundError:
        raise CliError(spec.not_found_hint) from None
    except subprocess.TimeoutExpired:
        raise CliError(
            f"{spec.name} 超過 {call.timeout + 10}s 沒回應", retryable=True
        ) from None
    return spec.read_response(proc, call)


def run(
    spec: CliSpec,
    model: str,
    instructions: str,
    user_text: str = "",
    image_png: bytes | None = None,
    output_type: Any = str,
    label: str = "",
    on_status: Callable[[str], None] | None = None,
) -> Any:
    """呼叫 CLI 並把回應驗證成 output_type。

    可重試的失敗（限流、逾時、輸出解析不了）沿用 translator 的節奏退避重試；
    解析失敗重試時會把錯誤訊息附回 prompt 讓模型修正。永遠在只放了這次截圖
    的暫存目錄裡執行，模型的檔案工具能看到的就只有這張圖。
    """
    label = label or spec.name
    adapter = (
        output_type
        if isinstance(output_type, TypeAdapter)
        else TypeAdapter(output_type)
    )
    tmp = Path(tempfile.mkdtemp(prefix="peeklate_"))  # 模型的 workspace
    side = Path(tempfile.mkdtemp(prefix="peeklate_side_"))  # log／輸出檔，模型看不到
    try:
        image = None
        prefix = ""
        if image_png is not None:
            image = tmp / "capture.png"
            image.write_bytes(image_png)
            if spec.image_via_prompt:
                # 必須指明完整路徑並「禁止搜尋」——模型一旦選了 file-search 工具，
                # 非互動模式下 search 永遠等不到結果，會空轉到 timeout
                prefix = (
                    f"Use your file view/read tool to open {image} — an image"
                    " file that already exists. Do NOT use any search tool.\n\n"
                )
        base_prompt = prefix + instructions
        if user_text:
            base_prompt += "\n\n" + user_text
        base_prompt += json_instruction(adapter)

        parse_err = ""
        for attempt in range(_MAX_RETRIES + 1):
            prompt = base_prompt
            if parse_err:
                prompt += (
                    f"\n\nYour previous reply was not valid ({parse_err})."
                    " Output ONLY the JSON value."
                )
            call = CliCall(
                model=model,
                prompt=prompt,
                cwd=tmp,
                side=side,
                image=image,
                timeout=spec.timeout,
            )
            t0 = time.monotonic()
            try:
                resp = _invoke(spec, call)
            except CliError as e:
                if e.retryable and attempt < _MAX_RETRIES:
                    wait = min(_BACKOFF_BASE * (2**attempt), _MAX_BACKOFF)
                    log.warning(
                        "%s（%s:%s）失敗，%.0fs 後重試（第 %d/%d 次）：%s",
                        label, spec.name, model, wait, attempt + 1, _MAX_RETRIES, e,
                    )
                    if on_status:
                        on_status(
                            f"{label}：{e}，{wait:.0f} 秒後重試"
                            f"（第 {attempt + 1}/{_MAX_RETRIES} 次）…"
                        )
                    time.sleep(wait)
                    continue
                log.error("%s（%s:%s）失敗：%s", label, spec.name, model, e)
                raise
            try:
                out = adapter.validate_json(extract_json(resp))
            except Exception as e:
                parse_err = str(e)[:200]
                if attempt < _MAX_RETRIES:
                    log.warning(
                        "%s（%s:%s）輸出解析失敗，重試：%s",
                        label, spec.name, model, parse_err,
                    )
                    if on_status:
                        on_status(f"{label}：輸出解析失敗，重試中…")
                    continue
                raise CliParseError(
                    f"輸出無法解析為預期格式：{parse_err}"
                ) from e
            log.info(
                "%s（%s:%s）成功，耗時 %.1fs",
                label, spec.name, model, time.monotonic() - t0,
            )
            return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(side, ignore_errors=True)
