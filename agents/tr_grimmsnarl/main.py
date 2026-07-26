"""
tr_grimmsnarl/main.py — Marnie's Grimmsnarl ex + Team Rocket's 悪グッドスタッフ

構築メモ:
  ラダー首位 Dries @ Tufa Labs(1173) のアーキを再現。
  この依頼の成否は Stage2 進化の安定と、盤面構築の政策にかかっている。

進化安定化の工夫:
  Impidimp(646)×4 + Rare Candy(1079)×3 で Grimmsnarl ex(648) への最速ルートを確保。
  Buddy-Buddy Poffin(1086)×4 でたね2体展開（Impidimp優先）。
  Transceiver(1134)→Petrel(1219) でRare Candy/必要札をサーチするチェーン。
  Morgrem(647)×1 は Rare Candy が引けない時の保険（Impidimp→Morgrem→Grimmsnarl）。
  Poké Pad(1152) は非ルールポケモン（Impidimp/Tarountula等）をサーチ。
  Night Stretcher(1097) はトラッシュからポケモン/エネ回収。

Grimmsnarl vs Spidopsの使い分け:
  Shadow Bullet(180dmg + ベンチ30): Grimmsnarl 2エネで常に安定。主力技。
  Rocket Rush(TR数×30dmg): TR系を3体以上並べてから使用（90dmg以上）。
  → 序盤はGrimmsnarl一本で戦い、TRが3体以上並んだらSpidopsも攻撃参加。
  → 盤面にTR系が少ない場合は Grimmsnarl 一本でも可（安定優先）。

TR Energy(15)の付け先:
  Team Rocket's Energy(id=15) は "Team Rocket's" ポケモン専用。
  Marnie's Grimmsnarl ex は "Marnie's" のため TR Energyが付かない可能性大。
  → Grimmsnarl の動力は基本悪エネ(id=7) で確保。
  → TR Energy は Spidops(401)/Tarountula(400) 専用と考えて配分。
  → 本 battle_start チェックログで確認結果を記載。

デッキ60枚:
  646×4 Impidimp / 647×1 Morgrem / 648×3 Grimmsnarl ex
  400×2 Tarountula / 401×2 Spidops / 112×2 Munkidori
  1079×3 Rare Candy / 1134×3 Transceiver / 1219×2 Petrel / 1218×2 Giovanni
  1086×4 Poffin / 1152×2 PokéPad / 1097×2 Night Stretcher
  1259×1 Spikemuth Gym / 1080×1 Unfair Stamp(ACE SPEC候補)
  7×22 基本悪エネ / 15×4 TR Energy
"""
from __future__ import annotations
import os, sys
from collections import defaultdict

# ── カードID ──────────────────────────────────────────────────
class C:
    IMPIDIMP    = 646   # Marnie's Impidimp: たね/悪
    MORGREM     = 647   # Marnie's Morgrem: 1進化/悪
    GRIMMSNARL  = 648   # Marnie's Grimmsnarl ex: Stage2/HP320/悪
                        # Shadow Bullet: 180dmg(悪×2)+ベンチ30
    TAROUNTULA  = 400   # Team Rocket's Tarountula: たね
    SPIDOPS     = 401   # Team Rocket's Spidops: Stage1/Rocket Rush(TR×30)
                        # 特性 Charging Up: トラッシュから基本エネ付け直し
    MUNKIDORI   = 112   # Munkidori: たね/超
    DARK_E      = 7     # 基本悪エネルギー (Grimmsnarl専用動力)
    TR_E        = 15    # Team Rocket's Energy (TR専用: Spidops等)
    RARE_CANDY  = 1079  # レアキャンディー: たね→2進化へ直接進化
    TRANSCEIVER = 1134  # TR Transceiver: TRサポートをサーチ
    PETREL      = 1219  # TR's Petrel: トレーナーを1枚サーチ
    GIOVANNI    = 1218  # TR's Giovanni: TRポケモンを入替
    POFFIN      = 1086  # Buddy-Buddy Poffin: たね2体をベンチへ
    POKE_PAD    = 1152  # Poké Pad: 非ルールポケモンサーチ
    NIGHT_STR   = 1097  # Night Stretcher: トラッシュから回収
    SPIKEMUTH   = 1259  # Spikemuth Gym: Marnie'sポケモンサーチ
    UNFAIR_STAMP= 1080  # Unfair Stamp(ACE SPEC): KO後手札リセット妨害

