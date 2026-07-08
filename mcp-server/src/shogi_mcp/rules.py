"""cshogiのラッパー。合法手判定・盤面表示・終局判定をcshogiに委譲する。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cshogi
from cshogi import KIF

_TURN_NAMES = {cshogi.BLACK: "black", cshogi.WHITE: "white"}
_TURN_FROM_NAME = {name: turn for turn, name in _TURN_NAMES.items()}

STATUS_PLAYING = "playing"
STATUS_CHECKMATE = "checkmate"
STATUS_DRAW_REPETITION = "draw_repetition"
STATUS_NYUGYOKU = "nyugyoku"


@dataclass(frozen=True)
class MoveInfo:
    usi: str
    kif: str


@dataclass(frozen=True)
class ApplyMoveResult:
    ok: bool
    error: Optional[str] = None
    candidates: Optional[list[MoveInfo]] = None


class Game:
    """1対局分の状態を保持するラッパー。ルール判断はすべてcshogiに委譲する。"""

    def __init__(self, sfen: Optional[str] = None):
        self.board = cshogi.Board()
        if sfen is not None:
            self.board.set_sfen(sfen)

    # --- 状態参照 -----------------------------------------------------

    def sfen(self) -> str:
        return self.board.sfen()

    def turn(self) -> str:
        return _TURN_NAMES[self.board.turn]

    def move_number(self) -> int:
        return self.board.move_number

    def in_check(self) -> bool:
        return self.board.is_check()

    def legal_moves(self) -> list[MoveInfo]:
        prev_move = self.board.peek() if self.board.move_number > 1 else None
        return [
            MoveInfo(usi=cshogi.move_to_usi(m), kif=KIF.move_to_kif(m, prev_move))
            for m in self.board.legal_moves
        ]

    def last_move(self) -> Optional[MoveInfo]:
        history = self.board.history
        if not history:
            return None
        move = history[-1]
        prev_move = history[-2] if len(history) >= 2 else None
        return MoveInfo(usi=cshogi.move_to_usi(move), kif=KIF.move_to_kif(move, prev_move))

    def board_display(self) -> str:
        lines = [KIF.board_to_bod(self.board)]
        last = self.last_move()
        if last is not None:
            # 直前に指したのは now手番の相手側。次数=現在の手数-1が直前手の着手番号。
            mover_mark = "▲" if self.board.turn == cshogi.WHITE else "△"
            lines.append(f"手数={self.move_number() - 1}  {mover_mark}{last.kif} まで")
        return "\n".join(lines)

    def board_svg(self, scale: float = 2.0) -> str:
        """GUI表示用のSVG文字列。駒配置・成駒表記・直前手ハイライトはcshogiに委譲する。"""
        lastmove = self.board.peek() if self.move_number() > 1 else None
        return str(self.board.to_svg(lastmove=lastmove, scale=scale))

    def status(self) -> str:
        if self.board.is_nyugyoku():
            return STATUS_NYUGYOKU
        if self.board.is_game_over():
            return STATUS_CHECKMATE
        if self.board.is_draw() == cshogi.REPETITION_DRAW:
            return STATUS_DRAW_REPETITION
        return STATUS_PLAYING

    def is_game_over(self) -> bool:
        return self.status() != STATUS_PLAYING

    # --- 局面の変更 -----------------------------------------------------

    def apply_move(self, usi: str) -> ApplyMoveResult:
        move = self.board.move_from_usi(usi)
        if move == 0 or not self.board.is_legal(move):
            return ApplyMoveResult(ok=False, error="illegal_move", candidates=self._similar_candidates(usi))
        self.board.push(move)
        return ApplyMoveResult(ok=True)

    def _similar_candidates(self, usi: str) -> list[MoveInfo]:
        """入力と着手先マスが同じ合法手を、聞き返し用の候補として返す。"""
        target_to = usi.rstrip("+")[-2:]
        prev_move = self.board.peek() if self.board.move_number > 1 else None
        return [
            MoveInfo(usi=cshogi.move_to_usi(m), kif=KIF.move_to_kif(m, prev_move))
            for m in self.board.legal_moves
            if cshogi.move_to_usi(m).rstrip("+")[-2:] == target_to
        ]
