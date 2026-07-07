"""
Kaggleノートブック用テストスクリプト
このファイルの内容をそのままノートブックに貼り付けて実行する

api モジュールは存在しないため、obs_dict を直接操作する実装。
enum値はゲームデータから逆引きした整数定数を使用。
"""

import random
from kaggle_environments import make

# ============================================================
# dict → 属性アクセス変換ラッパー（api 代替）
# ============================================================
class _S:
    """obs_dict の dict/list を属性アクセス可能なオブジェクトに変換する"""
    __slots__ = ('_d',)

    def __init__(self, d):
        object.__setattr__(self, '_d', d)

    def __getattr__(self, k):
        d = object.__getattribute__(self, '_d')
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, dict):  return _S(v)
        if isinstance(v, list):  return [_S(x) if isinstance(x, dict) else x for x in v]
        return v

    def __len__(self):   return len(object.__getattribute__(self, '_d'))
    def __bool__(self):  return bool(object.__getattribute__(self, '_d'))
    def __iter__(self):  return iter(object.__getattribute__(self, '_d'))
    def __getitem__(self, k): return object.__getattribute__(self, '_d')[k]
    def __repr__(self):  return f"S({object.__getattribute__(self, '_d')})"

# ============================================================
# 整数定数（ゲームデータから逆引き確定済み）
# ============================================================

# SelectType (select["type"])
_ST_MAIN   = 0   # メインフェーズ
_ST_CARD   = 1   # カード選択
_ST_ENERGY = 4   # エネルギー選択
_ST_ATTACK = 6   # 攻撃選択（どの技を使うか）
_ST_EVOLVE = 7   # 進化先選択
_ST_SKILL  = 8   # 特性発動
_ST_YESNO  = 9   # はい/いいえ

# SelectContext (select["context"]) — 公式ドキュメント確認済み
_CTX_SETUP_ACTIVE = 1   # バトル場の初期配置
_CTX_SETUP_BENCH  = 2   # ベンチの初期配置
_CTX_SWITCH       = 3   # 入れ替え（旧: 9=TO_DECK で誤り）
_CTX_TO_ACTIVE    = 4   # バトル場に出す（旧: 8=DISCARD で誤り）
_CTX_TO_HAND      = 7   # サーチ→手札へ
_CTX_DISCARD      = 8   # 捨てる（旧: 5=TO_BENCH で誤り）
_CTX_IS_FIRST     = 41  # 先攻/後攻選択
_CTX_MULLIGAN     = 42  # マリガン（旧: 未定義）

# OptionType (option["type"]) — 公式ドキュメント確認済み
_OPT_YES     = 1
_OPT_NO      = 2
_OPT_PLAY    = 7    # 手札からカードをプレイ
_OPT_ATTACH  = 8    # エネルギー付け
_OPT_EVOLVE  = 9    # 進化（MAINフェーズ内）
_OPT_ABIL    = 10   # 特性使用
_OPT_RETREAT = 12   # にげる（旧: 誤って END として使用）
_OPT_ATTACK  = 13   # 攻撃
_OPT_END     = 14   # ターン終了（旧: 12=RETREAT で誤り！）

# AreaType (option["area"] / option["inPlayArea"]) — 公式ドキュメント確認済み
_AREA_DECK   = 1
_AREA_HAND   = 2    # 旧: 1=DECK で誤り！サーチロジック全滅の原因
_AREA_ACTIVE = 4
_AREA_BENCH  = 5

# EnergyType (pokemon["energies"] の要素)
_ETYPE_DARK = 7   # ※ 要確認（カードID=7=基本悪エネルギーと仮定）

# ============================================================
# カードID定数
# ============================================================
ZOROA_N, ZOROARK_EX = 292, 293
VANIPETI_N, VANILLUXE_N = 862, 864
SYMBOLER_N, BACHURU_N = 277, 267
BOSS_ORDER, N_PLAN, LILLIE, SAZARE, JUDGE = 1182, 1221, 1227, 1183, 1213
MASTER_BALL, HYPER_BALL, WONDER_AME, N_POINT_UP = 1125, 1121, 1079, 1113
N_CASTLE = 1253
DARK_ENERGY = 7
BENCH_PRIORITY = [ZOROA_N, VANIPETI_N, SYMBOLER_N, BACHURU_N]

# ============================================================
# ルールベースエージェント
# ============================================================

def agent(obs_dict: dict) -> list[int]:
    if obs_dict.get("select") is None:
        return list(deck)
    try:
        return _decide(obs_dict)
    except Exception as e:
        _agent_errors[f"{type(e).__name__}: {str(e)[:80]}"] = \
            _agent_errors.get(f"{type(e).__name__}: {str(e)[:80]}", 0) + 1
        s = obs_dict["select"]
        n = max(s["minCount"], min(s["maxCount"], len(s["option"])))
        return random.sample(range(len(s["option"])), n)


