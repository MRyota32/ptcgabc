# harness/ — 評価ハーネス

## cabt_harness.py について

`cabt_harness.py` は評価ハーネス環境（ローカルではなく、Kaggle対戦エンジンが稼働する専用環境）に存在する。このリポジトリには含まれていない。

## 機能

- balanced / 座席固定 対戦のN=400〜1,000実行
- Wilson CI（勝率の信頼区間）
- 2標本差CI（版間比較）
- 発火率カウンタ同梱版（改修評価時）
- 陰性対照・複製ゲート対応

## プロトコル

`docs/agent/measurement-protocol.md` および `skills/stochastic-agent-eval/SKILL.md` 参照。

## ハーネス環境へのエージェントの渡し方

1. `scripts/check_deck_legal.py` でデッキ合法性確認（errorPlayer==-1）
2. `tar -czf vN.tar.gz main.py deck.csv` でパッケージ
3. ハーネス環境に渡して N=400〜1,000 balanced で実行
4. 結果を `experiments/results/` に保存
