"""
動作確認用スクリプト
ランダムエージェント同士で1ゲーム走らせ、obs_dict の構造を出力する。

実行方法:
  source .venv/bin/activate
  python3 test_random.py
"""

import random
from kaggle_environments import make

# ---- デッキ読み込み ----
with open("deck.csv") as f:
    deck = [int(line.strip()) for line in f if line.strip()]

assert len(deck) == 60, f"デッキが60枚ではありません: {len(deck)}枚"
print(f"デッキ読み込み完了: {len(deck)}枚")

# ---- デバッグ用エージェント ----
step_count = 0
MAX_DUMP_STEPS = 3  # 最初の3ステップだけ obs_dict を出力する

def debug_agent(obs_dict: dict) -> list[int]:
    global step_count
    step_count += 1

    if step_count <= MAX_DUMP_STEPS:
        sel = obs_dict.get("select", {})
        print(f"\n--- Step {step_count} ---")
        print(f"  SelectType   : {sel.get('type')}")
        print(f"  SelectContext: {sel.get('context')}")
        print(f"  minCount     : {sel.get('minCount')}  maxCount: {sel.get('maxCount')}")
        print(f"  options count: {len(sel.get('option', []))}")
        for i, opt in enumerate(sel.get("option", [])[:3]):
            print(f"    option[{i}]: {opt}")

    # ランダム選択
    options = obs_dict["select"]["option"]
    max_count = obs_dict["select"]["maxCount"]
    min_count = obs_dict["select"]["minCount"]
    count = max(min_count, min(max_count, len(options)))
    return random.sample(list(range(len(options))), count)

# ---- ゲーム実行 ----
print("\nゲーム開始...")
env = make("cabt", configuration={"decks": [deck, deck]})
env.run([debug_agent, debug_agent])

# ---- 結果表示 ----
print(f"\n=== ゲーム終了 ===")
print(f"ステップ数: {step_count}")

with open("result.html", "w") as f:
    f.write(env.render(mode="html"))
print("result.html を開いてブラウザで対戦の様子を確認できます")
