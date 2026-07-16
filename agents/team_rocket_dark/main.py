"""
team_rocket_dark — ロケット団バンギラスライン（crustleキラー / 非exメタ）

目的：Final Submission 第2枠候補。crustle の穴（非ex環境）を埋める。

── 勝ち筋 ───────────────────────────────────────────────────────────────────
Tyranitar (442) ぶちぬきタックル：闘●●●, 180dmg, 相手エネ1個トラッシュ
  → Crustle(HP150)を一撃。非exなので Mysterious Rock Inn を素通り。
Tyranitar 特性「すなおこし」：バトル場にいる限り、ポケモンチェックのたびに
  相手のたねポケモン全員に20ダメカン × 毎ターン。相手の展開をじわじわ削る。

── Stage2 安定化の工夫 ───────────────────────────────────────────────────────
Pupitar (441) ばくれつかくせい：●, 30dmg + 山札からバンギラスを選んで即進化。
  → 1エネで Pupitar 攻撃 → Tyranitar が即座にフィールドへ。Rare Candy 不要。
  → Larvitar×4 / Pupitar×4 の 8枚体制で序盤事故を防ぐ（crustle教訓）。

── エネルギー設計 ─────────────────────────────────────────────────────────
Fighting Energy(6)×18 + TR Energy(15)×8。
  Tyranitar 闘●●●: Fighting×1(闘要件) + 残●●● は TR Energy 2個(=●●●●)で充足。
  実質 1 Fighting + 2 TR Energy（3枚=4要件充足）で攻撃可能。
  Pupitar ●: Fighting or TR Energy 1枚で OK。

── Arbok 不採用の理由 ────────────────────────────────────────────────────────
Arbok(449) は悪悪悪の3エネ技が必要 → 悪エネ基盤が必要 → Tyranitar の闘エネと
2タイプ混成。安定性を損なうため Tyranitar 単軸に絞った。

── TR 専用カード ────────────────────────────────────────────────────────────
Ariana(1216): 手札が5枚になるまで引く。全 TR 場なら8枚。
Proton(1220): 先攻1ターン目も使用可。たね TR ポケモンを3枚サーチ。
TR Receiver(1134): TR サポートを1枚サーチ（主に Ariana / Giovanni）。
TR Super Ball(1132): コイン表→進化 TR・裏→たね TR を山札から1枚。
Petrel(1219): 任意トレーナーズ1枚サーチ（Night Stretcher / Factory 等）。
Giovanni(1218): 自陣 TR 入れ替え＋相手ベンチを引き出す。プライズ有利狙い。
TR Factory(1257): TR サポートを使ったターン、さらに2枚ドロー。Ariana と相性◎。
Night Stretcher(1097): トラッシュからポケモン回収。
Poké Pad(1152): 非ルールポケモン（Tyranitar 含む）をサーチ。
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
    LARVITAR        = 440   # ロケット団のヨーギラス HP70 (たね)
    PUPITAR         = 441   # ロケット団のサナギラス HP100 (1進化) ←自己進化攻撃
    TYRANITAR       = 442   # ロケット団のバンギラス HP180 (2進化) ←主力
    FIGHTING_ENERGY = 6
    TR_ENERGY       = 15    # ロケット団エネルギー: 特殊、TR のみ装着、2エネ分
    ARIANA          = 1216  # ロケット団のアテナ: draw to 5 (全TR場なら8)
    ARCHER          = 1217  # ロケット団のアポロ: TR きぜつ後に使用可、両者シャッフルドロー
    GIOVANNI        = 1218  # ロケット団のサカキ: TR 入れ替え＋相手ベンチ引き出し
    PETREL          = 1219  # ロケット団のラムダ: 任意トレーナーズサーチ
    PROTON          = 1220  # ロケット団のランス: T1 可、たね TR 最大3枚サーチ
    TR_RECEIVER     = 1134  # ロケット団のレシーバー: TR サポートサーチ
    TR_SUPER_BALL   = 1132  # ロケット団のスーパーボール: コイン→TR ポケモンサーチ
    TR_FACTORY      = 1257  # ロケット団のファクトリー: TR サポ使用後+2ドロー/turn
    NIGHT_STRETCHER = 1097  # 夜のタンカ: トラッシュ回収
    POKE_PAD        = 1152  # ポケパッド: 非ルールポケモンサーチ


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

    PAD = C.FIGHTING_ENERGY
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

    filler = ([opp_basic] if opp_basic else []) + opp_vis*2 + [C.FIGHTING_ENERGY]*60
    opp_deck  = (filler+[C.FIGHTING_ENERGY]*60)[:opp.deckCount]
    opp_prize = (filler+[C.FIGHTING_ENERGY]*10)[:len(opp.prize)]
    opp_hand  = (filler+[C.FIGHTING_ENERGY]*10)[:opp.handCount]
    opp_active = []
    if opp.active and opp.active[0] is None:
        opp_active = [opp_basic] if opp_basic else []

    return your_deck, your_prize, opp_deck, opp_prize, opp_hand, opp_active


def _evaluate_obs(obs):
    """1-ply search 評価関数。Tyranitar の攻撃準備状態を重視。"""
    if obs is None or obs.current is None: return 0
    state  = obs.current
    my_idx = state.yourIndex
    op_idx = 1 - my_idx
    me  = state.players[my_idx]
    opp = state.players[op_idx]
    if state.result == my_idx: return 200_000
    if state.result == op_idx: return -200_000

    score = (len(opp.prize) - len(me.prize)) * 8_000

    for p in me.active + me.bench:
        if p is None: continue
        ec = len(p.energies)
        if p.id == C.TYRANITAR:
            score += 5_000 + ec * 600
            if ec >= 4: score += 2_000   # ぶちぬきタックル可能
        elif p.id == C.PUPITAR:
            score += 1_500 + ec * 200
        elif p.id == C.LARVITAR:
            score += 600

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
        policy = TRDarkPolicy(obs)
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

    p0 = TRDarkPolicy(obs)
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


# ── TR Dark policy ────────────────────────────────────────────────────────────
class TRDarkPolicy:
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

    def _energy_value(self, pokemon):
        """TR Energy は2エネ分としてカウント。"""
        try:
            ec = 0
            for e in pokemon.energies:
                ec += 2 if getattr(e, "id", None) == C.TR_ENERGY else 1
            return ec
        except:
            return 0

    def _tyranitar_count(self):
        return sum(1 for p in self._my_board() if p and p.id == C.TYRANITAR)

    def _pupitar_count(self):
        return sum(1 for p in self._my_board() if p and p.id == C.PUPITAR)

    def _larvitar_count(self):
        return sum(1 for p in self._my_board() if p and p.id == C.LARVITAR)

    def _all_field_tr(self) -> bool:
        """場のポケモン全員が TR ポケモンか（Ariana の8ドロー条件）。"""
        for p in self.me.active + self.me.bench:
            if p is None: continue
            d = card_table.get(p.id)
            # TR ポケモンは ID 440-900 台。エンジン上の判定はカードデータに依存。
            # ここでは「自分のデッキに含まれる ID のポケモンのみ」で代替判定。
            if p.id not in (C.LARVITAR, C.PUPITAR, C.TYRANITAR):
                return False
        return True

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
        if t == OptionType.YES:     return 100 if self.context == SelectContext.IS_FIRST else 1
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
        if card.id == C.LARVITAR:
            # Larvitar 4枚体制。冗長展開最優先（crustle教訓）。
            return 22000 - 300 * n if self._open_bench() else -1
        if card.id == C.PUPITAR:
            # Pupitar は直接プレイしない（Larvitar からの進化）
            return -1
        return 15000 - 200 * n

    def _score_play_trainer(self, card) -> float:
        cid = card.id

        # ── サポート ─────────────────────────────────────────────────────────
        if cid == C.PROTON:
            if self.state.supporterPlayed: return -1
            # T1 に3体 Larvitar を集めるのが最優先
            larvitar_on_field = self._larvitar_count()
            return 20000 if larvitar_on_field < 3 else 5000

        if cid == C.ARIANA:
            if self.state.supporterPlayed or self._low_deck(): return -1
            # 全TR場なら8枚引ける
            if self._all_field_tr() and self._hand_size() <= 6:
                return 15000
            return 12000 if self._hand_size() <= 4 else 4000

        if cid == C.GIOVANNI:
            if self.state.supporterPlayed: return -1
            # 使うならプライズ有利確保または苦手ポケをどかすとき
            return 8000

        if cid == C.PETREL:
            if self.state.supporterPlayed: return -1
            # Night Stretcher / Factory が欲しいとき
            return 7000

        if cid == C.ARCHER:
            # TR ポケモンがきぜつした後のみ使用可能（エンジンが条件チェックする）
            if self.state.supporterPlayed: return -1
            return 6000

        # ── グッズ ─────────────────────────────────────────────────────────
        if cid == C.TR_RECEIVER:
            # TR サポートをサーチ（主に Ariana）
            has_ariana = self.hand_counts.get(C.ARIANA, 0) == 0
            return 11000 if has_ariana else 4000

        if cid == C.TR_SUPER_BALL:
            # コイン表→進化 TR / 裏→たね TR: どちらも有益
            need = (self._tyranitar_count() < 2 or
                    self._pupitar_count() + self._larvitar_count() < 2)
            return 12000 if need else 5000

        if cid == C.TR_FACTORY:
            # スタジアム枠。TR サポートと毎ターン相性◎ → 早期設置優先
            if self.state.stadiumPlayed: return -1
            return 9000

        if cid == C.NIGHT_STRETCHER:
            has_tyran  = self.disc_counts.get(C.TYRANITAR, 0) > 0
            has_pupitar = self.disc_counts.get(C.PUPITAR, 0) > 0
            has_larvi  = self.disc_counts.get(C.LARVITAR, 0) > 0
            if has_tyran: return 10000
            if has_pupitar: return 7500
            if has_larvi: return 5000
            return 300

        if cid == C.POKE_PAD:
            # 非ルールポケモン = Tyranitar もサーチできる
            need = self._tyranitar_count() == 0 and self._pupitar_count() >= 1
            return 9500 if need else 3000

        return 7000

    # ── Evolve ────────────────────────────────────────────────────────────────
    def _score_evolve(self, option) -> float:
        target = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon): return 0
        card = get_card(self.obs, AreaType.HAND, option.index, self.my_index)
        if card is None: return 0

        if card.id == C.TYRANITAR:
            # 手札から直接進化（通常進化ルート）。最高優先。
            return 25000 + self._energy_count(target) * 50
        if card.id == C.PUPITAR:
            # Larvitar → Pupitar 進化。
            return 23000 + self._energy_count(target) * 50
        return 18000

    # ── Attach ────────────────────────────────────────────────────────────────
    def _score_attach(self, option) -> float:
        pokemon = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(pokemon, Pokemon): return 0
        return self._energy_score(pokemon, option.inPlayArea == AreaType.ACTIVE)

    def _energy_score(self, pokemon, is_active) -> float:
        ev = self._energy_value(pokemon)  # TR Energy は2エネとしてカウント

        if pokemon.id == C.TYRANITAR:
            # ぶちぬきタックル要件: 4エネ（闘●●●）
            # TR Energy 2枚+Fighting 1枚 = 5要件 = 十分
            base = 10000 if ev < 4 else 300
        elif pokemon.id == C.PUPITAR:
            # ばくれつかくせい要件: 1エネ
            # 進化攻撃のために最低1エネ欲しい
            base = 8000 if ev == 0 else 200
        elif pokemon.id == C.LARVITAR:
            # 攻撃コスト: ●1
            base = 300 if ev == 0 else 50
        else:
            base = 50
        return base + (300 if is_active else 0)

    # ── Retreat ───────────────────────────────────────────────────────────────
    def _score_retreat(self) -> float:
        active = self.me.active[0] if self.me.active else None
        if active is None: return -1

        if active.id == C.TYRANITAR:
            # Tyranitar はアクティブで殴り続ける
            return -1

        if active.id == C.PUPITAR:
            # Pupitar は1エネ貯まれば攻撃（進化）の方が優先。攻撃できない状況なら退場。
            ev = self._energy_value(active)
            if ev == 0:
                # エネなし Pupitar は下げる
                for p in self.me.bench:
                    if p and p.id == C.TYRANITAR:
                        return 8000
            return -1

        if active.id == C.LARVITAR:
            # Larvitar がアクティブ → Pupitar/Tyranitar があれば入れ替える
            for p in self.me.bench:
                if p and p.id == C.TYRANITAR: return 9000
                if p and p.id == C.PUPITAR and self._energy_value(p) >= 1: return 7000
            return 3000

        return -1

    # ── Attack ────────────────────────────────────────────────────────────────
    def _score_attack(self, option) -> float:
        active = self.me.active[0] if self.me.active else None
        opp_a  = self.opponent.active[0] if self.opponent.active else None
        if active is None: return 500

        # ── Pupitar の攻撃（ばくれつかくせい: 1エネ/30dmg+Tyranitar 即進化） ─
        if active.id == C.PUPITAR:
            # 常に使う（Tyranitar への変身攻撃が最善）
            score = 6000 + 30   # 高スコアで確実に選択
            if opp_a and opp_a.hp <= 30:
                score += 1000
            return score

        # ── Larvitar の攻撃（●/10+山札トップトラッシュ） ────────────────────
        if active.id == C.LARVITAR:
            # 使えるなら使う（受動的）
            return 3000

        # ── Tyranitar の攻撃（ぶちぬきタックル: 闘●●●/180dmg+エネトラッシュ）─
        if active.id != C.TYRANITAR:
            return 500

        ev = self._energy_value(active)
        if ev < 4:
            # エネ不足: まだ攻撃しない（エネを貯める）
            return -1

        dmg = 180
        score = 5500 + min(dmg, 340)
        if opp_a:
            if opp_a.hp <= dmg:
                score += 3000 + prize_count(opp_a) * 1000
            # エネを剥ぐことで相手の攻撃準備を妨害
            if len(getattr(opp_a, "energies", [])) >= 2:
                score += 500
        return score

    # ── Card choice ───────────────────────────────────────────────────────────
    def _score_card(self, option) -> float:
        card = get_card(self.obs, option.area, option.index, option.playerIndex)
        if card is None: return 0
        ctx = self.context

        if ctx in (SelectContext.SWITCH, SelectContext.TO_ACTIVE):
            return self._score_active_switch(option, card)
        if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            if isinstance(card, Pokemon) and card.id == C.LARVITAR: return 6
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
        if option.playerIndex == self.op_index:
            # Giovanni で相手ベンチ引き出し: HP が低いか、プライズが多いポケモンを狙う
            hp_remaining = getattr(card, "hp", 999)
            return 5000 + prize_count(card) * 1000 + (200 - min(hp_remaining, 200))
        # 自分側: Tyranitar を最優先でアクティブへ
        ev = self._energy_value(card)
        if card.id == C.TYRANITAR: return 20000 + ev * 200
        if card.id == C.PUPITAR:   return 10000 + ev * 100
        if card.id == C.LARVITAR:  return 1000  + ev * 50
        return ev * 10 + 1

    def _score_to_bench(self, card) -> float:
        if not isinstance(card, Pokemon): return 0
        n = self.field_counts[card.id]
        if card.id == C.LARVITAR:   return 200 - 40 * n
        if card.id == C.TYRANITAR:  return 180 - 30 * n
        if card.id == C.PUPITAR:    return 150 - 30 * n
        return 50

    def _score_to_hand(self, card) -> float:
        if card is None: return 0
        cid = card.id
        s = 150 - self.hand_counts.get(cid, 0) * 60

        if cid == C.TYRANITAR:
            s += 400 if self._tyranitar_count() < 1 else 150
        elif cid == C.PUPITAR:
            s += 300 if self._pupitar_count() < 2 else 50
        elif cid == C.LARVITAR:
            total = self._larvitar_count() + self._pupitar_count() + self._tyranitar_count()
            s += 300 if total < 2 else 100
        elif cid in (C.FIGHTING_ENERGY, C.TR_ENERGY):
            s += 60
        elif cid == C.ARIANA:
            s += 200 if self.hand_counts.get(C.ARIANA, 0) == 0 else 50
        elif cid == C.NIGHT_STRETCHER:
            s += 150 if (self.disc_counts.get(C.TYRANITAR, 0) > 0 or
                         self.disc_counts.get(C.PUPITAR, 0) > 0) else 40
        return s

    def _score_discard(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid in (C.FIGHTING_ENERGY, C.TR_ENERGY): return 80
        if self.hand_counts.get(cid, 0) >= 2: return 60
        if cid in (C.LARVITAR, C.PUPITAR, C.TYRANITAR):
            return 5 if self.field_counts.get(cid, 0) > 0 else -80
        if cid in (C.ARIANA, C.PROTON, C.GIOVANNI, C.PETREL) and self.state.supporterPlayed:
            return 30
        return 5

    def _score_putback(self, card) -> float:
        if card is None: return 0
        cid = card.id
        if cid in (C.LARVITAR, C.PUPITAR, C.TYRANITAR): return -40
        if self.hand_counts.get(cid, 0) >= 2: return 50
        if cid in (C.FIGHTING_ENERGY, C.TR_ENERGY): return 20
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
            policy = TRDarkPolicy(obs)

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
