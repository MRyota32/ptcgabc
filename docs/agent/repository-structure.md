# リポジトリ構造

```
ptcgabc/
├── AGENTS.md                        # 薄いルーター：ハードルール・ルーティング表・docs一覧
├── README.md                        # セットアップ・実行方法
├── .gitignore                       # *.so, *.dll, *.tar.gz, __pycache__, .venv
│
├── docs/agent/                      # プロジェクト固有知識（AIが読む）
│   ├── project-overview.md          # 目的・締切・賞金・Kaggle提出状況
│   ├── repository-structure.md      # 本ファイル
│   ├── confirmed-facts.md           # 確定した実測事実（数値・CI・N・測定日つき）
│   ├── measurement-protocol.md      # 測定規律の要約
│   ├── workflow.md                  # 役割分担・標準フロー
│   ├── glossary.md                  # 用語定義
│   └── decision-log.md              # 意思決定の記録（理由・根拠・帰結）
│
├── agents/
│   ├── lucario/
│   │   ├── v2/  main.py + agent.py + deck.csv   ← 現チャンピオン（運用実績最多）
│   │   ├── v3/  main.py + deck.csv               ← Search API統合版
│   │   ├── v4/  main.py + deck.csv               ← 瀕死ロジック（dead weight）
│   │   └── v5/  main.py + deck.csv               ← 後攻改善試み（非昇格・ローカルのみ）
│   ├── opponents/
│   │   ├── crustle/  main.py + deck.csv + check_deck.py   ← メタ相手#1（stall）
│   │   └── zoroark/  main.py + agent.py + deck.csv + check_deck.py  ← メタ相手#2（counter-aggro）
│   └── ablations/
│       └── lucario_agent_pre_v5.py  # v5開発前の参照用
│
├── engine/                          # cg エンジン一式
│   ├── __init__.py
│   ├── game.py
│   ├── sim.py
│   ├── libcg.so  ← .gitignore対象（Kaggle Dataタブから取得）
│   ├── cg.dll    ← .gitignore対象（同上）
│   └── README.md  # 取得元・セットアップ手順
│
├── harness/
│   └── README.md  # cabt_harness.py の説明・取得元（ハーネス環境に存在・ローカル不在）
│
├── experiments/
│   ├── scripts/                     # 実験スクリプト（NNN_purpose.py の命名推奨）
│   │   ├── test_agent.py
│   │   ├── test_agent2.py
│   │   └── test_random.py
│   └── results/                     # マッチアップ表・ログ（CSV/MD）
│
├── prompts/                         # 再利用する依頼プロンプト
│   ├── request-red-team-review.prompt.md
│   ├── request-strategy.prompt.md
│   ├── request-cowork-build.prompt.md
│   └── run-meta-measurement.prompt.md
│
├── skills/                          # AIスキル（stochastic-agent-eval / llm-role-handoff）
│   ├── stochastic-agent-eval/SKILL.md
│   └── llm-role-handoff/SKILL.md
│
├── scripts/                         # 機械的検査（コードで担保するルール）
│   ├── check_deck_legal.py          # battle_start でデッキ合法性確認（必須）
│   └── validate_docs.py             # 必須ファイルの存在確認
│
├── writeup/                         # Strategy提出稿（Hackathon track）
│   └── strategy_writeup_v2_corrected.md  ← Google Driveより取得・要配置
│
└── strategy/                        # 戦略プラン・AI間入出力
    ├── ptcgabc_strategy_plan.md
    └── archive/
        └── retrospective_v1_OBSOLETE_DO_NOT_USE.md  ← 偽陽性含む旧版・使用禁止
```

## 主要ルール（AGENTS.mdより）

1. デッキ納品前に必ず `scripts/check_deck_legal.py` を実行（errorPlayer==-1 を確認）
2. 版比較は N≥400・事前登録・同時対照・複製ゲートを通す
3. 測定の採否判定はハーネス側でのみ行う（Coworkが判定しない）
4. 確定事実の源泉は `docs/agent/confirmed-facts.md`（旧版ファイルを使わない）
