"""KIF形式での対局保存・読込。1手ごとの自動保存(セッション断からの再開用)を担う。

入出力はcshogi.KIF.Exporter/Parserに委譲する。cshogiのExporter.end()は
投了(resign)・持将棋(draw)・千日手(sennichite)・入玉宣言(win)・反則手のみを
扱い、詰み(checkmate)専用の表記を持たない。詰み・千日手・入玉宣言は指し手の
履歴を再生してrules.Game.status()で再判定すれば復元できるため、
KIFへの明示的な終局宣言が必要なのは「ユーザーの投了」だけである。

難易度・手番・モードはKIFの棋譜情報として表現する手段がcshogiにないため、
最初の指し手より前のコメント行(`*`で始まる行)に埋め込む。この行は
cshogi.KIF.Parserがヘッダーコメント(`comment`属性)としてそのまま読み戻せる。

各指し手への注釈(エンジン評価値・Claudeのコメント、02_design.md §12)は、
指し手行の直後の`*`コメント行として書き込む。Parserは`comments`属性で
手数と同じ長さのリスト(コメント無しの手は`None`、複数行は`\n`連結)を返す
ことを実測確認済み(§12.1)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from cshogi import KIF

_META_RE = re.compile(
    r"difficulty:(\d+)\s+user_side:(black|white)\s+mode:(\S+)(?:\s+model:(.*))?"
)

# KIFはcp932で書き出される。エンコードできない文字(絵文字等)があると
# Exporterのwriteが失敗するため、書き込み前に置換する。
_KIF_ENCODING = "cp932"


class KifStoreError(Exception):
    pass


@dataclass(frozen=True)
class GameMeta:
    difficulty: int
    user_side: str  # "black" | "white"
    mode: str  # "auto" | "discuss" | "user" | "brain"
    # Claude自身が申告するモデル名(例:"Sonnet 5"。02_design.md §23)。
    # MCPサーバー側では自動判別できないため、new_gameの呼び出し側(スラッシュコマンド)が渡す。
    # 空文字は「未申告」を表し、対局者名にはモデル名を含めない(旧KIFとの後方互換)。
    model_name: str = ""


# ユーザー側の対局者名(モード別)。自動/対話はエンジンヒント併用だが、
# 手の決定主体としてClaudeと表記する(02_design.md §13.6)。
# csa(フェーズ24): ユーザー側=CSA対応クライアント経由の人間本人(02_design.md §26.6)。
_MODE_PLAYER_NAMES = {
    "auto": "Claude(自動)",
    "discuss": "Claude(対話)",
    "user": "ユーザー",
    "brain": "Claude(思考)",
    "csa": "ユーザー(CSA)",
}


def player_names(meta: GameMeta) -> tuple[str, str]:
    """メタ情報から(先手名, 後手名)を導出する(02_design.md §13.6, §23, §26.6)。"""
    user_name = _MODE_PLAYER_NAMES.get(meta.mode, meta.mode)
    if meta.model_name and user_name.startswith("Claude"):
        # 「Claude(思考)」→「Claude Sonnet 5(思考)」のように、Claudeが手の決定主体の
        # モードに限りモデル名を挿入する(user modeの「ユーザー」表記は対象外)。
        user_name = "Claude " + meta.model_name + user_name[len("Claude") :]
    if meta.mode == "csa":
        # csaモードは対局相手側もUSIエンジンではなくClaude(思考)が担う(§26.6)。
        opponent_name = "Claude(思考)"
        if meta.model_name:
            opponent_name = "Claude " + meta.model_name + "(思考)"
    else:
        opponent_name = f"やねうら王 Lv{meta.difficulty}"
    if meta.user_side == "black":
        return user_name, opponent_name
    return opponent_name, user_name


@dataclass(frozen=True)
class LoadedGame:
    meta: GameMeta
    moves: list[int]
    resigned: bool
    comments: dict[int, list[str]] = field(default_factory=dict)  # 手数(1始まり)→コメント行


def _sanitize_comment_line(line: str) -> str:
    """cp932にエンコードできない文字を置換し、KIF書き込みで落ちないようにする。"""
    return line.encode(_KIF_ENCODING, errors="replace").decode(_KIF_ENCODING)


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

    def save(
        self,
        moves: list[int],
        resigned: bool = False,
        comments: Optional[dict[int, list[str]]] = None,
    ) -> None:
        """現在までの指し手全体でKIFファイルを書き直す(自動保存)。

        1手ずつ追記するのではなく毎回全体を書き直す。指し手数は対局として
        現実的な範囲(数百手程度)であり、Exporterへ渡す情報(直前手・手数)を
        自前で追跡する複雑さを避けるほうを優先した。

        commentsは手数(1始まり)→コメント行のリスト。各行は指し手行の直後に
        `*`を前置して書き込む(02_design.md §12.2)。
        """
        if self.path is None or self.meta is None:
            raise KifStoreError("KIF file is not started; call start() first")
        comments = comments or {}

        exporter = KIF.Exporter(str(self.path))
        try:
            exporter.header(names=list(player_names(self.meta)))
            meta_line = (
                f"*difficulty:{self.meta.difficulty} "
                f"user_side:{self.meta.user_side} "
                f"mode:{self.meta.mode}"
            )
            if self.meta.model_name:
                meta_line += f" model:{self.meta.model_name}"
            exporter.kifu.write(meta_line + "\n")
            for number, move in enumerate(moves, start=1):
                exporter.move(move)
                for line in comments.get(number, []):
                    for part in line.splitlines() or [""]:
                        exporter.kifu.write(f"*{_sanitize_comment_line(part)}\n")
            if resigned:
                exporter.end("resign")
        finally:
            exporter.close()

    @staticmethod
    def load(path: Path) -> LoadedGame:
        """KIFファイルを読み込み、指し手列とメタ情報・コメントを返す。"""
        parser = KIF.Parser.parse_file(str(path))
        m = _META_RE.search(parser.comment or "")
        if not m:
            raise KifStoreError(f"metadata comment not found in {path}")
        meta = GameMeta(
            difficulty=int(m.group(1)),
            user_side=m.group(2),
            mode=m.group(3),
            model_name=(m.group(4) or "").strip(),
        )
        resigned = parser.endgame == "%TORYO"
        comments: dict[int, list[str]] = {}
        for index, comment in enumerate(getattr(parser, "comments", []) or []):
            if comment:
                comments[index + 1] = comment.split("\n")
        return LoadedGame(meta=meta, moves=parser.moves, resigned=resigned, comments=comments)
