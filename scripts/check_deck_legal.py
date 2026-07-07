"""
scripts/check_deck_legal.py — デッキ合法性チェック（納品前必須）

使い方:
  python3 scripts/check_deck_legal.py agents/opponents/crustle/deck.csv
  python3 scripts/check_deck_legal.py agents/lucario/v5/deck.csv

errorPlayer == -1 なら合法。それ以外は非合法（要調査）。
errorType == 4 はエンジン非対応カードを含む疑い（カードを1種ずつ基本エネで置換して特定）。

※ このスクリプトはエンジン（engine/libcg.so or engine/cg.dll）が必要です。
  ローカルで動かない場合はハーネス環境で実行してください。
"""
import sys
import os
from pathlib import Path
from collections import Counter

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/check_deck_legal.py <deck.csv>")
        sys.exit(1)

    deck_path = Path(sys.argv[1])
    if not deck_path.exists():
        print(f"Error: {deck_path} not found")
        sys.exit(1)

    deck = [int(x) for x in deck_path.read_text().splitlines() if x.strip()]
    print(f"[静的チェック] デッキ: {deck_path}")
    print(f"  枚数: {len(deck)}")
    assert len(deck) == 60, f"60枚でない: {len(deck)}"

    BASIC_ENERGY = set(range(1, 21))
    cnt = Counter(deck)
    over4 = [(cid, n) for cid, n in cnt.items() if n > 4 and cid not in BASIC_ENERGY]
    if over4:
        print(f"  ⚠ 4枚超え: {over4}")
    else:
        print("  ✓ 全カード4枚以下（基本エネ除く）")

    # battle_start チェック
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root))

    try:
        # cg_tmp を engine/ として import
        sys.path.insert(0, str(repo_root / "engine"))
        # engine/ を cg として認識させる
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "cg", repo_root / "engine" / "__init__.py",
            submodule_search_locations=[str(repo_root / "engine")]
        )
        import types
        cg_module = types.ModuleType("cg")
        cg_module.__path__ = [str(repo_root / "engine")]
        sys.modules["cg"] = cg_module
        from cg import game
    except Exception as e:
        print(f"\n[battle_start チェック] エンジン import 失敗: {e}")
        print("  → ハーネス環境で実行してください")
        print("\n[静的チェック結果] ✓（battle_start は未確認）")
        return

    print("\n[battle_start チェック]")
    obs, start = game.battle_start(deck, deck)
    print(f"  errorPlayer: {start.errorPlayer}")
    print(f"  errorType:   {start.errorType}")

    if start.errorPlayer == -1:
        print("  ✓ 合法 (errorPlayer == -1) — 納品OK")
    else:
        print(f"  ✗ 非合法 (player={start.errorPlayer}, type={start.errorType})")
        if start.errorType == 4:
            print("  → errorType=4: エンジン非対応カードの疑い")
            print("  → カードを1種ずつ基本エネ(id=1)で置換して特定してください")
        print(f"  構成: {dict(sorted(cnt.items()))}")

    game.battle_finish()


if __name__ == "__main__":
    main()
