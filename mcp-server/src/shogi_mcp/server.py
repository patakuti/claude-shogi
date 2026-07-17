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
        model_name: str = "",
    ):
        preset = presets.get(difficulty)
        self.game = rules.Game()
        self.difficulty = difficulty
        self.user_side = user_side
        self.mode = mode
        self.model_name = model_name
        self.resigned = False
        # 手数(1始まり)→その手に付けるKIFコメント行(エンジン評価値・Claudeコメント、02_design.md §12)
        self.comments: dict[int, list[str]] = {}

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

        meta = kif_store.GameMeta(
            difficulty=difficulty, user_side=user_side, mode=mode, model_name=model_name
        )
        self.kif_store = kif_store.KifStore(GAMES_DIR)
        if kif_path is not None:
            self.kif_store.path = Path(kif_path)
            self.kif_store.meta = meta
        else:
            self.kif_store.start(meta)

    def preset(self) -> presets.Difficulty:
        return presets.get(self.difficulty)

    def player_names(self) -> tuple[str, str]:
        """(先手名, 後手名)。メタ情報から導出する(02_design.md §13.6, §23)。"""
        meta = kif_store.GameMeta(self.difficulty, self.user_side, self.mode, self.model_name)
        return kif_store.player_names(meta)

    def moves_usi(self) -> list[str]:
        return [cshogi.move_to_usi(m) for m in self.game.board.history]

    def status(self) -> str:
        return "resigned" if self.resigned else self.game.status()

    def is_game_over(self) -> bool:
        return self.resigned or self.game.is_game_over()

    def add_comment_lines(self, move_number: int, lines: list[str]) -> None:
        self.comments.setdefault(move_number, []).extend(lines)

    def last_move_number(self) -> int:
        """直前に指された手の手数(1始まり)。まだ1手も指されていなければ0。"""
        return len(self.game.board.history)

    def autosave(self) -> None:
        moves = list(self.game.board.history)
        self.kif_store.save(moves, resigned=self.resigned, comments=self.comments)

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
    """gui_serverの`GET /board`が返すHTMLフラグメント(SVG + 対局者名 + 手数/手番/終局状態)。"""
    with _session_lock:
        session = _session
        if session is None:
            return gui_server.NO_GAME_FRAGMENT
        svg = session.game.board_svg()
        last_line = session.game.last_move_line()
        status = session.status()
        black_name, white_name = session.player_names()

    parts = [svg, f"<p>▲{black_name} △{white_name}</p>"]
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
        "turn": game.turn(),
        "move_number": game.move_number(),
        "legal_moves": [_move_info(m) for m in game.legal_moves()],
        "status": session.status(),
        "in_check": game.in_check(),
        "last_move": _move_info(last) if last else None,
        "user_side": session.user_side,
        "difficulty": session.difficulty,
        "mode": session.mode,
        "players": dict(zip(("black", "white"), session.player_names())),
    }


def _attack_report(session: SessionState) -> dict:
    """現局面のuser_side/エンジン側それぞれの駒への当たり一覧(§14.2)。

    user_pieces=放置すると取られる警告、engine_pieces=取れる駒の機会。
    """
    board = cshogi.Board(session.game.sfen())
    user_color = cshogi.BLACK if session.user_side == "black" else cshogi.WHITE
    engine_color = cshogi.WHITE if user_color == cshogi.BLACK else cshogi.BLACK
    return {
        "user_pieces": analysis.attacked_pieces(board, color=user_color),
        "engine_pieces": analysis.attacked_pieces(board, color=engine_color),
    }


def _eval_comment_line(primary, mover: str) -> Optional[str]:
    """engine_moveの思考結果からKIFコメント用の評価値行を作る(02_design.md §12.2)。

    エンジンの評価値は手番側(=mover)視点なので、先手有利=正へ符号を正規化する。
    pvは肥大化を防ぐため先頭6手まで。評価値が無ければNone。
    """
    if primary is None:
        return None
    sign = 1 if mover == "black" else -1
    if primary.score_mate is not None:
        eval_part = f"mate:{sign * primary.score_mate}"
    elif primary.score_cp is not None:
        eval_part = f"cp:{sign * primary.score_cp}"
    else:
        return None
    line = f"eval {eval_part}"
    if primary.pv:
        line += " pv:" + " ".join(primary.pv[:6])
    return line


