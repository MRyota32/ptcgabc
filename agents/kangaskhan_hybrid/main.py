"""
kangaskhan_hybrid/main.py — Kangaskhan × Crustle ハイブリッド

土台: crustle/main.py (397行・80.5% vs ルカリオex系) に
Mega Kangaskhan ex (756) の最小差分を追加。

変更点メモ (crustle/main.py から):
  +  C.KANGASKHAN = 756, C.ENRICHING_E = 13 を追加 (+2行)
  +  _play_pokemon: Kangaskhan ブロック追加 (+4行)
  +  _attach: Kangaskhan + Enriching 優先ケース追加 (+7行)
  +  _retreat: Kangaskhan の退場条件追加 (+8行)
  +  _attack: Kangaskhan 攻撃ブロック追加 (+10行)
  +  _card (SETUP/TO_BENCH): Kangaskhan スコア追加 (+2行)
  +  _card (SWITCH/TO_ACTIVE): Kangaskhan スコア追加 (+3行)
  +  _to_hand: Kangaskhan サーチ優先追加 (+3行)
  +  _attach_score_for: Kangaskhan ケース追加 (+3行)
  +  _discard: Kangaskhan / Enriching ケース追加 (+2行)
  合計: 約 +44行 → 約441行

攻撃ロジックの前提:
  「相手バトル場が Crustle(345)」のときだけ Kangaskhan は攻撃を避ける。
  _opp_has_ex() は使わない。相手の Mega Lucario ex には普通に 200+ dmg が通る。
  壁モード(Crustle) は常に攻撃する。「攻撃しない」は禁止。
"""
from __future__ import annotations
import os, sys, random
from collections import defaultdict

