"""将棋対局用MCPサーバー。ツール定義のみを持ち、実処理はrules/usi_engine/kif_storeに委譲する。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import cshogi
from mcp.server.fastmcp import FastMCP

from . import analysis, gui_server, kif_store, presets, rules
from .usi_engine import UsiEngine, UsiEngineError, UsiTimeoutError

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_PATH = REPO_ROOT / "engine" / "YaneuraOu-by-gcc"
GAMES_DIR = REPO_ROOT / "games"

mcp = FastMCP("shogi")


class SessionState:
    """1対局分のGame/エンジンプロセス/KIF保存先をまとめて保持する。"""

    def __init__(
        self,
        difficulty: int,
        user_side: str,
        mode: str,
        kif_path: Optional[Path] = None,
    ):
        preset = presets.get(difficulty)
        self.game = rules.Game()
        self.difficulty = difficulty
        self.user_side = user_side
        self.mode = mode
        self.resigned = False

        self.engine = UsiEngine(
            str(ENGINE_PATH),
            options={
                "USI_Hash": 1024,
                "Threads": preset.threads,
                "USI_Ponder": False,
                "USI_OwnBook": False,
            },
        )
        self.engine.start()

        meta = kif_store.GameMeta(difficulty=difficulty, user_side=user_side, mode=mode)
        self.kif_store = kif_store.KifStore(GAMES_DIR)
        if kif_path is not None:
            self.kif_store.path = Path(kif_path)
            self.kif_store.meta = meta
        else:
            self.kif_store.start(meta)

    def preset(self) -> presets.Difficulty:
        return presets.get(self.difficulty)

    def moves_usi(self) -> list[str]:
        return [cshogi.move_to_usi(m) for m in self.game.board.history]

    def status(self) -> str:
        return "resigned" if self.resigned else self.game.status()

    def is_game_over(self) -> bool:
        return self.resigned or self.game.is_game_over()

    def autosave(self) -> None:
        moves = list(self.game.board.history)
        self.kif_store.save(moves, resigned=self.resigned)

    def close(self) -> None:
        self.engine.quit()


_session: Optional[SessionState] = None
# MCPツール呼び出し(asyncioイベントループ側)とgui_serverのHTTPハンドラ(別スレッド)の
# 両方が_sessionと中のcshogi.Boardを読み書きするため、盤面を変更する箇所と
# GUI用フラグメント生成の両方でこのロックを取得する(02_design.md §7.1)。
_session_lock = threading.Lock()


def _current_session() -> Optional[SessionState]:
    return _session


_STATUS_LABELS = {
    rules.STATUS_CHECKMATE: "詰み",
    rules.STATUS_DRAW_REPETITION: "千日手",
    rules.STATUS_NYUGYOKU: "入玉宣言勝ち",
    "resigned": "投了",
}


def _board_fragment() -> str:
    """gui_serverの`GET /board`が返すHTMLフラグメント(SVG + 手数/手番/終局状態)。"""
    with _session_lock:
        session = _session
        if session is None:
            return gui_server.NO_GAME_FRAGMENT
        svg = session.game.board_svg()
        last_line = session.game.last_move_line()
        status = session.status()

    parts = [svg]
    if last_line is not None:
        parts.append(f"<p>{last_line}</p>")
    label = _STATUS_LABELS.get(status)
    if label is not None:
        parts.append(f"<p><strong>{label}</strong></p>")
    return "\n".join(parts)


def _move_info(m: rules.MoveInfo) -> dict:
    return {"usi": m.usi, "kif": m.kif}


def _state_dict(session: SessionState) -> dict:
    game = session.game
    last = game.last_move()
    return {
        "ok": True,
        "sfen": game.sfen(),
        "board": game.board_display(),
        "board_svg": game.board_svg(),
        "turn": game.turn(),
        "move_number": game.move_number(),
        "legal_moves": [_move_info(m) for m in game.legal_moves()],
        "status": session.status(),
        "in_check": game.in_check(),
        "last_move": _move_info(last) if last else None,
        "user_side": session.user_side,
        "difficulty": session.difficulty,
        "mode": session.mode,
    }


def _think_with_recovery(session: SessionState, **go_kwargs):
    """思考中にエンジンが応答しない/落ちた場合、1回だけ再起動して再試行する。"""
    try:
        return session.engine.go(**go_kwargs)
    except (UsiTimeoutError, UsiEngineError):
        session.engine.restart()
        return session.engine.go(**go_kwargs)


@mcp.tool()
def new_game(difficulty: int = presets.DEFAULT_LEVEL, user_side: str = "black", mode: str = "auto") -> dict:
    """新規対局を開始する。difficultyは1(入門)〜5(最強)、user_sideは"black"/"white"。

    対局中の場合は現在の対局を破棄して新規対局を開始する(直前まではKIFに自動保存済み)。
    """
    global _session
    if user_side not in ("black", "white"):
        return {"ok": False, "error": "invalid_user_side"}
    try:
        presets.get(difficulty)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if mode not in ("auto", "discuss", "user", "brain"):
        return {"ok": False, "error": "invalid_mode"}

    with _session_lock:
        if _session is not None:
            _session.close()
        _session = SessionState(difficulty=difficulty, user_side=user_side, mode=mode)
        result = _state_dict(_session)
        result["kif_path"] = str(_session.kif_store.path)
    return result


@mcp.tool()
def get_state() -> dict:
    """現在の対局状態(SFEN・盤面表示・合法手一覧・終局判定)を返す。"""
    with _session_lock:
        session = _current_session()
        if session is None:
            return {"ok": False, "error": "no_active_game"}
        return _state_dict(session)


@mcp.tool()
def apply_move(move: str) -> dict:
    """指し手(USI表記, 例: 7g7f / P*5e / 2b3a+)を適用する。ユーザー側・Claude側共通で使う。"""
    session = _current_session()
    if session is None:
        return {"ok": False, "error": "no_active_game"}
    if session.is_game_over():
        return {"ok": False, "error": "game_already_over"}

    with _session_lock:
        result = session.game.apply_move(move)
        if not result.ok:
            return {
                "ok": False,
                "error": result.error,
                "candidates": [_move_info(m) for m in (result.candidates or [])],
            }
        session.autosave()
        return _state_dict(session)


@mcp.tool()
def engine_move(byoyomi_ms: int = 0) -> dict:
    """コンピュータ側の手をやねうら王に思考させ、盤面へ反映して返す。

    byoyomi_ms=0の場合は現在の難易度プリセットの秒読みを使う。
    """
    session = _current_session()
    if session is None:
        return {"ok": False, "error": "no_active_game"}
    if session.is_game_over():
        return {"ok": False, "error": "game_already_over"}

    preset = session.preset()
    actual_byoyomi = byoyomi_ms if byoyomi_ms > 0 else preset.byoyomi_ms
    session.engine.set_option("NodesLimit", preset.nodes_limit)
    session.engine.set_option("MultiPV", 1)

    try:
        think = _think_with_recovery(
            session,
            sfen=cshogi.STARTING_SFEN,
            moves=session.moves_usi(),
            byoyomi_ms=actual_byoyomi,
        )
    except (UsiTimeoutError, UsiEngineError) as e:
        return {"ok": False, "error": f"engine_unavailable: {e}"}

    with _session_lock:
        if think.bestmove == "resign":
            result = _state_dict(session)
            result["status"] = "engine_resigned"
            return result
        if think.bestmove == "win":
            result = _state_dict(session)
            result["status"] = "engine_win_nyugyoku"
            return result

        apply_result = session.game.apply_move(think.bestmove)
        if not apply_result.ok:
            return {"ok": False, "error": "engine_returned_illegal_move", "bestmove": think.bestmove}

        session.autosave()
        result = _state_dict(session)
        primary = think.primary
        result["think"] = {
            "score_cp": primary.score_cp if primary else None,
            "score_mate": primary.score_mate if primary else None,
            "pv": primary.pv if primary else [],
        }
        return result


@mcp.tool()
def engine_hint(multipv: int = 3, byoyomi_ms: int = 1000) -> dict:
    """盤面を変えずに候補手上位multipv件と評価値を返す(難易度制限なしのフルパワー設定)。"""
    session = _current_session()
    if session is None:
        return {"ok": False, "error": "no_active_game"}

    session.engine.set_option("NodesLimit", 0)
    session.engine.set_option("MultiPV", multipv)

    try:
        think = _think_with_recovery(
            session,
            sfen=cshogi.STARTING_SFEN,
            moves=session.moves_usi(),
            byoyomi_ms=byoyomi_ms,
        )
    except (UsiTimeoutError, UsiEngineError) as e:
        return {"ok": False, "error": f"engine_unavailable: {e}"}

    candidates = []
    for idx in sorted(think.pvs):
        pv = think.pvs[idx]
        candidates.append(
            {
                "usi": pv.pv[0] if pv.pv else think.bestmove,
                "score_cp": pv.score_cp,
                "score_mate": pv.score_mate,
                "pv": pv.pv,
            }
        )
    return {"ok": True, "candidates": candidates}


def _board_snapshot() -> Optional[cshogi.Board]:
    """解析ツール用に現局面のコピーを取る。解析中に_session_lockを握り続けないための分離。"""
    with _session_lock:
        session = _current_session()
        if session is None:
            return None
        return cshogi.Board(session.game.sfen())


@mcp.tool()
def analyze_position() -> dict:
    """局面の構造化要約を返す(盤面は変更しない)。Claude思考モード(/shogi-brain)用。

    駒割り(material)・持ち駒(hands)・手番側から相手玉への詰み(mate_for_side_to_move)・
    手番側が放置した場合に相手から詰まされるか=詰めろ(mate_threat_against_side_to_move)を含む。
    王手中は詰めろ検出をスキップする(mate_threat_skipped_due_to_check)。
    """
    board = _board_snapshot()
    if board is None:
        return {"ok": False, "error": "no_active_game"}
    result = analysis.analyze(board)
    result["ok"] = True
    return result


@mcp.tool()
def verify_moves(moves: list[str], depth: int = analysis.DEFAULT_SEARCH_DEPTH) -> dict:
    """候補手(USI表記、最大10件)を機械検証する(盤面は変更しない)。Claude思考モード用。

    各候補について、legal(合法か)・is_mate(相手玉が即詰みか)・gives_check(王手か)・
    allows_mate(指した後に相手から自玉への詰みが生じるか=頓死チェック)・
    material_change(双方が材料点上の最善を尽くした場合の材料点差の変化。負なら駒損)・
    reply_pv_usi(その読み筋)を返す。
    """
    board = _board_snapshot()
    if board is None:
        return {"ok": False, "error": "no_active_game"}
    if not moves:
        return {"ok": False, "error": "no_moves_given"}
    depth = max(1, min(4, depth))
    results = analysis.verify_moves(board, moves[:10], depth=depth)
    return {"ok": True, "results": results}


@mcp.tool()
def simulate_line(moves: list[str]) -> dict:
    """読み筋(双方の指し手のUSI表記列)を盤のコピーへ順に適用する(実盤面は変更しない)。

    Claude思考モード用。途中に非合法手があればillegal_moveにその位置と手を返し、
    そこまでを適用した局面のboard(テキスト盤面)・sfen・材料点変化を返す。
    """
    board = _board_snapshot()
    if board is None:
        return {"ok": False, "error": "no_active_game"}
    if not moves:
        return {"ok": False, "error": "no_moves_given"}
    result = analysis.simulate_line(board, moves)
    result["ok"] = True
    return result


@mcp.tool()
def save_kif(path: str = "") -> dict:
    """現在の対局をKIF形式で保存する。pathを省略すると自動保存先に上書き保存する。"""
    session = _current_session()
    if session is None:
        return {"ok": False, "error": "no_active_game"}

    with _session_lock:
        moves = list(session.game.board.history)
        if path:
            target = kif_store.KifStore(GAMES_DIR)
            target.path = Path(path)
            target.meta = kif_store.GameMeta(session.difficulty, session.user_side, session.mode)
            target.save(moves, resigned=session.resigned)
            return {"ok": True, "path": str(target.path)}

        session.autosave()
        return {"ok": True, "path": str(session.kif_store.path)}


@mcp.tool()
def load_kif(path: str) -> dict:
    """保存済みのKIFファイルを読み込み、対局を再開する。"""
    global _session
    kif_path = Path(path)
    if not kif_path.is_absolute() and not kif_path.exists():
        # `ls games/*.kif`等が返す"games/"付きの相対パスと、
        # ファイル名だけの指定(GAMES_DIR基準)の両方を許容する。
        kif_path = GAMES_DIR / kif_path.name

    try:
        loaded = kif_store.KifStore.load(kif_path)
    except Exception as e:
        return {"ok": False, "error": f"failed_to_load_kif: {e}"}

    with _session_lock:
        if _session is not None:
            _session.close()

        new_session = SessionState(
            difficulty=loaded.meta.difficulty,
            user_side=loaded.meta.user_side,
            mode=loaded.meta.mode,
            kif_path=kif_path,
        )
        for move_int in loaded.moves:
            result = new_session.game.apply_move(cshogi.move_to_usi(move_int))
            if not result.ok:
                new_session.close()
                return {"ok": False, "error": f"kif_contains_illegal_move: {cshogi.move_to_usi(move_int)}"}
        new_session.resigned = loaded.resigned

        _session = new_session
        result = _state_dict(_session)
        result["kif_path"] = str(_session.kif_store.path)
        return result


@mcp.tool()
def resign() -> dict:
    """ユーザー側の投了。KIFに記録し対局を終了状態にする。"""
    session = _current_session()
    if session is None:
        return {"ok": False, "error": "no_active_game"}
    if session.is_game_over():
        return {"ok": False, "error": "game_already_over"}

    with _session_lock:
        session.resigned = True
        session.autosave()
        return _state_dict(session)


def main() -> None:
    gui_server.start(_board_fragment)
    mcp.run()


if __name__ == "__main__":
    main()
