"""
alakazam_combo/main.py — Alakazam Powerful Hand コンボデッキ

構築メモ:
  リーダーボード1位 (Majkel1337, 1339.5pt) が使うアーキの再現。
  Powerful Hand = 手札1枚につきダメカン2個 (=20dmg)。手札10枚→200dmg、超エネ1個で撃てる。

進化安定化の工夫:
  Abra×4 / Kadabra×4 / Alakazam×3 で進化ライン厚め。
  Dawn(1231)でたね/1進化/2進化を一括サーチ（ACE SPECの可能性を考慮して1枚）。
  Psychic Draw特性（Kadabra/Alakazam進化時ドロー）でハンドアドを稼ぐ。

手札を貯める閾値の設計（3状態ポリシー）:
  State 1 [進化]: Abra→Kadabra→Alakazam を最速で立てる。
                  Dawn・Ultra Ball・Poké Pad で進化ラインを揃える。
  State 2 [貯め]: Alakazam がactiveで超エネ1個以上。手札8枚未満。
                  サポートでドロー。グッズは手札に留める（Powerful Hand打点源）。
                  攻撃しない（手札少ないと0〜120dmgの無駄撃ち）。
  State 3 [攻撃]: 手札8枚以上（160dmg以上）、またはKO可能な枚数。
                  Powerful Hand で攻撃。手札が尽きたら State 2 に戻る。

デッキ60枚:
  741×4 Abra / 742×4 Kadabra / 743×3 Alakazam / 140×1 Fezandipiti ex
  1231×1 Dawn(ACE SPEC可能性あり・1枚) / 1227×4 Lillie / 1202×4 Drayton
  1225×3 Hilda / 1224×2 Cheren / 1210×2 Brock's / 1121×4 UltraBall / 1152×2 PokéPad
  13×1 Enriching Energy(ACE SPEC) / 5×25 超エネルギー

注意: Enriching Energy は超エネ要件を満たさないため Alakazam のエネとしては使用不可。
      ただし手札に持つだけで Powerful Hand の打点に加算されるため採用。
"""
from __future__ import annotations
import os, sys
from collections import defaultdict

# ── カードID ──────────────────────────────────────────────────
class C:
    ABRA        = 741   # たね/HP40/超
    KADABRA     = 742   # 1進化/Psychic Draw特性（進化時ドロー）
    ALAKAZAM    = 743   # 2進化/HP140/Powerful Hand（手札×20dmg/超1エネ）
    FEZANDIPITI = 140   # たね/ex/HP210/Flip the Script(KO後3ドロー)/Cruel Arrow(ベンチ100)
    PSYCHIC_E   = 5     # 基本超エネルギー（Powerful Hand の必要エネ）
    ENRICHING_E = 13    # リッチエネルギー (ACE SPEC/無色・手札に持つだけで打点に加算)
    DAWN        = 1231  # Dawn: たね/1進化/2進化を一括サーチ（ACE SPEC可能性あり）
    LILLIE      = 1227  # リーリエの決心
    KAKITSUBA   = 1202  # カキツバタ (Drayton)
    TOKO        = 1225  # トウコ (Hilda)
    CHEREN      = 1224  # チェレン
    TAKESHI     = 1210  # タケシのスカウト (Brock's)
    ULTRA_BALL  = 1121  # ハイパーボール
    POKE_PAD    = 1152  # ポケパッド（非ルールポケ = Abra/Kadabra/Alakazamサーチ）

