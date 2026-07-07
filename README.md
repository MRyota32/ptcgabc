# ポケカABC — Kaggle PTCG AI Battle Challenge

Kaggleのポケモンカード対戦AI大会（ポケカABC）のエージェント開発リポジトリ。  
**Sim締切：2026/8/16 / Strategy締切：2026年9月上旬**

---

## 開発フロー

このプロジェクトは3つのAIセッションが役割分担して動く。

```
┌─────────────┐    依頼文      ┌──────────────┐    tar.gz     ┌───────────────────┐
│    Fable    │ ──────────→  │    Cowork    │ ──────────→  │  評価ハーネス環境  │
│ 考える・書く │  ←────────── │   作る       │  ←────────── │     測る          │
└─────────────┘   戦略・構成   └──────────────┘  勝率・CI結果  └───────────────────┘
```

### Step 1｜設計（Fable）

`prompts/request-strategy.prompt.md` をFableに渡す。  
インプット：`docs/agent/confirmed-facts.md`（実測値）、`docs/agent/decision-log.md`（意思決定）、負けログ。  
アウトプット：改修仮説・事前登録（「主比較・N・判定基準」を文書化）。

### Step 2｜実装（Cowork）

`prompts/request-cowork-build.prompt.md` をCoworkに渡す。

```
agents/lucario/vN/
├── main.py    ← エージェント本体（agent(obs_dict) -> list[int]）
└── deck.csv   ← 60枚のカードID
```

**納品前に必ず実行：**

```bash
python3 scripts/check_deck_legal.py agents/lucario/vN/deck.csv
# errorPlayer: -1 → 合法。それ以外は要調査
```

### Step 3｜測定（評価ハーネス環境）

`prompts/run-meta-measurement.prompt.md` をハーネス環境に渡す。  
`harness/README.md` に詳細。

```
N=400〜1,000 balanced → Wilson CI + 2標本差CIで判定
有意差あり + 複製通過 → 昇格
有意差なし / 複製失敗 → 非昇格（棄却ログを decision-log.md に追記）
```

### Step 4｜記録・提出

```bash
# decision-log.md に判定結果を追記
# 昇格した場合：Kaggle にtar.gzを提出
tar -czf vN.tar.gz -C agents/lucario/vN main.py deck.csv
```

---

## セットアップ

```bash
git clone https://github.com/MRyota32/ptcgabc.git
cd ptcgabc
python3 -m venv .venv
source .venv/bin/activate
pip install kaggle-environments   # cgエンジンが同梱される
```

**エンジンバイナリ**（`engine/libcg.so` / `engine/cg.dll`）はgitignore対象。  
→ `engine/README.md` の手順でKaggle Dataタブから取得すること。

---

## ディレクトリ構造

```
ptcgabc/
├── AGENTS.md               ← ハードルール・ルーティング表（まずここを読む）
├── docs/agent/             ← プロジェクト知識ベース
│   ├── confirmed-facts.md  ← 確定した実測値（唯一の数値源泉）
│   ├── decision-log.md     ← 意思決定ログ
│   └── ...
├── agents/
│   ├── lucario/v2〜v5/     ← ルカリオエージェント各版
│   └── opponents/          ← メタ相手（crustle, zoroark）
├── prompts/                ← 各AIへの再利用依頼テンプレ
├── skills/                 ← stochastic-agent-eval / llm-role-handoff
├── scripts/
│   ├── check_deck_legal.py ← デッキ合法性チェック（納品前必須）
│   └── validate_docs.py    ← リポジトリ整合性チェック
├── experiments/            ← 実験スクリプト・結果
├── harness/                ← 評価ハーネス（cabt_harness.py）
├── writeup/                ← Strategy提出稿
└── strategy/               ← 戦略プラン・棚卸し文書
```

詳細は `docs/agent/repository-structure.md` 参照。

---

## 重要ルール（詳細は `AGENTS.md`）

- デッキ納品前に `scripts/check_deck_legal.py` を必ず実行
- 版比較は N≥400・事前登録・同時対照・複製ゲートを通す
- 採否判定はハーネス環境でのみ行う
- **確定事実は `docs/agent/confirmed-facts.md` が唯一の源泉**（旧版ファイル参照禁止）
- ラダーEloを版比較の判定器に使わない

---

## 現在の状態（2026-07-07）

| 項目 | 状態 |
|------|------|
| 現チャンピオン | lucario v2 |
| Kaggle Final仮置き | crustle + v2（手動選択・要確認） |
| 次のアクション | 対crustle敗因分析 → v6設計 |
| v6昇格ゲート | `docs/agent/decision-log.md` D-9参照 |
| Strategy writeup | `writeup/` にGoogle Driveから取得して配置 |

---

## validate_docs（整合性チェック）

```bash
python3 scripts/validate_docs.py
# ALL PASS → リポジトリ正常
```
