import cshogi
import pytest

from shogi_mcp import kif_store

MOVES_USI = ["7g7f", "3c3d", "2g2f", "8c8d"]


def _moves_int(usi_list):
    board = cshogi.Board()
    moves = []
    for usi in usi_list:
        move = board.move_from_usi(usi)
        moves.append(move)
        board.push(move)
    return moves


@pytest.fixture
def store(tmp_path):
    s = kif_store.KifStore(tmp_path)
    s.start(kif_store.GameMeta(difficulty=2, user_side="black", mode="brain"))
    return s


def test_comments_round_trip(store):
    comments = {
        1: ["居飛車でいく。飛車先を伸ばす前に角道を開ける。", "eval cp:50 pv:3c3d 2g2f"],
        2: ["eval cp:-30 pv:2g2f 8c8d"],
        4: ["eval cp:-45"],
    }
    store.save(_moves_int(MOVES_USI), comments=comments)

    loaded = kif_store.KifStore.load(store.path)
    assert [cshogi.move_to_usi(m) for m in loaded.moves] == MOVES_USI
    assert loaded.comments == comments
    # ヘッダーのメタ情報は指し手コメントと分離されて従来どおり読めること
    assert loaded.meta == kif_store.GameMeta(difficulty=2, user_side="black", mode="brain")


def test_comments_absent_moves_keep_index_alignment(store):
    # コメント無しの手が混在してもインデックスがずれないこと(3手目だけコメント)
    store.save(_moves_int(MOVES_USI), comments={3: ["飛車先の歩を伸ばす。"]})
    loaded = kif_store.KifStore.load(store.path)
    assert loaded.comments == {3: ["飛車先の歩を伸ばす。"]}


def test_save_without_comments_loads_empty(store):
    store.save(_moves_int(MOVES_USI))
    loaded = kif_store.KifStore.load(store.path)
    assert loaded.comments == {}


def test_multiline_comment_string_is_split_into_lines(store):
    # 1要素の中に改行が含まれていても行ごとに`*`前置され、読み戻しは行リストになる
    store.save(_moves_int(MOVES_USI), comments={1: ["1行目\n2行目"]})
    loaded = kif_store.KifStore.load(store.path)
    assert loaded.comments == {1: ["1行目", "2行目"]}


def test_non_cp932_characters_are_replaced_not_crash(store):
    store.save(_moves_int(MOVES_USI), comments={1: ["好手✨(絵文字はcp932非対応)"]})
    loaded = kif_store.KifStore.load(store.path)
    line = loaded.comments[1][0]
    assert "好手" in line and "cp932" in line  # 置換されつつ他の文字は残る


def test_comments_survive_resigned_save(store):
    store.save(_moves_int(MOVES_USI), resigned=True, comments={2: ["eval cp:-30"]})
    loaded = kif_store.KifStore.load(store.path)
    assert loaded.resigned
    assert loaded.comments == {2: ["eval cp:-30"]}


# --- 対局者名(02_design.md §13.6) ---------------------------------------------


def test_player_names_by_mode_and_side():
    assert kif_store.player_names(
        kif_store.GameMeta(difficulty=2, user_side="black", mode="brain")
    ) == ("Claude(思考)", "やねうら王 Lv2")
    assert kif_store.player_names(
        kif_store.GameMeta(difficulty=5, user_side="white", mode="user")
    ) == ("やねうら王 Lv5", "ユーザー")
    assert kif_store.player_names(
        kif_store.GameMeta(difficulty=1, user_side="black", mode="auto")
    ) == ("Claude(自動)", "やねうら王 Lv1")
    assert kif_store.player_names(
        kif_store.GameMeta(difficulty=3, user_side="white", mode="discuss")
    ) == ("やねうら王 Lv3", "Claude(対話)")


def test_kif_header_records_player_names(store):
    store.save(_moves_int(MOVES_USI))
    text = store.path.read_text(encoding="cp932")
    # cshogiのExporterは全角コロンで書き出す(ShogiGUI等の標準形式)
    assert "先手：Claude(思考)" in text
    assert "後手：やねうら王 Lv2" in text
    # cshogi Parserでも読み戻せること(リプレイ画面で使用)
    parser = cshogi.KIF.Parser.parse_file(str(store.path))
    assert parser.names[0] == "Claude(思考)"
    assert parser.names[1] == "やねうら王 Lv2"


# --- 対局者名へのモデル名記録(02_design.md §23) -------------------------------


def test_player_names_inserts_model_name_for_claude_driven_modes():
    assert kif_store.player_names(
        kif_store.GameMeta(difficulty=2, user_side="black", mode="brain", model_name="Sonnet 5")
    ) == ("Claude Sonnet 5(思考)", "やねうら王 Lv2")
    assert kif_store.player_names(
        kif_store.GameMeta(difficulty=1, user_side="white", mode="auto", model_name="Opus 4.8")
    ) == ("やねうら王 Lv1", "Claude Opus 4.8(自動)")


def test_player_names_ignores_model_name_for_user_mode():
    # userモードは手の決定主体がユーザー自身のため、model_nameを渡しても無視される
    assert kif_store.player_names(
        kif_store.GameMeta(difficulty=5, user_side="white", mode="user", model_name="Sonnet 5")
    ) == ("やねうら王 Lv5", "ユーザー")


def test_player_names_without_model_name_unchanged():
    # model_name未指定(既定"")は従来どおりの表記のまま(後方互換)
    assert kif_store.player_names(
        kif_store.GameMeta(difficulty=2, user_side="black", mode="brain")
    ) == ("Claude(思考)", "やねうら王 Lv2")


def test_model_name_round_trips_through_kif(tmp_path):
    s = kif_store.KifStore(tmp_path)
    s.start(
        kif_store.GameMeta(
            difficulty=2, user_side="black", mode="brain", model_name="Sonnet 5"
        )
    )
    s.save(_moves_int(MOVES_USI))

    text = s.path.read_text(encoding="cp932")
    assert "先手：Claude Sonnet 5(思考)" in text

    loaded = kif_store.KifStore.load(s.path)
    assert loaded.meta == kif_store.GameMeta(
        difficulty=2, user_side="black", mode="brain", model_name="Sonnet 5"
    )


def test_kif_without_model_name_loads_empty_model_name(store):
    # 旧KIF相当(model:行なし)を読んでもエラーにならず、空文字として復元される
    store.save(_moves_int(MOVES_USI))
    loaded = kif_store.KifStore.load(store.path)
    assert loaded.meta.model_name == ""
