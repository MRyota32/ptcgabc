"""
kanga_wall/main.py — Crushing Hammer版 Kangaskhan + Mega Latias ex 壁

構築メモ:
  ベース: Crushing Hammer版 純Kangaskhan（ラダー452.5・自己ベスト）
  追加: Mega Latias ex(754)×2（草エネ2枚と交換）

闘タイプ判定をどう実装したか:
  _opp_has_fighter(): 相手の場(active+bench)全体を走査し、
  card_table の eType == 6（闘）かどうかをチェック。
  active のみだと後攻1ターン目にLucarioがベンチにいる状態を見逃すため、
  bench も含めた広い判定にした。

Latiasを出す条件（厳格に1つだけ）:
  ① _opp_has_fighter() == True  ← 闘タイプが相手の場にいる
  ② Mega Latias ex(754) がフィールドにいる or 手札にある
  この2条件が揃った時だけ、LatiasをTO_ACTIVEで高スコアを与える。
  ★それ以外（zoroark/TR悪/草/ミラー等）では Latias のスコアを極めて低くし、
    絶対に前に出さない（測定で得意対面が崩れることが実証済み）。

Latias の役割:
  Strafe（無色1エネ, 40dmg + 自分をベンチと入替）で時間を稼ぎ、
  Kangaskhanに交代する繰り返しで、闘相手のKO機会を減らす。

Crushing Hammer:
  null政策のまま「引いたら相手エネに投げる」。
  スコア 8000（コインフリップ系 YES と同等に積極使用）。

デッキ60枚（Crushing Hammer版ベース）:
  756×4 Mega Kangaskhan ex / 754×2 Mega Latias ex
  1120×4 Crushing Hammer / 13×1 Enriching Energy(ACE SPEC)
  1227×4 Lillie / 1202×4 Drayton / 1225×3 Hilda / 1210×2 Brock's / 1224×2 Cheren
  1121×4 UltraBall / 1152×2 PokéPad / 1147×3 JumboIce / 1097×2 NightStr / 1264×2 BattleCage
  18×4 GrowGrass / 1×17 Grass Energy
"""
from __future__ import annotations
import os, sys
from collections import defaultdict

# ── カードID ──────────────────────────────────────────────────
class C:
    KANGASKHAN    = 756   # Mega Kangaskhan ex (たね/HP300/無色)
    LATIAS        = 754   # Mega Latias ex (たね/HP280/弱点なし) ← 闘相手の壁
                          # 技 Strafe: 無色1エネ, 40dmg, 自分をベンチと入替
    GRASS_E       = 1     # 基本草エネルギー
    GROW_E        = 18    # グロウ草エネルギー
    ENRICHING_E   = 13    # リッチエネルギー (ACE SPEC)
    CRUSHING      = 1120  # Crushing Hammer: 相手エネを1枚コインフリップで破壊
    LILLIE        = 1227
    KAKITSUBA     = 1202
    TOKO          = 1225
    TAKESHI       = 1210
    CHEREN        = 1224
    ULTRA_BALL    = 1121
    POKE_PAD      = 1152
    JUMBO_ICE     = 1147
    NIGHT_STR     = 1097
    BATTLE_CAGE   = 1264
    CRUSTLE_345   = 345   # Rock Inn → Kangaskhan/Latias の攻撃も無効の可能性

ENERGY_IDS = {C.GRASS_E, C.GROW_E, C.ENRICHING_E}
FIGHTING_ETYPE = 6  # 闘タイプの eType 値

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

def _pokemon_etype(p) -> int:
    """ポケモンの eType を返す。card_table → pokemon属性の順で参照。"""
    d = _card_table.get(p.id)
    if d is not None:
        return getattr(d, 'eType', 0)
    return getattr(p, 'eType', 0)


