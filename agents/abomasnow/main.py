"""
abomasnow/main.py — Mega Abomasnow ex デッキ エージェント

構築メモ:
  ラダー上位陣(485-493pt)の主力。純Kangaskhanキラー(66%)。
  「作り込むほど強くなる」初めての候補。

進化安定化の工夫:
  Snover(418)×4 + Mega Abomasnow ex(723)×4 で進化ラインを厚く。
  Abomasnow(419)×2 は非exサブアタッカー兼進化保険（vs crustle Rock Inn対策）。
  Poffin(1086)×4 でSnoverを2体展開 → 即座にMega進化できる状態を作る。
  Poké Pad(1152)で非ルールSnover/Abomasnowをサーチ。
  Ultra Ball(1121)でMega Abomasnow exもサーチ可能。

Frost Barrier vs Hammer-lanche の使い分け:
  Frost Barrier (氷×3, 200dmg + 次ターン30軽減):
    → エネ3個以上の基本攻撃。安定して殴りながら耐える。
    → 常にこちらを優先。
  Hammer-lanche (氷×2, 山札トップ6をトラッシュ・基本水エネ1枚につき100dmg):
    → エネ2個から撃てる早撃ち or 上振れ技。
    → エネ2個しかない時（Frost Barrierを撃てない）は積極使用。
    → エネ3個ある時はFrost Barrierを優先するが、
       相手HP>=300かつ山札に水エネが多く残っていそうな序盤は選択肢に入れる。

水エネ枚数の設計:
  基本水エネ(id=3)×24枚: 氷タイプ供給 + Hammer-lanche火力源を兼ねる。
  多いほどHammer-lancheの期待値が上がるが、24枚は安定と火力のバランス点。
  山札60枚中24枚 = 40%。Hammer-lanche6枚中期待値2.4枚 = 240dmg期待値。

vs crustle(Rock Inn)対策:
  Mega Abomasnow ex はexポケモンのため Rock Inn(345特性)で攻撃無効化される。
  相手activeが crustle(345) の時は非exのAbomasnow(419)に引いて攻撃。

デッキ60枚:
  418×4 Snover / 723×4 Mega Abomasnow ex / 419×2 Abomasnow
  1086×4 Poffin / 1121×4 UltraBall / 1152×2 PokéPad
  1227×4 Lillie / 1202×4 Drayton / 1225×3 Hilda
  1210×2 Brock's / 1224×2 Cheren
  13×1 Enriching Energy(ACE SPEC) / 3×24 基本水エネ
"""
from __future__ import annotations
import os, sys
from collections import defaultdict

# ── カードID ──────────────────────────────────────────────────
class C:
    SNOVER      = 418   # たね/HP60/氷(eType=3)
    MEGA_ABOMA  = 723   # Mega Abomasnow ex/HP350/氷/megaEx
                        # Hammer-lanche: 氷×2 / Frost Barrier: 氷×3(200dmg+30軽減)
    ABOMASNOW   = 419   # 非ex/Stage1/HP150: 非exサブアタッカー
    WATER_E     = 3     # 基本水エネルギー(氷タイプ供給+Hammer-lanche打点源)
    ENRICHING_E = 13    # リッチエネルギー(ACE SPEC/無色/アタッチ時4ドロー)
    POFFIN      = 1086  # Buddy-Buddy Poffin: 山札からたね2体をベンチへ
    ULTRA_BALL  = 1121  # ハイパーボール
    POKE_PAD    = 1152  # ポケパッド(非ルールポケモンサーチ)
    LILLIE      = 1227  # リーリエの決心
    KAKITSUBA   = 1202  # カキツバタ(Drayton)
    TOKO        = 1225  # トウコ(Hilda)
    TAKESHI     = 1210  # タケシのスカウト(Brock's)
    CHEREN      = 1224  # チェレン
    CRUSTLE     = 345   # イワパレス(Rock Inn: exからダメージを受けない)

