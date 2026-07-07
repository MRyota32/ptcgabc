# ポケカABC — Kaggle PTCG AI Battle Challenge

Kaggleのポケモンカード対戦AI大会（ポケカABC）のエージェント開発リポジトリ。  
詳細な知識ベースは `docs/agent/` を参照。

## セットアップ

```bash
cd ptcgabc
python3 -m venv .venv
source .venv/bin/activate
pip install kaggle-environments   # cgエンジンが同梱される
```

**エンジンバイナリについて**：`engine/` の `libcg.so`（Linux）/ `cg.dll`（Windows）は Kaggle Data タブの `sample_submission.zip` 由来。バイナリは `.gitignore` 対象のため、`engine/README.md` の手順で取得すること。

## 動作確認

```bash
python3 experiments/scripts/test_random.py   # ランダムエージェント同士の対戦テスト
```

## 評価ハーネスの実行

`harness/` に `cabt_harness.py` を配置後（`harness/README.md` 参照）：

```bash
python3 harness/cabt_harness.py \
  --agent_a agents/lucario/v2 \
  --agent_b agents/lucario/v5 \
  --n 500
```

## デッキ合法性チェック（納品前必須）

```bash
python3 scripts/check_deck_legal.py agents/opponents/crustle/deck.csv
# errorPlayer: -1 なら合法
```

## ディレクトリ構造

`docs/agent/repository-structure.md` 参照。

## 重要ルール

`AGENTS.md` 参照。特に：
- デッキ納品前 `check_deck_legal.py` 必須
- ラダーEloを版判定器に使わない
- 確定事実は `docs/agent/confirmed-facts.md` が唯一の源泉
