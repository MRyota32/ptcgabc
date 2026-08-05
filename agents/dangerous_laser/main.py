"""
dangerous_laser/main.py — Dangerous Laser 搭載 Crushing Hammer デッキ（null政策）

設計メモ:
  ベース: disrupt_C（Crushing Hammer Kangaskhan）から ACE SPEC を差し替え
    変更点: Enriching Energy (13) → Dangerous Laser (1095)
    差し替え以外はすべて同一（1-card swap）

  アタッカー: Mega Kangaskhan ex (ID 756) ×4
    HP240 / Mega ex / KO時2プライズ
    特性 Run Errand: 自分のターン開始時に2ドロー
    技 Crushing Swing: 無色×3 → 120固定

  妨害カード:
    Crushing Hammer (1120) ×4
      相手のエネルギーをコイン表で1枚トラッシュ（エネ破壊）
    Dangerous Laser (1095) — ACE SPEC（1枚制限）
      使用時: 相手アクティブを「やけど+こんらん」状態にする
      判断不要（状態異常付与のみ）→ null政策で問題なし

  エネ設計:
    無色×3なので草エネで払える
    1(草) ×19 / 18(Grow Grass) ×4 = 23枚
    ※ Enriching Energy(13) を抜いたので基本草+4 で補填

  政策: null政策（空政策）= 常に最小合法手を返す

デッキ60枚:
  756×4  Mega Kangaskhan ex
  1120×4 Crushing Hammer
  1095×1 Dangerous Laser (ACE SPEC)
  1227×4 Lillie's Determination / 1202×4 Drayton / 1121×4 Ultra Ball
  1225×3 Hilda / 1147×3 Jumbo Ice Cream
  1210×2 Brock's Scouting / 1224×2 Cheren / 1152×2 Poké Pad
  1097×2 Night Stretcher / 1264×2 Battle Cage
  18×4   Grow Grass Energy / 1×19  Basic Grass Energy
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