# ── カードID ──────────────────────────────────────────────────
class C:
    ISHIZUMAI   = 344   # Dwebble (たね)
    IWAPARESU   = 345   # Crustle (1進化)
    KANGASKHAN  = 756   # Mega Kangaskhan ex (たね/HP300/無色) ← ADD
    GRASS_E     = 1     # 基本草エネルギー
    GROW_E      = 18    # グロウ草エネルギー
    ENRICHING_E = 13    # リッチエネルギー (ACE SPEC/1枚/アタッチ時4ドロー) ← ADD
    POFFIN      = 1086  # なかよしポフィン
    MUSHI_SET   = 1094  # むしとりセット
    ULTRA_BALL  = 1121  # ハイパーボール
    POKE_PAD    = 1152  # ポケパッド（非ルールポケモン1枚サーチ）
    FOREST      = 1261  # 活力の森 (スタジアム)
    LILLIE      = 1227  # リーリエの決心
    KAKITSUBA   = 1202  # カキツバタ (Drayton)
    TOKO        = 1225  # トウコ (Hilda)
    TAKESHI     = 1210  # タケシのスカウト (Brock's Scout)
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
class KangaskhanPolicy:
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
    # ── ADD ──
    def _kang_count(self):
        return sum(1 for p in self._board() if p and p.id == C.KANGASKHAN)
    def _opp_active_is_crustle(self) -> bool:
        opp_a = self.opp.active[0] if self.opp.active else None
        return opp_a is not None and opp_a.id == C.IWAPARESU

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
        # ── ADD: Kangaskhan はたね → 直接ベンチへ ──
        if card.id == C.KANGASKHAN:
            n = self.field_cnt[C.KANGASKHAN]
            return 14000 - 200 * n if self._open_bench() else -1
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
            need = self.field_cnt[C.ISHIZUMAI] < 2
            return 13000 if need and self._open_bench() else 1000

        if cid == C.MUSHI_SET:
            return 9000 if self._crustle_count() < 3 else 4000

        if cid == C.POKE_PAD:
            need = self._crustle_count() < 3 or self.field_cnt[C.ISHIZUMAI] < 2
            return 9500 if need else 1500

        if cid == C.ULTRA_BALL:
            need = self._crustle_count() < 2 or self.field_cnt[C.ISHIZUMAI] < 2
            return 8000 if need and self._hand_size() >= 3 else 500

        # スタジアム
        if cid == C.FOREST:
            if self.state.stadiumPlayed: return -1
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
        # ── ADD: Kangaskhan に3エネ優先 ──
        if pokemon.id == C.KANGASKHAN:
            if ec < 3:
                # Enriching Energy はアタッチ時4ドロー → 最高優先
                card = _get_card(self.obs, AreaType.HAND, opt.index, self.my_idx)
                if card and card.id == C.ENRICHING_E:
                    return 12000
                return 9000 - ec * 700
            return 100
        if pokemon.id == C.IWAPARESU:
            if ec < 3:
                return 9000 - ec * 800
            return 100
        if pokemon.id == C.ISHIZUMAI:
            return 200 if ec == 0 else 50
        return 50

    # ── にげる ────────────────────────────────────────────────
    def _retreat(self) -> float:
        active = self.me.active[0] if self.me.active else None
        if active is None: return -1

        # ── BENCH-CHARGE FIX: Kangaskhan は ec>=3 になるまでベンチで充電 ──
        if active.id == C.KANGASKHAN:
            if self._opp_active_is_crustle() or _ec(active) < 3:
                # 相手Crustle (攻撃無効) or エネ不足 → ベンチに戻す
                for p in self.me.bench:
                    if p and p.id in (C.IWAPARESU, C.ISHIZUMAI):
                        return 7000
            return -1  # ec>=3 かつ相手が Crustle でない → 攻撃継続

        # ── BENCH-CHARGE FIX: Crustle がactive でKangaskhanが3エネ完成 → バトン ──
        if active.id == C.IWAPARESU:
            if not self._opp_active_is_crustle():
                for p in self.me.bench:
                    if p and p.id == C.KANGASKHAN and _ec(p) >= 3:
                        return 8000  # Kangaskhan 準備完了 → 前へ
            return -1  # それ以外は Crustle 継続

        # イシズマイがactiveならイワパレスと交代
        if active.id == C.ISHIZUMAI:
            for p in self.me.bench:
                if p and p.id == C.IWAPARESU and _ec(p) >= 1:
                    return 7000
        return -1

    # ── 攻撃 ──────────────────────────────────────────────────
    def _attack(self, opt) -> float:
        active = self.me.active[0] if self.me.active else None
        opp_a  = self.opp.active[0] if self.opp.active else None
        if active is None: return 500

        # ── ADD: Mega Kangaskhan ex の攻撃 (Rapid-Fire Combo: ●●●/200+コイン×50) ──
        if active.id == C.KANGASKHAN:
            ec = _ec(active)
            if ec < 3: return -1  # エネ不足
            # 相手バトル場が Crustle(=Rock Inn) → 攻撃無効なので避ける
            if self._opp_active_is_crustle(): return -1
            dmg = 200  # ベースダメージ（コインボーナス期待値除外）
            score = 5000 + min(dmg, 300)
            if opp_a and opp_a.hp <= dmg:
                score += 3000 + _prize_count(opp_a) * 500
                my_prizes_left = len(self.me.prize) if self.me.prize else 0
                if my_prizes_left <= _prize_count(opp_a):
                    score += 20000  # 勝ち確KO
            return score

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
            # ── ADD: Kangaskhan もセットアップで選択可 ──
            if isinstance(card, Pokemon) and card.id == C.KANGASKHAN:
                return 8
            return 1

        if ctx in (SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD):
            if isinstance(card, Pokemon):
                if card.id == C.ISHIZUMAI: return 200
                if card.id == C.IWAPARESU: return 150
                # ── ADD ──
                if card.id == C.KANGASKHAN: return 140
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
            # ── BENCH-CHARGE FIX: Kangaskhan は ec>=3 の時だけ前に出す ──
            if card.id == C.KANGASKHAN:
                if ec >= 3 and not self._opp_active_is_crustle():
                    return 700  # 3エネ完成 → 即出撃
                return 50  # 未完成 → ベンチ待機
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
        # ── ADD: Kangaskhan サーチ優先 ──
        elif cid == C.KANGASKHAN:
            s += 250 if self._kang_count() < 1 else (100 if self._kang_count() < 2 else -20)
        elif cid in GRASS_ENERGY_IDS:
            s += 80
        # ── ADD: Enriching はデッキ1枚のみ → 重複気にせず取る ──
        elif cid == C.ENRICHING_E:
            s += 90
        return s

    def _attach_score_for(self, pokemon) -> float:
        ec = _ec(pokemon)
        # ── ADD ──
        if pokemon.id == C.KANGASKHAN:
            return 9000 - ec * 700 if ec < 3 else 100
        if pokemon.id == C.IWAPARESU:
            return 9000 - ec * 800 if ec < 3 else 100
        if pokemon.id == C.ISHIZUMAI:
            return 150 if ec == 0 else 30
        return 30

    def _discard(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid in GRASS_ENERGY_IDS: return 40
        # ── ADD: Enriching は高価なので優先捨てない ──
        if cid == C.ENRICHING_E: return 20
        if self.hand_cnt[cid] >= 2:  return 60
        if cid in (C.ISHIZUMAI, C.IWAPARESU):
            return 5 if self.field_cnt[cid] > 0 else -100
        # ── ADD ──
        if cid == C.KANGASKHAN:
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
        policy = KangaskhanPolicy(obs)
        return policy.choose()
    except Exception:
        try:
            return _legal_dict(obs_dict)
        except Exception:
            return []
