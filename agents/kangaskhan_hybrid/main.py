"""
kangaskhan_hybrid — Mega Kangaskhan ex ＋ Crustle ハイブリッド

目的：Final Submission 主力候補。上位2位プレイヤーの構成を再現。

── なぜこのデッキが強いか ──────────────────────────────────────────────────
Mega Kangaskhan ex (756)：
  ・HP300 / basic（たね＝進化不要）/ eType=0（無色）
  ・マシンガンコンボ：●●●, 200dmg + ウラが出るまで表×50追加 → 期待値≈250
  ・特性「おつかいダッシュ」：バトル場で毎ターン2ドロー → 自力でハンドアド確保
  ・Stage2セットアップ事故 0%。タイプ不整合 0%（全エネ満たせる）。

Crustle (345)：
  ・特性「しんぴのいしやど」：相手のPokémon exからのワザダメを全無効
  ・Kangaskhan ex vs Crustle = 0ダメ → 対Kangaskhan戦の保険として機能

── 2ロール切り替え（シンプル2分岐） ───────────────────────────────────────
相手にex/megaExが場にいる → Crustle を前に出して完封（壁モード）
それ以外                 → Kangaskhan を前に出してマシンガンコンボ（攻撃モード）

── エネルギー設計 ─────────────────────────────────────────────────────────
草エネ(1)×14 + Enriching(13)×4 + Mist(11)×4 + Spiky(14)×2 + Grow草(18)×4 = 28枚
・Kangaskhan ●●● = 草/特殊全て充足可
・Enriching = 手札からアタッチ時に4ドロー → attach = 実質ドロー
・Mist = ワザ効果(特殊状態等)を無効化 → Kangaskhan の生存率向上
・Spiky = 攻撃してきた相手に20ダメ
・Grow草 = Dwebble/Crustle の HP+20（HP70→90/HP150→170）

── Dwebble のロール ───────────────────────────────────────────────────────
・Dwebble(344)のワザ「かくせい」(●)= 1エネでCrustleを山札から即進化
  → Poffin/Bug Catching Set で高速展開 → 壁を素早く準備できる

── 採用しなかったカード ───────────────────────────────────────────────────
・Grow草エネ(18)はDwebble/Crustleには+20HP有効だがKangaskhan(無色型)には無効
・Drayton(1238)は闘エネ回収専用なので不採用
・Levincia(1254)は雷エネ専用なので不採用
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

try:
    from cg.api import (
        AreaType, Card, CardType, EnergyType, LogType, Observation,
        OptionType, Pokemon, SelectContext, SelectType,
        all_card_data, to_observation_class,
    )
    _API_AVAILABLE = True
except Exception:
    _API_AVAILABLE = False

_SEARCH_AVAILABLE = False
try:
    from cg.api import (
        search_begin as _search_begin, search_step as _search_step,
        search_end as _search_end, search_release as _search_release,
    )
    _SEARCH_AVAILABLE = True
except Exception:
    pass


# ── Card IDs ──────────────────────────────────────────────────────────────────
class C:
    KANGASKHAN      = 756   # Mega Kangaskhan ex HP300 / basic / 無色
    DWEBBLE         = 344   # イシズマイ HP70 / 草型 / かくせい(●)で即Crustle進化
    CRUSTLE         = 345   # イワパレス HP150 / 壁 / ex攻撃完全無効
    GRASS_ENERGY    = 1     # 基本草エネ（無制限）
    ENRICHING_ENERGY= 13    # リッチエネルギー: 無色1個 + 手札アタッチ時4ドロー
    MIST_ENERGY     = 11    # ミストエネルギー: 無色1個 + ワザ効果無効
    SPIKY_ENERGY    = 14    # スパイクエネルギー: 無色1個 + 攻撃者に20ダメ
    GROW_ENERGY     = 18    # グロウ草エネ: 草1個 + 草ポケHP+20（Dwebble/Crustle用）
    LILLIE_DET      = 1227  # リーリエの決心: シャッフルドロー6/8
    POFFIN          = 1086  # なかよしポフィン: HP70以下たね2枚ベンチへ（Dwebble対応）
    BUG_CATCHING    = 1094  # むしとりセット: 上7枚から草ポケ+草エネ
    CYAN            = 1205  # シアノ: ex ポケモン3枚サーチ（Kangaskhan検索）
    JUMBO_ICE_CREAM = 1147  # ジャンボアイス: 3エネ以上のバトルポケを80回復
    NIGHT_STRETCHER = 1097  # 夜のタンカ: トラッシュ回収
    BATTLE_CAGE     = 1264  # バトルコロシアム: ベンチへのダメカン不可
    POKE_PAD        = 1152  # ポケパッド: 非ルールポケモン（Dwebble/Crustle）サーチ


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
            case AreaType.DECK:    return _safe_get(getattr(obs.select, "deck", None), index)
            case AreaType.HAND:    return _safe_get(player.hand, index)
            case AreaType.DISCARD: return _safe_get(player.discard, index)
            case AreaType.ACTIVE:  return _safe_get(player.active, index)
            case AreaType.BENCH:   return _safe_get(player.bench, index)
            case AreaType.PRIZE:   return _safe_get(player.prize, index)
            case AreaType.STADIUM: return _safe_get(obs.current.stadium, index)
            case AreaType.LOOKING: return _safe_get(obs.current.looking, index)
            case _:                return None
    except Exception:
        return None


def prize_count(pokemon) -> int:
    data = card_table.get(pokemon.id)
    if data is None: return 1
    return 3 if data.megaEx else 2 if data.ex else 1


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

    PAD = C.GRASS_ENERGY
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

    filler = ([opp_basic] if opp_basic else []) + opp_vis*2 + [C.GRASS_ENERGY]*60
    opp_deck  = (filler+[C.GRASS_ENERGY]*60)[:opp.deckCount]
    opp_prize = (filler+[C.GRASS_ENERGY]*10)[:len(opp.prize)]
    opp_hand  = (filler+[C.GRASS_ENERGY]*10)[:opp.handCount]
    opp_active = []
    if opp.active and opp.active[0] is None:
        opp_active = [opp_basic] if opp_basic else []

    return your_deck, your_prize, opp_deck, opp_prize, opp_hand, opp_active


def _evaluate_obs(obs):
    """1-ply search 評価関数。Kangaskhan の攻撃準備・Crustle の壁状況を評価。"""
    if obs is None or obs.current is None: return 0
    state  = obs.current
    my_idx = state.yourIndex
    op_idx = 1 - my_idx
    me  = state.players[my_idx]
    opp = state.players[op_idx]
    if state.result == my_idx: return 200_000
    if state.result == op_idx: return -200_000

    score = (len(opp.prize) - len(me.prize)) * 8_000

    opp_has_ex = any(p and card_table.get(p.id) and
                     (card_table[p.id].ex or card_table[p.id].megaEx)
                     for p in opp.active + opp.bench if p)

    for p in me.active + me.bench:
        if p is None: continue
        ec = len(p.energies)
        if p.id == C.KANGASKHAN:
            score += 5_000 + ec * 700
            if ec >= 3: score += 2_000  # マシンガンコンボ可能
            # 壁が必要な場面でKangaskhanがアクティブは減点
            if opp_has_ex and p in me.active:
                score -= 3_000
        elif p.id == C.CRUSTLE:
            score += 2_500
            # 壁が必要な場面でCrustleがアクティブは加点
            if opp_has_ex and p in me.active:
                score += 4_000
        elif p.id == C.DWEBBLE:
            score += 800

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
        policy = KangaskhanPolicy(obs)
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

    p0 = KangaskhanPolicy(obs)
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


# ── Kangaskhan Hybrid policy ──────────────────────────────────────────────────
class KangaskhanPolicy:
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

    def _kangaskhan_count(self):
        return sum(1 for p in self._my_board() if p and p.id == C.KANGASKHAN)

    def _crustle_count(self):
        return sum(1 for p in self._my_board() if p and p.id == C.CRUSTLE)

    def _dwebble_count(self):
        return sum(1 for p in self._my_board() if p and p.id == C.DWEBBLE)

    def _opp_has_ex(self) -> bool:
        """相手の場(active+bench)にex/megaExポケモンがいるか。壁モード切替判定。"""
        for p in self._opp_board():
            if p is None: continue
            d = card_table.get(p.id)
            if d and (d.ex or d.megaEx): return True
        return False

    def _want_crustle_up(self) -> bool:
        """Crustleを前に出したいか。exが場にいる、かつCrustleが場にいる。"""
        return self._opp_has_ex() and self._crustle_count() > 0

    def _active_hp_ratio(self):
        try:
            a = self.me.active[0]
            if a is None or a.maxHp == 0: return 1.0
            return a.hp / a.maxHp
        except: return 1.0

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
        if t == OptionType.YES:
            # Run Errand（2ドロー）・コインフリップ・壁切替はすべて YES
            return 5000
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
        if card.id == C.KANGASKHAN:
            # Kangaskhan はたね→直接ベンチへ
            return 22000 - 200 * n if self._open_bench() else -1
        if card.id == C.DWEBBLE:
            # 壁準備。Crustle がいない間は優先
            if self._crustle_count() == 0:
                return 20000 - 300 * n if self._open_bench() else -1
            return 10000 - 300 * n if self._open_bench() else -1
        return 15000 - 200 * n

    def _score_play_trainer(self, card) -> float:
        cid = card.id
        want_crustle = self._want_crustle_up()

        # ── サポート ─────────────────────────────────────────────────────────
        if cid == C.LILLIE_DET:
            if self.state.supporterPlayed or self._low_deck(): return -1
            return 12000 if self._hand_size() <= 4 else 3500

        if cid == C.CYAN:
            if self.state.supporterPlayed: return -1
            # Kangaskhan ex をサーチ
            need = self._kangaskhan_count() < 2
            return 11000 if need else 4000

        # ── グッズ ─────────────────────────────────────────────────────────
        if cid == C.POFFIN:
            # Dwebble(HP70)をベンチへ。Crustle がいないなら高優先
            need = self._dwebble_count() + self._crustle_count() < 2
            return 13000 if (need and self._open_bench()) else 3000

        if cid == C.BUG_CATCHING:
            # 草ポケ(Dwebble)+草エネを山札上7枚から確保
            need_mon = self._dwebble_count() + self._crustle_count() < 2
            return 11000 if need_mon else 5000

        if cid == C.JUMBO_ICE_CREAM:
            # バトルポケに3エネ以上ついていれば80回復
            active = self.me.active[0] if self.me.active else None
            if active and self._energy_count(active) >= 3:
                # HP が最大でないなら使う価値あり
                if self._active_hp_ratio() < 1.0:
                    return 10000
                # HP 満タンでも Kangaskhan は 300 → 余裕があれば温存
                if active.id == C.KANGASKHAN and self._active_hp_ratio() < 0.85:
                    return 8000
            return 500  # エネ不足 or HP 満タン → 後回し

        if cid == C.BATTLE_CAGE:
            if self.state.stadiumPlayed: return -1
            return 8000  # ベンチ保護は早期設置

        if cid == C.POKE_PAD:
            # Dwebble/Crustle をサーチ（非ルールポケモン）
            need = self._crustle_count() == 0 and self._dwebble_count() < 2
            return 9000 if need else 3000

        if cid == C.NIGHT_STRETCHER:
            has_kang   = self.disc_counts.get(C.KANGASKHAN, 0) > 0
            has_crustle= self.disc_counts.get(C.CRUSTLE, 0) > 0
            has_dwebble= self.disc_counts.get(C.DWEBBLE, 0) > 0
            if has_kang:    return 9500
            if has_crustle: return 7000
            if has_dwebble: return 5000
            return 300

        return 7000

    # ── Evolve ────────────────────────────────────────────────────────────────
    def _score_evolve(self, option) -> float:
        target = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon): return 0
        card = get_card(self.obs, AreaType.HAND, option.index, self.my_index)
        if card is None: return 0

        if card.id == C.CRUSTLE:
            # 壁が必要なら最優先進化
            bonus = 5000 if self._opp_has_ex() else 0
            return 25000 + self._energy_count(target) * 50 + bonus
        return 18000

    # ── Attach ────────────────────────────────────────────────────────────────
    def _score_attach(self, option) -> float:
        pokemon = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(pokemon, Pokemon): return 0

        # エネルギーカード自体のIDを特定
        card = get_card(self.obs, AreaType.HAND, option.index, self.my_index)
        energy_id = card.id if card else None

        return self._energy_score(pokemon, option.inPlayArea == AreaType.ACTIVE, energy_id)

    def _energy_score(self, pokemon, is_active, energy_id=None) -> float:
        ec = self._energy_count(pokemon)

        if pokemon.id == C.KANGASKHAN:
            # マシンガンコンボ要件: ●●● = 3エネ
            if ec >= 3:
                base = 200  # 3エネ到達後は低優先
            else:
                # Enriching を最優先（手札からアタッチ → 4ドロー）
                if energy_id == C.ENRICHING_ENERGY:
                    base = 12000
                else:
                    base = 9000
        elif pokemon.id == C.DWEBBLE:
            # かくせい(●)1エネで進化できる → 最低限のエネ
            if energy_id == C.GROW_ENERGY:
                base = 5000 if ec == 0 else 100   # HP+20 付与
            else:
                base = 3000 if ec == 0 else 50
        elif pokemon.id == C.CRUSTLE:
            # 壁として基本攻撃しないが、Grow草でHP+20は有益
            if energy_id == C.GROW_ENERGY:
                base = 4000 if ec < 2 else 200
            else:
                base = 1000 if ec < 2 else 100
        else:
            base = 50
        return base + (300 if is_active else 0)

    # ── Retreat ───────────────────────────────────────────────────────────────
    def _score_retreat(self) -> float:
        """
        2ロール切り替え：
        ・壁モード（相手がex）: Kangaskhanを下げてCrustleを前へ
        ・攻撃モード（非ex）: Crustleを下げてKangaskhanを前へ
        """
        active = self.me.active[0] if self.me.active else None
        if active is None: return -1
        opp_ex = self._opp_has_ex()

        # 壁モード: Kangaskhan → Crustle/Dwebble に交代
        if active.id == C.KANGASKHAN and opp_ex:
            for p in self.me.bench:
                if p and p.id == C.CRUSTLE:
                    return 30000
                if p and p.id == C.DWEBBLE:
                    return 25000
            # Crustle/Dwebble がベンチにいない → 仕方なく居続ける
            return -1

        # 攻撃モード: Crustle/Dwebble → Kangaskhan に交代
        if active.id in (C.CRUSTLE, C.DWEBBLE) and not opp_ex:
            for p in self.me.bench:
                if p and p.id == C.KANGASKHAN:
                    return 28000
            return -1

        # Kangaskhan が攻撃モードなら居続ける
        if active.id == C.KANGASKHAN and not opp_ex:
            return -1

        # Crustle が壁モードなら居続ける
        if active.id == C.CRUSTLE and opp_ex:
            return -1

        return -1

    # ── Attack ────────────────────────────────────────────────────────────────
    def _score_attack(self, option) -> float:
        active = self.me.active[0] if self.me.active else None
        opp_a  = self.opponent.active[0] if self.opponent.active else None
        if active is None: return 500
        opp_ex = self._opp_has_ex()

        # ── Mega Kangaskhan ex の攻撃（マシンガンコンボ: ●●●/200+コイン×50）──
        if active.id == C.KANGASKHAN:
            ec = self._energy_count(active)
            if ec < 3:
                return -1  # エネ不足: 攻撃しない
            if opp_ex:
                # 壁モードなのにKangaskhanが攻撃するのは不要（Crustleが欲しい）
                # ただし Crustle が場にいないなら攻撃しかない
                if self._crustle_count() + self._dwebble_count() == 0:
                    return 3000  # やむを得ず攻撃
                return -1  # Crustle 待ち
            # 非ex相手: 積極的に攻撃
            dmg = 200  # 期待値は250だがベース200で計算
            score = 6000 + min(dmg, 340)
            if opp_a and opp_a.hp <= dmg:
                score += 3000 + prize_count(opp_a) * 500
            return score

        # ── Dwebble の攻撃（かくせい: ●/0dmg+即Crustle進化） ─────────────────
        if active.id == C.DWEBBLE:
            ec = self._energy_count(active)
            if ec < 1: return -1  # 1エネ必要
            # 壁準備として常に進化攻撃を優先
            return 8000

        # ── Crustle の攻撃 ──────────────────────────────────────────────────
        if active.id == C.CRUSTLE:
            # 壁モード: Crustleは攻撃しない（HPを保ちたい）
            if opp_ex: return 1000  # 低スコアだが合法手として残す
            ec = self._energy_count(active)
            if ec < 2: return -1
            score = 3000
            if opp_a and opp_a.hp <= 120:  # Crustleの攻撃は大体100-120dmg
                score += 2000
            return score

        return 500

    # ── Card choice ───────────────────────────────────────────────────────────
    def _score_card(self, option) -> float:
        card = get_card(self.obs, option.area, option.index, option.playerIndex)
        if card is None: return 0
        ctx = self.context

        if ctx in (SelectContext.SWITCH, SelectContext.TO_ACTIVE):
            return self._score_active_switch(option, card)
        if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            # セットアップ: Kangaskhan を優先アクティブへ
            if isinstance(card, Pokemon) and card.id == C.KANGASKHAN: return 10
            if isinstance(card, Pokemon) and card.id == C.DWEBBLE: return 5
            return 1
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
        opp_ex = self._opp_has_ex()

        if option.playerIndex == self.op_index:
            # 相手ベンチ引き出し: プライズ多い or HP 低い方を狙う
            hp_remaining = getattr(card, "hp", 999)
            return 5000 + prize_count(card) * 1000 + (200 - min(hp_remaining, 200))

        # 自分側:
        ec = self._energy_count(card)
        if opp_ex:
            # 壁モード: Crustle > Dwebble > その他
            if card.id == C.CRUSTLE: return 35000
            if card.id == C.DWEBBLE: return 25000 + ec * 50
            return 1000
        else:
            # 攻撃モード: Kangaskhan > その他
            if card.id == C.KANGASKHAN: return 35000 + ec * 200
            if card.id == C.DWEBBLE:    return 5000 + ec * 50
            return 1000

    def _score_to_bench(self, card) -> float:
        if not isinstance(card, Pokemon): return 0
        n = self.field_counts[card.id]
        if card.id == C.KANGASKHAN: return 200 - 30 * n
        if card.id == C.DWEBBLE:    return 180 - 40 * n
        if card.id == C.CRUSTLE:    return 150 - 30 * n
        return 50

    def _score_to_hand(self, card) -> float:
        if card is None: return 0
        cid = card.id
        s = 150 - self.hand_counts.get(cid, 0) * 60

        if cid == C.KANGASKHAN:
            s += 400 if self._kangaskhan_count() < 2 else 150
        elif cid == C.CRUSTLE:
            s += 350 if self._crustle_count() == 0 else 80
        elif cid == C.DWEBBLE:
            s += 250 if self._dwebble_count() + self._crustle_count() < 2 else 60
        elif cid in (C.ENRICHING_ENERGY, C.MIST_ENERGY, C.SPIKY_ENERGY,
                     C.GROW_ENERGY, C.GRASS_ENERGY):
            s += 60
        elif cid == C.JUMBO_ICE_CREAM:
            # 回復カードは3エネ到達後に価値が出る
            kang_active = (self.me.active and self.me.active[0] and
                           self.me.active[0].id == C.KANGASKHAN and
                           self._energy_count(self.me.active[0]) >= 3)
            s += 200 if kang_active else 80
        elif cid == C.NIGHT_STRETCHER:
            s += 150 if (self.disc_counts.get(C.KANGASKHAN, 0) > 0 or
                         self.disc_counts.get(C.CRUSTLE, 0) > 0) else 40
        return s

    def _score_discard(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid in (C.GRASS_ENERGY, C.ENRICHING_ENERGY,
                   C.MIST_ENERGY, C.SPIKY_ENERGY, C.GROW_ENERGY): return 80
        if self.hand_counts.get(cid, 0) >= 2: return 60
        if cid in (C.KANGASKHAN, C.CRUSTLE, C.DWEBBLE):
            return 5 if self.field_counts.get(cid, 0) > 0 else -80
        if cid in (C.LILLIE_DET, C.CYAN) and self.state.supporterPlayed:
            return 30
        return 5

    def _score_putback(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid in (C.KANGASKHAN, C.CRUSTLE, C.DWEBBLE): return -40
        if self.hand_counts.get(cid, 0) >= 2: return 50
        if cid in (C.GRASS_ENERGY, C.ENRICHING_ENERGY): return 20
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
            policy = KangaskhanPolicy(obs)

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
