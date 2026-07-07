# engine/ — cgエンジン

## 取得元

Kaggle PTCG AI Battle Challenge の Data タブにある `sample_submission.zip` に同梱。

```
Kaggle → Competitions → PTCG AI Battle Challenge → Data → sample_submission.zip
```

解凍後、`cg/` フォルダの中身をこのディレクトリに配置：

```bash
unzip sample_submission.zip
cp cg/__init__.py cg/game.py cg/sim.py engine/
cp cg/libcg.so engine/    # Linux
cp cg/cg.dll engine/      # Windows
```

## バイナリについて

`libcg.so`（Linux）と `cg.dll`（Windows）は `.gitignore` 対象。コミットしない。

## 使用方法

```python
import sys
sys.path.insert(0, ".")  # ptcgabc/ ルートから
from engine import game

obs, start = game.battle_start(deck0, deck1)
# start.errorPlayer == -1 なら合法
```