def _safe(result, sel):
    """返り値を minCount≤len≤maxCount かつ有効インデックスに正規化する"""
    n = len(sel.option)
    # 有効インデックスのみ・重複除去
    seen = set()
    valid = []
    for i in (result or []):
        if isinstance(i, int) and 0 <= i < n and i not in seen:
            valid.append(i); seen.add(i)
    min_c = sel.minCount or 0
    max_c = sel.maxCount if (sel.maxCount is not None) else n
    # 足りなければ先頭から補充
    for i in range(n):
        if len(valid) >= max(min_c, max_c): break
        if i not in seen:
            valid.append(i); seen.add(i)
    return valid[:max_c]


def _decide(obs_dict):
    obs = _S(obs_dict)
    sel = obs.select
    if sel is None:
        return []
    t   = sel.type
    ctx = sel.context

    # コンテキスト優先
    if ctx == _CTX_IS_FIRST:     return _safe(_pick_no(sel), sel)
    if ctx == _CTX_SETUP_ACTIVE: return _safe(_setup_active(obs), sel)
    if ctx == _CTX_SETUP_BENCH:  return _safe(_setup_bench(obs), sel)
    if t == _ST_YESNO:           return _safe(_yes_no(obs), sel)

    # タイプ優先
    if t == _ST_MAIN:   return _safe(_main_phase(obs), sel)
    if t == _ST_CARD:   return _safe(_select_card(obs), sel)
    if t == _ST_ATTACK: return _safe([0] if sel.option else [], sel)
    if t == _ST_EVOLVE: return _safe(_select_evolve(obs), sel)
    if t == _ST_SKILL:  return _safe([0], sel)
    if t == _ST_ENERGY:
        n = max(sel.minCount or 0, min(sel.maxCount or 1, len(sel.option)))
        return _safe(list(range(n)), sel)

    # COUNT タイプ
    nums = [o.number for o in sel.option if o.number is not None]
    if nums:
        mx = max(nums)
        for i, o in enumerate(sel.option):
            if o.number == mx:
                return _safe([i], sel)

    n = max(sel.minCount or 0, min(sel.maxCount or 1, len(sel.option)))
    return _safe(random.sample(range(len(sel.option)), min(n, len(sel.option))), sel)


def _setup_active(obs):
    sel  = obs.select
    me   = obs.current.players[obs.current.yourIndex]
    for i, o in enumerate(sel.option):
        c = _hc(me, o)
        if c and c.id == ZOROA_N: return [i]
    return [0]


def _setup_bench(obs):
    sel = obs.select
    me  = obs.current.players[obs.current.yourIndex]
    result = []
    for pid in BENCH_PRIORITY:
        for i, o in enumerate(sel.option):
            if i in result: continue
            c = _hc(me, o)
            if c and c.id == pid:
                result.append(i); break
    while len(result) < sel.minCount and len(result) < len(sel.option):
        for i in range(len(sel.option)):
            if i not in result: result.append(i); break
    return result[:sel.maxCount]


