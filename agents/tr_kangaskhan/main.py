"""
tr_kangaskhan/main.py — TR Kangaskhan ex メトロノームデッキ（null政策・対照実験）

設計メモ:
  アタッカー：Team Rocket's Kangaskhan ex (ID 24) ×4
    HP230 / 通常ex / KO時2プライズ
    技 Wicked Impact: 無色×3 → 120固定（毎ターン反復可）
    ※ Mega Kangaskhan ex(756)と異なり「Run Errand(毎ターン2ドロー)」特性を持たない

  対照設計（コントロール実験）:
    殻(トレーナー28枚)・エネルギー28枚は pk_nullpol（pure Kanga null）と完全同一。
    差し替えは「756→24」のみ。
    Run Errand不在によるドロー低下を、殻のドローサポート（Lillie/Drayton/Hilda/Cheren）
    が代替できるかを測定側が評価する。

  エネ設計:
    無色×3なのでどの基本エネでも払える。
    pk_nullpolと同一: 草(1)×23 + Grow Grass(18)×4 + Enriching Energy(13)×1(ACE SPEC)

  政策：null政策（空政策）= 常に最小合法手を返す。

デッキ60枚:
  24×4 TR Kangaskhan ex / 殻トレーナー×28 / エネ×28(pk_nullpol同一)
    [エネ] 1×23 Basic Grass / 18×4 Grow Grass / 13×1 Enriching(ACE SPEC)
    [殻]   1227×4 Lillie / 1202×4 Drayton / 1121×4 UltraBall
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
    if isinstance(obs_dict, dict) and obs_dict.get("select") is None:
        return my_deck
    try:
        sel = (obs_dict or {}).get("select") or {}
        opts = sel.get("option") or []
        k = min(max(0, sel.get("minCount", 0)), len(opts))
        return list(range(k))
    except Exception:
        return []
