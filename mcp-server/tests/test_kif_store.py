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