# Powerful Hand のダメージ閾値（手札枚数）
ATTACK_HAND_THRESHOLD = 8   # 8枚 = 160dmg → 攻撃する最低ライン
HOLD_HAND_THRESHOLD   = 6   # 6枚未満は絶対に攻撃しない

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
class AlakazamPolicy:
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

    def _alakazam_on_field(self) -> bool:
        return self.field_cnt[C.ALAKAZAM] > 0

    def _alakazam_active_ready(self) -> bool:
        """Alakazam が active かつ超エネ1個以上 = Powerful Hand 射出可能状態"""
        active = self.me.active[0] if self.me.active else None
        return (active is not None
                and active.id == C.ALAKAZAM
                and _ec(active) >= 1)

    def _powerful_hand_dmg(self) -> int:
        """現在の手札で Powerful Hand が与えるダメージ"""
        return self._hand_size() * 20

    def _need_alakazam_more(self) -> bool:
        """まだ Alakazam が足りない（field に0体）"""
        return self.field_cnt[C.ALAKAZAM] == 0

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
        n = self.field_cnt[card.id]
        if card.id == C.ABRA:
            return 15000 - 300 * n if self._open_bench() else -1
        if card.id == C.FEZANDIPITI:
            # サブアタッカー: 1体で十分
            return 8000 if (n == 0 and self._open_bench()) else -1
        return 5000 if self._open_bench() else -1

    def _play_trainer(self, card) -> float:
        cid = card.id
        alak_ready = self._alakazam_active_ready()

        # ── State 2/3: Alakazam ready → グッズは手札に留める ──────────
        # グッズ（サーチ・回収系）は Powerful Hand の打点源になるので手札に保持
        if alak_ready and cid in (C.ULTRA_BALL, C.POKE_PAD):
            return -1  # ★手札に留める

        # ── サポーター（1ターン1枚）────────────────────────────────
        if cid == C.DAWN:
            if self.state.supporterPlayed: return -1
            # Dawn: 進化ライン一括サーチ。Alakazamがいない間は最高優先
            return 13000 if self._need_alakazam_more() else 4000

        if cid == C.LILLIE:
            if self.state.supporterPlayed: return -1
            # 手札8枚未満の時に使う（8枚になるまで引く）
            return 12000 if self._hand_size() < 6 else (
                   5000 if self._hand_size() < 8 else 1000)

        if cid == C.KAKITSUBA:
            if self.state.supporterPlayed: return -1
            return 11000 if self._need_alakazam_more() else 3000

        if cid == C.TOKO:
            if self.state.supporterPlayed: return -1
            return 10000 if self._need_alakazam_more() else 2000

        if cid == C.TAKESHI:
            if self.state.supporterPlayed: return -1
            # Abra/Kadabra を bench に引き込む
            abra_on_field = self.field_cnt[C.ABRA] + self.field_cnt[C.KADABRA]
            return 9000 if abra_on_field < 3 else 1500

        if cid == C.CHEREN:
            if self.state.supporterPlayed: return -1
            # 毎ターン3ドロー → 手札を増やすのに有効
            return 8000 if self._hand_size() < 8 else 2000

        # ── グッズ（Setup フェーズのみ積極使用）──────────────────────
        if cid == C.ULTRA_BALL:
            need = (self.field_cnt[C.ABRA] + self.field_cnt[C.KADABRA]
                    + self.field_cnt[C.ALAKAZAM] < 3)
            return 9000 if need and self._hand_size() >= 3 else 1000

        if cid == C.POKE_PAD:
            # 非ルール = Abra/Kadabra/Alakazam をサーチ
            need = self.field_cnt[C.ALAKAZAM] < 1
            return 9500 if need else 2000

        return 5000

    # ── 進化 ──────────────────────────────────────────────────
    def _evolve(self, opt) -> float:
        """★最優先。Psychic Draw も自動発動する。"""
        card = _get_card(self.obs, AreaType.HAND, opt.index, self.my_idx)
        if card is None: return 15000
        if card.id == C.ALAKAZAM:
            return 25000  # Alakazam進化 = 最最優先
        if card.id == C.KADABRA:
            return 20000  # Kadabra進化 = 高優先
        return 15000

    # ── エネルギーアタッチ ────────────────────────────────────
    def _attach(self, opt) -> float:
        pokemon = _get_card(self.obs, opt.inPlayArea, opt.inPlayIndex, self.my_idx)
        if not isinstance(pokemon, Pokemon): return 0
        ec = _ec(pokemon)

        if pokemon.id == C.ALAKAZAM:
            # Powerful Hand に必要なエネは超1個だけ
            if ec < 1:
                return 10000  # 1個目は最高優先
            return -1   # 2個目以降は手札に残して打点に変換

        if pokemon.id in (C.ABRA, C.KADABRA):
            # 攻撃用というよりアクティブにいる間の生存用
            return 200 if ec == 0 else 50

        if pokemon.id == C.FEZANDIPITI:
            # Cruel Arrow のエネ（Colorless or Psychic）
            return 500 if ec == 0 else 50

        return 50

    # ── にげる ────────────────────────────────────────────────
    def _retreat(self) -> float:
        active = self.me.active[0] if self.me.active else None
        if active is None: return -1

        # Abra/Kadabra がactive → Alakazam をベンチから前へ
        if active.id in (C.ABRA, C.KADABRA):
            for p in self.me.bench:
                if p and p.id == C.ALAKAZAM:
                    return 9000
            # Fezandipiti があれば一時的に前へ出してドロー稼ぐ
            for p in self.me.bench:
                if p and p.id == C.FEZANDIPITI and _ec(p) >= 1:
                    return 5000

        # Alakazam は active のまま（攻撃継続）
        if active.id == C.ALAKAZAM:
            return -1

        return -1

    # ── 攻撃 ──────────────────────────────────────────────────
    def _attack(self, opt) -> float:
        active = self.me.active[0] if self.me.active else None
        opp_a  = self.opp.active[0] if self.opp.active else None
        if active is None: return 500

        # ── Powerful Hand (Alakazam) ─────────────────────────
        if active.id == C.ALAKAZAM:
            ec = _ec(active)
            if ec < 1: return -1  # エネなし → 撃てない

            hand_size = self._hand_size()
            dmg = hand_size * 20
            opp_hp = opp_a.hp if opp_a else 200

            # KO できるなら即撃つ
            if dmg >= opp_hp:
                score = 20000 + _prize_count(opp_a) * 500 if opp_a else 20000
                my_prizes = len(self.me.prize) if self.me.prize else 0
                if opp_a and my_prizes <= _prize_count(opp_a):
                    score += 10000  # 勝ち確KO
                return score

            # 手札が十分（160dmg以上）→ 攻撃する価値あり
            if hand_size >= ATTACK_HAND_THRESHOLD:
                return 15000

            # 手札が少ない → 無駄撃ち回避
            if hand_size < HOLD_HAND_THRESHOLD:
                return -1  # 絶対に撃たない (100dmg未満の無駄撃ち)

            # 中間（120-140dmg）: 相手のHPが低ければ撃つ、そうでなければ手札を溜める
            if opp_hp <= dmg + 40:  # あと1〜2枚で KO できる
                return 8000
            return -1  # もう少し手札を溜めてから撃つ

        # ── Fezandipiti ex: Cruel Arrow (ベンチ狙撃100) ─────
        if active.id == C.FEZANDIPITI:
            ec = _ec(active)
            if ec >= 1:
                return 6000  # ベンチへの 100 dmg は常に価値あり
            return -1

        # Abra/Kadabra はなるべく攻撃しない（倒されると3プライズ与えてしまう場合がある）
        if active.id == C.ABRA:
            return -1  # Abra は攻撃手段がほぼない

        return 500

    # ── カード選択 ────────────────────────────────────────────
    def _card(self, opt) -> float:
        card = _get_card(self.obs, opt.area, opt.index, opt.playerIndex)
        if card is None: return 0
        ctx = self.ctx

        if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            # Abra を active に（Alakazam 育成の起点）
            if isinstance(card, Pokemon) and card.id == C.ABRA:        return 10
            if isinstance(card, Pokemon) and card.id == C.FEZANDIPITI: return 5
            return 1

        if ctx in (SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD):
            if isinstance(card, Pokemon):
                n = self.field_cnt[card.id]
                if card.id == C.ABRA:        return 200 - 30 * n
                if card.id == C.FEZANDIPITI: return 120
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
            # 自分側: Alakazam を最優先で active へ
            if card.id == C.ALAKAZAM:    return 600 + _ec(card) * 100
            if card.id == C.FEZANDIPITI: return 200 + _ec(card) * 50
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
        if cid == C.ALAKAZAM:    s += 500 if self.field_cnt[cid] == 0 else 100
        elif cid == C.KADABRA:   s += 350 if self.field_cnt[C.ALAKAZAM] == 0 else 80
        elif cid == C.ABRA:      s += 250 if self.field_cnt[cid] + self.field_cnt[C.KADABRA] < 2 else 60
        elif cid == C.FEZANDIPITI: s += 100 if self.field_cnt[cid] == 0 else -30
        elif cid == C.PSYCHIC_E: s += 80
        elif cid == C.ENRICHING_E: s += 90
        return s

    def _attach_score_for(self, pokemon) -> float:
        ec = _ec(pokemon)
        if pokemon.id == C.ALAKAZAM:    return 10000 if ec < 1 else -1
        if pokemon.id in (C.ABRA, C.KADABRA): return 150 if ec == 0 else 30
        if pokemon.id == C.FEZANDIPITI: return 400 if ec == 0 else 30
        return 30

    def _discard(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid == C.PSYCHIC_E:   return 40
        if cid == C.ENRICHING_E: return 20   # ACE SPEC 1枚 → なるべく捨てない
        if self.hand_cnt[cid] >= 2: return 60
        if cid in (C.ABRA, C.KADABRA, C.ALAKAZAM):
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
        return AlakazamPolicy(obs).choose()
    except Exception:
        try:
            return _legal_dict(obs_dict)
        except Exception:
            return []
