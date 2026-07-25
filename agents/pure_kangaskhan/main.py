"""
pure_kangaskhan/main.py — 純 Mega Kangaskhan ex デッキ（Crustle無し）

構築メモ:
  Crustle との接ぎ木を完全排除した別アーキ。
  弱点(闘) = Mega Lucario ex 系には構造的に負ける（捨てマッチ・別提出の crustle が担当）。
  闘以外（zoroark 等）には HP300 + 期待250打点 + 毎ターン2ドローで圧倒する設計。

デッキ60枚:
  756×4  Mega Kangaskhan ex (唯一のアタッカー)
  1227×4 Lillie's Det / 1202×4 Drayton / 1225×3 Hilda / 1210×2 Brock's / 1224×2 Cheren
  1121×4 Ultra Ball / 1152×2 Poké Pad / 1147×3 Jumbo Ice Cream / 1097×2 Night Stretcher
  1264×2 Battle Cage / 13×1 Enriching Energy (ACE SPEC) / 18×4 Grow Grass / 1×23 Grass Energy

ポリシー原則（シンプル・先読みなし）:
  1. Kangaskhan をベンチ/バトル場に配置
  2. エネルギーを積極的にアタッチ (ec が少ない方優先)
  3. ec>=3 かつ 相手 active ≠ Crustle(345) → Rapid-Fire Combo で攻撃
  4. YES = 常に YES (Run Errand 2ドロー, コインフリップ等)
  5. 3エネ以上の時 Jumbo Ice Cream で継続回復
"""
from __future__ import annotations
import os, sys
from collections import defaultdict

# ── カードID ──────────────────────────────────────────────────
class C:
    KANGASKHAN  = 756   # Mega Kangaskhan ex (たね/HP300/無色)
    GRASS_E     = 1     # 基本草エネルギー
    GROW_E      = 18    # グロウ草エネルギー
    ENRICHING_E = 13    # リッチエネルギー (ACE SPEC/アタッチ時4ドロー)
    LILLIE      = 1227  # リーリエの決心
    KAKITSUBA   = 1202  # カキツバタ (Drayton)
    TOKO        = 1225  # トウコ (Hilda)
    TAKESHI     = 1210  # タケシのスカウト (Brock's)
    CHEREN      = 1224  # チェレン
    ULTRA_BALL  = 1121  # ハイパーボール
    POKE_PAD    = 1152  # ポケパッド (非ルールポケモンサーチ = Kangaskhan)
    JUMBO_ICE   = 1147  # ジャンボアイスクリーム (3エネ以上バトルポケ80回復)
    NIGHT_STR   = 1097  # 夜のタンカ (トラッシュから回収)
    BATTLE_CAGE = 1264  # バトルコロシアム (ベンチダメカン禁止)
    CRUSTLE_345 = 345   # 相手の Rock Inn イワパレス → 攻撃無効なので避ける

ENERGY_IDS = {C.GRASS_E, C.GROW_E, C.ENRICHING_E}

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