# 初期水エネ枚数(Hammer-lanche期待値計算用)
INITIAL_WATER_COUNT = 24

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
class AbomasnowPolicy:
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

    def _mega_count(self):
        return self.field_cnt[C.MEGA_ABOMA]

    def _mega_ready(self):
        """フィールド上でエネ3個以上のMega Abomasnow exが存在するか"""
        return any(p and p.id == C.MEGA_ABOMA and _ec(p) >= 3
                   for p in self.me.active + self.me.bench)

    def _opp_active_is_crustle(self) -> bool:
        opp_a = self.opp.active[0] if self.opp.active else None
        return opp_a is not None and opp_a.id == C.CRUSTLE

    def _hammer_lanche_expected_dmg(self) -> float:
        """Hammer-lanche の期待ダメージ推定（山札残水エネ × 100 / 6枚中）"""
        water_in_field = sum(
            _ec(p) for p in self.me.active + self.me.bench
            if p and p.id in (C.SNOVER, C.MEGA_ABOMA, C.ABOMASNOW)
        )
        water_discarded = self.disc_cnt[C.WATER_E]
        water_in_hand   = self.hand_cnt[C.WATER_E]
        water_remaining = max(0, INITIAL_WATER_COUNT
                              - water_in_field - water_discarded - water_in_hand)
        cards_total = 60
        cards_seen  = (water_in_field + water_discarded + water_in_hand
                       + sum(self.hand_cnt.values())
                       + sum(self.disc_cnt.values()))
        deck_remaining = max(1, cards_total - cards_seen)
        # 山札トップ6枚の中に水エネが何枚入るかの期待値
        reveal = min(6, deck_remaining)
        rate = water_remaining / deck_remaining
        return rate * reveal * 100

    def _get_attack_idx(self, opt) -> int:
        """このATTACKオプションが何番目の攻撃か（0=Hammer-lanche, 1=Frost Barrier）"""
        atk_opts = [o for o in self.select.option if o.type == OptionType.ATTACK]
        for i, o in enumerate(atk_opts):
            if o is opt:
                return i
        return 0

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
        if card.id == C.SNOVER:
            n = self.field_cnt[C.SNOVER]
            return 15000 - 200 * n if self._open_bench() else -1
        if card.id == C.ABOMASNOW:
            # 非exサブ: vs crustle用。1体で十分
            return 8000 if (self.field_cnt[C.ABOMASNOW] == 0 and self._open_bench()) else -1
        return 5000 if self._open_bench() else -1

    def _play_trainer(self, card) -> float:
        cid = card.id
        need_evolution = self._mega_count() < 3

        # ── サポーター（1ターン1枚）────────────────────────────────
        if cid == C.LILLIE:
            if self.state.supporterPlayed: return -1
            return 12000 if self._hand_size() <= 4 else 2000

        if cid == C.KAKITSUBA:
            if self.state.supporterPlayed: return -1
            return 11000 if need_evolution else 3000

        if cid == C.TOKO:
            if self.state.supporterPlayed: return -1
            return 10000 if need_evolution else 2000

        if cid == C.TAKESHI:
            if self.state.supporterPlayed: return -1
            snover_total = self.field_cnt[C.SNOVER] + self._mega_count()
            return 9000 if snover_total < 3 else 1500

        if cid == C.CHEREN:
            if self.state.supporterPlayed: return -1
            return 8000 if self._hand_size() <= 3 else 1000

        # ── グッズ ────────────────────────────────────────────────
        if cid == C.POFFIN:
            need = self.field_cnt[C.SNOVER] < 2
            return 13000 if need and self._open_bench() else 1000

        if cid == C.POKE_PAD:
            # 非ルールポケモン(Snover/Abomasnow)をサーチ
            need = self.field_cnt[C.SNOVER] < 2 or self.field_cnt[C.ABOMASNOW] < 1
            return 9500 if need else 1500

        if cid == C.ULTRA_BALL:
            need = self._mega_count() < 2 or self.field_cnt[C.SNOVER] < 2
            return 8000 if need and self._hand_size() >= 3 else 500

        return 5000

    def _hand_size(self): return sum(self.hand_cnt.values())

    # ── 進化 ──────────────────────────────────────────────────
    def _evolve(self, opt) -> float:
        """進化を最優先。Mega Abomasnow ex > Abomasnow。"""
        card = _get_card(self.obs, AreaType.HAND, opt.index, self.my_idx)
        if card is None: return 15000
        if card.id == C.MEGA_ABOMA: return 25000   # ★最高優先
        if card.id == C.ABOMASNOW:  return 20000   # 非exサブも進化させる
        return 15000

    # ── エネルギーアタッチ ────────────────────────────────────
    def _attach(self, opt) -> float:
        pokemon = _get_card(self.obs, opt.inPlayArea, opt.inPlayIndex, self.my_idx)
        if not isinstance(pokemon, Pokemon): return 0
        ec = _ec(pokemon)

        if pokemon.id == C.MEGA_ABOMA:
            # Frost Barrier に必要な氷×3。0→9000, 1→8200, 2→7400, 3+→100
            if ec < 3:
                return 9000 - ec * 800
            return 100

        if pokemon.id == C.ABOMASNOW:
            # 非exサブ: 1エネあれば攻撃できる想定
            return 500 if ec == 0 else 50

        if pokemon.id == C.SNOVER:
            # たねにEnriching Energyをアタッチして早期ドロー加速する価値はあるが
            # 水エネのほうが後続の攻撃につながるので低め
            return 100 if ec == 0 else 20

        return 30

    # ── にげる ────────────────────────────────────────────────
    def _retreat(self) -> float:
        active = self.me.active[0] if self.me.active else None
        if active is None: return -1

        # SnoverがactiveならMega Abomasnow exと交代
        if active.id == C.SNOVER:
            for p in self.me.bench:
                if p and p.id == C.MEGA_ABOMA and _ec(p) >= 1:
                    return 9000
            # AbomasnowがいればそちらでもOK
            for p in self.me.bench:
                if p and p.id == C.ABOMASNOW and _ec(p) >= 1:
                    return 5000

        # Mega Abomasnow ex が active で相手が crustle → 非exのAbomasnowに引く
        if active.id == C.MEGA_ABOMA and self._opp_active_is_crustle():
            for p in self.me.bench:
                if p and p.id == C.ABOMASNOW:
                    return 8000  # Rock Inn を回避するために引く

        # Mega Abomasnow ex はFrost Barrier連打が基本 → activeのまま
        if active.id == C.MEGA_ABOMA:
            return -1

        return -1

    # ── 攻撃 ──────────────────────────────────────────────────
    def _attack(self, opt) -> float:
        active = self.me.active[0] if self.me.active else None
        opp_a  = self.opp.active[0] if self.opp.active else None
        if active is None: return 500

        # ── Mega Abomasnow ex ─────────────────────────────────
        if active.id == C.MEGA_ABOMA:
            ec = _ec(active)
            opp_hp = opp_a.hp if opp_a else 200

            # Rock Inn: exポケモンは crustle に攻撃できない
            if self._opp_active_is_crustle():
                return -1

            # 攻撃インデックスで Hammer-lanche(0) vs Frost Barrier(1) を区別
            atk_idx = self._get_attack_idx(opt)

            if atk_idx == 0:
                # ── Hammer-lanche (氷×2) ──────────────────────
                if ec < 2: return -1
                expected_dmg = self._hammer_lanche_expected_dmg()

                # KO 可能ならほぼ必ず撃つ価値あり
                if expected_dmg >= opp_hp:
                    score = 18000 + _prize_count(opp_a) * 500 if opp_a else 18000
                    return score

                # Frost Barrier(ec=3)が使えない時は最善手として使う
                if ec < 3:
                    score = 5000 + min(expected_dmg, 300)
                    if opp_a and opp_hp <= expected_dmg + 60:
                        score += 2000  # 近いうちにKO見込める
                    return score

                # ec >= 3 の時はFrost Barrier優先 → Hammer-lancheを低めに設定
                # ただし相手HPが高くHammer-lancheの期待値が高ければ選択肢
                if opp_hp >= 300 and expected_dmg >= 250:
                    return 4000 + expected_dmg  # Frost Barrier(5200)に負けうる設定
                return 1000  # ec>=3 の時は基本Frost Barrierを選ぶ

            else:
                # ── Frost Barrier (氷×3) → 200dmg + 次ターン30軽減 ──
                if ec < 3: return -1
                dmg = 200
                score = 5000 + dmg
                if opp_a:
                    if opp_hp <= dmg:
                        score += 5000 + _prize_count(opp_a) * 500  # KO確定
                        my_prizes = len(self.me.prize) if self.me.prize else 0
                        if my_prizes <= _prize_count(opp_a):
                            score += 20000  # 勝ち確KO
                return score

        # ── 非ex Abomasnow (サブアタッカー) ─────────────────────
        if active.id == C.ABOMASNOW:
            ec = _ec(active)
            if ec < 1: return -1
            # Rock Inn を持つ crustle 相手でも攻撃可能（非exなのでRock Inn無効）
            score = 4000
            if opp_a and opp_a.hp <= 150:  # Abomasnowの想定打点以内ならKO狙い
                score += 3000
            return score

        # Snover は基本攻撃しない（倒されると不利なので）
        if active.id == C.SNOVER:
            return -1

        return 500

    # ── カード選択 ────────────────────────────────────────────
    def _card(self, opt) -> float:
        card = _get_card(self.obs, opt.area, opt.index, opt.playerIndex)
        if card is None: return 0
        ctx = self.ctx

        if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            if isinstance(card, Pokemon):
                if card.id == C.SNOVER:      return 10
                if card.id == C.ABOMASNOW:   return 5
            return 1

        if ctx in (SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD):
            if isinstance(card, Pokemon):
                n = self.field_cnt[card.id]
                if card.id == C.SNOVER:      return 200 - 30 * n
                if card.id == C.ABOMASNOW:   return 120
                if card.id == C.MEGA_ABOMA:  return 100
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
            # 自分側: Mega Abomasnow ex → Abomasnow の順で前へ
            if card.id == C.MEGA_ABOMA:
                # crustle 相手なら前に出しても無意味
                if self._opp_active_is_crustle(): return 50
                return 600 + _ec(card) * 100
            if card.id == C.ABOMASNOW:
                # crustle 相手なら積極的に前へ
                if self._opp_active_is_crustle(): return 800
                return 200 + _ec(card) * 50
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
        if cid == C.MEGA_ABOMA:
            s += 500 if self.field_cnt[cid] < 2 else 100
        elif cid == C.SNOVER:
            on_field = self.field_cnt[C.SNOVER] + self._mega_count()
            s += 300 if on_field < 2 else (100 if on_field < 4 else -20)
        elif cid == C.ABOMASNOW:
            s += 200 if self.field_cnt[cid] == 0 else -30
        elif cid == C.WATER_E:
            s += 80
        elif cid == C.ENRICHING_E:
            s += 90
        return s

    def _attach_score_for(self, pokemon) -> float:
        ec = _ec(pokemon)
        if pokemon.id == C.MEGA_ABOMA: return 9000 - ec * 800 if ec < 3 else 100
        if pokemon.id == C.ABOMASNOW:  return 400 if ec == 0 else 30
        if pokemon.id == C.SNOVER:     return 80 if ec == 0 else 10
        return 30

    def _discard(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid == C.WATER_E:     return 40
        if cid == C.ENRICHING_E: return 20   # ACE SPEC 1枚 → なるべく捨てない
        if self.hand_cnt[cid] >= 2: return 60
        if cid in (C.SNOVER, C.MEGA_ABOMA, C.ABOMASNOW):
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
        return AbomasnowPolicy(obs).choose()
    except Exception:
        try:
            return _legal_dict(obs_dict)
        except Exception:
            return []
