"""
field_lucario_ex — ラダー実観測デッキの再現（測定用相手役）

目的：「勝つエージェント」ではなく、ラダーに実在する Mega Lucario ex 系を
ローカルで安定再現し、測定の外的妥当性を高める相手役。

観測元：ラダー 9 戦中 2 戦で対面した Mega Lucario ex 系デッキ
（濱津祐貴376, Aditya Sasidhar442 戦のスクショより）

── デッキ構成（v2 との差分） ───────────────────────────────────────────────
追加（観測フィールド準拠）：
  Riolu 333 (HP70)          ×4  ← Poffin 対応。v2 は 677(HP80)
  Makuhita (673)             ×2  ← 闘サブアタッカーライン種
  Hariyama (674)             ×2  ← ワイルドプレス 210dmg、どすこいキャッチャー特性
  Buddy-Buddy Poffin (1086)  ×2  ← HP70 以下たねをベンチへ（Riolu 333 対応）
  Dusk Ball (1102)           ×3  ← 山札下7枚からポケモン確保
  Gong / ファイトゴング(1142) ×4  ← 闘たね or 基本闘エネをサーチ
  Drayton / タラゴン(1238)   ×2  ← トラッシュから闘ポケモン+闘エネ計4枚回収
  Scramble Switch (1107)     ×1  ← 入れ替え＋エネ付け替え（1枚制限の可能性あり）
  Night Stretcher (1097)     ×1  ← トラッシュ回収（v2 同等）
  Mitsuru (1229)             ×2  ← メガシンカexを全回復＋エネ手札戻し
  Takeshi's Scout (1210)     ×2  ← たね2枚 or 進化1枚をサーチ

除外（v2 からの差分）：
  Ultra Ball (1121)          → Dusk Ball / Gong / Poffin で代替
  Canari (1233)              → 雷専用サーチのため Fighting デッキでは無効
  Levincia (1254)            → フィールド観測で見えなかったため除外
  Energy Retrieval (1118)    → Drayton (1238) で代替
  Max Rod (1110)             → Drayton で代替

── Hariyama 特性メモ ────────────────────────────────────────────────────────
「どすこいキャッチャー」：手札から出して進化させたとき1回使える。
相手のベンチポケモン1匹をバトルポケモンと入れ替えさせる。
→ エンジンが SWITCH / TO_ACTIVE コンテキストで選択を求める可能性あり。
  ターゲット：プライズ数が多い（ex/Mega）or HP が低い相手を優先。

ワイルドプレス：闘闘闘 → 210dmg（自分にも 70 dmg）。
→ HP150 を1発 KO 可能。自傷 70 で残 HP80 → 次ターン倒される可能性あり。
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

try:
    from cg.api import (
        AreaType, Card, CardType, EnergyType, LogType, Observation,
        OptionType, Pokemon, SelectContext, SelectType,
        all_card_data, to_observation_class,
    )
    _API_AVAILABLE = True
except Exception:
    _API_AVAILABLE = False

_SEARCH_AVAILABLE = False
try:
    from cg.api import (
        search_begin as _search_begin, search_step as _search_step,
        search_end as _search_end, search_release as _search_release,
    )
    _SEARCH_AVAILABLE = True
except Exception:
    pass


# ── Card IDs ──────────────────────────────────────────────────────────────────
class C:
    RIOLU           = 333   # HP70 — Poffin でサーチ可能
    MEGA_LUCARIO    = 678   # Mega Lucario ex (1進化)
    MAKUHITA        = 673   # HP80 — サブアタッカーライン種
    HARIYAMA        = 674   # HP150 — ワイルドプレス210dmg/どすこいキャッチャー特性
    FIGHTING_ENERGY = 6
    LILLIE_DET      = 1227  # リーリエの決心: 手札→山札→6枚(or8枚)ドロー
    MITSURU         = 1229  # ミツルの思いやり: Mega ex 全回復+エネ手札戻し
    TAKESHI         = 1210  # タケシのスカウト: たね2枚 or 進化1枚サーチ
    POFFIN          = 1086  # なかよしポフィン: HP70以下たね2枚ベンチへ
    DUSK_BALL       = 1102  # ダークボール: 山札下7枚からポケモン1枚
    GONG            = 1142  # ファイトゴング: 闘たね or 基本闘エネサーチ
    DRAYTON         = 1238  # タラゴン: トラッシュから闘ポケモン+闘エネ計4枚
    SCRAMBLE_SW     = 1107  # スクランブルスイッチ: 入れ替え+エネ付け替え
    NIGHT_STRETCHER = 1097  # 夜のタンカ: トラッシュ回収


LOW_DECK_COUNT = 6
MAX_SEARCH_DEPTH = 20
SEARCH_TOP_K = 6

_DIAG = {"decisions": 0, "errors": {}}


def _diag_error(exc):
    k = type(exc).__name__ + ": " + str(exc)[:120]
    _DIAG["errors"][k] = _DIAG["errors"].get(k, 0) + 1


# ── Deck loading ──────────────────────────────────────────────────────────────
def _resolve_deck_path() -> str:
    cands = []
    if "__file__" in globals():
        cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "deck.csv"))
    cands += ["deck.csv", "/kaggle_simulations/agent/deck.csv"]
    cands += [os.path.join(p, "deck.csv") for p in sys.path if p]
    for path in cands:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("deck.csv not found")


DECK_PATH = _resolve_deck_path()
with open(DECK_PATH, "r", encoding="utf-8") as f:
    my_deck = [int(line) for line in f.read().splitlines() if line.strip()]
if len(my_deck) != 60:
    raise ValueError(f"deck must be 60 cards, got {len(my_deck)}")

if _API_AVAILABLE:
    all_card = all_card_data()
    card_table = {c.cardId: c for c in all_card}
else:
    card_table = {}


# ── Generic helpers ───────────────────────────────────────────────────────────
def _safe_get(seq, index):
    try:
        return seq[index] if seq and 0 <= index < len(seq) else None
    except Exception:
        return None


def _legal_fallback(select):
    try:
        n = len(select.option)
        return list(range(min(max(0, select.minCount), n)))
    except Exception:
        return []


def _legal_fallback_dict(obs_dict):
    try:
        sel = (obs_dict or {}).get("select") or {}
        opts = sel.get("option") or []
        return list(range(min(max(0, sel.get("minCount", 0)), len(opts))))
    except Exception:
        return []


def get_card(obs, area, index, player_index):
    try:
        player = obs.current.players[player_index]
        match area:
            case AreaType.DECK:    return _safe_get(getattr(obs.select, "deck", None), index)
            case AreaType.HAND:    return _safe_get(player.hand, index)
            case AreaType.DISCARD: return _safe_get(player.discard, index)
            case AreaType.ACTIVE:  return _safe_get(player.active, index)
            case AreaType.BENCH:   return _safe_get(player.bench, index)
            case AreaType.PRIZE:   return _safe_get(player.prize, index)
            case AreaType.STADIUM: return _safe_get(obs.current.stadium, index)
            case AreaType.LOOKING: return _safe_get(obs.current.looking, index)
            case _:                return None
    except Exception:
        return None


def prize_count(pokemon) -> int:
    data = card_table.get(pokemon.id)
    if data is None: return 1
    return 3 if data.megaEx else 2 if data.ex else 1


def normalize_selection(ranked, scores, select):
    n = len(select.option)
    minc = max(0, min(select.minCount, n))
    maxc = max(minc, min(select.maxCount, n))
    out, seen = [], set()
    for i in ranked:
        if not (0 <= i < n) or i in seen: continue
        if scores[i] > 0 or len(out) < minc:
            out.append(i); seen.add(i)
        if len(out) >= maxc: break
    for i in range(n):
        if len(out) >= minc: break
        if i not in seen: out.append(i); seen.add(i)
    return out


# ── Search helpers ────────────────────────────────────────────────────────────
def _build_predictions(obs):
    from collections import Counter
    state  = obs.current
    my_idx = state.yourIndex
    op_idx = 1 - my_idx
    me  = state.players[my_idx]
    opp = state.players[op_idx]

    deck_ctr = Counter(my_deck)
    used = Counter()
    for p in me.active + me.bench:
        if p: used[p.id] += 1
    for c in (me.hand or []):  used[c.id] += 1
    for c in me.discard:       used[c.id] += 1
    for c in me.prize:
        if c: used[c.id] += 1

    remaining = []
    for cid, total in deck_ctr.items():
        remaining.extend([cid] * max(0, total - used[cid]))

    PAD = C.FIGHTING_ENERGY
    your_deck  = (remaining + [PAD]*60)[:me.deckCount]
    pool       = remaining[me.deckCount:] + [PAD]*10
    your_prize = []
    for p in me.prize:
        if p is None: your_prize.append(pool.pop(0) if pool else PAD)
        else:         your_prize.append(p.id)

    opp_vis, opp_basic = [], None
    for p in opp.active + opp.bench:
        if p:
            opp_vis.append(p.id)
            if opp_basic is None:
                d = card_table.get(p.id)
                if d and d.basic: opp_basic = p.id
    for c in opp.discard: opp_vis.append(c.id)
    for c in opp.prize:
        if c: opp_vis.append(c.id)
    if opp_basic is None and opp_vis: opp_basic = opp_vis[0]

    filler = ([opp_basic] if opp_basic else []) + opp_vis*2 + [C.FIGHTING_ENERGY]*60
    opp_deck  = (filler+[C.FIGHTING_ENERGY]*60)[:opp.deckCount]
    opp_prize = (filler+[C.FIGHTING_ENERGY]*10)[:len(opp.prize)]
    opp_hand  = (filler+[C.FIGHTING_ENERGY]*10)[:opp.handCount]
    opp_active = []
    if opp.active and opp.active[0] is None:
        opp_active = [opp_basic] if opp_basic else []

    return your_deck, your_prize, opp_deck, opp_prize, opp_hand, opp_active


def _evaluate_obs(obs):
    """1-ply search 評価関数。Hariyama の攻撃準備状況を加味。"""
    if obs is None or obs.current is None: return 0
    state  = obs.current
    my_idx = state.yourIndex
    op_idx = 1 - my_idx
    me  = state.players[my_idx]
    opp = state.players[op_idx]
    if state.result == my_idx: return 200_000
    if state.result == op_idx: return -200_000

    score = (len(opp.prize) - len(me.prize)) * 8_000

    for p in me.active + me.bench:
        if p is None: continue
        ec = len(p.energies)
        if p.id == C.MEGA_LUCARIO:
            score += 4_000 + ec * 500
            if ec >= 2: score += 1_000
        elif p.id == C.RIOLU:
            score += 500
        elif p.id == C.HARIYAMA:
            score += 2_000 + ec * 600
            if ec >= 3: score += 1_500  # ワイルドプレス可能
        elif p.id == C.MAKUHITA:
            score += 300 + ec * 100

    opp_a = opp.active[0] if opp.active else None
    if opp_a:
        score += (opp_a.maxHp - opp_a.hp) * 3
        if opp_a.hp <= 0:
            score += prize_count(opp_a) * 10_000
    return score


def _greedy_resolve(state, my_orig_idx, depth=0):
    if depth >= MAX_SEARCH_DEPTH: return state
    obs = state.observation
    if obs is None or obs.select is None or obs.current is None: return state
    if obs.current.result != -1: return state
    if obs.current.yourIndex != my_orig_idx: return state
    if obs.select.maxCount == 0 or not obs.select.option: return state
    try:
        policy = FieldLucarioPolicy(obs)
        choices = policy.choose()
        if not choices: return state
        nxt = _search_step(state.searchId, choices)
        return _greedy_resolve(nxt, my_orig_idx, depth+1)
    except Exception:
        return state


def _run_lookahead(obs):
    if not _SEARCH_AVAILABLE or obs.search_begin_input is None: return None
    if obs.select is None or not obs.select.option: return None
    try:
        if obs.select.type != SelectType.MAIN: return None
    except Exception:
        return None
    my_idx = obs.current.yourIndex
    try:
        preds = _build_predictions(obs)
        root = _search_begin(obs,
                             your_deck=preds[0], your_prize=preds[1],
                             opponent_deck=preds[2], opponent_prize=preds[3],
                             opponent_hand=preds[4], opponent_active=preds[5])
    except Exception:
        return None

    p0 = FieldLucarioPolicy(obs)
    h = [p0._score_option(o) for o in obs.select.option]
    n = len(obs.select.option)
    top_k = sorted(range(n), key=lambda i: h[i], reverse=True)[:SEARCH_TOP_K]

    best_idx, best_score = top_k[0] if top_k else 0, -float("inf")
    for i in top_k:
        try:
            nxt = _search_step(root.searchId, [i])
            fin = _greedy_resolve(nxt, my_idx)
            sc  = _evaluate_obs(fin.observation)
            _search_release(fin.searchId)
            if sc > best_score:
                best_score = sc; best_idx = i
        except Exception:
            continue
    try:
        _search_release(root.searchId)
        _search_end()
    except Exception:
        pass
    return best_idx


# ── Field Lucario ex policy ───────────────────────────────────────────────────
class FieldLucarioPolicy:
    def __init__(self, obs):
        self.obs      = obs
        self.state    = obs.current
        self.select   = obs.select
        self.context  = self.select.context
        self.my_index = self.state.yourIndex
        self.op_index = 1 - self.my_index
        self.me       = self.state.players[self.my_index]
        self.opponent = self.state.players[self.op_index]

        self.field_counts = defaultdict(int)
        self.hand_counts  = defaultdict(int)
        self.disc_counts  = defaultdict(int)
        self._count_cards()

    def _count_cards(self):
        for p in self.me.active + self.me.bench:
            if p: self.field_counts[p.id] += 1
        for c in (self.me.hand or []):
            self.hand_counts[c.id] += 1
        for c in self.me.discard:
            self.disc_counts[c.id] += 1

    def _my_board(self):   return self.me.active + self.me.bench
    def _opp_board(self):  return self.opponent.active + self.opponent.bench
    def _low_deck(self):   return self.me.deckCount <= LOW_DECK_COUNT
    def _hand_size(self):  return sum(self.hand_counts.values())
    def _open_bench(self):
        return sum(1 for p in self.me.bench if p) < getattr(self.me, "benchMax", 5)

    def _energy_count(self, pokemon):
        try: return len(pokemon.energies)
        except: return 0

    def _lucario_count(self):
        return sum(1 for p in self._my_board() if p and p.id == C.MEGA_LUCARIO)

    def _hariyama_count(self):
        return sum(1 for p in self._my_board() if p and p.id == C.HARIYAMA)

    def _active_hp_ratio(self):
        """アクティブの HP 残率（低いほどリトリート・Mitsuru が有効）。"""
        try:
            a = self.me.active[0]
            if a is None or a.maxHp == 0: return 1.0
            return a.hp / a.maxHp
        except Exception:
            return 1.0

    # ── Main scorer ────────────────────────────────────────────────────────────
    def rank(self):
        if not self.select.option or self.select.maxCount == 0:
            return [], []
        scores = [self._score_option(o) for o in self.select.option]
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return ranked, scores

    def choose(self):
        ranked, scores = self.rank()
        return normalize_selection(ranked, scores, self.select)

    def _score_option(self, option) -> float:
        t = option.type
        if t == OptionType.NUMBER:  return option.number if option.number is not None else 0
        if t == OptionType.YES:     return 100 if self.context == SelectContext.IS_FIRST else 1
        if t == OptionType.NO:      return 0
        if t == OptionType.CARD:    return self._score_card(option)
        if t == OptionType.PLAY:    return self._score_play(option)
        if t in (OptionType.ENERGY, OptionType.ATTACH): return self._score_attach(option)
        if t == OptionType.EVOLVE:  return self._score_evolve(option)
        if t == OptionType.RETREAT: return self._score_retreat()
        if t == OptionType.ATTACK:  return self._score_attack(option)
        if t == OptionType.END:     return 0
        return 0

    # ── Play ──────────────────────────────────────────────────────────────────
    def _score_play(self, option) -> float:
        card = get_card(self.obs, AreaType.HAND, option.index, self.my_index)
        if card is None: return 0
        data = card_table.get(card.id)
        if data is None: return 0
        if data.cardType == CardType.POKEMON:
            return self._score_play_pokemon(card)
        return self._score_play_trainer(card)

    def _score_play_pokemon(self, card) -> float:
        n = self.field_counts[card.id]

        if card.id == C.RIOLU:
            return 20000 - 300 * n if self._open_bench() else -1
        if card.id == C.MAKUHITA:
            # Hariyama が場にいない間はライン確保を優先
            return (16000 - 300 * n if self._hariyama_count() == 0
                    else 9000 - 200 * n) if self._open_bench() else -1
        return 15000 - 200 * n

    def _score_play_trainer(self, card) -> float:
        cid = card.id

        # ── サポート ─────────────────────────────────────────────────────────
        if cid == C.LILLIE_DET:
            if self.state.supporterPlayed or self._low_deck(): return -1
            return 12000 if self._hand_size() <= 4 else 3000

        if cid == C.MITSURU:
            if self.state.supporterPlayed: return -1
            active = self.me.active[0] if self.me.active else None
            # Mega ex がアクティブで HP が半分以下なら回復価値大
            if active and active.id == C.MEGA_LUCARIO and self._active_hp_ratio() <= 0.5:
                return 11000
            # HP残り多いうちは使わない（エネ全戻しのデメリットがある）
            return 1500

        if cid == C.TAKESHI:
            if self.state.supporterPlayed: return -1
            need_riolu = self.field_counts[C.RIOLU] + self._lucario_count() < 2
            need_makuhita = self.field_counts[C.MAKUHITA] + self._hariyama_count() < 1
            return 10000 if (need_riolu or need_makuhita) else 3000

        # ── グッズ ─────────────────────────────────────────────────────────
        if cid == C.POFFIN:
            # Riolu 333 (HP70) をベンチへ — open bench 必須
            need = self.field_counts[C.RIOLU] < 2
            return 13000 if (need and self._open_bench()) else 500

        if cid == C.DUSK_BALL:
            # 山札下7枚からポケモン確保（Makuhita/Hariyama/Riolu/Lucario 狙い）
            need = (self._lucario_count() < 2 or
                    self.field_counts[C.RIOLU] + self._lucario_count() < 2 or
                    self._hariyama_count() < 1)
            return 10000 if need else 4000

        if cid == C.GONG:
            # 闘たね（Riolu/Makuhita）or 基本闘エネをサーチ
            need_mon = self.field_counts[C.RIOLU] < 2 or self.field_counts[C.MAKUHITA] < 1
            if need_mon:
                return 10500
            # エネが手札に少ない場合は闘エネをサーチ
            if self.hand_counts.get(C.FIGHTING_ENERGY, 0) < 2:
                return 8000
            return 3000

        if cid == C.DRAYTON:
            # トラッシュから闘ポケモン+闘エネ回収
            has_mon  = (self.disc_counts.get(C.MEGA_LUCARIO, 0) > 0 or
                        self.disc_counts.get(C.HARIYAMA, 0) > 0 or
                        self.disc_counts.get(C.RIOLU, 0) > 0)
            has_ene  = self.disc_counts.get(C.FIGHTING_ENERGY, 0) >= 2
            if has_mon and has_ene: return 9000
            if has_mon or has_ene: return 6000
            return 500

        if cid == C.SCRAMBLE_SW:
            # 入れ替え + エネ付け替え：Hariyama をアクティブへ置き換えるとき最適
            active = self.me.active[0] if self.me.active else None
            if active and active.id not in (C.MEGA_LUCARIO, C.HARIYAMA):
                # Riolu/Makuhita がアクティブにいる = 逃がしたい
                return 9500
            # Hariyama がエネ満載でベンチにいて Lucario がアクティブなら交代も有効
            for p in self.me.bench:
                if p and p.id == C.HARIYAMA and self._energy_count(p) >= 3:
                    return 8500
            return 2000

        if cid == C.NIGHT_STRETCHER:
            has_lucario  = self.disc_counts.get(C.MEGA_LUCARIO, 0) > 0
            has_riolu    = self.disc_counts.get(C.RIOLU, 0) > 0
            has_hariyama = self.disc_counts.get(C.HARIYAMA, 0) > 0
            if has_lucario or has_hariyama: return 8500
            if has_riolu:                   return 6000
            return 300

        return 7000

    # ── Evolve ────────────────────────────────────────────────────────────────
    def _score_evolve(self, option) -> float:
        target = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon): return 0
        card = get_card(self.obs, AreaType.HAND, option.index, self.my_index)
        if card is None: return 0

        if card.id == C.MEGA_LUCARIO:
            return 25000 + self._energy_count(target) * 50
        if card.id == C.HARIYAMA:
            # どすこいキャッチャー特性 = 進化するだけで相手を引き出せる
            return 22000 + self._energy_count(target) * 50
        return 18000

    # ── Attach ────────────────────────────────────────────────────────────────
    def _score_attach(self, option) -> float:
        pokemon = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(pokemon, Pokemon): return 0
        return self._energy_score(pokemon, option.inPlayArea == AreaType.ACTIVE)

    def _energy_score(self, pokemon, is_active) -> float:
        ec = self._energy_count(pokemon)

        if pokemon.id == C.MEGA_LUCARIO:
            base = 9000 if ec < 2 else 500
        elif pokemon.id == C.HARIYAMA:
            # ワイルドプレスは闘闘闘 = 3エネ。3エネ到達を優先。
            base = 10000 if ec < 3 else 200
        elif pokemon.id == C.MAKUHITA:
            # 進化前は最低限のエネだけ（進化後 Hariyama に付け替わる）
            base = 500 if ec == 0 else 50
        elif pokemon.id == C.RIOLU:
            base = 100
        else:
            base = 50
        return base + (200 if is_active else 0)

    # ── Retreat ───────────────────────────────────────────────────────────────
    def _score_retreat(self) -> float:
        active = self.me.active[0] if self.me.active else None
        if active is None: return -1

        if active.id == C.MEGA_LUCARIO:
            if self._energy_count(active) >= 1:
                return -1  # 攻撃継続
            # エネなし Lucario はベンチに下げて Hariyama/Riolu を前へ
            return 3000

        if active.id == C.HARIYAMA:
            return -1  # Hariyama はアクティブで攻撃し続ける

        # Riolu / Makuhita がアクティブ → 下げる
        if active.id in (C.RIOLU, C.MAKUHITA):
            for p in self.me.bench:
                if p and p.id == C.MEGA_LUCARIO and self._energy_count(p) >= 1:
                    return 8000
                if p and p.id == C.HARIYAMA:
                    return 7000
            return 3000

        return -1

    # ── Attack ────────────────────────────────────────────────────────────────
    def _score_attack(self, option) -> float:
        active = self.me.active[0] if self.me.active else None
        opp_a  = self.opponent.active[0] if self.opponent.active else None
        if active is None: return 500

        # ── Hariyama の攻撃（ワイルドプレス 210dmg、自 70dmg） ────────────
        if active.id == C.HARIYAMA:
            dmg = 210
            score = 4500 + min(dmg, 340)
            if opp_a and opp_a.hp <= dmg:
                score += 3000 + prize_count(opp_a) * 500
            # 自傷 70 で瀕死になる場合は警戒（残 HP80 → 相手の攻撃で落とされやすい）
            if active.hp - 70 <= 0:
                score -= 2000  # 自爆は避けたい
            return score

        # ── Mega Lucario ex の攻撃 ────────────────────────────────────────
        if active.id != C.MEGA_LUCARIO:
            return 500

        data = card_table.get(C.MEGA_LUCARIO)
        aura_id = brave_id = None
        if data and hasattr(data, "attacks") and len(data.attacks) >= 2:
            aura_id, brave_id = data.attacks[0], data.attacks[1]

        if option.attackId == brave_id:
            dmg = 270
            score = 5000 + min(dmg, 340)
            if opp_a and opp_a.hp <= dmg:
                score += 3000 + prize_count(opp_a) * 500
        elif option.attackId == aura_id:
            dmg = 130
            bench_lucarios = sum(1 for p in self.me.bench
                                 if p and p.id == C.MEGA_LUCARIO
                                 and self._energy_count(p) < 2)
            ramp_value = bench_lucarios * 1200
            score = 3000 + min(dmg, 340) + ramp_value
            if opp_a and opp_a.hp <= dmg:
                score += 3000 + prize_count(opp_a) * 500
        else:
            score = 500

        return score

    # ── Card choice ───────────────────────────────────────────────────────────
    def _score_card(self, option) -> float:
        card = get_card(self.obs, option.area, option.index, option.playerIndex)
        if card is None: return 0
        ctx = self.context

        if ctx in (SelectContext.SWITCH, SelectContext.TO_ACTIVE):
            return self._score_active_switch(option, card)
        if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            # セットアップ時は Riolu を優先
            if isinstance(card, Pokemon) and card.id == C.RIOLU: return 6
            if isinstance(card, Pokemon) and card.id == C.MAKUHITA: return 3
            return 1
        if ctx in (SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD):
            return self._score_to_bench(card)
        if ctx == SelectContext.TO_HAND:
            return self._score_to_hand(card)
        if ctx == SelectContext.ATTACH_TO:
            if isinstance(card, Pokemon):
                return self._energy_score(card, option.inPlayArea == AreaType.ACTIVE)
            return 0
        if ctx in (SelectContext.DISCARD, SelectContext.DISCARD_CARD_OR_ATTACHED_CARD,
                   SelectContext.DISCARD_ENERGY, SelectContext.DISCARD_ENERGY_CARD):
            return self._score_discard(card)
        if ctx in (SelectContext.DAMAGE_COUNTER, SelectContext.DAMAGE_COUNTER_ANY):
            if isinstance(card, Pokemon) and option.playerIndex == self.op_index:
                return 10000 + prize_count(card)*1000 - getattr(card, "hp", 0)
            return 0
        if ctx in (SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM,
                   SelectContext.TO_PRIZE, SelectContext.TO_DECK_ENERGY):
            return self._score_putback(card)
        return 0

    def _score_active_switch(self, option, card) -> float:
        if not isinstance(card, Pokemon): return 0
        if option.playerIndex == self.op_index:
            # Hariyama どすこいキャッチャー or Scramble Switch: 高プライズのものを引き出す
            return 5000 + prize_count(card) * 1000
        # 自分側の交代先: Hariyama (エネあり) > Lucario (エネあり) > その他
        ec = self._energy_count(card)
        if card.id == C.HARIYAMA: return 15000 + ec * 200
        if card.id == C.MEGA_LUCARIO: return 8000 + ec * 200
        return ec * 10 + 1

    def _score_to_bench(self, card) -> float:
        if not isinstance(card, Pokemon): return 0
        n = self.field_counts[card.id]
        if card.id == C.RIOLU:        return 200 - 40 * n
        if card.id == C.MEGA_LUCARIO: return 150 - 30 * n
        if card.id == C.MAKUHITA:     return 120 - 30 * n
        if card.id == C.HARIYAMA:     return 100 - 20 * n
        return 50

    def _score_to_hand(self, card) -> float:
        if card is None: return 0
        cid = card.id
        s = 150 - self.hand_counts[cid] * 60

        if cid == C.MEGA_LUCARIO:
            if self.field_counts[C.RIOLU] >= 1 and self._lucario_count() < 1:
                s += 400
            elif self.field_counts[C.RIOLU] >= 1:
                s += 200
            else:
                s += 50
        elif cid == C.RIOLU:
            total = self.field_counts[C.RIOLU] + self._lucario_count()
            s += 300 if total < 1 else (150 if total < 2 else -20)
        elif cid == C.HARIYAMA:
            s += 350 if self._hariyama_count() == 0 else 100
        elif cid == C.MAKUHITA:
            s += 200 if self.field_counts[C.MAKUHITA] + self._hariyama_count() < 1 else 50
        elif cid == C.FIGHTING_ENERGY:
            s += 40
        elif cid == C.NIGHT_STRETCHER:
            s += 150 if self.disc_counts.get(C.MEGA_LUCARIO, 0) > 0 else 40
        return s

    def _score_discard(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid == C.FIGHTING_ENERGY: return 80
        if self.hand_counts[cid] >= 2: return 60
        if cid in (C.RIOLU, C.MEGA_LUCARIO):
            return 5 if self.field_counts[cid] > 0 else -80
        if cid in (C.MAKUHITA, C.HARIYAMA):
            return 5 if self.field_counts[cid] > 0 else -60
        if cid in (C.LILLIE_DET, C.MITSURU, C.TAKESHI) and self.state.supporterPlayed:
            return 30
        return 5

    def _score_putback(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid in (C.RIOLU, C.MEGA_LUCARIO, C.MAKUHITA, C.HARIYAMA): return -40
        if self.hand_counts[cid] >= 2:   return 50
        if cid == C.FIGHTING_ENERGY:     return 20
        return 10


# ── Agent entry point ─────────────────────────────────────────────────────────
def agent(obs_dict: dict) -> list[int]:
    try:
        is_deck_select = isinstance(obs_dict, dict) and obs_dict.get("select") is None
    except Exception:
        is_deck_select = False
    if is_deck_select:
        return my_deck

    _DIAG["decisions"] += 1

    if not _API_AVAILABLE:
        return _legal_fallback_dict(obs_dict)

    try:
        obs = to_observation_class(obs_dict)
        if obs.select is None:
            return my_deck

        try:
            policy = FieldLucarioPolicy(obs)

            search_idx = None
            try:
                search_idx = _run_lookahead(obs)
            except Exception as exc:
                _diag_error(exc)

            if search_idx is not None:
                n = len(obs.select.option)
                minc = max(0, min(obs.select.minCount, n))
                if 0 <= search_idx < n:
                    result = [search_idx]
                    if minc > 1:
                        ranked, scores = policy.rank()
                        for ri in ranked:
                            if ri != search_idx: result.append(ri)
                            if len(result) >= minc: break
                    return result

            ranked, scores = policy.rank()
            return normalize_selection(ranked, scores, obs.select)

        except Exception as exc:
            _diag_error(exc)
            return _legal_fallback(obs.select)
    except Exception as exc:
        _diag_error(exc)
        return _legal_fallback_dict(obs_dict if isinstance(obs_dict, dict) else {})
