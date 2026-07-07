# AGENTS.md — ポケカABC プロジェクトルーター

## ハードルール（例外なし）

1. **デッキ納品前に `scripts/check_deck_legal.py` を実行**。`errorPlayer == -1` を確認してから渡す。errorType=4 はエンジン非対応カードの疑い（例：Hyper Aroma id=1082）。
2. **版比較は N≥400・事前登録・同時対照・複製ゲート**。別セッション・別Nの数字を突き合わせない。
3. **採否判定はハーネス環境でのみ行う**。Coworkは判定しない。
4. **確定事実の源泉は `docs/agent/confirmed-facts.md` のみ**。旧版（`strategy/archive/retrospective_v1_OBSOLETE_DO_NOT_USE.md`）は参照禁止。
5. **ラダーEloを版比較の判定器に使わない**。ローカル vs ラダーの逆転を実証済み。
6. **全実験はwriteupの1節として回収できること**（dual-purpose原則）。回収できない実験はやらない。

## ルーティング表

| タスク | 担当 | 参照スキル/文書 |
|--------|------|----------------|
| エージェント・デッキの実装 | Cowork | `docs/agent/workflow.md` |
| 対戦シミュレーション・CI計算 | ハーネス環境 | `skills/stochastic-agent-eval/SKILL.md` |
| 戦略立案・writeup執筆 | Fable | `skills/llm-role-handoff/SKILL.md` |
| AI間ハンドオフ文書の作成 | Cowork/Fable | `skills/llm-role-handoff/SKILL.md` |
| デッキ合法性チェック | Cowork（必須） | `scripts/check_deck_legal.py` |
| 発火率監査 | ハーネス環境 | `docs/agent/measurement-protocol.md` |

## docs/agent/ 一覧

| ファイル | 内容 |
|---------|------|
| `project-overview.md` | 目的・締切・賞金・提出状況 |
| `confirmed-facts.md` | 確定した実測事実（数値・CI・N・測定日） |
| `decision-log.md` | 意思決定ログ（理由・根拠・帰結） |
| `measurement-protocol.md` | 測定規律の要約 |
| `workflow.md` | 役割分担・標準フロー |
| `glossary.md` | 用語定義 |
| `repository-structure.md` | ディレクトリ構造の説明 |

## 現在の状態（2026-07-07）

- **現チャンピオン**：lucario v2（運用実績最多）
- **Kaggle Final仮置き**：crustle + v2（手動仮置き要確認）
- **次のアクション**：lucario 対crustle 敗因一次分析（N=100〜200）→ v6設計入力
- **v6昇格ゲート**：`docs/agent/decision-log.md` D-9参照
