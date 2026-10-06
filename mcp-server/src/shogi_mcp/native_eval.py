"""評価関数のネイティブ実装(任意)のバインディング(02_design.md §34, §37)。

共有ライブラリは`native_lib`が読み込む。ライブラリが使えない場合は`None`を返し、
呼び出し側(analysis.py)はPython実装を使う(挙動は変わらず速度のみ異なる)。
利きの定義はC側(shogi_core.c)の駒の動きの表を使い、Pythonは駒の価値・持ち駒の価値・
玉の危険度の重み(analysis.EvalWeights)だけを渡す。
"""

from __future__ import annotations

import ctypes
import logging
from typing import Callable, Optional, Sequence

import cshogi

from . import native_lib

logger = logging.getLogger(__name__)

_NCODE = 32
_NSQ = 81


def load(
    black_value: Sequence[int],
    white_value: Sequence[int],
    hand_value: Sequence[int],
    weights: Sequence[int],
    fallback: Callable[[cshogi.Board], int],
) -> Optional[Callable[[cshogi.Board], int]]:
    """手番側視点の評価関数を返す。使えなければNone。

    玉の座標が範囲外の局面ではfallback(Python実装)に委ねる。
    """
    lib = native_lib.load_library()
    if lib is None:
        return None
    try:
        values = ctypes.c_int32 * _NCODE
        lib.shogi_init.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        lib.shogi_init.restype = None
        lib.shogi_eval_black.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        lib.shogi_eval_black.restype = ctypes.c_int32
        lib.shogi_init(
            values(*black_value), values(*white_value),
            (ctypes.c_int32 * 7)(*hand_value), (ctypes.c_int32 * 5)(*weights),
        )
    except (OSError, AttributeError) as exc:
        logger.warning("native eval failed to load (%s); using Python implementation", exc)
        return None

    eval_black = lib.shogi_eval_black
    black_color = cshogi.BLACK

    def evaluate(board: cshogi.Board) -> int:
        black_king = board.king_square(cshogi.BLACK)
        white_king = board.king_square(cshogi.WHITE)
        if not (0 <= black_king < _NSQ and 0 <= white_king < _NSQ):
            return fallback(board)
        hand_black, hand_white = board.pieces_in_hand
        score = eval_black(bytes(board.pieces), bytes(hand_black + hand_white), black_king, white_king)
        return score if board.turn == black_color else -score

    logger.info("native eval loaded")
    return evaluate
