"""
cabt_harness.py -- 本物の cg エンジンに直結したローカル評価ハーネス（ポケカABC）

できること:
  - 自分のエージェント(main.py)を呼び出し可能物として読み込む
  - 2デッキで1試合を完走させ勝敗(result)を取る
  - 固定相手にNマッチ回し、勝率をWilson信頼区間つきで出す
  - 先攻/後攻はデッキの渡し順を毎試合入れ替えて自動バランス
  - 2バージョンの比較は2標本の差の信頼区間で（※engineにseed注入が無く
    共通乱数ペア比較は不可。Nを増やして対応する）

使い方(例):
  CG_DIR=./cg python3 cabt_harness.py              # 同梱デモ(mirror & vs random)
  # コードから:
  #   my_agent, my_deck = load_agent("../lucario_v4", "v4")
  #   res = run_matchup("v4", my_agent, my_deck, "random", random_agent, my_deck, 200)
"""

from __future__ import annotations

import importlib.util
import math
import os
import random
import sys

# cg パッケージを import 可能に（CG_DIR かこのファイルの隣を探す）
_HERE = os.path.dirname(os.path.abspath(__file__))
_CG_PARENT = os.path.dirname(os.environ.get("CG_DIR", os.path.join(_HERE, "cg")))
for p in (_CG_PARENT, _HERE):
    if p and p not in sys.path:
        sys.path.insert(0, p)

from cg.game import battle_start, battle_select, battle_finish  # noqa: E402


# ── 統計 ──────────────────────────────────────────────────────────────
def wilson_ci(wins: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d
    return (max(0.0, c - h), min(1.0, c + h))


def two_prop_diff_ci(w1: int, n1: int, w2: int, n2: int, z: float = 1.96):
    """独立2標本の勝率差(p1 - p2)の近似95%CI。0をまたがなければ有意差。"""
    if n1 == 0 or n2 == 0:
        return (0.0, -1.0, 1.0)
    p1, p2 = w1 / n1, w2 / n2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    d = p1 - p2
    return (d, d - z * se, d + z * se)


# ── エージェント読み込み / 相手 ────────────────────────────────────────
def load_agent(folder: str, modname: str):
    """folder/main.py を独立モジュールとして読み込み (agent, my_deck) を返す。"""
    path = os.path.join(folder, "main.py")
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod.agent, list(mod.my_deck)


def _legal(obs) -> list[int]:
    sel = (obs or {}).get("select") or {}
    opts = sel.get("option") or []
    k = min(max(0, sel.get("minCount", 0)), len(opts))
    return list(range(k))


def random_agent(obs_dict: dict) -> list[int]:
    """ランダム合法エージェント(基準線)。min〜maxの枚数をランダムに選ぶ。"""
    sel = obs_dict.get("select")
    if sel is None:
        return []  # デッキ選択はドライバ側で処理
    opts = sel.get("option") or []
    n = len(opts)
    if n == 0:
        return []
    lo = max(0, min(sel.get("minCount", 0), n))
    hi = max(lo, min(sel.get("maxCount", lo), n))
    k = random.randint(lo, hi) if hi >= lo else lo
    return sorted(random.sample(range(n), k)) if k > 0 else []


# ── 対戦ドライバ ───────────────────────────────────────────────────────
def _safe_select(move, obs):
    """agent返り値を適用。不正手ならlegal fallbackで落とさない。"""
    try:
        return battle_select(list(move))
    except Exception:
        return battle_select(_legal(obs))


def play_one(agent0, deck0, agent1, deck1) -> int:
    """1試合。deck0が先攻。戻り値 result: 0=先攻勝ち,1=後攻勝ち,2=引分。"""
    agents = (agent0, agent1)
    obs, start = battle_start(deck0, deck1)
    if obs is None:
        raise RuntimeError(f"battle_start failed: errorPlayer={start.errorPlayer}")
    guard = 0
    try:
        while True:
            cur = obs.get("current") or {}
            result = cur.get("result", -1)
            if result != -1:
                return result
            who = cur.get("yourIndex", 0)
            sel = obs.get("select")
            if sel is None:
                move = deck0 if who == 0 else deck1
            else:
                try:
                    move = agents[who](obs)
                except Exception:
                    move = _legal(obs)
            obs = _safe_select(move, obs)
            guard += 1
            if guard > 5000:
                return 2  # 異常長は引分扱い
    finally:
        battle_finish()


def run_matchup(nameA, agentA, deckA, nameB, agentB, deckB, n_games: int,
                verbose: bool = True) -> dict:
    """AとBをn_games戦。先攻/後攻を交互に。A視点のW/L/Dを返す。"""
    aw = al = draw = 0
    for i in range(n_games):
        a_first = (i % 2 == 0)
        if a_first:
            res = play_one(agentA, deckA, agentB, deckB)
            a_won = (res == 0)
        else:
            res = play_one(agentB, deckB, agentA, deckA)
            a_won = (res == 1)
        if res == 2:
            draw += 1
        elif a_won:
            aw += 1
        else:
            al += 1
        if verbose and (i + 1) % 10 == 0:
            print(f"    ... {i+1}/{n_games}  {nameA} {aw}-{al}-{draw}", flush=True)
    decided = aw + al
    rate = aw / decided if decided else 0.0
    lo, hi = wilson_ci(aw, decided)
    return {"A": nameA, "B": nameB, "n": n_games,
            "A_win": aw, "A_loss": al, "draw": draw,
            "A_rate": rate, "A_ci": (lo, hi)}


def _fmt(r: dict) -> str:
    lo, hi = r["A_ci"]
    return (f"{r['A']} vs {r['B']}: {r['A_win']}-{r['A_loss']}-{r['draw']} "
            f"(引分除く勝率 {r['A_rate']:.1%}, 95%CI[{lo:.1%},{hi:.1%}], n={r['n']})")


if __name__ == "__main__":
    import time
    V4_DIR = os.path.join(_HERE, "..", "lucario_v4")
    v4_agent, v4_deck = load_agent(V4_DIR, "lucario_v4")
    print(f"loaded v4 agent, deck={len(v4_deck)} cards")

    # 速度プローブ: 1試合の所要
    t = time.time()
    r0 = play_one(v4_agent, v4_deck, random_agent, v4_deck)
    print(f"probe game (v4 vs random) result={r0}  {time.time()-t:.2f}s/game")

    N = int(os.environ.get("N", "20"))

    print(f"\n=== v4 vs random (baseline, n={N}) ===")
    r_rand = run_matchup("v4", v4_agent, v4_deck, "random", random_agent, v4_deck, N)
    print("  " + _fmt(r_rand))

    print(f"\n=== v4 vs v4 (mirror sanity, n={N}) ===")
    r_mirror = run_matchup("v4", v4_agent, v4_deck, "v4b", v4_agent, v4_deck, N)
    print("  " + _fmt(r_mirror))
    print("  (ミラーは≈50%が理想。先攻後攻バランスの健全性チェック)")
