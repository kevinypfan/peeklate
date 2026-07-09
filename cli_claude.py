"""Claude Code CLI backend：透過本機已登入的 `claude` 指令跑推論。

吃的是 Claude 訂閱／API 額度，跟 Antigravity 的免費 Gemini 池、GOOGLE_API_KEY
的 API 池三者互相獨立。安裝與登入見 https://claude.com/claude-code

實測踩過的坑，改動前先讀：
- --output-format json 會回一個 envelope（is_error / api_error_status / result
  / subtype / permission_denials）。**exit code 不可信**：模型名打錯時 exit 仍是
  0，只有 envelope 裡 is_error=true、api_error_status=404。所以一律解析 envelope。
- api_error_status 是 HTTP 狀態碼，直接沿用 RETRYABLE_STATUS 判斷可不可重試，
  跟 translator 的 API 路徑同一套語意。
- result 常常包在 ```json fence 裡，交給 cli_runner.extract_json 處理。
- 安全姿態（重要）：聊天內容是陌生玩家打的不可信文字，會整段進 -p 的 prompt。
  headless 預設是會執行工具的——實測用 -p 叫它跑 shell，它真的跑了。因此一定要
  --permission-mode plan（實測擋掉 shell 執行、但仍可讀檔）再加 --disallowedTools
  當第二層。--strict-mcp-config 則避免載入使用者自己的 MCP server。
  絕對不要加 --dangerously-skip-permissions。
"""

import json
import logging
import shutil
from subprocess import CompletedProcess

import config
from cli_runner import RETRYABLE_STATUS, CliCall, CliError, CliQuotaError, CliSpec

log = logging.getLogger(__name__)

_CLAUDE = shutil.which("claude") or "claude"

# 就算 plan 模式已經擋住執行，仍明確拔掉會寫檔／連外／開子 agent 的工具
_DENY = ["Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task"]

# 訂閱額度用盡的說法（重試沒用）。429 也可能只是短暫限流，所以只認這些字樣
_QUOTA_HINTS = ("usage limit", "rate limit reset", "upgrade to", "out of credit")

_NOT_FOUND = "找不到 claude 指令；請先安裝 Claude Code CLI 並登入（https://claude.com/claude-code）"


def _build_argv(call: CliCall) -> list[str]:
    argv = [
        _CLAUDE, "-p", call.prompt,
        "--output-format", "json",
        "--strict-mcp-config",  # 不要載入使用者的 MCP server
        "--permission-mode", "plan",  # 唯讀：擋掉 prompt injection 誘導的執行
        "--disallowedTools", *_DENY,
    ]
    if call.model:
        argv += ["--model", call.model]
    if call.image is not None:
        # OCR 這段要讀截圖；plan 模式下 Read 仍可用（實測過）
        argv += ["--allowedTools", "Read", "--add-dir", str(call.cwd)]
    return argv


def _read_response(proc: CompletedProcess, call: CliCall) -> str:
    raw = (proc.stdout or "").strip()
    if not raw:
        detail = ((proc.stderr or "").strip() or "（無輸出）")[:300]
        raise CliError(f"claude 沒有輸出（exit {proc.returncode}）：{detail}", retryable=True)
    try:
        env = json.loads(raw)
    except json.JSONDecodeError:
        # 不是 envelope（例如 CLI 自己的 usage 訊息）；當暫時性問題再試一次
        raise CliError(f"claude 回應不是 JSON envelope：{raw[:300]}", retryable=True) from None

    if env.get("is_error"):
        status = env.get("api_error_status")
        detail = (env.get("result") or env.get("subtype") or "（無說明）")[:300]
        if any(h in detail.lower() for h in _QUOTA_HINTS):
            raise CliQuotaError(
                f"Claude 額度已用盡：{detail}。改用其他 backend 或等額度重置",
                retryable=False,
            )
        raise CliError(
            f"claude 失敗（api_error_status={status}）：{detail}",
            retryable=status in RETRYABLE_STATUS,
        )

    result = (env.get("result") or "").strip()
    if not result:
        denials = env.get("permission_denials") or []
        if denials:
            # 工具被擋住而交不出答案：多半是姿態設定壞了，重試無益
            raise CliError(f"claude 的工具被拒絕，拿不到結果：{denials}", retryable=False)
        raise CliError("claude 回了空結果", retryable=True)
    return result


BACKEND = CliSpec(
    name="claude",
    binary=_CLAUDE,
    not_found_hint=_NOT_FOUND,
    timeout=config.CLAUDE_CLI_TIMEOUT,
    build_argv=_build_argv,
    read_response=_read_response,
)
