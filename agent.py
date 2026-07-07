"""
agent.py - Iono's Bellibolt ex deck
Elo 836 実績のルールベースエージェント
出典: github.com/wmh/ptcg-abc/agents/bellibolt/main.py
"""
from __future__ import annotations

import os
import time
import random
import pathlib
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
        all_card_data,
        to_observation_class,
    )
    _API_AVAILABLE = True
except Exception:
    _API_AVAILABLE = False

try:
    from cg.api import search_begin, search_step, search_end
    _SEARCH_AVAILABLE = True
except Exception:
    _SEARCH_AVAILABLE = False


# ── Card IDs (Iono's Bellibolt ex deck) ──────────────────────────────────────
class C:
    VOLTORB = 265
    TADBULB = 268
    BELLIBOLT_EX = 269
    WATTREL = 270
    KILOWATTREL = 271
    LIGHTNING_ENERGY = 4
    LILLIE_DET = 1227
    CANARI = 1233
    BUDDY_POFFIN = 1086
    ULTRA_BALL = 1121
    LEVINCIA = 1254
    NIGHT_STRETCHER = 1097
    POKE_PAD = 1152
    MAX_ROD = 1110
    ENERGY_RETRIEVAL = 1118


THUNDEROUS_BOLT = 368
MACH_BOLT = 370
VOLTAIC_CHAIN = 363
TINY_CHARGE = 367
QUICK_ATTACK = 369

ATTACK_DATA = {
    THUNDEROUS_BOLT: (C.BELLIBOLT_EX, 4, 230, True),
    MACH_BOLT:       (C.KILOWATTREL, 3, 70, False),
    VOLTAIC_CHAIN:   (C.VOLTORB, 2, 20, False),
    TINY_CHARGE:     (C.TADBULB, 2, 30, False),
    QUICK_ATTACK:    (C.WATTREL, 1, 10, False),
}

ATTACKER_IDS = {C.BELLIBOLT_EX, C.KILOWATTREL, C.VOLTORB}
FIGHTING_WEAK_IDS = {C.BELLIBOLT_EX, C.VOLTORB, C.TADBULB}
SAFE_VS_FIGHTING = {C.KILOWATTREL, C.WATTREL}
IMMUNE_TO_EX = {158, 207, 330, 345}

# 主力攻撃に必要なエネルギー数（minではなくprimary攻撃基準）
PRIMARY_ENERGY_REQ = {
    C.BELLIBOLT_EX: 4,   # Thunderous Bolt
    C.KILOWATTREL:  3,   # Mach Bolt
    C.VOLTORB:      2,   # Voltaic Chain
}

LOW_DECK_COUNT = 6
USE_ANTI_FIGHTING = True   # Lucario(格闘)メタ対策: Kilowattrelを優先
VALUE_NET = None
USE_VALUE_SEARCH = False
USE_BC = False

_DIAG = {"decisions": 0, "policy_ok": 0, "policy_fallback": 0,
         "obs_fallback": 0, "deck_returns": 0, "errors": {},
         "chosen_types": {}, "attack_ids_chosen": {}}


def _diag_record_error(exc):
    key = type(exc).__name__ + ": " + str(exc)[:160]
    _DIAG["errors"][key] = _DIAG["errors"].get(key, 0) + 1


# ── Deck loading ─────────────────────────────────────────────────────────────
def _resolve_deck_path() -> str:
    import sys
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
    raise ValueError(f"deck.csv must contain 60 card ids, got {len(my_deck)}")

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


def _lightning_count(pokemon) -> int:
    try:
        return sum(1 for e in pokemon.energies if e == EnergyType.LIGHTNING)
    except Exception:
        return 0


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


