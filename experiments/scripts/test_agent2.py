"""
test_agent2.py - agent.py をインポートして勝率テスト
Kaggleノートブックで以下のように実行:

  !cp /kaggle/input/xxx/agent.py .
  !cp /kaggle/input/xxx/deck.csv .
  # このファイルのセルを実行

N_GAMES = 60 ゲームを agent vs ランダムAI で対戦
"""

import random
from kaggle_environments import make
from agent import agent  # agent.py をそのまま使う

random.seed(42)
N_GAMES = 60

def random_agent(obs_dict):
    if obs_dict.get("select") is None:
        # ランダムデッキ（たねポケモン含む最低限）
        deck = (
            [292]*4 + [293]*3 +
            [862]*2 + [864]*2 +
            [277]*2 + [267]*2 +
            [1182]*3 + [1221]*4 +
            [1227]*2 + [1183]*2 + [1213]*1 +
            [1125]*1 + [1121]*4 +
            [1079]*4 + [1113]*4 +
            [1253]*2 +
            [7]*18
        )
        return deck
    s = obs_dict["select"]
    n = max(s["minCount"], min(s["maxCount"], len(s["option"])))
    return random.sample(range(len(s["option"])), n)

wins = 0
wins_first = 0   # 先攻での勝利
wins_second = 0  # 後攻での勝利
games_first = 0
games_second = 0

for game_i in range(N_GAMES):
    if game_i % 2 == 0:
        agents = [agent, random_agent]
        my_pos = 0
        is_first = True
    else:
        agents = [random_agent, agent]
        my_pos = 1
        is_first = False

    env = make("cabt", debug=False)
    env.run(agents)
    steps = env.steps
    last = steps[-1]

    reward = last[my_pos].get("reward")
    won = reward is not None and reward > 0
    if won:
        wins += 1
    if is_first:
        games_first += 1
        if won: wins_first += 1
    else:
        games_second += 1
        if won: wins_second += 1

    if (game_i + 1) % 10 == 0:
        print(f"Game {game_i+1:3d}/{N_GAMES}  wins={wins}  rate={wins/(game_i+1)*100:.1f}%")

print(f"\n=== 最終結果 ===")
print(f"全体:  {wins}/{N_GAMES} = {wins/N_GAMES*100:.1f}%")
print(f"先攻:  {wins_first}/{games_first} = {wins_first/games_first*100:.1f}%")
print(f"後攻:  {wins_second}/{games_second} = {wins_second/games_second*100:.1f}%")
