"""花札こいこい — エンジン公開モジュール

中身は C++ 実装 (`koikoi_cpp` 経由) を再エクスポートしているだけ。
オリジナルの純 Python 実装は `engine_py.py` に保存してある。

環境変数 `KOIKOI_USE_PY=1` を設定すると、純 Python 実装にフォールバックする
（C++ 拡張がビルドされてない環境や差分検証用）。
"""
import os

if os.environ.get("KOIKOI_USE_PY") == "1":
    # 純 Python 実装にフォールバック
    from engine_py import (  # noqa: F401
        ACTION_KOIKOI,
        ACTION_SHOWDOWN,
        DEFAULT_RULES,
        NUM_ACTIONS,
        NUM_CARDS,
        OBS_SIZE,
        KoikoiEngine,
        Phase,
        rule_based_policy,
    )
else:
    from koikoi_cpp import (  # noqa: F401
        ACTION_KOIKOI,
        ACTION_SHOWDOWN,
        DEFAULT_RULES,
        NUM_ACTIONS,
        NUM_CARDS,
        OBS_SIZE,
        KoikoiEngine,
        Phase,
        rule_based_policy,
    )
