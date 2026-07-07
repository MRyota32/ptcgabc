"""
crustle/main.py — イワパレスデッキ エージェント
戦略:
  - イワパレス(345) 特性「しんぴのいしやど」: 相手のexポケモンからダメージを受けない
    → Mega Lucario ex の攻撃を完全無効
  - イシズマイ(344) ワザ「かくせい」(●): 山札からイワパレスを即進化
  - グレートシザー(草●●, 120ダメ): 効果を無視して120ダメージ
"""
from __future__ import annotations
import os, sys, random
from collections import defaultdict

# ── カードID ──────────────────────────────────────────────────
class C:
    ISHIZUMAI   = 344   # Dwebble (たね)
    IWAPARESU   = 345   # Crustle (1進化)
    GRASS_E     = 1     # 基本草エネルギー
    GROW_E      = 18    # グロウ草エネルギー
    POFFIN      = 1086  # なかよしポフィン
    MUSHI_SET   = 1094  # むしとりセット
    ULTRA_BALL  = 1121  # ハイパーボール
    POKE_PAD    = 1152  # ポケパッド（非ルールポケモン1枚サーチ）
    FOREST      = 1261  # 活力の森 (スタジアム)
    LILLIE      = 1227  # リーリエの決心
    KAKITSUBA   = 1202  # カキツバタ
    TOKO        = 1225  # トウコ
    TAKESHI     = 1210  # タケシのスカウト
    CHEREN      = 1224  # チェレン

GRASS_ENERGY_IDS = {C.GRASS_E, C.GROW_E}

# ── デッキ読み込み ─────────────────────────────────────────────
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

# ── API import (Kaggle環境のみ動作) ───────────────────────────
try:
    from cg.api import (
        AreaType, CardType, OptionType, SelectContext, SelectType,
        Pokemon, Card, Observation, to_observation_class, all_card_data,
    )
    _API = True
    _card_table = {c.cardId: c for c in all_card_data()}
except Exception:
    _API = False
    _card_table = {}


# ── ヘルパー ──────────────────────────────────────────────────
def _safe(seq, i):
    try: return seq[i] if seq and 0 <= i < len(seq) else None
    except: return None

def _legal_fallback(sel):
    try:
        n = len(sel.option)
        return list(range(min(max(0, sel.minCount), n)))
    except: return []

def _legal_dict(obs_dict):
    try:
        sel = (obs_dict or {}).get("select") or {}
        opts = sel.get("option") or []
        return list(range(min(max(0, sel.get("minCount", 0)), len(opts))))
    except: return []

def _prize_count(pokemon) -> int:
    d = _card_table.get(pokemon.id)
    if d is None: return 1
    return 3 if d.megaEx else 2 if d.ex else 1

def _ec(pokemon) -> int:
    try: return len(pokemon.energies)
    except: return 0

def _get_card(obs, area, index, player_index):
    try:
        p = obs.current.players[player_index]
        match area:
            case AreaType.HAND:    return _safe(p.hand, index)
            case AreaType.ACTIVE:  return _safe(p.active, index)
            case AreaType.BENCH:   return _safe(p.bench, index)
            case AreaType.DISCARD: return _safe(p.discard, index)
            case AreaType.DECK:    return _safe(getattr(obs.select, "deck", None), index)
            case AreaType.PRIZE:   return _safe(p.prize, index)
            case _:                return None
    except: return None

def _normalize(ranked, scores, select):
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