def _think_with_recovery(session: SessionState, **go_kwargs):
    """思考中にエンジンが応答しない/落ちた場合、1回だけ再起動して再試行する。"""
    try:
        return session.engine.go(**go_kwargs)
    except (UsiTimeoutError, UsiEngineError):
        session.engine.restart()
        return session.engine.go(**go_kwargs)


@mcp.tool()
def new_game(
    difficulty: int = presets.DEFAULT_LEVEL,
    user_side: str = "black",
    mode: str = "auto",
    model_name: str = "",
) -> dict:
    """新規対局を開始する。difficultyは1(入門)〜5(最強)、user_sideは"black"/"white"。

    対局中の場合は現在の対局を破棄して新規対局を開始する(直前まではKIFに自動保存済み)。
    model_nameは手の決定主体がClaude自身のモード(auto/discuss/brain)で、Claude自身の
    モデル名(例:"Sonnet 5")を渡すとKIFの対局者名に含める(例:「Claude Sonnet 5(思考)」)。
    MCPサーバー側ではモデル名を自動判別できないため呼び出し側の自己申告に依存する。
    空文字(既定)なら従来どおりモデル名なしの表記のまま(§23)。
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
        _session = SessionState(
            difficulty=difficulty, user_side=user_side, mode=mode, model_name=model_name
        )
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
def apply_move(move: str, comment: str = "") -> dict:
    """指し手(USI表記, 例: 7g7f / P*5e / 2b3a+)を適用する。ユーザー側・Claude側共通で使う。

    commentが非空なら、この手へのコメント(狙い・読みなど)としてKIFに記録する
    (KIF標準の`*`コメント行。振り返り再生 http://localhost:8765/replay で表示される)。
    応答にはattack_report(§14.2。user_pieces=放置すると取られる警告、
    engine_pieces=取れる駒の機会。king_only_defense=紐が玉のみであることを示す、
    §19.1)を毎回含む。
    """
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
        if comment:
            session.add_comment_lines(session.last_move_number(), [comment])
        session.autosave()
        state = _state_dict(session)
        state["attack_report"] = _attack_report(session)
        return state


@mcp.tool()
def engine_move(byoyomi_ms: int = 0) -> dict:
    """コンピュータ側の手をやねうら王に思考させ、盤面へ反映して返す。

    byoyomi_ms=0の場合は現在の難易度プリセットの秒読みを使う。
    応答にはattack_report(§14.2。user_pieces=放置すると取られる警告、
    engine_pieces=取れる駒の機会。king_only_defense=紐が玉のみであることを示す、
    §19.1)を毎回含む。
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

        mover = session.game.turn()  # 適用前の手番=エンジン側(評価値の符号正規化に使う)
        apply_result = session.game.apply_move(think.bestmove)
        if not apply_result.ok:
            return {"ok": False, "error": "engine_returned_illegal_move", "bestmove": think.bestmove}

        eval_line = _eval_comment_line(think.primary, mover)
        if eval_line is not None:
            session.add_comment_lines(session.last_move_number(), [eval_line])
        session.autosave()
        result = _state_dict(session)
        primary = think.primary
        result["think"] = {
            "score_cp": primary.score_cp if primary else None,
            "score_mate": primary.score_mate if primary else None,
            "pv": primary.pv if primary else [],
        }
        result["attack_report"] = _attack_report(session)
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
    手番側が放置した場合に相手から詰まされるか=詰めろ(mate_threat_against_side_to_move)・
    手番側の駒への当たり一覧(attacked_pieces。相手の利き数/味方の紐の数/浮き駒かどうか。
    相手の持ち駒の歩による当たりを示すpawn_drop_riskも含む、§15.1)を含む。
    king_only_defense(§19.1)は、紐が1つ以上あり、かつその全てが自玉である場合に
    true。実際に取り返すと玉自身が危険になる特殊なケースで、hanging(紐なし)と同様に
    実質的な無防備として扱うべき(hangingとは排他)。
    王手中は詰めろ検出の代わりに全回避手を個別検証し、回避後も詰みが残らない手を返す
    (check_evasions.safe_usi。all_allow_mate=trueなら受けなし)。
    major_piece_drop_threats(§17.1、盤上前進版は§21.1)は、自陣3段目以内の紐なし
    マスへの相手の飛・角の安全な打ち込み、または盤上に既にある相手の未成りの飛・角の
    自陣3段目以内への前進が、成り込みと組み合わさって王手・両取り・安全な当たりに
    発展する脅威の一覧([{square, piece, source, patterns, example_move_usi}, ...])。
    source(§21.1)は打ち込み由来なら"drop"(squareは打ち込み先)、盤上の駒の前進
    由来なら"board"(squareはその駒の現在地)。既に成っている駒(龍・馬)はsource:
    "board"の対象外。王手中は空リスト。
    trapped_major_pieces(§18.1)は、盤上に既にある相手の飛・角(成りを含む: 龍・馬)の
    うち、合法な移動先の全てに手番側の利きが及んでいて安全に逃げられない駒の一覧
    ([{square, piece, legal_move_count, attackers}, ...])。合法な移動先が一つもない
    (完全に動けない)駒はlegal_move_count: 0で含まれる。attackers(§20.3)はその駒へ
    現在実際に利いている手番側の駒数(0は退避不可だがまだ当たっていない、1以上は
    既に当たっており無償捕獲できる可能性が高いことを示す)。打ち込み(持ち駒からの
    新規配置)は対象外。静的な利き数のみの判定でピンや取り合いの最終損得は考慮
    しない。王手中は空リスト。
    major_piece_fork_opportunities(§24.1)は、手番側の持ち駒にある飛・角の打ち込み、
    または盤上の未成りの飛・角の移動が、単純な両取り(王手も成りも伴わない)になる
    機会の一覧([{square, piece, source, targets, example_move_usi}, ...])。
    sourceは打ち込み由来なら"drop"、盤上の駒の移動由来なら"board"。targetsは
    両取りされる相手の駒(2件以上、玉は含まない)。王手を伴う両取りはallows_mate/
    check_evasionsの範疇、成り込みを伴う打ち込みはmajor_piece_drop_threatsの
    範疇であり、本フィールドは両者と重複しない「単純な両取り」のみを対象とする。
    紐が1つでもあればその駒は対象から外れる(ピン・取り合いの最終損得は考慮
    しない、§17.1と同じ既知の限界)。王手中は空リスト。
    king_safety(§22.4)は手番側視点の玉の安全度の要約。own_shelter_countは自玉に
    隣接する自分の金・銀(金と同格の成駒を含む)の数、opponent_hand_valueは相手の
    持ち駒の合計価値(既存の駒価値換算)。material(駒割り)だけでは見えない、
    「駒得していても玉が薄く、相手の攻撃力が蓄積している」状態を数値で確認できる
    (王手中でも他のフィールドと異なり空にならず、通常どおり計算される)。判断の
    重み付け自体は呼び出し側に委ねる。
    """
    board = _board_snapshot()
    if board is None:
        return {"ok": False, "error": "no_active_game"}
    result = analysis.analyze(board)
    result["ok"] = True
    return result


@mcp.tool()
def verify_moves(
    moves: list[str],
    depth: int = analysis.DEFAULT_SEARCH_DEPTH,
    node_limit: int = analysis.DEFAULT_NODE_LIMIT,
    mate_ply: int = analysis.DEFAULT_MATE_PLY,
) -> dict:
    """候補手(USI表記、最大10件)を機械検証する(盤面は変更しない)。Claude思考モード用。

    各候補について、legal(合法か)・is_mate(相手玉が即詰みか)・gives_check(王手か)・
    allows_mate(指した後に相手から自玉への詰みが生じるか=頓死チェック)・
    destination(移動先/打ち込み先マスへの相手の利き数opponent_effectsと味方の紐数
    own_supports。opponent_effects>0かつown_supports==0はタダ捨ての警告)・
    own_attacked_after(着手直後の自駒への当たり上位5件。§13.3のattacked_pieces形式。
    盤上の利きに加え、相手の持ち駒の歩による当たりも`pawn_drop_risk`で示す。§15.1。
    king_only_defenseは紐が玉のみであることを示す、§19.1)・
    search_depth_completed(反復深化で完了した深さ。0なら信頼できる読みなし)・
    material_change(双方が材料点上の最善を尽くした場合の材料点差の変化。負なら駒損。
    search_depth_completed==0のときはnull)・reply_pv_usi(その読み筋)を返す。
    destination/own_attacked_afterはis_mateの候補には付けない。
    node_limit(§15.2): 候補ごとの探索ノード予算。既定値は数秒以内の応答を保証する
    従来値のまま。合法手が多く読みが浅くなりがちな複雑な局面で、重要な判断の前だけ
    大きく指定すると、より完了率の高い(信頼できる)読みが得られる(応答時間とのトレードオフ)。
    major_piece_trade(§16.1): この手、または読み筋(reply_pv_usi)のどこかで
    飛・角(成りを含む、龍・馬も対象)が捕られるかを示す真偽値。自分・相手どちらの
    大駒が捕られる場合も対象で、取る/取られるや成り/不成は区別しない。
    search_depth_completed==0のときは読み筋側の将来の大駒交換は検出できず、
    候補手自体の捕り駒のみで判定する(material_changeがnullになるのと同じ制約)。
    本ツールは局面フェーズ(序盤/中盤/終盤)を判定しない。大駒交換をなるべく
    避けたいのは序盤・中盤に限るといった運用判断は呼び出し側(get_state等と
    併用)で行うこと。
    major_piece_drop_threats_after/trapped_major_pieces_after(§20.2): この手を
    指した直後(応手を読む前)の局面に対するmajor_piece_drop_threats/
    trapped_major_pieces(この手を指す側=自分視点、攻撃側=自分)。前者が非空は
    この手が新たな大駒打ち込み・前進の脅威を自ら生むことを(source§21.1で
    出所を区別)、後者が非空は相手の飛・角を捕獲確定に追い込めることを示す。
    どちらもown_attacked_afterと同様、is_mateの候補には付けない。
    own_trapped_major_pieces_after(§21.2): trapped_major_piecesを攻守逆転
    (攻撃側=相手、防御側=自分)で呼んだ結果。空でなければ、この手を指した
    直後に自分の飛・角(成りを含む)が捕獲確定(トラップ)になっていることを
    示す(候補手を選ぶ際は原則避けるべき)。is_mateの候補には付けない。
    own_king_shelter_after(§22.2): 自玉に隣接する自分の金・銀(金と同格の
    成駒を含む)の数を、immediately_after(着手直後)/after_pv(読み筋
    reply_pv_usiを最後まで適用した後)の2値で返す。after_pvがimmediately_after
    より減っていれば、材料点変化が同等でも読み筋の途中で玉の守備駒が
    引き剥がされることを示す。search_depth_completed==0のときafter_pvはnull
    (material_changeがnullになる場合と同じ制約)。is_mateの候補には付けない。
    mate_ply(§22.3): allows_mate判定に使う詰み探索の深さ(手数上限)。既定値
    (5)は変更しない。王手中で合法手が少ない局面など、探索コストが低い局面で
    重要な判断の前だけ大きく指定すると、既定より深い強制詰み筋を検出できる
    (node_limitと同じ「既定は変えず、必要な時だけ引き上げる」考え方)。
    own_attacked_after_pv(§24.2): 読み筋(reply_pv_usi)を最後まで適用した局面
    に対するattacked_pieces(この手を指す側視点)の上位5件。own_attacked_after
    (着手直後、応手を読む前)には現れない、読み筋の途中で自分の駒に新たに
    生じる当たりを検出できる(例: 相手の歩打ち→と金前進が読み筋に含まれる場合)。
    search_depth_completed == 0の場合はnull(material_changeと同じ扱い)。
    is_mateの候補には付けない。
    mate_threat_after_pv(§24.3): 読み筋を最後まで適用した局面に対する詰めろ
    判定({found, within_ply, first_move_usi}、詰めろなしはnull)。「読み筋の
    最後で自分が何もしなければ、相手から詰みがあるか」の早期警告。非nullの
    候補は、材料点変化が良くても優先度を下げ、詰めろを受ける代替候補を優先
    的に検討すること。reply_pv_usiは材料点+玉の安全度ベースの浅い探索の結果
    であり、実際の相手の指し手と一致するとは限らない(material_changeと同じ
    制約)。mate_ply引数をそのまま流用する。search_depth_completed == 0の
    場合はnull。is_mateの候補には付けない。
    既知の限界: 読み筋の総手数の偶奇によっては読み筋終端の手番がこの手を
    指した側に戻っていないことがあり、その場合はnullを返す(見逃しうる)。
    """
    board = _board_snapshot()
    if board is None:
        return {"ok": False, "error": "no_active_game"}
    if not moves:
        return {"ok": False, "error": "no_moves_given"}
    depth = max(1, min(4, depth))
    node_limit = max(1_000, min(300_000, node_limit))
    # mate_ply上限21: 実測(games/2026-07-15_182533.kif 66手目相当の局面、
    # 詰みなし候補で find_mate が3,5,...,21と累積探索する最悪ケース)で
    # 約2.4秒、23では約13秒に跳ね上がることを確認した上で確定(§22.3)。
    mate_ply = max(1, min(21, mate_ply))
    results = analysis.verify_moves(
        board, moves[:10], depth=depth, node_limit=node_limit, mate_ply=mate_ply
    )
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
def add_comment(text: str) -> dict:
    """直前に指された手にコメントを追記する(KIF標準の`*`コメント行として記録)。

    用途: 相手の手への所感、終局時の総括など、着手時点では書けないコメント。
    自分の着手と同時に書くコメントは`apply_move`の`comment`引数を使う。
    終局後でも呼べる(総括用)。まだ1手も指されていない場合はエラー。
    """
    session = _current_session()
    if session is None:
        return {"ok": False, "error": "no_active_game"}
    if not text.strip():
        return {"ok": False, "error": "empty_comment"}

    with _session_lock:
        move_number = session.last_move_number()
        if move_number == 0:
            return {"ok": False, "error": "no_move_to_comment"}
        session.add_comment_lines(move_number, [text])
        session.autosave()
        last = session.game.last_move()
        return {"ok": True, "move_number": move_number, "move": _move_info(last) if last else None}


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
            target.meta = kif_store.GameMeta(
                session.difficulty, session.user_side, session.mode, session.model_name
            )
            target.save(moves, resigned=session.resigned, comments=session.comments)
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
            model_name=loaded.meta.model_name,
        )
        for move_int in loaded.moves:
            result = new_session.game.apply_move(cshogi.move_to_usi(move_int))
            if not result.ok:
                new_session.close()
                return {"ok": False, "error": f"kif_contains_illegal_move: {cshogi.move_to_usi(move_int)}"}
        new_session.resigned = loaded.resigned
        # コメントを復元しないと、再開後の自動保存(全体書き直し)で既存コメントが消える
        new_session.comments = {k: list(v) for k, v in loaded.comments.items()}

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
    gui_server.start(_board_fragment, games_dir=GAMES_DIR)
    mcp.run()


if __name__ == "__main__":
    main()
