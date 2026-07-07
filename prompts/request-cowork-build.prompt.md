# Cowork 制作依頼テンプレート

このプロンプトを Cowork（Claude デスクトップアプリ）にそのまま渡す。

---

```
あなたはポケカABC（Kaggle PTCG AI Battle Challenge）のエージェント・デッキ制作を担当します。
`docs/agent/confirmed-facts.md`（確定事実）と `docs/agent/decision-log.md`（意思決定ログ）を前提に、以下を作ってください。

【依頼内容】
<!-- ここに具体的な依頼を記載。例：
- v6 対crustle適応版の実装（設計仕様：...）
- 相手デッキ#3 の作成（デッキコンセプト：...）
-->

【成果物の形式】
- `agents/lucario/vN/main.py` + `deck.csv`（または `agents/opponents/XXX/`）
- 納品前に `scripts/check_deck_legal.py` を実行し errorPlayer==-1 を確認すること
- チェックログを成果物に同梱

【技術制約】
- エージェント契約：`agent(obs_dict) -> list[int]`（select.option のindex。デッキ選択局面のみ60枚のID）
- 対戦中にLLMは呼べない（オフライン隔離 + 時間制限）= 純Pythonのヒューリスティック/探索で書く
- 例外・タイムアウトは即敗北。必ず合法手フォールバックを持たせること
- エンジンのSearch API（`cg.api.search_begin/step/end/release`）で1ply先読みが使える

【採否判定】
作った後、ハーネス環境で vs v2 を N=400 以上・balanced で実行して統計的有意差で判定します。
Cowork側での勝率予測・判定は不要です。
```
