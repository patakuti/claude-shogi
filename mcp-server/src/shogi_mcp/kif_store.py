"""KIF形式での対局保存・読込。1手ごとの自動保存(セッション断からの再開用)を担う。

入出力はcshogi.KIF.Exporter/Parserに委譲する。cshogiのExporter.end()は
投了(resign)・持将棋(draw)・千日手(sennichite)・入玉宣言(win)・反則手のみを
扱い、詰み(checkmate)専用の表記を持たない。詰み・千日手・入玉宣言は指し手の
履歴を再生してrules.Game.status()で再判定すれば復元できるため、
KIFへの明示的な終局宣言が必要なのは「ユーザーの投了」だけである。

難易度・手番・モードはKIFの棋譜情報として表現する手段がcshogiにないため、
最初の指し手より前のコメント行(`*`で始まる行)に埋め込む。この行は
cshogi.KIF.Parserがヘッダーコメント(`comment`属性)としてそのまま読み戻せる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from cshogi import KIF

_META_RE = re.compile(r"difficulty:(\d+)\s+user_side:(black|white)\s+mode:(\S+)")


class KifStoreError(Exception):
    pass


@dataclass(frozen=True)
class GameMeta:
    difficulty: int
    user_side: str  # "black" | "white"
    mode: str  # "auto" | "discuss" | "user"


@dataclass(frozen=True)
class LoadedGame:
    meta: GameMeta
    moves: list[int]
    resigned: bool


class KifStore:
    """1対局分のKIF自動保存を担当する。"""

    def __init__(self, games_dir: Path):
        self.games_dir = Path(games_dir)
        self.games_dir.mkdir(parents=True, exist_ok=True)
        self.path: Optional[Path] = None
        self.meta: Optional[GameMeta] = None

    def start(self, meta: GameMeta, path: Optional[Path] = None) -> Path:
        """新規対局用のKIFファイルを作成する。"""
        if path is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            path = self.games_dir / f"{timestamp}.kif"
        self.path = Path(path)
        self.meta = meta
        self.save(moves=[], resigned=False)
        return self.path

    def save(self, moves: list[int], resigned: bool = False) -> None:
        """現在までの指し手全体でKIFファイルを書き直す(自動保存)。

        1手ずつ追記するのではなく毎回全体を書き直す。指し手数は対局として
        現実的な範囲(数百手程度)であり、Exporterへ渡す情報(直前手・手数)を
        自前で追跡する複雑さを避けるほうを優先した。
        """
        if self.path is None or self.meta is None:
            raise KifStoreError("KIF file is not started; call start() first")

        exporter = KIF.Exporter(str(self.path))
        try:
            exporter.header(names=["先手", "後手"])
            exporter.kifu.write(
                f"*difficulty:{self.meta.difficulty} "
                f"user_side:{self.meta.user_side} "
                f"mode:{self.meta.mode}\n"
            )
            for move in moves:
                exporter.move(move)
            if resigned:
                exporter.end("resign")
        finally:
            exporter.close()

    @staticmethod
    def load(path: Path) -> LoadedGame:
        """KIFファイルを読み込み、指し手列とメタ情報を返す。"""
        parser = KIF.Parser.parse_file(str(path))
        m = _META_RE.search(parser.comment or "")
        if not m:
            raise KifStoreError(f"metadata comment not found in {path}")
        meta = GameMeta(
            difficulty=int(m.group(1)),
            user_side=m.group(2),
            mode=m.group(3),
        )
        resigned = parser.endgame == "%TORYO"
        return LoadedGame(meta=meta, moves=parser.moves, resigned=resigned)
