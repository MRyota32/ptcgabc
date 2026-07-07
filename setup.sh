#!/bin/bash
# PTCG AI Battle Challenge - 環境セットアップスクリプト
# 実行: bash setup.sh

set -e
echo "=== PTCGABC 開発環境セットアップ ==="

python3 --version

# 仮想環境作成
python3 -m venv .venv
source .venv/bin/activate

# kaggle-environments インストール (cabt エンジン同梱)
pip install --upgrade pip
pip install kaggle-environments

echo ""
echo "=== インストール完了 ==="
echo "動作確認: python3 test_random.py"
