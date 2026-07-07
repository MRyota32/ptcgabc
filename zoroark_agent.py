"""
zoroark_agent.py - Zoroark anti-EX counter deck
戦略:
  - Neutralization Zone(1247) でZoroarkを相手EX攻撃から完全無効化
  - Illusory Hijacking: 60 × 相手のex/V数 → Lucario ex メタ最適
  - Boss's Orders で相手のベンチexを引き出してKO
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

# Search API (1-ply lookahead)
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

MAX_SEARCH_DEPTH = 20   # max sub-selection steps per option
SEARCH_TOP_K     = 8    # only lookahead on top-K heuristic options


# ── Card IDs (Zoroark anti-EX deck) ──────────────────────────────────────────
class C:
    ZORUA          = 136
    ZOROARK        = 137
    DARK_ENERGY    = 7
    BUDDY_POFFIN   = 1086   # Basic 70HP以下を2枚サーチ (Zorua 70HP ✓)
    ULTRA_BALL     = 1121
    MASTER_BALL    = 1125
    NIGHT_STRETCHER= 1097
    POKEMON_CATCHER= 1124   # コイン表: 相手ベンチを引き出す
    SWITCH         = 1123   # 自分のポケモン入れ替え
    LILLIE_DET     = 1227
    CANARI         = 1233
    COLRESS        = 1194   # ドローサポーター
    NEUTRAL_ZONE   = 1247   # ★ ルールボックスなしポケモンをexの攻撃から守る


LOW_DECK_COUNT = 6

_DIAG = {"decisions": 0, "errors": {}}


def _diag_record_error(exc):
    key = type(exc).__name__ + ": " + str(exc)[:160]
    _DIAG["errors"][key] = _DIAG["errors"].get(key, 0) + 1


# ── Deck loading ──────────────────────────────────────────────────────────────
def _resolve_deck_path() -> str:
    cands = []
    if "__file__" in globals():
        cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "zoroark_deck.csv"))
    cands += ["zoroark_deck.csv", "/kaggle_simulations/agent/zoroark_deck.csv"]
    cands += [os.path.join(p, "zoroark_deck.csv") for p in sys.path if p]
    for path in cands:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("zoroark_deck.csv not found")


DECK_PATH = _resolve_deck_path()
with open(DECK_PATH, "r", encoding="utf-8") as f:
    my_deck = [int(line) for line in f.read().splitlines() if line.strip()]
if len(my_deck) != 60:
    raise ValueError(f"zoroark_deck.csv must contain 60 card ids, got {len(my_deck)}")

if _API_AVAILABLE:
    all_card = all_card_data()
    card_table = {card.cardId: card for card in all_card}
else:
    card_table = {}


# ── Generic helpers ───────────────────────────────────────────────────────────
def normalize_selection(ranked, scores, select):
    n = len(select.option)
    minc = max(0, min(select.minCount, n))
    maxc = max(minc, min(select.maxCount, n))
    out, seen = [], set()
    for i in ranked:
        if not (0 <= i < n) or i in seen:
            continue
        score = scores[i] if i < len(scores) else 0
        if score > 0 or len(out) < minc:
            out.append(i)
            seen.add(i)
        if len(out) >= maxc:
            break
    for i in range(n):
        if len(out) >= minc:
            break
        if i not in seen:
            out.append(i)
            seen.add(i)
    return out


def _legal_fallback(select):
    try:
        n = len(select.option)
        return list(range(min(max(0, select.minCount), n)))
    except Exception:
        return []


def _legal_fallback_from_dict(obs_dict):
    try:
        sel = obs_dict.get("select") or {}
        opts = sel.get("option") or []
        return list(range(min(max(0, sel.get("minCount", 0)), len(opts))))
    except Exception:
        return []


def _safe_get(seq, index):
    try:
        if seq is None or index is None or index < 0 or index >= len(seq):
            return None
        return seq[index]
    except Exception:
        return None


def get_card(obs, area, index, player_index):
    try:
        player = obs.current.players[player_index]
        match area:
            case AreaType.DECK:
                return _safe_get(getattr(obs.select, "deck", None), index)
            case AreaType.HAND:
                return _safe_get(getattr(player, "hand", None), index)
            case AreaType.DISCARD:
                return _safe_get(getattr(player, "discard", None), index)
            case AreaType.ACTIVE:
                return _safe_get(getattr(player, "active", None), index)
            case AreaType.BENCH:
                return _safe_get(getattr(player, "bench", None), index)
            case AreaType.PRIZE:
                return _safe_get(getattr(player, "prize", None), index)
            case AreaType.STADIUM:
                return _safe_get(getattr(obs.current, "stadium", None), index)
            case AreaType.LOOKING:
                return _safe_get(getattr(obs.current, "looking", None), index)
            case _:
                return None
    except Exception:
        return None


def prize_count(pokemon) -> int:
    data = card_table.get(pokemon.id)
    if data is None:
        return 1
    return 3 if data.megaEx else 2 if data.ex else 1


def _is_ex(pokemon) -> bool:
    data = card_table.get(pokemon.id)
    return data is not None and (data.ex or data.megaEx)


def target_value(pokemon) -> int:
    score = prize_count(pokemon) * 1000
    data = card_table.get(pokemon.id)
    if data is not None:
        if data.stage2:
            score += 200
        elif data.stage1:
            score += 100
    score += len(pokemon.energies) * 120
    score += getattr(pokemon, "hp", 0)
    return score


# ── Search helpers ────────────────────────────────────────────────────────────
def _build_search_predictions(obs, my_deck_list, card_table):
    """Build hidden-information predictions required by search_begin."""
    from collections import Counter
    state = obs.current
    my_idx  = state.yourIndex
    op_idx  = 1 - my_idx
    me  = state.players[my_idx]
    opp = state.players[op_idx]

    # ---- My deck ----
    deck_ctr = Counter(my_deck_list)
    used = Counter()
    for p in me.active + me.bench:
        if p: used[p.id] += 1
    for c in (me.hand or []):
        used[c.id] += 1
    for c in me.discard:
        used[c.id] += 1
    for c in me.prize:
        if c: used[c.id] += 1

    remaining = []
    for cid, total in deck_ctr.items():
        remaining.extend([cid] * max(0, total - used[cid]))

    PAD = my_deck_list[0] if my_deck_list else C.DARK_ENERGY
    your_deck = (remaining + [PAD] * 60)[:me.deckCount]

    prize_pool = remaining[me.deckCount:] + [C.DARK_ENERGY] * 10
    your_prize = []
    for p in me.prize:
        if p is None:
            your_prize.append(prize_pool.pop(0) if prize_pool else C.DARK_ENERGY)
        else:
            your_prize.append(p.id)

    # ---- Opponent deck ----
    opp_visible = []
    opp_basic_id = None
    for p in opp.active + opp.bench:
        if p:
            opp_visible.append(p.id)
            if opp_basic_id is None:
                data = card_table.get(p.id)
                if data and data.basic:
                    opp_basic_id = p.id
    for c in opp.discard:
        opp_visible.append(c.id)
    for c in opp.prize:
        if c: opp_visible.append(c.id)

    # Ensure at least 1 basic Pokémon in deck prediction
    if opp_basic_id is None:
        for cid in opp_visible:
            data = card_table.get(cid)
            if data and data.basic:
                opp_basic_id = cid
                break
    if opp_basic_id is None and opp_visible:
        opp_basic_id = opp_visible[0]

    FIGHTING = 6  # Fighting energy card ID
    filler = ([opp_basic_id] if opp_basic_id else []) + opp_visible * 2 + [FIGHTING] * 60

    opponent_deck  = (filler + [FIGHTING] * 60)[:opp.deckCount]
    opponent_prize = (filler + [FIGHTING] * 10)[:len(opp.prize)]
    opponent_hand  = (filler + [FIGHTING] * 10)[:opp.handCount]

    opponent_active = []
    if opp.active and opp.active[0] is None:
        opponent_active = [opp_basic_id] if opp_basic_id else []

    return your_deck, your_prize, opponent_deck, opponent_prize, opponent_hand, opponent_active


def _evaluate_search_obs(obs, my_deck_list, card_table):
    """Heuristic board evaluation for lookahead states."""
    if obs is None or obs.current is None:
        return 0
    state  = obs.current
    my_idx = state.yourIndex
    op_idx = 1 - my_idx
    me  = state.players[my_idx]
    opp = state.players[op_idx]

    if state.result == my_idx:
        return 200_000
    if state.result == op_idx:
        return -200_000

    score = 0

    # Prize lead (each prize difference is huge)
    score += (len(opp.prize) - len(me.prize)) * 8_000

    # My board: Zoroark with energy
    for p in me.active + me.bench:
        if p is None: continue
        ec = len(p.energies)
        if p.id == C.ZOROARK:
            score += 4_000 + ec * 600
            if ec >= 2: score += 1_000   # ready to attack
        elif p.id == C.ZORUA:
            score += 800 + ec * 80

    # Damage dealt to opponent's active
    opp_active = opp.active[0] if opp.active else None
    if opp_active:
        damage = opp_active.maxHp - opp_active.hp
        score += damage * 3
        data = card_table.get(opp_active.id)
        if data:
            pv = 3 if data.megaEx else (2 if data.ex else 1)
            if opp_active.hp <= 0:
                score += pv * 10_000

    # Opponent ex count → Illusory Hijacking multiplier
    opp_ex = sum(1 for p in opp.active + opp.bench
                 if p and card_table.get(p.id)
                 and (card_table[p.id].ex or card_table[p.id].megaEx))
    score += opp_ex * 300

    # Neutral Zone bonus
    if state.stadium and state.stadium[0].id == C.NEUTRAL_ZONE:
        score += 1_500

    return score


def _greedy_resolve_search(state, my_orig_idx, depth=0):
    """Greedily resolve sub-selections (our own) during search."""
    if depth >= MAX_SEARCH_DEPTH:
        return state
    obs = state.observation
    if obs is None or obs.select is None or obs.current is None:
        return state
    if obs.current.result != -1:
        return state
    # Stop when it becomes the opponent's turn
    if obs.current.yourIndex != my_orig_idx:
        return state
    if obs.select.maxCount == 0 or not obs.select.option:
        return state
    try:
        policy = ZoroarkPolicy(obs)
        choices = policy.choose()
        if not choices:
            return state
        next_state = _search_step(state.searchId, choices)
        return _greedy_resolve_search(next_state, my_orig_idx, depth + 1)
    except Exception:
        return state


def _run_lookahead(obs, my_deck_list, card_table):
    """
    1-ply lookahead for MAIN selection.
    Returns the best option index, or None if search unavailable / failed.
    """
    if not _SEARCH_AVAILABLE:
        return None
    if obs.search_begin_input is None:
        return None
    if obs.select is None or not obs.select.option:
        return None
    # Only useful for MAIN selection
    try:
        if obs.select.type != SelectType.MAIN:
            return None
    except Exception:
        return None

    my_idx = obs.current.yourIndex

    try:
        preds = _build_search_predictions(obs, my_deck_list, card_table)
        your_deck, your_prize, opp_deck, opp_prize, opp_hand, opp_active = preds
        root = _search_begin(
            obs,
            your_deck=your_deck,
            your_prize=your_prize,
            opponent_deck=opp_deck,
            opponent_prize=opp_prize,
            opponent_hand=opp_hand,
            opponent_active=opp_active,
        )
    except Exception:
        return None

    # Determine top-K options by heuristic to limit search cost
    policy0 = ZoroarkPolicy(obs)
    h_scores = [policy0._score_option(o) for o in obs.select.option]
    n = len(obs.select.option)
    top_k = sorted(range(n), key=lambda i: h_scores[i], reverse=True)[:SEARCH_TOP_K]

    best_idx   = top_k[0] if top_k else 0
    best_score = -float("inf")

    for i in top_k:
        try:
            next_st = _search_step(root.searchId, [i])
            final_st = _greedy_resolve_search(next_st, my_idx)
            score = _evaluate_search_obs(final_st.observation, my_deck_list, card_table)
            _search_release(final_st.searchId)
            if score > best_score:
                best_score = score
                best_idx = i
        except Exception:
            continue

    try:
        _search_release(root.searchId)
        _search_end()
    except Exception:
        pass

    return best_idx


# ── Zoroark policy ─────────────────────────────────────────────────────────────
class ZoroarkPolicy:
    def __init__(self, obs):
        self.obs = obs
        self.state = obs.current
        self.select = obs.select
        self.context = self.select.context
        self.my_index = self.state.yourIndex
        self.op_index = 1 - self.my_index
        self.me = self.state.players[self.my_index]
        self.opponent = self.state.players[self.op_index]
        self.stadium_id = self.state.stadium[0].id if self.state.stadium else 0

        self.field_counts = defaultdict(int)
        self.hand_counts = defaultdict(int)
        self.discard_counts = defaultdict(int)
        self._count_cards()

    def _count_cards(self):
        for pokemon in self._my_board():
            if pokemon is None:
                continue
            self.field_counts[pokemon.id] += 1
        for card in self.me.hand:
            self.hand_counts[card.id] += 1
        for card in self.me.discard:
            self.discard_counts[card.id] += 1

    def _my_board(self):
        return self.me.active + self.me.bench

    def _opponent_board(self):
        return self.opponent.active + self.opponent.bench

    def _low_deck(self) -> bool:
        return self.me.deckCount <= LOW_DECK_COUNT

    def _hand_size(self) -> int:
        return sum(self.hand_counts.values())

    def _open_bench(self) -> bool:
        bench_used = sum(1 for p in self.me.bench if p is not None)
        return bench_used < getattr(self.me, "benchMax", 5)

    def _opponent_ex_count(self) -> int:
        """相手場のex/V数を数える (Illusory Hijackingのダメージ計算用)"""
        return sum(1 for p in self._opponent_board() if p is not None and _is_ex(p))

    def _neutral_zone_active(self) -> bool:
        return self.stadium_id == C.NEUTRAL_ZONE

    def _count_inplay_attackers(self) -> int:
        return sum(1 for p in self._my_board()
                   if p is not None and p.id == C.ZOROARK)

    def _dark_count(self, pokemon) -> int:
        try:
            return sum(1 for e in pokemon.energies if e == EnergyType.DARK)
        except Exception:
            return 0

    def _energy_count(self, pokemon) -> int:
        try:
            return len(pokemon.energies)
        except Exception:
            return 0

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
        if t == OptionType.NUMBER:
            return option.number if option.number is not None else 0
        if t == OptionType.YES:
            return 100 if self.context == SelectContext.IS_FIRST else 1
        if t == OptionType.NO:
            return 0
        if t == OptionType.CARD:
            return self._score_card_choice(option)
        if t == OptionType.PLAY:
            return self._score_play(option)
        if t in (OptionType.ENERGY, OptionType.ATTACH):
            return self._score_attach(option)
        if t == OptionType.EVOLVE:
            return self._score_evolve(option)
        if t == OptionType.RETREAT:
            return self._score_retreat()
        if t == OptionType.ATTACK:
            return self._score_attack(option)
        if t == OptionType.END:
            return 0
        return 0

    def _score_play(self, option) -> float:
        card = get_card(self.obs, AreaType.HAND, option.index, self.my_index)
        if card is None:
            return 0
        data = card_table.get(card.id)
        if data is None:
            return 0
        if data.cardType == CardType.POKEMON:
            return self._score_play_pokemon(card)
        return self._score_play_trainer(card)

    def _score_play_pokemon(self, card) -> float:
        cid = card.id
        n = self.field_counts[cid]
        if cid == C.ZORUA:
            return 20000 - 200 * n
        return 17000 - 200 * n

    def _score_play_trainer(self, card) -> float:
        cid = card.id
        opp_ex_count = self._opponent_ex_count()

        # ★ Neutralization Zone: Zoroarkをexから守る最優先スタジアム
        if cid == C.NEUTRAL_ZONE:
            if self.state.stadiumPlayed:
                return -1
            if self.stadium_id == C.NEUTRAL_ZONE:
                return -1  # already active
            if opp_ex_count > 0:
                return 15000  # 相手がexデッキなら最優先
            return 5000

        # Pokémon Catcher: コイン表なら相手ベンチを引き出す
        if cid == C.POKEMON_CATCHER:
            opp_bench_ex = sum(1 for p in self.opponent.bench
                               if p is not None and _is_ex(p))
            return 9000 if opp_bench_ex > 0 else 1000

        # Switch: 退場用
        if cid == C.SWITCH:
            active = self.me.active[0] if self.me.active else None
            if active and active.id == C.ZORUA:
                for p in self.me.bench:
                    if p and p.id == C.ZOROARK and self._energy_count(p) >= 2:
                        return 8000
            return 500

        if cid == C.LILLIE_DET:
            if self._low_deck() or self.state.supporterPlayed:
                return -1
            return 12000 if self._hand_size() <= 4 else 2600

        if cid == C.CANARI:
            if self.state.supporterPlayed:
                return -1
            need = self._count_inplay_attackers() < 2
            hand_small = self._hand_size() <= 3
            return 11500 if need else (10000 if hand_small else 1500)

        if cid == C.COLRESS:
            if self.state.supporterPlayed:
                return -1
            return 10000 if self._hand_size() <= 4 else 1500

        # Buddy-Buddy Poffin: Zorua(70HP)を2体並べる
        if cid == C.BUDDY_POFFIN:
            zorua_needed = (self.field_counts[C.ZORUA]
                            + self.hand_counts[C.ZORUA]) < 4
            return 13000 if self._open_bench() and zorua_needed else 600

        if cid == C.ULTRA_BALL:
            if self._count_inplay_attackers() < 2 and self._hand_size() >= 3:
                return 9000
            return 400

        if cid == C.MASTER_BALL:
            if self._count_inplay_attackers() < 2:
                return 8500
            return 300

        if cid == C.NIGHT_STRETCHER:
            has_zoroark_in_discard = self.discard_counts.get(C.ZOROARK, 0) > 0
            return 7000 if has_zoroark_in_discard else 300

        return 8000

    def _score_evolve(self, option) -> float:
        target = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon):
            return 0
        card = get_card(self.obs, AreaType.HAND, option.index, self.my_index)
        cid = card.id if card is not None else None
        if cid == C.ZOROARK:
            return 22000 + self._energy_count(target) * 20
        return 19000

    def _score_attach(self, option) -> float:
        pokemon = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(pokemon, Pokemon):
            return 0
        return self._energy_target_score(pokemon, option.inPlayArea == AreaType.ACTIVE)

    def _energy_target_score(self, pokemon, is_active) -> float:
        ec = self._energy_count(pokemon)
        if pokemon.id == C.ZOROARK:
            # Illusory Hijacking: 2エネ必要
            base = 8000 if ec < 2 else 1200
        elif pokemon.id == C.ZORUA:
            base = 3000 if ec < 1 else 200
        else:
            base = 100
        if is_active:
            base += 150
        return base

    def _score_retreat(self) -> float:
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return -1
        # Neutral Zone下: Zoroarkは退場不要 (exから攻撃受けない)
        if self._neutral_zone_active() and active.id == C.ZOROARK:
            return -1
        # アクティブが攻撃できるなら退場しない
        if active.id == C.ZOROARK and self._energy_count(active) >= 2:
            return -1
        # ベンチにZoroarkがいてエネ足りているなら交代
        for p in self.me.bench:
            if p is not None and p.id == C.ZOROARK and self._energy_count(p) >= 2:
                return 6000
        return -1

    def _score_attack(self, option) -> float:
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None:
            return 800

        ex_count = self._opponent_ex_count()

        # Zoroarkの技を識別: attacks[0]=Illusory Hijacking, attacks[1]=Claw Slash
        data = card_table.get(active.id)
        attack_list = list(data.attacks) if data and hasattr(data, "attacks") else []

        if option.attackId in attack_list:
            idx = attack_list.index(option.attackId)
            if idx == 0:
                # Illusory Hijacking: 60 × ex数
                dmg = 60 * ex_count
            else:
                # Claw Slash: 110 固定
                dmg = 110
        else:
            # 不明な技: 60ダメージとして扱う
            dmg = 60

        if dmg <= 0:
            # exが0体の時はClaw Slashにフォールバックしたい
            # ただしこのオプションは0ダメ → 他のオプションを優先
            return -1

        score = 1000 + min(dmg, 280)
        if opp is not None and opp.hp <= dmg:
            score += 2500 + prize_count(opp) * 200
        return score

    def _score_card_choice(self, option) -> float:
        card = get_card(self.obs, option.area, option.index, option.playerIndex)
        if card is None:
            return 0
        ctx = self.context

        if ctx in (SelectContext.SWITCH, SelectContext.TO_ACTIVE):
            return self._score_active_choice(option, card)
        if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            return self._score_setup_active(card)
        if ctx in (SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD):
            return self._score_to_bench(card)
        if ctx == SelectContext.TO_HAND:
            return self._score_to_hand(card)
        if ctx == SelectContext.ATTACH_TO:
            if isinstance(card, Pokemon):
                return self._energy_target_score(card, option.inPlayArea == AreaType.ACTIVE)
            return 0
        if ctx in (SelectContext.ATTACH_FROM, SelectContext.TO_HAND_ENERGY):
            return 100 if card.id == C.DARK_ENERGY else 10
        if ctx in (SelectContext.DISCARD, SelectContext.DISCARD_CARD_OR_ATTACHED_CARD,
                   SelectContext.DISCARD_ENERGY, SelectContext.DISCARD_ENERGY_CARD):
            return self._score_discard(card)
        if ctx in (SelectContext.DAMAGE_COUNTER, SelectContext.DAMAGE_COUNTER_ANY):
            if isinstance(card, Pokemon) and option.playerIndex == self.op_index:
                return 10000 + prize_count(card) * 1000 - getattr(card, "hp", 0)
            return -target_value(card) if isinstance(card, Pokemon) else 0
        if ctx in (SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM,
                   SelectContext.TO_PRIZE, SelectContext.TO_DECK_ENERGY):
            return self._score_putback(card)
        return 0

    def _score_active_choice(self, option, card) -> float:
        if not isinstance(card, Pokemon):
            return 0
        if option.playerIndex == self.op_index:
            # Boss's Orders: 相手ベンチから価値の高いexを選ぶ
            return target_value(card)
        # 自分のスイッチ: エネルギーが多くZoroarkを優先
        score = self._energy_count(card) * 10
        if card.id == C.ZOROARK:
            score += 200
        return score + 1

    def _score_setup_active(self, card) -> int:
        if card is None:
            return 0
        # セットアップ時: Zoruaをアクティブに (Zoroarkに進化する土台)
        if card.id == C.ZORUA:
            return 6
        return 1

    def _score_to_bench(self, card) -> float:
        if card is None:
            return 0
        data = card_table.get(card.id)
        if data is None or data.cardType != CardType.POKEMON:
            return 0
        cid = card.id
        n = self.field_counts[cid]
        if cid == C.ZORUA:
            return 200 - 30 * n
        return 100 - 20 * n

    def _score_to_hand(self, card) -> float:
        if card is None:
            return 0
        cid = card.id
        score = 200 - self.hand_counts[cid] * 60
        if cid == C.ZORUA:
            score += 40 if self.field_counts[C.ZORUA] < 2 else -10
        elif cid == C.ZOROARK:
            score += 60 if self.field_counts[C.ZORUA] >= 1 else 10
        elif cid == C.DARK_ENERGY:
            score += 30
        elif cid in (C.NEUTRAL_ZONE,):
            score += 20 if not self._neutral_zone_active() else 0
        return score

    def _score_discard(self, card) -> float:
        if card is None:
            return 0
        cid = card.id
        if cid == C.DARK_ENERGY:
            return 20 if self.hand_counts[cid] >= 4 else -60
        if self.hand_counts[cid] >= 2:
            return 60
        if cid in (C.ZORUA, C.ZOROARK):
            return -50 if self.field_counts[cid] == 0 else 5
        if cid in (C.LILLIE_DET, C.CANARI) and self.state.supporterPlayed:
            return 30
        return 0

    def _score_putback(self, card) -> float:
        if card is None:
            return 0
        cid = card.id
        if self.hand_counts[cid] >= 2:
            return 60
        if cid == C.DARK_ENERGY and self.hand_counts[cid] >= 4:
            return 40
        if cid in (C.ZORUA, C.ZOROARK):
            return -40
        return 10


# ── Agent entry point ─────────────────────────────────────────────────────────
def agent(obs_dict: dict) -> list[int]:
    try:
        select_is_none = isinstance(obs_dict, dict) and obs_dict.get("select") is None
    except Exception:
        select_is_none = False
    if select_is_none:
        return my_deck

    _DIAG["decisions"] += 1

    if not _API_AVAILABLE:
        return _legal_fallback_from_dict(obs_dict)

    try:
        obs = to_observation_class(obs_dict)
        if obs.select is None:
            return my_deck

        try:
            policy = ZoroarkPolicy(obs)

            # 1-ply lookahead for MAIN selection
            search_idx = None
            try:
                search_idx = _run_lookahead(obs, my_deck, card_table)
            except Exception as exc:
                _diag_record_error(exc)

            if search_idx is not None:
                # Build a single-element selection from the search result
                n = len(obs.select.option)
                minc = max(0, min(obs.select.minCount, n))
                if 0 <= search_idx < n:
                    result = [search_idx]
                    # If minCount > 1, fill remaining via heuristic
                    if minc > 1:
                        ranked, scores = policy.rank()
                        for ri in ranked:
                            if ri != search_idx:
                                result.append(ri)
                            if len(result) >= minc:
                                break
                    return result

            ranked, scores = policy.rank()
            return normalize_selection(ranked, scores, obs.select)
        except Exception as exc:
            _diag_record_error(exc)
            return _legal_fallback(obs.select)
    except Exception as exc:
        _diag_record_error(exc)
        return _legal_fallback_from_dict(obs_dict if isinstance(obs_dict, dict) else {})