# ── ポリシー ──────────────────────────────────────────────────
class CrustlePolicy:
    def __init__(self, obs):
        self.obs      = obs
        self.state    = obs.current
        self.select   = obs.select
        self.ctx      = self.select.context
        self.my_idx   = self.state.yourIndex
        self.op_idx   = 1 - self.my_idx
        self.me       = self.state.players[self.my_idx]
        self.opp      = self.state.players[self.op_idx]
        self.hand_cnt  = defaultdict(int)
        self.field_cnt = defaultdict(int)
        self.disc_cnt  = defaultdict(int)
        self._count()

    def _count(self):
        for c in (self.me.hand or []):
            self.hand_cnt[c.id] += 1
        for p in self.me.active + self.me.bench:
            if p: self.field_cnt[p.id] += 1
        for c in self.me.discard:
            self.disc_cnt[c.id] += 1

    def _board(self):   return self.me.active + self.me.bench
    def _hand_size(self): return sum(self.hand_cnt.values())
    def _open_bench(self):
        return sum(1 for p in self.me.bench if p) < getattr(self.me, "benchMax", 5)
    def _crustle_count(self):
        return sum(1 for p in self._board() if p and p.id == C.IWAPARESU)
    def _crustle_ready(self):
        return sum(1 for p in self._board()
                   if p and p.id == C.IWAPARESU and _ec(p) >= 3)

    def choose(self):
        if not self.select.option or self.select.maxCount == 0:
            return []
        scores = [self._score(o) for o in self.select.option]
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return _normalize(ranked, scores, self.select)

    def _score(self, opt) -> float:
        t = opt.type
        if t == OptionType.NUMBER:  return opt.number if opt.number is not None else 0
        if t == OptionType.YES:     return 100 if self.ctx == SelectContext.IS_FIRST else 1
        if t == OptionType.NO:      return 0
        if t == OptionType.PLAY:    return self._play(opt)
        if t in (OptionType.ENERGY, OptionType.ATTACH): return self._attach(opt)
        if t == OptionType.EVOLVE:  return self._evolve(opt)
        if t == OptionType.RETREAT: return self._retreat()
        if t == OptionType.ATTACK:  return self._attack(opt)
        if t == OptionType.CARD:    return self._card(opt)
        if t == OptionType.END:     return 0
        return 0

    # ── プレイ ─────────────────────────────────────────────────
    def _play(self, opt) -> float:
        card = _get_card(self.obs, AreaType.HAND, opt.index, self.my_idx)
        if card is None: return 0
        d = _card_table.get(card.id)
        if d is None: return 0
        if d.cardType == CardType.POKEMON:
            return self._play_pokemon(card)
        return self._play_trainer(card)

    def _play_pokemon(self, card) -> float:
        if card.id == C.ISHIZUMAI:
            n = self.field_cnt[C.ISHIZUMAI]
            return 15000 - 200 * n if self._open_bench() else -1
        return 5000 if self._open_bench() else -1

    def _play_trainer(self, card) -> float:
        cid = card.id

        # サポーター系（1ターン1枚）
        if cid == C.LILLIE:
            if self.state.supporterPlayed: return -1
            return 12000 if self._hand_size() <= 4 else 2000

        if cid == C.KAKITSUBA:
            if self.state.supporterPlayed: return -1
            return 11000 if self._crustle_count() < 3 else 3000

        if cid == C.TOKO:
            if self.state.supporterPlayed: return -1
            # 進化ポケモン+エネルギーをサーチ: イワパレスがまだ少ない時
            return 10000 if self._crustle_count() < 2 else 2000

        if cid == C.TAKESHI:
            if self.state.supporterPlayed: return -1
            need = self.field_cnt[C.ISHIZUMAI] + self._crustle_count() < 3
            return 9000 if need else 1500

        if cid == C.CHEREN:
            if self.state.supporterPlayed: return -1
            return 8000 if self._hand_size() <= 3 else 1000

        # グッズ系
        if cid == C.POFFIN:
            # ベンチにイシズマイを2枚展開
            need = self.field_cnt[C.ISHIZUMAI] < 2
            return 13000 if need and self._open_bench() else 1000

        if cid == C.MUSHI_SET:
            # 草ポケモンとエネルギーをサーチ (top7から2枚)
            return 9000 if self._crustle_count() < 3 else 4000

        if cid == C.POKE_PAD:
            # 非ルールポケモン(=イワパレス/イシズマイ)を1枚サーチ
            need = self._crustle_count() < 3 or self.field_cnt[C.ISHIZUMAI] < 2
            return 9500 if need else 1500

        if cid == C.ULTRA_BALL:
            need = self._crustle_count() < 2 or self.field_cnt[C.ISHIZUMAI] < 2
            return 8000 if need and self._hand_size() >= 3 else 500

        # スタジアム
        if cid == C.FOREST:
            if self.state.stadiumPlayed: return -1
            # 草ポケモンが出したばかりでも進化可能になる
            return 11000 if self.field_cnt[C.ISHIZUMAI] >= 1 else 3000

        return 5000

    # ── 進化 ──────────────────────────────────────────────────
    def _evolve(self, opt) -> float:
        card = _get_card(self.obs, AreaType.HAND, opt.index, self.my_idx)
        if card and card.id == C.IWAPARESU:
            return 20000  # 最優先で進化
        return 15000

    # ── エネルギーアタッチ ─────────────────────────────────────
    def _attach(self, opt) -> float:
        pokemon = _get_card(self.obs, opt.inPlayArea, opt.inPlayIndex, self.my_idx)
        if not isinstance(pokemon, Pokemon): return 0
        ec = _ec(pokemon)
        if pokemon.id == C.IWAPARESU:
            # 3エネルギー必要 (草●●)。0→9000, 1→8200, 2→7400, 3+→100
            if ec < 3:
                return 9000 - ec * 800
            return 100
        if pokemon.id == C.ISHIZUMAI:
            # かくせいのため1エネ必要だが、進化優先
            return 200 if ec == 0 else 50
        return 50

    # ── にげる ────────────────────────────────────────────────
    def _retreat(self) -> float:
        active = self.me.active[0] if self.me.active else None
        if active is None: return -1
        # イシズマイがactiveならイワパレスと交代
        if active.id == C.ISHIZUMAI:
            for p in self.me.bench:
                if p and p.id == C.IWAPARESU and _ec(p) >= 1:
                    return 7000
        # イワパレスはactiveのまま攻撃
        if active.id == C.IWAPARESU and _ec(active) >= 3:
            return -1
        return -1

    # ── 攻撃 ──────────────────────────────────────────────────
    def _attack(self, opt) -> float:
        active = self.me.active[0] if self.me.active else None
        opp_a  = self.opp.active[0] if self.opp.active else None
        if active is None: return 500

        dmg = 0
        if active.id == C.IWAPARESU:
            dmg = 120
        elif active.id == C.ISHIZUMAI:
            # かくせいは攻撃だが進化効果 → イワパレスがいない場合のみ
            if self._crustle_count() == 0:
                return 3000  # 緊急: 進化のために使う
            return -1  # イワパレスがいるなら使わない

        score = 4000 + min(dmg, 300)
        if opp_a and opp_a.hp <= dmg:
            score += 3000 + _prize_count(opp_a) * 500
            my_prizes_left = len(self.me.prize) if self.me.prize else 0
            if my_prizes_left <= _prize_count(opp_a):
                score += 20000  # 勝ち確KO
        return score

    # ── カード選択 ────────────────────────────────────────────
    def _card(self, opt) -> float:
        card = _get_card(self.obs, opt.area, opt.index, opt.playerIndex)
        if card is None: return 0
        ctx = self.ctx

        if ctx in (SelectContext.SETUP_ACTIVE_POKEMON,):
            if isinstance(card, Pokemon) and card.id == C.ISHIZUMAI:
                return 10
            return 1

        if ctx in (SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD):
            if isinstance(card, Pokemon):
                if card.id == C.ISHIZUMAI: return 200
                if card.id == C.IWAPARESU: return 150
            return 50

        if ctx == SelectContext.TO_HAND:
            return self._to_hand(card)

        if ctx == SelectContext.ATTACH_TO:
            if isinstance(card, Pokemon):
                return self._attach_score_for(card)
            return 0

        if ctx in (SelectContext.DISCARD, SelectContext.DISCARD_CARD_OR_ATTACHED_CARD,
                   SelectContext.DISCARD_ENERGY, SelectContext.DISCARD_ENERGY_CARD):
            return self._discard(card)

        if ctx in (SelectContext.SWITCH, SelectContext.TO_ACTIVE):
            if not isinstance(card, Pokemon): return 0
            if opt.playerIndex == self.op_idx:
                return _prize_count(card) * 2000
            ec = _ec(card)
            if card.id == C.IWAPARESU: return 500 + ec * 100
            return ec * 10 + 1

        if ctx in (SelectContext.DAMAGE_COUNTER, SelectContext.DAMAGE_COUNTER_ANY):
            if isinstance(card, Pokemon) and opt.playerIndex == self.op_idx:
                return 10000 + _prize_count(card) * 1000 - getattr(card, "hp", 0)
            return 0

        return 0

    def _to_hand(self, card) -> float:
        if card is None: return 0
        cid = card.id
        s = 100 - self.hand_cnt[cid] * 40
        if cid == C.IWAPARESU:
            if self.field_cnt[C.ISHIZUMAI] >= 1 and self._crustle_count() < 2:
                s += 400
            else:
                s += 150
        elif cid == C.ISHIZUMAI:
            on_field = self.field_cnt[C.ISHIZUMAI] + self._crustle_count()
            s += 300 if on_field < 2 else (100 if on_field < 4 else -20)
        elif cid in GRASS_ENERGY_IDS:
            s += 80
        return s

    def _attach_score_for(self, pokemon) -> float:
        ec = _ec(pokemon)
        if pokemon.id == C.IWAPARESU:
            return 9000 - ec * 800 if ec < 3 else 100
        if pokemon.id == C.ISHIZUMAI:
            return 150 if ec == 0 else 30
        return 30

    def _discard(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid in GRASS_ENERGY_IDS: return 40
        if self.hand_cnt[cid] >= 2:  return 60
        if cid in (C.ISHIZUMAI, C.IWAPARESU):
            return 5 if self.field_cnt[cid] > 0 else -100
        return 10


# ── エントリーポイント ─────────────────────────────────────────
def agent(obs_dict: dict) -> list[int]:
    # デッキ選択局面
    if isinstance(obs_dict, dict) and obs_dict.get("select") is None:
        return my_deck

    if not _API:
        return _legal_dict(obs_dict)

    try:
        obs = to_observation_class(obs_dict)
        if obs is None or obs.select is None:
            return []
        policy = CrustlePolicy(obs)
        return policy.choose()
    except Exception:
        try:
            return _legal_dict(obs_dict)
        except Exception:
            return []
