"""審核翻譯時記下的候選術語，挑選後補進 slang.json。

翻譯過程中，模型遇到術語表沒收錄的遊戲術語會記到 slang_candidates.jsonl。
這支工具逐條顯示，讓你決定：收錄（可改譯法）／略過（留著下次再看）／丟棄。
收錄的會寫進 slang.json，被處理掉的（收錄或丟棄）會從候選檔移除。

用法：
    uv run python review_candidates.py            # 逐條互動審核
    uv run python review_candidates.py --list      # 只列出候選，不進審核
"""

import argparse
import json
import sys
from pathlib import Path

import config

BASE = Path(__file__).parent
SLANG = BASE / config.SLANG_PATH
CANDIDATES = BASE / config.CANDIDATES_PATH


def load_candidates() -> list[dict]:
    if not CANDIDATES.exists():
        return []
    out = []
    for line in CANDIDATES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def load_slang() -> dict[str, str]:
    if SLANG.exists():
        return json.loads(SLANG.read_text(encoding="utf-8"))
    return {}


def save_slang(slang: dict[str, str]) -> None:
    # 依 key 排序輸出，維持檔案穩定好讀
    SLANG.write_text(
        json.dumps(dict(sorted(slang.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def save_candidates(remaining: list[dict]) -> None:
    if not remaining:
        CANDIDATES.unlink(missing_ok=True)
        return
    CANDIDATES.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in remaining),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="審核候選術語，補進 slang.json")
    parser.add_argument("--list", action="store_true", help="只列出候選，不審核")
    args = parser.parse_args()

    candidates = load_candidates()
    slang = load_slang()
    # 過濾掉已在 slang.json 的（大小寫不敏感）
    have = {k.lower() for k in slang}
    pending = [c for c in candidates if c.get("en", "").lower() not in have]

    if not pending:
        print("沒有待審核的候選術語。")
        # 順手清掉已被收錄的殘留
        if len(pending) != len(candidates):
            save_candidates(pending)
        return

    if args.list:
        print(f"共 {len(pending)} 個待審核候選：")
        for c in pending:
            print(f"  {c['en']:24} → {c.get('zh','')}   ({c.get('ts','')})")
        return

    print(f"共 {len(pending)} 個候選。每條選擇：")
    print("  [y] 收錄（用模型建議的譯法）")
    print("  [e] 收錄但改譯法")
    print("  [n] 略過（留著下次再看）")
    print("  [d] 丟棄（從候選檔移除）")
    print("  [q] 存檔離開\n")

    accepted = 0
    processed_en = set()  # 已收錄或丟棄的（小寫），要從候選檔移除
    quit_early = False

    for i, c in enumerate(pending, 1):
        en, zh = c.get("en", ""), c.get("zh", "")
        print(f"[{i}/{len(pending)}] {en}  →  模型建議：{zh}")
        choice = input("  (y/e/n/d/q) > ").strip().lower()

        if choice == "q":
            quit_early = True
            break
        if choice == "n":
            continue  # 留在候選檔
        if choice == "d":
            processed_en.add(en.lower())
            continue
        if choice in ("y", "e"):
            value = zh
            if choice == "e":
                # 讓使用者輸入完整譯法（可含英文括號提示），空白則沿用
                new = input(f"  新譯法（Enter 沿用「{zh}」）> ").strip()
                if new:
                    value = new
            slang[en] = value
            processed_en.add(en.lower())
            accepted += 1
            print(f"  ✅ 收錄 {en} → {value}")
        else:
            print("  （未辨識，當作略過）")

    if accepted:
        save_slang(slang)
    # 從候選檔移除已處理的（收錄/丟棄）；略過的與未審到的留著
    remaining = [c for c in candidates if c.get("en", "").lower() not in processed_en]
    save_candidates(remaining)

    print()
    print(f"收錄 {accepted} 條到 slang.json，候選檔剩 {len(remaining)} 條。")
    if quit_early:
        print("（中途離開，其餘保留）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