# Team Rocket's ポケモン一覧（Rocket Rushの打点計算用）
TR_POKEMON_IDS = {400, 401}  # Tarountula, Spidops (Munkidoriは非TRと仮定)

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
class GrimmsnarlPolicy:
    def __init__(self, obs):
        self.obs    = obs
        self.state  = obs.current
        self.select = obs.select
        self.ctx    = self.select.context
        self.my_idx = self.state.yourIndex
        self.op_idx = 1 - self.my_idx
        self.me     = self.state.players[self.my_idx]
        self.opp    = self.state.players[self.op_idx]
        self.hand_cnt  = defaultdict(int)
        self.field_cnt = defaultdict(int)
        self.disc_cnt  = defaultdict(int)
        self._count()

    def _count(self):
        for c in (self.me.hand or []):
            self.hand_cnt[c.id] += 1
        for p in self.me.active + self.me.bench:
            if p: self.field_cnt[p.id] += 1
        for c in (self.me.discard or []):
            self.disc_cnt[c.id] += 1

    def _open_bench(self):
        return sum(1 for p in self.me.bench if p) < getattr(self.me, "benchMax", 5)

    def _hand_size(self): return sum(self.hand_cnt.values())

    def _grimmsnarl_count(self):
        return self.field_cnt[C.GRIMMSNARL]

    def _grimmsnarl_ready(self):
        """フィールド上でエネ2個以上のGrimmsnarl exが存在するか"""
        return any(p and p.id == C.GRIMMSNARL and _ec(p) >= 2
                   for p in self.me.active + self.me.bench)

    def _tr_count_on_field(self) -> int:
        """フィールド上のTeam Rocket'sポケモン数（Rocket Rush打点計算用）"""
        return sum(1 for p in self.me.active + self.me.bench
                   if p and p.id in TR_POKEMON_IDS)

    def _can_rare_candy(self) -> bool:
        """Rare Candyを使える状況か (Impidimp+Grimmsnarlが手元にある)"""
        return (self.field_cnt[C.IMPIDIMP] >= 1
                and self.hand_cnt[C.GRIMMSNARL] >= 1)

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
        cid = card.id
        n = self.field_cnt[cid]
        if cid == C.IMPIDIMP:
            # Grimmsnarl進化ラインの起点: 最優先で並べる
            return 15000 - 200 * n if self._open_bench() else -1
        if cid == C.TAROUNTULA:
            # TR系を並べることでRocket Rushの打点UP
            return 10000 - 200 * n if self._open_bench() else -1
        if cid == C.MUNKIDORI:
            return 8000 if (n == 0 and self._open_bench()) else -1
        return 5000 if self._open_bench() else -1

    def _play_trainer(self, card) -> float:
        cid = card.id
        grimm_count = self._grimmsnarl_count()
        need_grimmsnarl = grimm_count < 2

        # ── Rare Candy (最重要グッズ) ──────────────────────────
        if cid == C.RARE_CANDY:
            # Impidimpがいて、手札にGrimmsnarl exがある時に使う
            if self._can_rare_candy():
                return 20000  # ★進化の生命線: 最高スコア
            # Impidimpはいるが手札にGrimmsnarl exがない時も将来のために使う
            if self.field_cnt[C.IMPIDIMP] >= 1:
                return 8000
            return 1000

        # ── サポーター（1ターン1枚）────────────────────────────────
        if cid == C.TRANSCEIVER:
            if self.state.supporterPlayed: return -1
            # TRサポート(Petrel/Giovanni)をサーチ: 常に高優先
            return 13000 if need_grimmsnarl else 5000

        if cid == C.PETREL:
            if self.state.supporterPlayed: return -1
            # トレーナーをサーチ: Rare Candyを引きに行く
            return 12000 if need_grimmsnarl else 4000

        if cid == C.GIOVANNI:
            if self.state.supporterPlayed: return -1
            # TRポケモンを入替え: 戦略的な場面で使う
            return 7000 if grimm_count >= 1 else 3000

        if cid == C.SPIKEMUTH:
            if getattr(self.state, "stadiumPlayed", False): return -1
            # Marnie'sポケモンをサーチ: Impidimpが少ない時
            return 10000 if self.field_cnt[C.IMPIDIMP] < 2 else 3000

        # ── グッズ ────────────────────────────────────────────────
        if cid == C.POFFIN:
            # たね2体をベンチへ: Impidimp優先
            need = self.field_cnt[C.IMPIDIMP] + self.field_cnt[C.TAROUNTULA] < 3
            return 13000 if need and self._open_bench() else 1000

        if cid == C.POKE_PAD:
            # 非ルールポケモンサーチ (Impidimp/Tarountula等)
            need = self.field_cnt[C.IMPIDIMP] < 2 or self.field_cnt[C.TAROUNTULA] < 1
            return 9000 if need else 2000

        if cid == C.NIGHT_STR:
            # トラッシュからポケモン/エネ回収
            grimm_in_disc = self.disc_cnt[C.GRIMMSNARL] + self.disc_cnt[C.IMPIDIMP]
            return 9000 if grimm_in_disc >= 1 else 3000

        if cid == C.UNFAIR_STAMP:
            # ACE SPEC: KO直後に使うと相手手札をリセット
            # 自分がKOされた直後(プライズが減った時)に有効
            my_prizes = len(self.me.prize) if self.me.prize else 0
            return 8000 if my_prizes <= 3 else 2000

        return 5000

    # ── 進化 ──────────────────────────────────────────────────
    def _evolve(self, opt) -> float:
        """
        進化は最優先。Rare Candy との連携で Grimmsnarl ex が最高。
        Grimmsnarl ex(648) > Morgrem(647) > Spidops(401)
        """
        card = _get_card(self.obs, AreaType.HAND, opt.index, self.my_idx)
        if card is None: return 15000
        if card.id == C.GRIMMSNARL: return 25000  # ★最高優先 (Shadow Bullet解禁)
        if card.id == C.MORGREM:    return 22000  # 保険ルート
        if card.id == C.SPIDOPS:    return 18000  # TR Rocket Rush解禁
        return 15000

    # ── エネルギーアタッチ ────────────────────────────────────
    def _attach(self, opt) -> float:
        pokemon = _get_card(self.obs, opt.inPlayArea, opt.inPlayIndex, self.my_idx)
        if not isinstance(pokemon, Pokemon): return 0
        ec = _ec(pokemon)

        # Grimmsnarl ex: Shadow Bulletに悪×2必要。基本悪エネを集中投資
        if pokemon.id == C.GRIMMSNARL:
            if ec < 2:
                return 9000 - ec * 800  # 0→9000, 1→8200
            return 100  # 2個以上は余剰

        # Spidops: TR EnergyもOK。Rocket Rushのため最低1個は確保
        if pokemon.id == C.SPIDOPS:
            return 600 if ec == 0 else 50

        # Tarountula: Rocket Rush前準備のため1エネ
        if pokemon.id == C.TAROUNTULA:
            return 200 if ec == 0 else 20

        # Impidimp/Morgrem: 進化後に引き継がれるので1エネは有効
        if pokemon.id in (C.IMPIDIMP, C.MORGREM):
            return 150 if ec == 0 else 20

        if pokemon.id == C.MUNKIDORI:
            return 100 if ec == 0 else 10

        return 30

    # ── にげる ────────────────────────────────────────────────
    def _retreat(self) -> float:
        active = self.me.active[0] if self.me.active else None
        if active is None: return -1

        # Impidimp/Morgrem がactive → Grimmsnarl ex をベンチから前へ
        if active.id in (C.IMPIDIMP, C.MORGREM):
            for p in self.me.bench:
                if p and p.id == C.GRIMMSNARL and _ec(p) >= 1:
                    return 9000
            # Spidops があれば繋ぎで前へ
            for p in self.me.bench:
                if p and p.id == C.SPIDOPS and _ec(p) >= 1:
                    return 5000

        # Grimmsnarl はactiveのまま Shadow Bullet 連打
        if active.id == C.GRIMMSNARL:
            return -1

        # Tarountula がactive → 進化済みSpidopsか Grimmsnarl に引く
        if active.id == C.TAROUNTULA:
            for p in self.me.bench:
                if p and p.id == C.GRIMMSNARL and _ec(p) >= 1:
                    return 8000
            for p in self.me.bench:
                if p and p.id == C.SPIDOPS:
                    return 5000

        return -1

    # ── 攻撃 ──────────────────────────────────────────────────
    def _attack(self, opt) -> float:
        active = self.me.active[0] if self.me.active else None
        opp_a  = self.opp.active[0] if self.opp.active else None
        if active is None: return 500

        # ── Grimmsnarl ex: Shadow Bullet (180dmg + ベンチ30) ──────
        if active.id == C.GRIMMSNARL:
            ec = _ec(active)
            if ec < 2: return -1  # 悪×2必要
            dmg = 180
            score = 5000 + dmg
            if opp_a:
                if opp_a.hp <= dmg:
                    score += 5000 + _prize_count(opp_a) * 500  # KO確定
                    my_prizes = len(self.me.prize) if self.me.prize else 0
                    if my_prizes <= _prize_count(opp_a):
                        score += 20000  # 勝ち確KO
            return score

        # ── Spidops: Rocket Rush (TR数×30dmg) ─────────────────────
        if active.id == C.SPIDOPS:
            ec = _ec(active)
            if ec < 1: return -1
            tr_count = self._tr_count_on_field()
            dmg = tr_count * 30
            if dmg <= 0: return -1  # TR系がいないと0dmg = 無意味
            score = 3000 + dmg
            if opp_a and opp_a.hp <= dmg:
                score += 3000 + _prize_count(opp_a) * 300
            return score

        # Tarountula は基本攻撃しない
        if active.id == C.TAROUNTULA:
            return -1

        # Impidimp/Morgrem も攻撃しない（すぐKOされる）
        if active.id in (C.IMPIDIMP, C.MORGREM):
            return -1

        return 500

    # ── カード選択 ────────────────────────────────────────────
    def _card(self, opt) -> float:
        card = _get_card(self.obs, opt.area, opt.index, opt.playerIndex)
        if card is None: return 0
        ctx = self.ctx

        if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            if isinstance(card, Pokemon):
                if card.id == C.IMPIDIMP:   return 10
                if card.id == C.TAROUNTULA: return 7
                if card.id == C.MUNKIDORI:  return 5
            return 1

        if ctx in (SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD):
            if isinstance(card, Pokemon):
                n = self.field_cnt[card.id]
                if card.id == C.IMPIDIMP:   return 200 - 30 * n
                if card.id == C.TAROUNTULA: return 150 - 20 * n
                if card.id == C.MUNKIDORI:  return 100
                if card.id == C.GRIMMSNARL: return 80 + _ec(card) * 20
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
            if card.id == C.GRIMMSNARL: return 600 + _ec(card) * 100
            if card.id == C.SPIDOPS:    return 300 + _ec(card) * 50
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
        if cid == C.GRIMMSNARL:
            s += 500 if self.field_cnt[cid] < 2 else 100
        elif cid == C.IMPIDIMP:
            on_field = self.field_cnt[C.IMPIDIMP] + self._grimmsnarl_count()
            s += 300 if on_field < 2 else (100 if on_field < 4 else -20)
        elif cid == C.MORGREM:
            s += 150 if self.field_cnt[cid] < 1 else -20
        elif cid == C.RARE_CANDY:
            s += 400 if self.field_cnt[C.IMPIDIMP] >= 1 else 200
        elif cid == C.DARK_E:
            s += 80
        elif cid == C.TR_E:
            s += 60
        return s

    def _attach_score_for(self, pokemon) -> float:
        ec = _ec(pokemon)
        if pokemon.id == C.GRIMMSNARL: return 9000 - ec * 800 if ec < 2 else 100
        if pokemon.id == C.SPIDOPS:    return 500 if ec == 0 else 30
        if pokemon.id in (C.IMPIDIMP, C.MORGREM): return 100 if ec == 0 else 10
        if pokemon.id == C.TAROUNTULA: return 150 if ec == 0 else 10
        return 30

    def _discard(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid == C.DARK_E:   return 40
        if cid == C.TR_E:     return 35
        if self.hand_cnt[cid] >= 2: return 60
        if cid in (C.IMPIDIMP, C.MORGREM, C.GRIMMSNARL):
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
        return GrimmsnarlPolicy(obs).choose()
    except Exception:
        try:
            return _legal_dict(obs_dict)
        except Exception:
            return []
