"""ネイティブの盤面・合法手生成(native/shogi_core.c)のバインディング(02_design.md §36)。

現時点ではテストと検証用。合法手の集合がcshogiと一致することを確かめるために使う
(フェーズ36でネイティブ探索がこのコアを内部で使う)。ライブラリが使えなければ
`available()`がFalseを返す。
"""

from __future__ import annotations

import ctypes
from functools import lru_cache
from typing import Optional

from . import native_lib

_BUF_SIZE = 16384


@lru_cache(maxsize=1)
def _library() -> Optional[ctypes.CDLL]:
    lib = native_lib.load_library()
    if lib is None:
        return None
    lib.shogi_core_perft.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.shogi_core_perft.restype = ctypes.c_int64
    lib.shogi_core_legal_moves.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    lib.shogi_core_legal_moves.restype = ctypes.c_int
    lib.shogi_core_apply.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    lib.shogi_core_apply.restype = ctypes.c_int
    return lib


def available() -> bool:
    return _library() is not None


def perft(sfen: str, depth: int) -> int:
    """sfenからdepth手先までの合法手の総数(葉の数)。"""
    result = _library().shogi_core_perft(sfen.encode(), depth)
    if result < 0:
        raise ValueError(f"invalid sfen: {sfen}")
    return result


def legal_moves(sfen: str) -> list[str]:
    """sfenの合法手(USI表記)を返す。順序は不定。"""
    buf = ctypes.create_string_buffer(_BUF_SIZE)
    n = _library().shogi_core_legal_moves(sfen.encode(), buf, _BUF_SIZE)
    if n < 0:
        raise ValueError(f"invalid sfen: {sfen}")
    return buf.value.decode().split()


def apply_moves(sfen: str, usi_moves: list[str]) -> str:
    """sfenにUSI手順を適用した局面のSFEN(手数は1固定)。非合法手があればValueError。"""
    buf = ctypes.create_string_buffer(_BUF_SIZE)
    n = _library().shogi_core_apply(sfen.encode(), " ".join(usi_moves).encode(), buf, _BUF_SIZE)
    if n < 0:
        raise ValueError(f"invalid sfen or illegal move: {sfen} {usi_moves}")
    return buf.value.decode()
