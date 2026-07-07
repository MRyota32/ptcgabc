"""
crustle/check_deck.py — battle_start 合法性チェック
測定環境（cg使用可能環境）で実行してください。
Usage: python3 check_deck.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cg import game

deck_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deck.csv")
deck = [int(x) for x in open(deck_path) if x.strip()]
assert len(deck) == 60, f"60枚でない: {len(deck)}"

print(f"[battle_start check] deck size: {len(deck)}")
obs, start = game.battle_start(deck, deck)
print(f"errorPlayer: {start.errorPlayer}")
print(f"errorType:   {start.errorType}")

if start.errorPlayer == -1:
    print("✓ 合法 (errorPlayer==-1) — 納品OK")
else:
    print(f"✗ 非合法 (player={start.errorPlayer}, type={start.errorType}) — 要調査")
    from collections import Counter
    cnt = Counter(deck)
    print("構成:", dict(sorted(cnt.items())))

game.battle_finish()
