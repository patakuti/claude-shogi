"""ネイティブ実装(任意)の共有ライブラリのローダー(02_design.md §34, §36)。

`scripts/build_native.sh`が生成する`libshogi_native.so`を`ctypes`で1回だけ読み込む。
ライブラリがない・読めない・`SHOGI_MCP_NATIVE=0`の場合は`None`を返し、呼び出し側は
Python実装を使う(挙動は変わらず速度のみ異なる)。評価関数・盤面と合法手生成・探索の
各ネイティブ実装がこのローダーを共有する。
"""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LIB_PATH = Path(__file__).parent / "_native" / "libshogi_native.so"


def enabled() -> bool:
    """ライブラリがビルド済みで、環境変数で無効化されていないか(ログは出さない)。"""
    return os.environ.get("SHOGI_MCP_NATIVE") != "0" and LIB_PATH.exists()


def load_library() -> Optional[ctypes.CDLL]:
    """共有ライブラリを読み込んで返す。使えなければ理由をログに出してNone。

    呼び出しごとに`ctypes.CDLL`を作る(同じライブラリは共有される)。呼び出し側が
    起動時に1回だけ呼ぶこと。
    """
    if os.environ.get("SHOGI_MCP_NATIVE") == "0":
        logger.info("native library disabled by SHOGI_MCP_NATIVE=0; using Python implementation")
        return None
    if not LIB_PATH.exists():
        logger.warning(
            "native library not built (%s); using the slower Python implementation "
            "(run scripts/build_native.sh to enable it)",
            LIB_PATH,
        )
        return None
    try:
        return ctypes.CDLL(str(LIB_PATH))
    except OSError as exc:
        logger.warning("native library failed to load (%s); using Python implementation", exc)
        return None
