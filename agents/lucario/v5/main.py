"""
lucario_agent.py - Mega Lucario ex メタデッキ
戦略:
  - Aura Jab (1F, 130) → 捨て場から基本Fエネ3枚をベンチに配布
  - Mega Brave (2F, 270) → ほぼ全ポケモンOHKO（次ターン使用不可）
  - 交互運用: Aura Jab→Mega Brave→Aura Jab... でエネ加速しながら連続KO
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

try:
    from cg.api import (
        AreaType,
        Card,
        CardType,
        EnergyType,
        LogType,
        Observation,
        OptionType,
        Pokemon,
        SelectContext,
        SelectType,
        all_card_data,
        to_observation_class,
    )
    _API_AVAILABLE = True
except Exception:
    _API_AVAILABLE = False

_SEARCH_AVAILABLE = False
try:
    from cg.api import (
        search_begin as _search_begin,
        search_step as _search_step,
        search_end as _search_end,
        search_release as _search_release,
    )
    _SEARCH_AVAILABLE = True
except Exception:
    pass


# ── Card IDs ──────────────────────────────────────────────────────────────────
class C:
    RIOLU          = 677
    MEGA_LUCARIO   = 678
    FIGHTING_ENERGY= 6
    ULTRA_BALL     = 1121
    LILLIE_DET     = 1227
    CANARI         = 1233
    NIGHT_STRETCHER= 1097
    POKE_PAD       = 1152
    LEVINCIA       = 1254
    MAX_ROD        = 1110
    ENERGY_RET     = 1118


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
        cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lucario_deck.csv"))
    cands += ["lucario_deck.csv", "deck.csv",
              "/kaggle_simulations/agent/lucario_deck.csv",
              "/kaggle_simulations/agent/deck.csv"]
    cands += [os.path.join(p, "lucario_deck.csv") for p in sys.path if p]
    cands += [os.path.join(p, "deck.csv") for p in sys.path if p]
    for path in cands:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("lucario_deck.csv / deck.csv not found")


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
            case AreaType.DECK:   return _safe_get(getattr(obs.select, "deck", None), index)
            case AreaType.HAND:   return _safe_get(player.hand, index)
            case AreaType.DISCARD:return _safe_get(player.discard, index)
            case AreaType.ACTIVE: return _safe_get(player.active, index)
            case AreaType.BENCH:  return _safe_get(player.bench, index)
            case AreaType.PRIZE:  return _safe_get(player.prize, index)
            case AreaType.STADIUM:return _safe_get(obs.current.stadium, index)
            case AreaType.LOOKING:return _safe_get(obs.current.looking, index)
            case _:               return None
    except Exception:
        return None


def prize_count(pokemon) -> int:
    data = card_table.get(pokemon.id)
    if data is None: return 1
    return 3 if data.megaEx else 2 if data.ex else 1


def _is_ex(pokemon) -> bool:
    data = card_table.get(pokemon.id)
    return data is not None and (data.ex or data.megaEx)


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

    # Mirror match detection: if opponent has Lucario or Riolu visible → predict our deck
    opp_lucario_ids = {C.MEGA_LUCARIO, C.RIOLU}
    opp_is_lucario  = any(vid in opp_lucario_ids for vid in opp_vis)

    if opp_is_lucario:
        # Predict mirror deck from visible cards
        from collections import Counter as _Counter
        mirror_deck = my_deck[:]  # same 60-card deck
        opp_vis_ctr = _Counter(opp_vis)
        mirror_ctr  = _Counter(mirror_deck)
        # Remove already-visible cards from prediction pool
        for cid, cnt in opp_vis_ctr.items():
            mirror_ctr[cid] = max(0, mirror_ctr[cid] - cnt)
        mirror_pool = []
        for cid, cnt in mirror_ctr.items():
            mirror_pool.extend([cid] * cnt)
        filler = mirror_pool + [C.FIGHTING_ENERGY] * 10
    else:
        filler = ([opp_basic] if opp_basic else []) + opp_vis*2 + [C.FIGHTING_ENERGY]*60

    opp_deck   = (filler+[C.FIGHTING_ENERGY]*60)[:opp.deckCount]
    opp_prize  = (filler+[C.FIGHTING_ENERGY]*10)[:len(opp.prize)]
    opp_hand   = (filler+[C.FIGHTING_ENERGY]*10)[:opp.handCount]
    opp_active = []
    if opp.active and opp.active[0] is None:
        opp_active = [opp_basic] if opp_basic else []

    return your_deck, your_prize, opp_deck, opp_prize, opp_hand, opp_active


def _evaluate_obs(obs):
    if obs is None or obs.current is None: return 0
    state  = obs.current
    my_idx = state.yourIndex
    op_idx = 1 - my_idx
    me  = state.players[my_idx]
    opp = state.players[op_idx]
    if state.result == my_idx: return 200_000
    if state.result == op_idx: return -200_000

    score = (len(opp.prize) - len(me.prize)) * 8_000

    # 後攻・ターン認識（v5: lookahead側にも後攻文脈を渡す）
    going_second = getattr(state, 'firstPlayer', -1) != my_idx
    turn         = getattr(state, 'turn', 1)
    early_second = going_second and turn <= 3

    # 自分のボード評価 ── 最活性レバー(61%発火)
    for p in me.active + me.bench:
        if p is None: continue
        ec = len(p.energies)
        is_active_slot = (p in me.active)
        if p.id == C.MEGA_LUCARIO:
            # 0エネ→4000, 1エネ→4800, 2エネ→7200(Mega Brave圏)
            energy_val = ec * 800 + (1_600 if ec >= 2 else 0)
            # 後攻early: activeのLucarioにエネルギーがある = 攻撃できる状態を高評価
            if early_second and is_active_slot and ec >= 1:
                energy_val += 1_200  # 後攻でactiveが攻撃圏 → Searchがこの状態を好む
            score += 4_000 + energy_val
        elif p.id == C.RIOLU:
            score += 500

    # 相手activeへのダメージ蓄積
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
        policy = LucarioPolicy(obs)
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

    p0 = LucarioPolicy(obs)
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


# ── Lucario policy ─────────────────────────────────────────────────────────────
class LucarioPolicy:
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

        # ターン・先後攻認識（v5: 後攻改善のコア）
        self.turn         = getattr(self.state, 'turn', 1)
        self.is_first     = getattr(self.state, 'firstPlayer', -1) == self.my_index
        self.going_second = not self.is_first
        self.early_game   = self.turn <= 3

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

    def _lucario_with_energy(self):
        return sum(1 for p in self._my_board()
                   if p and p.id == C.MEGA_LUCARIO and self._energy_count(p) >= 1)

    # ── attack ID helpers ──────────────────────────────────────────────────────
    def _attack_ids(self):
        """Returns (aura_jab_id, mega_brave_id) or (None, None)."""
        data = card_table.get(C.MEGA_LUCARIO)
        if data is None or not hasattr(data, "attacks") or len(data.attacks) < 2:
            return None, None
        return data.attacks[0], data.attacks[1]  # 0=Aura Jab, 1=Mega Brave

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
        return 15000 - 200 * n

    def _score_play_trainer(self, card) -> float:
        cid = card.id

        if cid == C.LILLIE_DET:
            if self.state.supporterPlayed or self._low_deck(): return -1
            # 後攻1-2ターン: 最優先（手札8枚 = 初動最大化、攻撃できるターンに最大展開）
            if self.going_second and self.turn <= 2:
                return 14000
            return 12000 if self._hand_size() <= 4 else 3000

        if cid == C.CANARI:
            if self.state.supporterPlayed: return -1
            total_on_field = sum(1 for p in self._my_board() if p)
            if total_on_field <= 1:
                return 13000  # 緊急: 場にPokémonがほぼいない → サーチ最優先
            # 後攻early: Lucarioを早く揃える
            if self.going_second and self.early_game and self._lucario_count() < 2:
                return 12000
            need = self._lucario_count() < 2
            return 11000 if need else (9500 if self._hand_size() <= 3 else 1500)

        if cid == C.ULTRA_BALL:
            need = self._lucario_count() < 2 or self.field_counts[C.RIOLU] < 2
            # 後攻early: 手札2枚でも展開優先
            min_hand = 2 if (self.going_second and self.early_game) else 3
            return 10000 if need and self._hand_size() >= min_hand else 500

        if cid == C.NIGHT_STRETCHER:
            has_lucario = self.disc_counts.get(C.MEGA_LUCARIO, 0) > 0
            has_riolu   = self.disc_counts.get(C.RIOLU, 0) > 0
            return 9000 if has_lucario else (7000 if has_riolu else 300)

        if cid == C.POKE_PAD:
            return 8000 if self._lucario_count() < 2 else 400

        if cid == C.ENERGY_RET:
            fe_disc = self.disc_counts.get(C.FIGHTING_ENERGY, 0)
            return 6000 if fe_disc >= 3 else 1000

        if cid == C.MAX_ROD:
            return 5000 if self.me.deckCount <= 10 else 400

        if cid == C.LEVINCIA:
            if self.state.stadiumPlayed: return -1
            return 3000

        return 7000

    # ── Evolve ────────────────────────────────────────────────────────────────
    def _score_evolve(self, option) -> float:
        target = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon): return 0
        card = get_card(self.obs, AreaType.HAND, option.index, self.my_index)
        if card and card.id == C.MEGA_LUCARIO:
            # Evolve immediately, bonus for energy on target
            return 25000 + self._energy_count(target) * 50
        return 18000

    # ── Attach ────────────────────────────────────────────────────────────────
    def _score_attach(self, option) -> float:
        pokemon = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(pokemon, Pokemon): return 0
        return self._energy_score(pokemon, option.inPlayArea == AreaType.ACTIVE)

    def _energy_score(self, pokemon, is_active) -> float:
        ec = self._energy_count(pokemon)
        if pokemon.id == C.MEGA_LUCARIO:
            if ec < 2:
                base = 9000 - ec * 400  # 0エネ→9000, 1エネ→8600
            else:
                base = 200
        elif pokemon.id == C.RIOLU:
            base = -1  # Rioluに付けない（進化すると消える）
        else:
            base = 50
        # 後攻early: activeへの付けを強く優先（攻撃機会を逃さない）
        active_bonus = 300 if is_active else 0
        if is_active and self.going_second and self.turn <= 2:
            active_bonus += 600  # 後攻1-2ターンは攻撃できるうちに殴る
        return base + active_bonus

    # ── Retreat ───────────────────────────────────────────────────────────────
    def _score_retreat(self) -> float:
        active = self.me.active[0] if self.me.active else None
        if active is None: return -1
        # Lucarioがactiveでエネルギーあり → 攻撃優先。退場しない。
        if active.id == C.MEGA_LUCARIO and self._energy_count(active) >= 1:
            return -1
        # Rioluなどがactiveなら、エネルギー持ちLucarioと交代
        for p in self.me.bench:
            if p and p.id == C.MEGA_LUCARIO and self._energy_count(p) >= 1:
                return 7000
        return -1

    # ── Attack ────────────────────────────────────────────────────────────────
    def _score_attack(self, option) -> float:
        active = self.me.active[0] if self.me.active else None
        opp    = self.opponent.active[0] if self.opponent.active else None
        if active is None or active.id != C.MEGA_LUCARIO:
            return 500

        aura_id, brave_id = self._attack_ids()
        my_prizes_left = len(self.me.prize) if self.me.prize else 0

        # 後攻ターン1: 攻撃できる=先攻優位を取り戻すチャンス → 大幅ボーナス
        first_strike_bonus = 2500 if (self.going_second and self.turn == 1) else 0

        if option.attackId == brave_id:
            # Mega Brave: 270 damage — almost always OHKO
            dmg = 270
            score = 5000 + min(dmg, 340) + first_strike_bonus
            if opp and opp.hp <= dmg:
                prizes_from_ko = prize_count(opp)
                score += 3000 + prizes_from_ko * 500
                if my_prizes_left <= prizes_from_ko:
                    score += 20000  # 勝ち確KO!
        elif option.attackId == aura_id:
            # Aura Jab: 130 + energy ramp to bench
            # Prefer when: (a) only 1 energy so Mega Brave unavailable,
            #              (b) bench Lucarios need energy badly,
            #              (c) KO is possible anyway (opp HP ≤ 130)
            dmg = 130
            bench_lucarios = sum(1 for p in self.me.bench
                                 if p and p.id == C.MEGA_LUCARIO
                                 and self._energy_count(p) < 2)
            # Ramp value: each bench Lucario that needs energy gets 1200
            ramp_value = bench_lucarios * 1200
            score = 3000 + min(dmg, 340) + ramp_value + first_strike_bonus
            if opp and opp.hp <= dmg:
                prizes_from_ko = prize_count(opp)
                score += 3000 + prizes_from_ko * 500
                if my_prizes_left <= prizes_from_ko:
                    score += 20000  # 勝ち確KO!
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
            return 6 if (isinstance(card, Pokemon) and card.id == C.RIOLU) else 1
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
            return 5000 + prize_count(card) * 1000  # pick high-value target
        ec = self._energy_count(card)
        if card.id == C.MEGA_LUCARIO: return 300 + ec * 100
        return ec * 10 + 1

    def _score_to_bench(self, card) -> float:
        if not isinstance(card, Pokemon): return 0
        n = self.field_counts[card.id]
        if card.id == C.RIOLU:      return 200 - 40 * n
        if card.id == C.MEGA_LUCARIO: return 150 - 30 * n
        return 50

    def _score_to_hand(self, card) -> float:
        if card is None: return 0
        cid = card.id
        s = 150 - self.hand_counts[cid] * 60  # penalize duplicates more
        if cid == C.MEGA_LUCARIO:
            # Top priority: get Lucario when Riolu is ready to evolve
            if self.field_counts[C.RIOLU] >= 1 and self._lucario_count() < 1:
                s += 400  # urgent: Riolu waiting to evolve
            elif self.field_counts[C.RIOLU] >= 1:
                s += 200  # secondary Lucario
            else:
                s += 50   # no Riolu yet, less urgent
        elif cid == C.RIOLU:
            total_on_field = self.field_counts[C.RIOLU] + self._lucario_count()
            s += 300 if total_on_field < 1 else (150 if total_on_field < 2 else -20)
        elif cid == C.FIGHTING_ENERGY:
            s += 40  # energies are useful in hand, but prefer Pokémon
        elif cid == C.NIGHT_STRETCHER:
            s += 150 if self.disc_counts.get(C.MEGA_LUCARIO, 0) > 0 else 40
        return s

    def _score_discard(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid == C.FIGHTING_ENERGY:
            # GOOD to discard! Aura Jab recovers up to 3 from discard.
            # Having energy in discard is like having energy in a second hand.
            return 80
        if self.hand_counts[cid] >= 2: return 60
        if cid in (C.RIOLU, C.MEGA_LUCARIO):
            return 5 if self.field_counts[cid] > 0 else -80  # never discard last copy
        if cid in (C.LILLIE_DET, C.CANARI) and self.state.supporterPlayed:
            return 30
        return 5

    def _score_putback(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid in (C.RIOLU, C.MEGA_LUCARIO): return -40
        if self.hand_counts[cid] >= 2:        return 50
        if cid == C.FIGHTING_ENERGY:          return 20
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
            policy = LucarioPolicy(obs)

            # 1-ply lookahead
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