def _main_phase(obs):
    sel   = obs.select
    state = obs.current
    opts  = sel.option
    me    = state.players[state.yourIndex]
    opp   = state.players[1 - state.yourIndex]

    play   = [(i, o) for i, o in enumerate(opts) if o.type == _OPT_PLAY]
    attach = [(i, o) for i, o in enumerate(opts) if o.type == _OPT_ATTACH]
    evolve = [(i, o) for i, o in enumerate(opts) if o.type == _OPT_EVOLVE]
    abil   = [(i, o) for i, o in enumerate(opts) if o.type == _OPT_ABIL]
    attack = [(i, o) for i, o in enumerate(opts) if o.type == _OPT_ATTACK]
    end    = [(i, o) for i, o in enumerate(opts) if o.type == _OPT_END]

    bench_list = me.bench if me.bench else []
    hand_list  = me.hand  if me.hand  else []

    # 1. サポート（最優先 — 手札補充が全てを加速する）
    if not state.supporterPlayed:
        for i, o in play:
            c = _hc(me, o)
            if c and c.id == N_PLAN: return [i]          # 条件なしで常にプレイ
        for i, o in play:
            c = _hc(me, o)
            if c and c.id == LILLIE and (me.handCount or 99) <= 4: return [i]
        for i, o in play:
            c = _hc(me, o)
            if c and c.id == SAZARE: return [i]
        opp_bench = opp.bench if opp.bench else []
        for i, o in play:
            c = _hc(me, o)
            if c and c.id == BOSS_ORDER and len(opp_bench) > 0: return [i]

    # 2. マスターボール（サーチ）
    for i, o in play:
        c = _hc(me, o)
        if c and c.id == MASTER_BALL: return [i]

    # 3. とりひき特性（手札 ≤ 5 枚）
    for i, o in abil:
        pk = _fp(me, o.area, o.index)
        if pk and pk.id == ZOROARK_EX and (me.handCount or 0) <= 5: return [i]

    # 4. ふしぎなアメ（バニプッチがベンチにいてバニリッチが手札にある）
    if (any(getattr(p, 'id', None) == VANIPETI_N for p in bench_list) and
            any(getattr(c, 'id', None) == VANILLUXE_N for c in hand_list)):
        for i, o in play:
            c = _hc(me, o)
            if c and c.id == WONDER_AME: return [i]

    # 5. 進化（ゾロアークex 優先）
    for i, o in evolve:
        c = _hc(me, o)
        if c and c.id == ZOROARK_EX: return [i]
    if evolve: return [evolve[0][0]]

    # 6. エネルギー付け（バトル場ゾロアーク優先）
    if attach:
        active = (me.active[0] if me.active else None)
        for i, o in attach:
            if o.inPlayArea == _AREA_ACTIVE and active and getattr(active, 'id', None) == ZOROARK_EX:
                return [i]
        for i, o in attach:
            if o.inPlayArea == _AREA_BENCH:
                idx = o.inPlayIndex
                pk  = bench_list[idx] if idx is not None and idx < len(bench_list) else None
                if pk and getattr(pk, 'id', None) == ZOROARK_EX: return [i]
        return [attach[0][0]]

    # 7. 攻撃（エンジンが検証済み → 選択肢に出た時点で実行可能）
    if attack:
        active = me.active[0] if me.active else None
        energies = getattr(active, 'energies', None) or [] if active else []
        dark = sum(1 for e in energies if e == _ETYPE_DARK)
        _dbg_energies.append((energies, dark))
        return [attack[0][0]]

    # 8. ハイパーボール（手札 ≥ 3 枚）
    if (me.handCount or 0) >= 3:
        for i, o in play:
            c = _hc(me, o)
            if c and c.id == HYPER_BALL: return [i]

    # 9. たね展開（ベンチ < 4 体）
    if len(bench_list) < 4:
        for pid in BENCH_PRIORITY:
            for i, o in play:
                c = _hc(me, o)
                if c and c.id == pid: return [i]

    # 10. ターン終了
    if end: return [end[0][0]]

    n = max(sel.minCount, min(sel.maxCount, len(opts)))
    return random.sample(range(len(opts)), n)


def _yes_no(obs):
    sel = obs.select
    ctx = sel.context
    # デフォルト YES（能力トリガー・マリガン等、拒否すると損するケースが多い）
    _dbg_yesno.append(ctx)
    yes = next((i for i, o in enumerate(sel.option) if o.type == _OPT_YES), None)
    return [yes] if yes is not None else [0]


def _select_card(obs):
    sel   = obs.select
    state = obs.current
    me    = state.players[state.yourIndex]
    ctx   = sel.context

    # サーチ系 → Zoroark ラインを優先
    if ctx not in (_CTX_DISCARD, _CTX_TO_ACTIVE, _CTX_SWITCH):
        for pid in [ZOROARK_EX, VANILLUXE_N, VANIPETI_N, ZOROA_N, SYMBOLER_N, BACHURU_N]:
            for i, o in enumerate(sel.option):
                c = _card_opt(me, o)
                if c and getattr(c, 'id', None) == pid: return [i]
        return [0]

    # 捨てる → 不要牌から捨てる
    if ctx == _CTX_DISCARD:
        trash  = [DARK_ENERGY, N_CASTLE, JUDGE, N_POINT_UP]
        result = []
        for tid in trash:
            for i, o in enumerate(sel.option):
                if i in result: continue
                c = _hc(me, o)
                if c and getattr(c, 'id', None) == tid: result.append(i)
            if len(result) >= sel.maxCount: break
        for i in range(len(sel.option)):
            if i not in result: result.append(i)
            if len(result) >= sel.maxCount: break
        return result[:sel.maxCount]

    # 入れ替え/KO後 → ZoroarkEX > ZoroaN > VanilluxeN > VanipetiN
    for pid in [ZOROARK_EX, ZOROA_N, VANILLUXE_N, VANIPETI_N]:
        for i, o in enumerate(sel.option):
            pk = _fp(me, o.area, o.index)
            if pk and getattr(pk, 'id', None) == pid: return [i]
    return [0]


