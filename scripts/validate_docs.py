"""
scripts/validate_docs.py — 必須ファイルの存在確認

使い方:
  python3 scripts/validate_docs.py

全てのチェックが PASS なら終了コード0。FAIL があれば終了コード1。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

REQUIRED_FILES = [
    # ルーター
    "AGENTS.md",
    "README.md",
    ".gitignore",
    # docs/agent
    "docs/agent/project-overview.md",
    "docs/agent/confirmed-facts.md",
    "docs/agent/decision-log.md",
    "docs/agent/measurement-protocol.md",
    "docs/agent/workflow.md",
    "docs/agent/glossary.md",
    "docs/agent/repository-structure.md",
    # agents
    "agents/lucario/v2/main.py",
    "agents/lucario/v2/deck.csv",
    "agents/lucario/v5/main.py",
    "agents/lucario/v5/deck.csv",
    "agents/opponents/crustle/main.py",
    "agents/opponents/crustle/deck.csv",
    "agents/opponents/zoroark/main.py",
    "agents/opponents/zoroark/deck.csv",
    # skills
    "skills/stochastic-agent-eval/SKILL.md",
    "skills/llm-role-handoff/SKILL.md",
    # scripts
    "scripts/check_deck_legal.py",
    "scripts/validate_docs.py",
    # harness & engine docs
    "harness/README.md",
    "engine/README.md",
]

FORBIDDEN_IN_CONFIRMED_FACTS = [
    "v4最弱",
    "62.1%",
    "416.9",
    "因果確認済み",
]


def main():
    failures = []

    print("=== validate_docs.py ===\n")

    # 必須ファイル存在確認
    print("[1] 必須ファイル存在確認")
    for f in REQUIRED_FILES:
        path = ROOT / f
        if path.exists():
            print(f"  ✓ {f}")
        else:
            print(f"  ✗ MISSING: {f}")
            failures.append(f"Missing: {f}")

    # confirmed-facts.md に撤回済み偽陽性が含まれていないか確認
    print("\n[2] confirmed-facts.md に撤回済み偽陽性が含まれていないか確認")
    cf_path = ROOT / "docs/agent/confirmed-facts.md"
    if cf_path.exists():
        content = cf_path.read_text()
        for forbidden in FORBIDDEN_IN_CONFIRMED_FACTS:
            if forbidden in content:
                print(f"  ✗ FORBIDDEN TEXT FOUND: '{forbidden}'")
                failures.append(f"Forbidden text in confirmed-facts.md: '{forbidden}'")
            else:
                print(f"  ✓ '{forbidden}' なし")
    else:
        print("  SKIP（ファイルなし）")

    # デッキ枚数確認
    print("\n[3] デッキ枚数確認（60枚）")
    deck_files = list((ROOT / "agents").rglob("deck.csv"))
    for df in deck_files:
        lines = [l.strip() for l in df.read_text().splitlines() if l.strip()]
        rel = df.relative_to(ROOT)
        if len(lines) == 60:
            print(f"  ✓ {rel}: {len(lines)}枚")
        else:
            print(f"  ✗ {rel}: {len(lines)}枚（60枚でない）")
            failures.append(f"Deck not 60 cards: {rel}")

    # 結果
    print(f"\n{'='*30}")
    if failures:
        print(f"FAIL: {len(failures)} 件の問題")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL PASS ✓")
        sys.exit(0)


if __name__ == "__main__":
    main()
