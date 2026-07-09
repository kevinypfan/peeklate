"""審核翻譯時記下的候選術語，挑選後補進 slang.json。

翻譯過程中，模型遇到術語表沒收錄的遊戲術語會記到 slang_candidates.jsonl。
這支工具逐條顯示，讓你決定：收錄（可改譯法）／併入現有概念當別名／略過／丟棄。
收錄的會寫進 slang.json，被處理掉的（收錄或丟棄）會從候選檔移除。

slang.json 支援兩種寫法：
- 扁平："dps": "輸出 (...)"
- 分組："escalation": {"zh": "...", "aka": ["esc", "escal"]}
同一概念的多種拼法用 aka 收在一起，共用一條譯文，避免同義詞各寫各的飄掉。
收錄時若偵測到譯文跟現有某條很像，會提醒你八成是同義、可直接併為別名。

用法：
    uv run python review_candidates.py            # 逐條互動審核
    uv run python review_candidates.py --list      # 只列出候選，不進審核
"""

import argparse
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

import config

BASE = Path(__file__).parent
SLANG = BASE / config.SLANG_PATH
CANDIDATES = BASE / config.CANDIDATES_PATH

# 譯文相似度達這個門檻就當作可能同義，提醒使用者併為別名
_SYNONYM_THRESHOLD = 0.62


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


def load_slang() -> dict:
    if SLANG.exists():
        return json.loads(SLANG.read_text(encoding="utf-8"))
    return {}


def _dump_val(val):
    """輸出前整理：aka 去重排序；空 aka 的分組收回成扁平字串。"""
    if isinstance(val, dict):
        aka = sorted({a for a in val.get("aka", []) if a})
        zh = val.get("zh", "")
        return {"zh": zh, "aka": aka} if aka else zh
    return val


def save_slang(slang: dict) -> None:
    # 依 key 排序輸出，維持檔案穩定好讀
    ordered = {k: _dump_val(slang[k]) for k in sorted(slang)}
    SLANG.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
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


def surface_forms(slang: dict) -> set[str]:
    """所有可比對的縮寫（canonical key + 每個 aka），小寫。"""
    forms = set()
    for en, val in slang.items():
        forms.add(en.lower())
        if isinstance(val, dict):
            forms.update(a.lower() for a in val.get("aka", []))
    return forms


def concept_zh(val) -> str:
    return val.get("zh", "") if isinstance(val, dict) else val


def _norm(s: str) -> str:
    """比對用的正規化：統一全半形括號、去空白、英文轉小寫。"""
    return (
        s.lower()
        .replace("（", "(")
        .replace("）", ")")
        .replace(" ", "")
        .replace("　", "")
    )


def best_synonym(zh: str, slang: dict) -> tuple[str, str, float] | None:
    """在現有概念裡找譯文最像的一條，回 (canonical_key, 該概念 zh, 相似度)。"""
    target = _norm(zh)
    if not target:
        return None
    best: tuple[str, str, float] | None = None
    for en, val in slang.items():
        other = concept_zh(val)
        ratio = SequenceMatcher(None, target, _norm(other)).ratio()
        if best is None or ratio > best[2]:
            best = (en, other, ratio)
    if best and best[2] >= _SYNONYM_THRESHOLD:
        return best
    return None


def add_alias(slang: dict, concept_key: str, alias: str) -> None:
    """把 alias 掛到既有概念底下（必要時把扁平條目升級成分組）。"""
    val = slang[concept_key]
    if not isinstance(val, dict):
        val = {"zh": val, "aka": []}
        slang[concept_key] = val
    if alias.lower() not in {a.lower() for a in val["aka"]}:
        val["aka"].append(alias)


def main() -> None:
    parser = argparse.ArgumentParser(description="審核候選術語，補進 slang.json")
    parser.add_argument("--list", action="store_true", help="只列出候選，不審核")
    args = parser.parse_args()

    candidates = load_candidates()
    slang = load_slang()
    # 過濾掉已在 slang.json 的（含 aka 別名，大小寫不敏感）
    have = surface_forms(slang)
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
    print("  [y] 收錄為新概念（用模型建議的譯法）")
    print("  [e] 收錄為新概念但改譯法")
    print("  [a] 併入偵測到的相似概念，當它的別名")
    print("  [n] 略過（留著下次再看）")
    print("  [d] 丟棄（從候選檔移除）")
    print("  [q] 存檔離開\n")

    accepted = 0
    processed_en = set()  # 已收錄或丟棄的（小寫），要從候選檔移除
    quit_early = False

    for i, c in enumerate(pending, 1):
        en, zh = c.get("en", ""), c.get("zh", "")
        print(f"[{i}/{len(pending)}] {en}  →  模型建議：{zh}")

        syn = best_synonym(zh, slang)
        if syn:
            print(
                f"  ⚠ 疑似同義（相似度 {syn[2]:.0%}）：現有「{syn[0]}」→ {syn[1]}"
                f"\n     按 [a] 可把「{en}」併為「{syn[0]}」的別名"
            )
        choice = input("  (y/e/a/n/d/q) > ").strip().lower()

        if choice == "q":
            quit_early = True
            break
        if choice == "n":
            continue  # 留在候選檔
        if choice == "d":
            processed_en.add(en.lower())
            continue
        if choice == "a":
            if not syn:
                print("  （沒有偵測到相似概念，當作略過）")
                continue
            add_alias(slang, syn[0], en)
            processed_en.add(en.lower())
            accepted += 1
            print(f"  ✅ 併入 {syn[0]} 的別名：{en}")
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
    print(f"處理 {accepted} 條到 slang.json，候選檔剩 {len(remaining)} 條。")
    if quit_early:
        print("（中途離開，其餘保留）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