def _select_evolve(obs):
    sel = obs.select
    me  = obs.current.players[obs.current.yourIndex]
    for i, o in enumerate(sel.option):
        c = _hc(me, o)
        if c and getattr(c, 'id', None) == ZOROARK_EX: return [i]
    for i, o in enumerate(sel.option):
        c = _hc(me, o)
        if c and getattr(c, 'id', None) == VANILLUXE_N: return [i]
    return [0]


# ---- ヘルパー ----
def _hc(me, option):
    """手札から option.index 番目のカードを返す（index省略時は0番目）"""
    hand = me.hand if me.hand else []
    idx  = option.index
    if idx is None: idx = 0   # index省略 = 手札0番目
    if 0 <= idx < len(hand):
        return hand[idx]
    return None

def _fp(ps, area, index):
    """プレイヤーの指定エリア・インデックスの Pokémon を返す"""
    if index is None: return None
    if area == _AREA_ACTIVE:
        active = ps.active if ps.active else []
        return active[index] if index < len(active) else None
    if area == _AREA_BENCH:
        bench = ps.bench if ps.bench else []
        return bench[index] if index < len(bench) else None
    return None

def _card_opt(me, option):
    """option の area+index からカードを返す（手札のみ対応）"""
    if option.area == _AREA_HAND:
        hand = me.hand if me.hand else []
        idx  = option.index
        if idx is not None and idx < len(hand): return hand[idx]
    return None

def _pick_no(sel):
    for i, o in enumerate(sel.option):
        if o.type == _OPT_NO: return [i]
    return [0]


# ============================================================
# テスト実行
# ============================================================
deck = (
    [ZOROA_N]*4 + [ZOROARK_EX]*3 +
    [VANIPETI_N]*2 + [VANILLUXE_N]*2 +
    [SYMBOLER_N]*2 + [BACHURU_N]*2 +
    [BOSS_ORDER]*3 + [N_PLAN]*4 +
    [LILLIE]*2 + [SAZARE]*2 + [JUDGE]*1 +
    [MASTER_BALL]*1 + [HYPER_BALL]*4 +
    [WONDER_AME]*4 + [N_POINT_UP]*4 +
    [N_CASTLE]*2 +
    [DARK_ENERGY]*18
)
assert len(deck) == 60

_agent_errors = {}
_dbg_energies = []  # (energies_list, dark_count) のログ
_dbg_yesno    = []  # YES/NO が呼ばれた context のログ

random.seed(42)
N_GAMES = 60
print(f"ルールベースAI vs ランダムAI で{N_GAMES}ゲーム実行...")
wins = 0
for game_num in range(N_GAMES):
    def random_agent(obs_dict):
        if obs_dict.get("select") is None:
            return list(deck)
        s = obs_dict["select"]
        n = max(s["minCount"], min(s["maxCount"], len(s["option"])))
        return random.sample(range(len(s["option"])), n)

    env = make("cabt", configuration={"decks": [deck, deck]})
    env.run([agent, random_agent])

    p0 = env.state[0]
    print(f"  DEBUG steps={len(env.steps)} status={p0.status} reward={p0.reward}")
    reward = p0.reward
    if reward is None: reward = 0
    if reward > 0:
        wins += 1; label = '🏆 WIN'
    elif reward < 0:
        label = '❌ LOSE'
    else:
        label = '△ DRAW'
    print(f"  Game {game_num+1}: {label}  (reward={reward})")

print(f"\n結果: {wins}/{N_GAMES} 勝利 ({wins/N_GAMES*100:.0f}%)")
if _agent_errors:
    print("\n[exceptに落ちたエラー一覧]")
    for k, v in sorted(_agent_errors.items(), key=lambda x: -x[1]):
        print(f"  {v}回: {k}")
else:
    print("\n[exceptへの落ち込みなし ✅]")

# エネルギーデバッグ
from collections import Counter
if _dbg_energies:
    all_e = []
    for elist, dark in _dbg_energies:
        all_e.extend(elist)
    print(f"\n[energy debug] attack判定 {len(_dbg_energies)}回")
    print(f"  dark>=2: {sum(1 for _,d in _dbg_energies if d>=2)}回  dark==1: {sum(1 for _,d in _dbg_energies if d==1)}回  dark==0: {sum(1 for _,d in _dbg_energies if d==0)}回")
    print(f"  energyの値の分布: {Counter(all_e).most_common(10)}")
else:
    print("\n[energy debug] attack判定 0回（攻撃オプション自体が出なかった）")

# YES/NOデバッグ
if _dbg_yesno:
    print(f"\n[yesno debug] YES/NO呼び出し {len(_dbg_yesno)}回  context分布: {Counter(_dbg_yesno).most_common()}")
else:
    print("\n[yesno debug] YES/NO呼び出し 0回")