# ── ポリシー ──────────────────────────────────────────────────
class KangaWallPolicy:
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
        for c in (self.me.discard or []):
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

    # ★ 闘タイプ判定（唯一の追加分岐の核心）
    def _opp_has_fighter(self) -> bool:
        """相手の場(active+bench)に闘タイプ(eType=6)ポケモンがいるか。
        activeだけでなくbenchも見ることで、後攻1ターン目にLucarioが
        ベンチにいる状態でも即座にLatias壁モードに入れる。"""
        for p in self.opp.active + self.opp.bench:
            if p is not None and _pokemon_etype(p) == FIGHTING_ETYPE:
                return True
        return False

    def _latias_on_field(self) -> bool:
        return self.field_cnt[C.LATIAS] > 0

    def _latias_available(self) -> bool:
        """フィールドまたは手札にLatiasがいるか"""
        return self._latias_on_field() or self.hand_cnt[C.LATIAS] > 0

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
        if card.id == C.KANGASKHAN:
            n = self.field_cnt[C.KANGASKHAN]
            return 15000 - 300 * n if self._open_bench() else -1
        if card.id == C.LATIAS:
            # ベンチに置いておくのは常にOK（出す条件は別途_card/_retreatで制御）
            n = self.field_cnt[C.LATIAS]
            return 8000 - 200 * n if self._open_bench() else -1
        return 5000 if self._open_bench() else -1

    def _play_trainer(self, card) -> float:
        cid = card.id

        # ── サポーター（1ターン1枚）────────────────────────────────
        if cid == C.LILLIE:
            if self.state.supporterPlayed: return -1
            return 12000 if self._hand_size() <= 4 else 2000

        if cid == C.KAKITSUBA:
            if self.state.supporterPlayed: return -1
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

        # ── グッズ ────────────────────────────────────────────────
        if cid == C.CRUSHING:
            # null政策のまま「引いたら即投げる」
            return 8000

        if cid == C.ULTRA_BALL:
            need = self._kang_count() < 2
            return 9000 if need and self._hand_size() >= 3 else 1000

        if cid == C.POKE_PAD:
            need = self._kang_count() < 2
            return 9500 if need else 2000

        if cid == C.JUMBO_ICE:
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
            return 8000

        return 5000

    # ── エネルギーアタッチ ────────────────────────────────────
    def _attach(self, opt) -> float:
        pokemon = _get_card(self.obs, opt.inPlayArea, opt.inPlayIndex, self.my_idx)
        if not isinstance(pokemon, Pokemon): return 0

        if pokemon.id == C.KANGASKHAN:
            ec = _ec(pokemon)
            if ec >= 3: return 100
            card = _get_card(self.obs, AreaType.HAND, opt.index, self.my_idx)
            if card and card.id == C.ENRICHING_E:
                return 12000
            is_active = (opt.inPlayArea == AreaType.ACTIVE)
            base = 9000 - ec * 800
            return base + (300 if is_active else 0)

        if pokemon.id == C.LATIAS:
            ec = _ec(pokemon)
            # Strafe に無色1エネで足りる。闘相手がいる時のみ1個投資。
            if ec == 0 and self._opp_has_fighter():
                return 1000  # Kangaskhanより低いが闘相手なら確保する
            return 30  # 非闘相手 or エネ済み → 最低限

        return 50

    # ── にげる ────────────────────────────────────────────────
    def _retreat(self) -> float:
        active = self.me.active[0] if self.me.active else None
        if active is None: return -1

        # ── Kangaskhan が active の場合 ─────────────────────
        if active.id == C.KANGASKHAN:
            # 闘相手 + Latiasがベンチにいる → Latias壁モードへ切り替え
            if self._opp_has_fighter() and self.field_cnt[C.LATIAS] > 0:
                return 9000  # ★唯一の追加分岐: Latiasに引く
            return -1  # 非闘相手 → 常に前でKangaskhanが殴る

        # ── Latias が active の場合 ──────────────────────────
        if active.id == C.LATIAS:
            # 非闘相手になった → 即座にKangaskhanに引き戻す
            if not self._opp_has_fighter():
                for p in self.me.bench:
                    if p and p.id == C.KANGASKHAN:
                        return 9000  # Kangaskhanに戻る
            # まだ闘相手 → Latiasがアクティブのまま壁継続
            # (Strafe後にまた前に出ることになるので許容)
            return -1

        return -1

    # ── 攻撃 ──────────────────────────────────────────────────
    def _attack(self, opt) -> float:
        active = self.me.active[0] if self.me.active else None
        opp_a  = self.opp.active[0] if self.opp.active else None
        if active is None: return 500

        # ── Kangaskhan: Rapid-Fire Combo ─────────────────────
        if active.id == C.KANGASKHAN:
            ec = _ec(active)
            if ec < 3: return -1
            if self._opp_active_is_crustle(): return -1
            dmg = 200
            score = 5000 + min(dmg, 300)
            if opp_a and opp_a.hp <= dmg:
                score += 3000 + _prize_count(opp_a) * 500
                my_prizes = len(self.me.prize) if self.me.prize else 0
                if my_prizes <= _prize_count(opp_a):
                    score += 20000
            return score

        # ── Latias: Strafe（無色1エネ, 40dmg, ベンチと入替）────
        if active.id == C.LATIAS:
            ec = _ec(active)
            if ec < 1: return -1  # エネなし → 攻撃できない
            # Strafe後にベンチと入替 → Kangaskhanを呼び戻せる
            dmg = 40
            score = 3000 + dmg
            if opp_a and opp_a.hp <= dmg:
                score += 2000
            return score

        return 500

    # ── カード選択 ────────────────────────────────────────────
    def _card(self, opt) -> float:
        card = _get_card(self.obs, opt.area, opt.index, opt.playerIndex)
        if card is None: return 0
        ctx = self.ctx

        if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            # セットアップ: KangaskhanをACTIVEに。LatiasはACTIVEスターターにしない
            if isinstance(card, Pokemon):
                if card.id == C.KANGASKHAN: return 10
                if card.id == C.LATIAS:     return 2  # 低め: Kangaskhanが先
            return 1

        if ctx in (SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD):
            if isinstance(card, Pokemon):
                if card.id == C.KANGASKHAN:
                    n = self.field_cnt[C.KANGASKHAN]
                    return 200 - 30 * n
                if card.id == C.LATIAS:
                    return 100  # ベンチ置きはOK（但しKangaskhanより低い）
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

            # ★ 自分側: これが出し分けの核心
            if card.id == C.LATIAS:
                # 闘相手がいる時だけLatiasを前に出す
                if self._opp_has_fighter():
                    return 700 + _ec(card) * 50  # Kangaskhanより高い状況で使う
                else:
                    return 1  # 非闘相手 → 絶対に前に出さない
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
        elif cid == C.LATIAS:
            s += 150 if self.field_cnt[cid] == 0 else 20
        elif cid in ENERGY_IDS:
            s += 80
        elif cid == C.NIGHT_STR:
            s += 150 if self.disc_cnt.get(C.KANGASKHAN, 0) > 0 else 40
        elif cid == C.JUMBO_ICE:
            active = self.me.active[0] if self.me.active else None
            s += 200 if (active and _ec(active) >= 3) else 60
        return s

    def _attach_score_for(self, pokemon) -> float:
        if pokemon.id == C.KANGASKHAN:
            ec = _ec(pokemon)
            return 9000 - ec * 800 if ec < 3 else 100
        if pokemon.id == C.LATIAS:
            ec = _ec(pokemon)
            return 800 if (ec == 0 and self._opp_has_fighter()) else 20
        return 30

    def _discard(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid in (C.GRASS_E, C.GROW_E): return 40
        if cid == C.ENRICHING_E:          return 20
        if self.hand_cnt[cid] >= 2:       return 60
        if cid == C.KANGASKHAN:
            return 5 if self.field_cnt[cid] > 0 else -100
        if cid == C.LATIAS:
            return 5 if self.field_cnt[cid] > 0 else -50
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
        return KangaWallPolicy(obs).choose()
    except Exception:
        try:
            return _legal_dict(obs_dict)
        except Exception:
            return []
