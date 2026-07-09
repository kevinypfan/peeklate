"""Codex CLI backend：透過本機已登入的 `codex` 指令跑推論。

吃 OpenAI/Codex 的額度，跟其他 backend 互相獨立。安裝後跑一次 `codex login`。

三家裡介面最好用的一個，實測要點：
- `codex exec` 是非互動模式。**stdout 是整份對話 transcript，不是答案**；要用
  -o/--output-last-message 把最後一則訊息寫到檔案再讀回來。
- -i/--image 可以直接附圖，不用像 agy/claude 那樣叫模型自己開檔
  （所以 CliSpec.image_via_prompt=False）。
- --output-schema 看起來很誘人，但它走 OpenAI strict structured output：root 必須是
  object 且每層都要 additionalProperties:false。我們的 list[OcrLine] 是 array root，
  會直接 400（invalid_json_schema）。所以照樣用 cli_runner 的 schema-in-prompt。
- exit code 這家是可信的（錯誤會回非 0），跟 agy／claude 不同。
- 安全姿態：聊天內容是陌生玩家打的不可信文字。-s read-only 讓模型產生的 shell
  指令只能在唯讀 sandbox 跑（預設 approval: never、網路關閉）；--ignore-user-config
  與 --ephemeral 則避免載入使用者的 config.toml、也不留 session 檔。
  絕對不要加 --dangerously-bypass-approvals-and-sandbox。
"""

import logging
import re
import shutil
from pathlib import Path
from subprocess import CompletedProcess

import config
from cli_runner import RETRYABLE_STATUS, CliCall, CliError, CliQuotaError, CliSpec

log = logging.getLogger(__name__)

_CODEX = shutil.which("codex") or "codex"

# codex 把 API 錯誤原文（含 JSON）吐在 stderr，撈得到 HTTP 狀態就照狀態判斷
_STATUS_PAT = re.compile(r'"status"\s*:\s*(\d{3})|\b(4\d\d|5\d\d)\b')
_QUOTA_PAT = re.compile(
    r"usage limit|quota|insufficient_quota|billing|out of credit", re.IGNORECASE
)

_NOT_FOUND = "找不到 codex 指令；請先安裝 Codex CLI 並執行 `codex login`"


def _out_path(call: CliCall) -> Path:
    # 放在 side（cwd 外面），免得模型的檔案工具看到自己的輸出檔
    return call.side / "out.txt"


def _build_argv(call: CliCall) -> list[str]:
    argv = [
        _CODEX, "exec",
        "--skip-git-repo-check",  # 暫存工作區不是 git repo
        "--ephemeral",  # 不要留 session 檔
        "--ignore-user-config",  # 不要載入使用者的 config.toml
        "-s", "read-only",  # 模型產生的 shell 只能在唯讀 sandbox 跑
        "-o", str(_out_path(call)),
    ]
    if call.model:  # 留空就用 codex 自己的預設模型
        argv += ["-m", call.model]
    if call.image is not None:
        # 一定要用 --image=<path> 這種綁死單一值的寫法：-i/--image 是 variadic
        # （<FILE>...），寫成 ["-i", path] 的話它會把後面的 prompt 也吃進來當第二張圖，
        # codex 反而抱怨沒有 prompt、改去讀 stdin
        argv.append(f"--image={call.image}")
    argv.append(call.prompt)
    return argv


def _status_of(text: str) -> int | None:
    m = _STATUS_PAT.search(text)
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def _read_response(proc: CompletedProcess, call: CliCall) -> str:
    out_file = _out_path(call)
    try:
        text = out_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        text = ""

    if proc.returncode == 0 and text:
        return text

    # stdout 是 transcript，錯誤細節在 stderr
    detail = ((proc.stderr or "").strip() or text or "（無輸出）")[:300]
    if _QUOTA_PAT.search(detail):
        raise CliQuotaError(
            f"Codex 額度已用盡：{detail}。改用其他 backend 或等額度重置",
            retryable=False,
        )
    status = _status_of(detail)
    # exit 0 卻沒寫出檔案 → 當暫時性問題再試
    empty_ok = proc.returncode == 0 and not text
    raise CliError(
        f"codex 失敗（exit {proc.returncode}）：{detail}",
        retryable=(status in RETRYABLE_STATUS) or empty_ok,
    )


BACKEND = CliSpec(
    name="codex",
    binary=_CODEX,
    not_found_hint=_NOT_FOUND,
    timeout=config.CODEX_CLI_TIMEOUT,
    build_argv=_build_argv,
    read_response=_read_response,
    image_via_prompt=False,  # 有 -i，不用叫模型自己開檔
)