# ── Bellibolt policy ──────────────────────────────────────────────────────────
class BellipoltPolicy:
    def __init__(self, obs):
        self.obs = obs
        self.state = obs.current
        self.select = obs.select
        self.context = self.select.context
        self.my_index = self.state.yourIndex
        self.op_index = 1 - self.my_index
        self.me = self.state.players[self.my_index]
        self.opponent = self.state.players[self.op_index]
        self.my_prizes_left = len(self.me.prize)
        self.op_prizes_left = len(self.opponent.prize)
        self.stadium_id = self.state.stadium[0].id if self.state.stadium else 0

        self.field_counts = defaultdict(int)
        self.hand_counts = defaultdict(int)
        self.discard_counts = defaultdict(int)
        self.board_lightning = 0
        self._count_cards()
        self.fighting_threat = self._fighting_threat()

    def _fighting_threat(self) -> bool:
        if not USE_ANTI_FIGHTING:
            return False
        for p in self._opponent_board():
            if p is None:
                continue
            d = card_table.get(p.id)
            if d is not None and d.energyType == EnergyType.FIGHTING:
                return True
        return False

    def _count_cards(self):
        for pokemon in self._my_board():
            if pokemon is None:
                continue
            self.field_counts[pokemon.id] += 1
            self.board_lightning += _lightning_count(pokemon)
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

    def _attack_damage(self, attacker, attack_id, target) -> int:
        data = ATTACK_DATA.get(attack_id)
        if data is None or target is None:
            return 0
        _, _req, base, is_ex = data
        if is_ex and target.id in IMMUNE_TO_EX:
            return 0
        if attack_id == VOLTAIC_CHAIN:
            dmg = 20 + 20 * self.board_lightning
        else:
            dmg = base
        op_data = card_table.get(target.id)
        if op_data is not None:
            if op_data.weakness == EnergyType.LIGHTNING:
                dmg *= 2
            elif op_data.resistance == EnergyType.LIGHTNING:
                dmg = max(0, dmg - 30)
        return dmg

    def _best_damage_against(self, pokemon, target) -> int:
        data = card_table.get(pokemon.id)
        if data is None:
            return 0
        best = 0
        for aid in data.attacks:
            best = max(best, self._attack_damage(pokemon, aid, target))
        return best

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
        if t == OptionType.ABILITY:
            return self._score_ability(option)
        if t == OptionType.RETREAT:
            return self._score_retreat()
        if t == OptionType.ATTACK:
            return self._score_attack(option)
        if t == OptionType.END:
            return 0
        return 0

    def _score_ability(self, option) -> float:
        card = get_card(self.obs, option.area, option.index, self.my_index)
        if card is None:
            return 0
        if card.id == C.BELLIBOLT_EX:
            if self.hand_counts[C.LIGHTNING_ENERGY] <= 0:
                return -1
            if self._needs_more_energy():
                return 15000
            return 1500
        if card.id == C.KILOWATTREL:
            if self._low_deck() or self._hand_size() >= 5:
                return -1
            return 11000
        return 12000

    def _needs_more_energy(self) -> bool:
        for pokemon in self._my_board():
            if pokemon is None or pokemon.id not in ATTACKER_IDS:
                continue
            # primary攻撃（最大ダメージ）に必要なエネルギー数で判定
            req = PRIMARY_ENERGY_REQ.get(pokemon.id, 2)
            if len(pokemon.energies) < req:
                return True
        return False

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
        wattrel_bonus = 2500 if self.fighting_threat else 0
        if cid == C.TADBULB:
            return 20000 - 200 * n
        if cid == C.WATTREL:
            return 19000 + wattrel_bonus - 200 * n
        if cid == C.VOLTORB:
            return 18000 - 300 * n
        return 17000 - 200 * n

    def _score_play_trainer(self, card) -> float:
        cid = card.id
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
        if cid == C.BUDDY_POFFIN:
            return 13000 if self._open_bench() and self._basics_in_deck_likely() else 600
        if cid == C.ULTRA_BALL:
            if self._count_inplay_attackers() < 2 and self._hand_size() >= 3:
                return 9000
            return 400
        if cid == C.POKE_PAD:
            return 8500 if self._count_inplay_attackers() < 2 else 500
        if cid == C.LEVINCIA:
            return self._score_levincia()
        if cid == C.NIGHT_STRETCHER:
            return 7000 if (self.discard_counts.get(C.BELLIBOLT_EX, 0)
                            or self.discard_counts.get(C.KILOWATTREL, 0)) else 300
        if cid == C.MAX_ROD:
            return 6000 if self.me.discard and self._low_deck() else 200
        if cid == C.ENERGY_RETRIEVAL:
            return 5000 if self.discard_counts.get(C.LIGHTNING_ENERGY, 0) >= 2 \
                and self.hand_counts[C.LIGHTNING_ENERGY] == 0 else 200
        return 9000

    def _score_levincia(self) -> float:
        if self.state.stadiumPlayed:
            return -1
        if self.stadium_id == C.LEVINCIA:
            return -1
        if self.stadium_id and self.stadium_id != C.LEVINCIA:
            return 9500
        if self.discard_counts.get(C.LIGHTNING_ENERGY, 0) >= 1:
            return 8000
        return 1500

    def _count_inplay_attackers(self) -> int:
        return sum(1 for p in self._my_board()
                   if p is not None and p.id in (C.BELLIBOLT_EX, C.KILOWATTREL, C.VOLTORB,
                                                 C.TADBULB, C.WATTREL))

    def _open_bench(self) -> bool:
        bench_used = sum(1 for p in self.me.bench if p is not None)
        return bench_used < getattr(self.me, "benchMax", 5)

    def _basics_in_deck_likely(self) -> bool:
        in_play_or_hand = (self.field_counts[C.TADBULB] + self.field_counts[C.WATTREL]
                           + self.field_counts[C.VOLTORB]
                           + self.hand_counts[C.TADBULB] + self.hand_counts[C.WATTREL]
                           + self.hand_counts[C.VOLTORB])
        return in_play_or_hand < 9

    def _score_evolve(self, option) -> float:
        target = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon):
            return 0
        card = get_card(self.obs, AreaType.HAND, option.index, self.my_index)
        cid = card.id if card is not None else None
        base = 21000 if cid == C.BELLIBOLT_EX else 20500 if cid == C.KILOWATTREL else 19500
        if self.fighting_threat and cid == C.KILOWATTREL:
            base = 21500
        return base + len(target.energies) * 20

    def _score_attach(self, option) -> float:
        pokemon = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(pokemon, Pokemon):
            return 0
        return self._energy_target_score(pokemon, option.inPlayArea == AreaType.ACTIVE)

    def _energy_target_score(self, pokemon, is_active) -> float:
        if pokemon.id not in ATTACKER_IDS:
            return 100  # 非アタッカーは超低優先

        have = len(pokemon.energies)
        target = PRIMARY_ENERGY_REQ.get(pokemon.id, 2)

        if have >= target:
            return 200  # 充足済み → 他に回す

        # 残り必要エネが少ないほど高優先（あと1枚 > あと2枚 > ...）
        needed = target - have
        base = 10000 - needed * 1500  # 残1→8500, 残2→7000, 残3→5500, 残4→4000

        # 格闘脅威時: Kilowattrel大幅UP、格闘弱点組は投資しない
        if self.fighting_threat:
            if pokemon.id == C.KILOWATTREL:
                base += 2000
            elif pokemon.id in FIGHTING_WEAK_IDS:
                base -= 2500

        # アクティブボーナス（ただし格闘弱点＋格闘脅威なら逆効果）
        if is_active:
            if self.fighting_threat and pokemon.id in FIGHTING_WEAK_IDS:
                base -= 1000
            else:
                base += 300

        return base

    def _score_retreat(self) -> float:
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return -1
        # 格闘脅威: EX弱点ポケモンを安全なKilowattrelと交代
        if self.fighting_threat and active.id in FIGHTING_WEAK_IDS:
            for p in self.me.bench:
                if p is not None and p.id in SAFE_VS_FIGHTING and self._best_damage_against(p, opp) > 0:
                    return 6500
        # 瀕死EXポケモン保護: HPが30%未満なら2枚サイド献上を避けるため交代
        if active.id == C.BELLIBOLT_EX and active.maxHp > 0:
            hp_ratio = active.hp / active.maxHp
            if hp_ratio < 0.30:
                active_can_ko = self._best_damage_against(active, opp) >= opp.hp if opp else False
                if not active_can_ko:
                    for p in self.me.bench:
                        if p is not None and p.id != C.VOLTORB and self._best_damage_against(p, opp) > 0:
                            return 5800  # 攻撃はできるが退場優先
        active_dmg = self._best_damage_against(active, opp)
        if active_dmg > 0:
            # アクティブが攻撃できる → 基本は攻撃優先
            # ただしEXで瀕死かつKO取れないなら守る
            if active.id == C.BELLIBOLT_EX:
                can_ko = active_dmg >= opp.hp
                if not can_ko and active.maxHp > 0 and active.hp / active.maxHp < 0.25:
                    for p in self.me.bench:
                        if p and p.id != C.VOLTORB and self._best_damage_against(p, opp) > 0:
                            return 5000
            return -1
        for p in self.me.bench:
            if p is not None and self._best_damage_against(p, opp) > 0:
                return 6000
        return -1

    def _score_attack(self, option) -> float:
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return 800
        dmg = self._attack_damage(active, option.attackId, opp)
        if dmg <= 0:
            return -1
        score = 1000 + min(dmg, 280)
        if opp.hp <= dmg:
            prizes_from_ko = prize_count(opp)
            score += 2500 + prizes_from_ko * 500
            # 勝利確定ボーナス（このKOでゲーム終了）
            if self.op_prizes_left <= prizes_from_ko:
                score += 15000
            # サイドレース逆転ボーナス
            elif self.op_prizes_left - prizes_from_ko < self.my_prizes_left:
                score += 2000
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
            return 100 if card.id == C.LIGHTNING_ENERGY else 10
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

        # 相手のポケモンを選ぶ場合（ボスの指令など）
        if option.playerIndex == self.op_index:
            pv = prize_count(card)
            score = pv * 3000  # EX(2枚)・メガEX(3枚)を優先
            # すでにダメージを受けているならKO圏内の可能性UP
            damage_taken = getattr(card, 'maxHp', 0) - getattr(card, 'hp', 0)
            score += damage_taken * 5
            # 自分の場でKOできるなら更に優先
            for p in self._my_board():
                if p and self._best_damage_against(p, card) >= card.hp:
                    score += 8000
                    break
            return score

        # 自分のポケモンを選ぶ場合（SWITCH / TO_ACTIVE）
        opp = self.opponent.active[0] if self.opponent.active else None
        score = len(card.energies) * 10
        if opp is not None and self._best_damage_against(card, opp) > 0:
            score += 200
        if self.fighting_threat:
            if card.id in SAFE_VS_FIGHTING:
                score += 300
            elif card.id in FIGHTING_WEAK_IDS:
                score -= 250
            return score + 1
        if opp is not None and opp.id in IMMUNE_TO_EX:
            if card.id in (C.KILOWATTREL, C.VOLTORB):
                score += 150
        else:
            if card.id == C.BELLIBOLT_EX:
                score += 120
            elif card.id == C.KILOWATTREL:
                score += 60
        return score + 1

    def _score_setup_active(self, card) -> int:
        if card is None:
            return 0
        # WattrelをアクティブにすることでKilowattrel(非EX・格闘安全)を早期育成
        if card.id == C.WATTREL:
            return 6
        if card.id == C.TADBULB:
            return 5
        if card.id == C.VOLTORB:
            return 4
        return 1

    def _score_to_bench(self, card) -> float:
        if card is None:
            return 0
        data = card_table.get(card.id)
        if data is None or data.cardType != CardType.POKEMON:
            return 0
        cid = card.id
        n = self.field_counts[cid]
        if cid == C.TADBULB:
            return 200 - 30 * n
        if cid == C.WATTREL:
            return 190 - 30 * n
        if cid == C.VOLTORB:
            return 170 - 40 * n
        return 100 - 20 * n

    def _score_to_hand(self, card) -> float:
        if card is None:
            return 0
        cid = card.id
        score = 200 - self.hand_counts[cid] * 60
        if cid == C.TADBULB:
            score += 40 if self.field_counts[C.BELLIBOLT_EX] + self.field_counts[C.TADBULB] < 2 else -20
        elif cid == C.BELLIBOLT_EX:
            score += 60 if self.field_counts[C.TADBULB] >= 1 else 0
        elif cid == C.WATTREL:
            score += 30 if self.field_counts[C.KILOWATTREL] + self.field_counts[C.WATTREL] < 1 else -10
        elif cid == C.KILOWATTREL:
            score += 50 if self.field_counts[C.WATTREL] >= 1 else 0
        elif cid == C.VOLTORB:
            score += 25
        elif cid == C.LIGHTNING_ENERGY:
            score += 35
        return score

    def _score_discard(self, card) -> float:
        if card is None:
            return 0
        cid = card.id
        if cid == C.LIGHTNING_ENERGY:
            return 20 if self.hand_counts[cid] >= 3 else -60
        if self.hand_counts[cid] >= 2:
            return 60
        if cid in (C.TADBULB, C.WATTREL, C.VOLTORB, C.BELLIBOLT_EX, C.KILOWATTREL):
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
        if cid == C.LIGHTNING_ENERGY and self.hand_counts[cid] >= 3:
            return 40
        if cid in (C.TADBULB, C.BELLIBOLT_EX, C.WATTREL, C.KILOWATTREL):
            return -40
        return 10


# ── Agent entry point ─────────────────────────────────────────────────────────
def agent(obs_dict: dict) -> list[int]:
    try:
        select_is_none = isinstance(obs_dict, dict) and obs_dict.get("select") is None
    except Exception:
        select_is_none = False
    if select_is_none:
        _DIAG["deck_returns"] += 1
        return my_deck

    _DIAG["decisions"] += 1

    if not _API_AVAILABLE:
        # フォールバック：APIなし環境（ローカルテスト）
        return _legal_fallback_from_dict(obs_dict)

    try:
        obs = to_observation_class(obs_dict)
        if obs.select is None:
            return my_deck

        try:
            policy = BellipoltPolicy(obs)
            ranked, scores = policy.rank()
            selection = normalize_selection(ranked, scores, obs.select)
            _DIAG["policy_ok"] += 1
            return selection
        except Exception as exc:
            _diag_record_error(exc)
            _DIAG["policy_fallback"] += 1
            return _legal_fallback(obs.select)
    except Exception as exc:
        _diag_record_error(exc)
        _DIAG["obs_fallback"] += 1
        return _legal_fallback_from_dict(obs_dict if isinstance(obs_dict, dict) else {})
