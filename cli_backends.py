"""CLI backend 註冊表：把 config 的前綴對應到各家 adapter。

新增一家 CLI 只要寫一個 adapter 模組（提供 BACKEND）再登記到 _BACKENDS。
沒有前綴（或前綴不認識）的 model spec 會落到 translator 的 pydantic-ai 路徑，
例如 "google:gemini-3.5-flash"。
"""

import antigravity_cli
import cli_claude
import cli_codex
from cli_runner import CliSpec

_BACKENDS: dict[str, CliSpec] = {
    "antigravity-cli": antigravity_cli.BACKEND,
    "claude-cli": cli_claude.BACKEND,
    "codex-cli": cli_codex.BACKEND,
}


def resolve(spec: str) -> tuple[CliSpec | None, str]:
    """把 "claude-cli:sonnet" 拆成 (BACKEND, "sonnet")。

    不是 CLI backend 就回 (None, 原字串)，交給 pydantic-ai。
    模型名允許留空（"codex-cli:"）→ 用該 CLI 自己的預設模型。
    """
    prefix, sep, model = spec.partition(":")
    if not sep:
        return None, spec
    backend = _BACKENDS.get(prefix)
    return (backend, model) if backend else (None, spec)
