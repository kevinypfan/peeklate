"""Antigravity CLI backend：透過本機已登入的 `agy` 指令跑推論。

Google 在 2026-06-18 停止 Gemini CLI 服務個人帳號，個人免費額度移到
Antigravity（安裝：curl -fsSL https://antigravity.google/cli/install.sh | bash，
執行一次 `agy` 完成 Google 帳號登入）。額度掛在 Antigravity 方案上，跟
GOOGLE_API_KEY 的 API 池互相獨立。

agy 是 agentic CLI，print 模式（-p）輸出純文字、沒有直接附圖的旗標：圖片要
寫進暫存目錄、在 prompt 裡明確要求它用 view/read 工具開啟該絕對路徑（由
cli_runner 的 image_via_prompt 負責）。三個實測踩過的坑，改動前先讀：
- prompt 必須指明完整路徑並「禁止搜尋」——模型一旦選了 file-search 工具，
  print 模式下 search 永遠等不到結果，會空轉到 timeout。
- 不要加 --dangerously-skip-permissions：讀檔工具本來就免核准即可執行，而
  聊天內容是陌生玩家打的不可信文字，不能給自動核准 shell 的權限
  （prompt injection）。
- agy 額度用盡時 exit code 是 0、stdout/stderr 全空，真正的 429 只寫進
  --log-file。所以判斷成敗一定要回頭撈 log，不能信 exit code。
"""

import logging
import re
import shutil
from pathlib import Path
from subprocess import CompletedProcess

import config
from cli_runner import CliCall, CliError, CliQuotaError, CliSpec

log = logging.getLogger(__name__)

# 熱鍵觸發時程式可能從 GUI 環境啟動，PATH 不一定有 ~/.local/bin，找不到就用預設安裝路徑
_AGY = shutil.which("agy") or str(Path.home() / ".local" / "bin" / "agy")

# agy 沒有結構化的錯誤輸出，用訊息內容判斷是否值得重試
_RETRYABLE_PAT = re.compile(
    r"rate.?limit|quota|resource.?exhausted|overload|unavailable|too many requests"
    r"|timeout waiting|\b429\b|\b50[0234]\b",
    re.IGNORECASE,
)

# 方案額度用盡（週配額）——重試到天荒地老也沒用，要壓過 _RETRYABLE_PAT 的 quota/429
_QUOTA_PAT = re.compile(
    r"individual quota reached|upgrade your subscription", re.IGNORECASE
)
_RESET_PAT = re.compile(r"resets? in ([0-9hms]+)", re.IGNORECASE)

# agy 把 429 之類的真正錯誤只寫進 --log-file，stdout/stderr 全空、exit code 還是 0，
# 所以失敗時得回頭撈它的 log 才知道發生什麼事。glog 格式：E0709 11:43:14.466443 6752 log.go:398] msg
_LOG_ERR_PAT = re.compile(r"^E\d{4} [\d:.]+ +\d+ +[^]]+\] (.*)$", re.MULTILINE)
# agy 自己的無害雜訊，撈錯誤時略過免得蓋掉真正的原因
_LOG_NOISE_PAT = re.compile(r"transcript\.jsonl", re.IGNORECASE)

_NOT_FOUND = (
    "找不到 agy 指令；請先安裝 Antigravity CLI"
    "（curl -fsSL https://antigravity.google/cli/install.sh | bash）"
    "並執行一次 `agy` 完成 Google 帳號登入"
)


def _log_errors(log_path: Path) -> str:
    """從 agy 的 log 撈出這次執行的錯誤訊息（agy 不會印在 stdout/stderr）。"""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    msgs: list[str] = []
    for m in _LOG_ERR_PAT.finditer(text):
        msg = m.group(1).strip()
        if _LOG_NOISE_PAT.search(msg) or msg in msgs:
            continue
        msgs.append(msg)
    return " | ".join(msgs[-2:])


def _log_path(call: CliCall) -> Path:
    # 放在 side（cwd 外面）：cwd 是 agy 的 workspace，多一個檔案會讓它的檔案工具看到
    return call.side / "agy.log"


def _build_argv(call: CliCall) -> list[str]:
    # --print-timeout 讓 agy 自己先放棄（它遇到 429 會內部退避重試，預設等 5 分鐘），
    # 這樣我們拿得到它寫的 log；subprocess 的 timeout 只當作兜底的硬牆
    return [
        _AGY, "-p", call.prompt, "--model", call.model,
        "--log-file", str(_log_path(call)),
        "--print-timeout", f"{call.timeout}s",
    ]


def _read_response(proc: CompletedProcess, call: CliCall) -> str:
    out = (proc.stdout or "").strip()
    if proc.returncode == 0 and out:
        return out

    # agy 額度用盡時 exit 0、stdout/stderr 全空，真正的 429 只在 log 裡
    logged = _log_errors(_log_path(call))
    detail = (logged or (proc.stderr or "").strip() or out or "（無輸出）")[:300]
    if _QUOTA_PAT.search(logged):
        reset = _RESET_PAT.search(logged)
        when = f"，額度約 {reset.group(1)} 後重置" if reset else ""
        # 不標 retryable：週配額重試只是白等三輪退避
        raise CliQuotaError(
            f"Antigravity 額度已用盡{when}。"
            "改用其他 backend（config 換成 claude-cli:／codex-cli:／google:）或等額度重置",
            retryable=False,
        )
    # exit 0 卻沒輸出且 log 也沒線索 → 當暫時性問題；非零 exit 依錯誤訊息判斷
    # （auth 錯誤之類重試也沒用，直接拋）
    empty_ok = proc.returncode == 0 and not out and not logged
    raise CliError(
        f"agy 失敗（exit {proc.returncode}）：{detail}",
        retryable=bool(_RETRYABLE_PAT.search(detail)) or empty_ok,
    )


BACKEND = CliSpec(
    name="agy",
    binary=_AGY,
    not_found_hint=_NOT_FOUND,
    timeout=config.ANTIGRAVITY_CLI_TIMEOUT,
    build_argv=_build_argv,
    read_response=_read_response,
)
