"""浅い探索のネイティブ実装(native/shogi_search.c)のバインディング(02_design.md §37)。

`load()`はライブラリが使えなければNone。返す`NativeSearch`から、共有状態(置換表・ヒストリ)の
コンテキストと、`analysis._iterative_deepen`が使うインターフェース(`search`/`nodes`/`truncated`)を
持つ探索器を作る。PVのやり取りはUSI文字列で、cshogiの指し手(int)へ変換する。
"""

from __future__ import annotations

import ctypes
import logging
from typing import Optional, Sequence

import cshogi

from . import native_lib

logger = logging.getLogger(__name__)

_MATE_SCORE = 100_000
_INVALID_SFEN = -_MATE_SCORE * 2
_PV_BUF = 4096

# 無効化フラグ(shogi_search.c と同じ値)。同値性検証用。
NO_TT_CUTOFF = 1
NO_NULL_MOVE = 2
NO_LMR = 4
NO_FUTILITY = 8
NO_QUIESCE_PRUNING = 16
NO_PRUNING = NO_TT_CUTOFF | NO_NULL_MOVE | NO_LMR | NO_FUTILITY | NO_QUIESCE_PRUNING


class NativeContext:
    """置換表・ヒストリ・キラーのネイティブ側の領域。破棄時に解放する。"""

    def __init__(self, lib: ctypes.CDLL):
        self._lib = lib
        self.handle = lib.shogi_ctx_new()
        if not self.handle:
            raise MemoryError("shogi_ctx_new failed")

    def __del__(self) -> None:
        handle, self.handle = getattr(self, "handle", None), None
        if handle:
            self._lib.shogi_ctx_free(ctypes.c_void_p(handle))


class NativeSearcher:
    """`analysis._Searcher`と同じインターフェースのネイティブ探索器。"""

    def __init__(self, lib: ctypes.CDLL, board: cshogi.Board, node_limit: int,
                 context: NativeContext, flags: int = 0):
        self._lib = lib
        self.board = board
        self.node_limit = node_limit
        self.nodes = 0
        self.truncated = False
        self._context = context
        self._flags = flags
        lib.shogi_ctx_new_search(ctypes.c_void_p(context.handle))

    def search(self, depth: int, alpha: int, beta: int) -> tuple[int, list[int]]:
        nodes = ctypes.c_int64(self.nodes)
        truncated = ctypes.c_int(int(self.truncated))
        pv_buf = ctypes.create_string_buffer(_PV_BUF)
        score = self._lib.shogi_search(
            ctypes.c_void_p(self._context.handle), self.board.sfen().encode(), depth, alpha, beta,
            self.node_limit, ctypes.byref(nodes), ctypes.byref(truncated), self._flags, pv_buf, _PV_BUF,
        )
        if score == _INVALID_SFEN:
            raise ValueError(f"native search rejected the position: {self.board.sfen()}")
        self.nodes = nodes.value
        self.truncated = bool(truncated.value)
        return score, self._pv_moves(pv_buf.value.decode().split())

    def _pv_moves(self, usi_moves: list[str]) -> list[int]:
        moves: list[int] = []
        try:
            for usi in usi_moves:
                move = self.board.move_from_usi(usi)
                self.board.push(move)
                moves.append(move)
        finally:
            for _ in moves:
                self.board.pop()
        return moves


class NativeSearch:
    def __init__(self, lib: ctypes.CDLL):
        self._lib = lib

    def new_context(self) -> NativeContext:
        return NativeContext(self._lib)

    def searcher(self, board: cshogi.Board, node_limit: int, context: NativeContext,
                 flags: int = 0) -> NativeSearcher:
        return NativeSearcher(self._lib, board, node_limit, context, flags)


def load(piece_values: Sequence[int]) -> Optional[NativeSearch]:
    """駒種(0..15)→材料点の表を渡してネイティブ探索を初期化する。使えなければNone。"""
    lib = native_lib.load_library()
    if lib is None:
        return None
    try:
        lib.shogi_search_set_piece_values.argtypes = [ctypes.c_void_p]
        lib.shogi_search_set_piece_values.restype = None
        lib.shogi_ctx_new.argtypes = []
        lib.shogi_ctx_new.restype = ctypes.c_void_p
        lib.shogi_ctx_free.argtypes = [ctypes.c_void_p]
        lib.shogi_ctx_free.restype = None
        lib.shogi_ctx_new_search.argtypes = [ctypes.c_void_p]
        lib.shogi_ctx_new_search.restype = None
        lib.shogi_search.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int64,
            ctypes.POINTER(ctypes.c_int64), ctypes.POINTER(ctypes.c_int), ctypes.c_int,
            ctypes.c_char_p, ctypes.c_int,
        ]
        lib.shogi_search.restype = ctypes.c_int
        lib.shogi_search_set_piece_values((ctypes.c_int32 * 16)(*piece_values))
    except (OSError, AttributeError) as exc:
        logger.warning("native search failed to load (%s); using Python implementation", exc)
        return None
    logger.info("native search loaded")
    return NativeSearch(lib)