# ── API import ────────────────────────────────────────────────
try:
    from cg.api import (
        AreaType, CardType, OptionType, SelectContext,
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
class PureKangaskhanPolicy:
    def __init__(self, obs):
        self.obs     = obs
        self.state   = obs.current
        self.select  = obs.select
        self.ctx     = self.select.context
        self.my_idx  = self.state.yourIndex
        self.op_idx  = 1 - self.my_idx
        self.me      = self.state.players[self.my_idx]
        self.opp     = self.state.players[self.op_idx]
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

    def _board(self):     return self.me.active + self.me.bench
    def _hand_size(self): return sum(self.hand_cnt.values())
    def _open_bench(self):
        return sum(1 for p in self.me.bench if p) < getattr(self.me, "benchMax", 5)
    def _kang_count(self):
        return sum(1 for p in self._board() if p and p.id == C.KANGASKHAN)
    def _opp_active_is_crustle(self) -> bool:
        opp_a = self.opp.active[0] if self.opp.active else None
        return opp_a is not None and opp_a.id == C.CRUSTLE_345

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
        if t == OptionType.EVOLVE:  return 15000
        if t == OptionType.RETREAT: return -1   # Kangaskhanは常にアクティブで戦う
        if t == OptionType.ATTACK:  return self._attack(opt)
        if t == OptionType.CARD:    return self._card(opt)
        if t == OptionType.END:     return 0
        return 0

    # ── プレイ ────────────────────────────────────────────────
    def _play(self, opt) -> float:
        card = _get_card(self.obs, AreaType.HAND, opt.index, self.my_idx)
        if card is None: return 0
        d = _card_table.get(card.id)
        if d is None: return 0
        if d.cardType == CardType.POKEMON:
            return self._play_pokemon(card)
        return self._play_trainer(card)

    def _play_pokemon(self, card) -> float:
        if card.id == C.KANGASKHAN:
            n = self.field_cnt[C.KANGASKHAN]
            return 15000 - 300 * n if self._open_bench() else -1
        return 5000 if self._open_bench() else -1

    def _play_trainer(self, card) -> float:
        cid = card.id

        # ── サポーター（1ターン1枚）──────────────────────────
        if cid == C.LILLIE:
            if self.state.supporterPlayed: return -1
            return 12000 if self._hand_size() <= 4 else 2000

        if cid == C.KAKITSUBA:
            if self.state.supporterPlayed: return -1
            # Kangaskhanが場にいない間は高優先（サーチ系）
            return 11000 if self._kang_count() < 2 else 3000

        if cid == C.TOKO:
            if self.state.supporterPlayed: return -1
            return 10000 if self._kang_count() < 2 else 2000

        if cid == C.TAKESHI:
            if self.state.supporterPlayed: return -1
            return 9000 if self._kang_count() < 3 else 1500

        if cid == C.CHEREN:
            if self.state.supporterPlayed: return -1
            return 8000 if self._hand_size() <= 3 else 1000

        # ── グッズ ───────────────────────────────────────────
        if cid == C.ULTRA_BALL:
            need = self._kang_count() < 2
            return 9000 if need and self._hand_size() >= 3 else 1000

        if cid == C.POKE_PAD:
            # 非ルールポケモン = Kangaskhan をサーチ
            need = self._kang_count() < 2
            return 9500 if need else 2000

        if cid == C.JUMBO_ICE:
            # バトル場に3エネ以上付いていれば80回復
            active = self.me.active[0] if self.me.active else None
            if active and active.id == C.KANGASKHAN and _ec(active) >= 3:
                if getattr(active, "hp", 9999) < getattr(active, "maxHp", 9999):
                    return 10000
            return 500

        if cid == C.NIGHT_STR:
            has_kang = self.disc_cnt.get(C.KANGASKHAN, 0) > 0
            return 9000 if has_kang else 300

        if cid == C.BATTLE_CAGE:
            if self.state.stadiumPlayed: return -1
            return 8000  # ベンチ保護は早めに設置

        return 5000

    # ── エネルギーアタッチ ────────────────────────────────────
    def _attach(self, opt) -> float:
        pokemon = _get_card(self.obs, opt.inPlayArea, opt.inPlayIndex, self.my_idx)
        if not isinstance(pokemon, Pokemon): return 0
        if pokemon.id != C.KANGASKHAN: return 50  # Kangaskhan 以外には基本付けない
        ec = _ec(pokemon)
        if ec >= 3: return 100  # 3エネ到達済み → 低優先（他の方に回す）
        # Enriching Energy はアタッチ時4ドロー → 最高優先
        card = _get_card(self.obs, AreaType.HAND, opt.index, self.my_idx)
        if card and card.id == C.ENRICHING_E:
            return 12000
        # ec が少ない方を優先 (active > bench で同 ec なら active 優先)
        is_active = (opt.inPlayArea == AreaType.ACTIVE)
        base = 9000 - ec * 800
        return base + (300 if is_active else 0)

    # ── 攻撃 ──────────────────────────────────────────────────
    def _attack(self, opt) -> float:
        active = self.me.active[0] if self.me.active else None
        opp_a  = self.opp.active[0] if self.opp.active else None
        if active is None: return 500
        if active.id != C.KANGASKHAN: return 500

        ec = _ec(active)
        if ec < 3: return -1  # エネ不足 → 攻撃しない
        if self._opp_active_is_crustle(): return -1  # Rock Inn → 攻撃無効

        dmg = 200  # Rapid-Fire Combo ベースダメ（コイン期待値除外）
        score = 5000 + min(dmg, 300)
        if opp_a and opp_a.hp <= dmg:
            score += 3000 + _prize_count(opp_a) * 500
            my_prizes = len(self.me.prize) if self.me.prize else 0
            if my_prizes <= _prize_count(opp_a):
                score += 20000  # 勝ち確KO
        return score

    # ── カード選択 ────────────────────────────────────────────
    def _card(self, opt) -> float:
        card = _get_card(self.obs, opt.area, opt.index, opt.playerIndex)
        if card is None: return 0
        ctx = self.ctx

        if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            if isinstance(card, Pokemon) and card.id == C.KANGASKHAN:
                return 10
            return 1

        if ctx in (SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD):
            if isinstance(card, Pokemon) and card.id == C.KANGASKHAN:
                n = self.field_cnt[C.KANGASKHAN]
                return 200 - 30 * n
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
            # 自分側: エネが多い Kangaskhan を優先
            if card.id == C.KANGASKHAN:
                return 500 + _ec(card) * 100
            return _ec(card) * 10 + 1

        if ctx in (SelectContext.DAMAGE_COUNTER, SelectContext.DAMAGE_COUNTER_ANY):
            if isinstance(card, Pokemon) and opt.playerIndex == self.op_idx:
                return 10000 + _prize_count(card) * 1000 - getattr(card, "hp", 0)
            return 0

        return 0

    def _to_hand(self, card) -> float:
        if card is None: return 0
        cid = card.id
        s = 100 - self.hand_cnt[cid] * 40
        if cid == C.KANGASKHAN:
            s += 400 if self._kang_count() < 2 else (100 if self._kang_count() < 4 else -20)
        elif cid in ENERGY_IDS:
            s += 80
        elif cid == C.NIGHT_STR:
            s += 150 if self.disc_cnt.get(C.KANGASKHAN, 0) > 0 else 40
        elif cid == C.JUMBO_ICE:
            active = self.me.active[0] if self.me.active else None
            s += 200 if (active and _ec(active) >= 3) else 60
        return s

    def _attach_score_for(self, pokemon) -> float:
        if pokemon.id != C.KANGASKHAN: return 30
        ec = _ec(pokemon)
        return 9000 - ec * 800 if ec < 3 else 100

    def _discard(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid in (C.GRASS_E, C.GROW_E): return 40
        if cid == C.ENRICHING_E:          return 20  # 1枚のみ → 捨てにくい
        if self.hand_cnt[cid] >= 2:       return 60
        if cid == C.KANGASKHAN:
            return 5 if self.field_cnt[cid] > 0 else -100
        return 10


# ── エントリーポイント ─────────────────────────────────────────
def agent(obs_dict: dict) -> list[int]:
    if isinstance(obs_dict, dict) and obs_dict.get("select") is None:
        return my_deck
    if not _API:
        return _legal_dict(obs_dict)
    try:
        obs = to_observation_class(obs_dict)
        if obs is None or obs.select is None:
            return []
        return PureKangaskhanPolicy(obs).choose()
    except Exception:
        try:
            return _legal_dict(obs_dict)
        except Exception:
            return []
