"""
hooh_ex/main.py — Ethan's Ho-Oh ex メトロノームデッキ（null政策）

設計メモ:
  アタッカー：Ethan's Ho-Oh ex (ID 357) ×4
    HP230 / 通常ex / KO時2プライズ
    技 Shining Feathers: 炎×4 → 160固定 + 全味方50回復（毎ターン反復可）
    特性 Golden Flame: 手札から基本炎エネを2枚「ヒビキの」ベンチへ加速
      ※ アクティブのHo-Oh自身は加速できない = アクティブへは手貼りのみ

  エネ設計:
    基本炎エネ(id=2) ×28。炎×4コスト要件に対し厚めに確保。
    Enriching Energy(13/無色) ・ Grow Grass(18/草) は炎コストを払えないため除外。
    殻(トレーナー28枚)はpk_nullpolと完全同一。

  政策：null政策（空政策）= 常に最小合法手を返す。
    汎化検証目的: Kangaskhan以外でもnull政策が機能するかを確認するため。

デッキ60枚:
  357×4 Ho-Oh ex / 基本炎(2)×28 / 殻トレーナー×28
    [殻] 1227×4 Lillie / 1202×4 Drayton / 1121×4 UltraBall
         1225×3 Hilda / 1147×3 JumboIce / 1210×2 Brock's
         1224×2 Cheren / 1152×2 PokéPad / 1097×2 NightStr / 1264×2 BattleCage
"""
import os, sys

def _find_deck():
    cands = []
    if "__file__" in globals():
        cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "deck.csv"))
    cands += ["deck.csv", "/kaggle_simulations/agent/deck.csv"]
    cands += [os.path.join(p, "deck.csv") for p in sys.path if p]
    for path in cands:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("deck.csv not found")

_deck_path = _find_deck()
my_deck = [int(l.strip()) for l in open(_deck_path, encoding="utf-8") if l.strip()]
assert len(my_deck) == 60, f"deck must be 60, got {len(my_deck)}"


def agent(obs_dict: dict) -> list[int]:
    """null政策: 常に最小合法手を返す。"""
    # デッキ選択フェーズ
    if isinstance(obs_dict, dict) and obs_dict.get("select") is None:
        return my_deck
    # 行動選択フェーズ: 最小合法手（range(minCount)）
    try:
        sel = (obs_dict or {}).get("select") or {}
        opts = sel.get("option") or []
        k = min(max(0, sel.get("minCount", 0)), len(opts))
        return list(range(k))
    except Exception:
        return []
