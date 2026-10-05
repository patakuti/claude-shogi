"""評価関数のネイティブ実装(任意)のバインディング(02_design.md §34)。

共有ライブラリは`native_lib`が読み込む。ライブラリが使えない場合は`None`を返し、
呼び出し側(analysis.py)はPython実装を使う(挙動は変わらず速度のみ異なる)。
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
_MAX_STEP = 8
_MAX_RAY_DIR = 8
_MAX_RAY_LEN = 8


def _flatten_tables(step_targets, ray_targets, king_zones):
    step = (ctypes.c_int8 * (_NCODE * _NSQ * _MAX_STEP))(*([-1] * (_NCODE * _NSQ * _MAX_STEP)))
    ray = (ctypes.c_int8 * (_NCODE * _NSQ * _MAX_RAY_DIR * _MAX_RAY_LEN))(
        *([-1] * (_NCODE * _NSQ * _MAX_RAY_DIR * _MAX_RAY_LEN))
    )
    zone = (ctypes.c_uint8 * (_NSQ * _NSQ))()
    for code in range(_NCODE):
        targets = step_targets[code]
        if targets is not None:
            for sq in range(_NSQ):
                for i, t in enumerate(sorted(targets[sq])):
                    step[(code * _NSQ + sq) * _MAX_STEP + i] = t
        paths = ray_targets[code]
        if paths is not None:
            for sq in range(_NSQ):
                for d, (path, _) in enumerate(paths[sq]):
                    for i, t in enumerate(path):
                        ray[((code * _NSQ + sq) * _MAX_RAY_DIR + d) * _MAX_RAY_LEN + i] = t
    for king_sq, squares in enumerate(king_zones):
        for sq in squares:
            zone[king_sq * _NSQ + sq] = 1
    return step, ray, zone


def load(
    step_targets,
    ray_targets,
    king_zones,
    black_value: Sequence[int],
    white_value: Sequence[int],
    hand_value: Sequence[int],
    king_safety_weight: int,
    fallback: Callable[[cshogi.Board], int],
) -> Optional[Callable[[cshogi.Board], int]]:
    """手番側視点の評価関数を返す。使えなければNone。

    玉の座標が範囲外の局面ではfallback(Python実装)に委ねる。
    """
    lib = native_lib.load_library()
    if lib is None:
        return None
    try:
        lib.shogi_init.argtypes = [ctypes.c_void_p] * 6
        lib.shogi_init.restype = None
        lib.shogi_eval_black.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]
        lib.shogi_eval_black.restype = ctypes.c_int32
        step, ray, zone = _flatten_tables(step_targets, ray_targets, king_zones)
        values = ctypes.c_int32 * _NCODE
        lib.shogi_init(
            step, ray, zone,
            values(*black_value), values(*white_value),
            (ctypes.c_int32 * 7)(*hand_value),
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
        score = eval_black(
            bytes(board.pieces), bytes(hand_black + hand_white),
            black_king, white_king, king_safety_weight,
        )
        return score if board.turn == black_color else -score

    logger.info("native eval loaded")
    return evaluate
