---
description: 将棋を自動モードで対局する(Claudeが会話を挟まず自動で指す)
argument-hint: [difficulty 1-5] [user_side black|white]
---

将棋の新しい対局を「自動モード」で開始し、進行する。

## 開始時の確認

引数 `$ARGUMENTS` に難易度(1-5)と手番(black/white)が両方指定されていればそれを使う。
指定がなければ、対局を始める前にユーザーに尋ねる(勝手にデフォルト値を使わない)。

確認後、`new_game(difficulty, user_side, mode="auto")` を呼ぶ。

## GUI盤面の自動更新

ツールの戻り値に含まれる `board_svg` を使い、`apply_move()` / `engine_move()` を呼ぶたび
(ユーザー側・コンピュータ側どちらも)にGUI盤面を更新する。

1. `new_game`直後、`board_svg`を次のHTMLに埋め込み、スクラッチパッドディレクトリへ書き出す。
   ```html
   <div style="display:flex;justify-content:center;padding:16px;">
   {{board_svg}}
   </div>
   <script>setInterval(() => location.reload(), 2000)</script>
   ```
   `Artifact`ツールでこのファイルを公開する(`favicon`は`♟️`、`title`は「将棋対局」)。
   公開したURLをユーザーに一度だけ伝える。
2. 以降、`apply_move()` / `engine_move()` の戻り値に含まれる新しい`board_svg`で同じHTMLファイルを
   上書きし、**同じ`file_path`**で`Artifact`を再度呼んで同一URLへ再デプロイする(会話での報告が
   ない手でもGUI更新だけは毎手行う)。

## 対局の進め方

対局が終了する(`status`が`"playing"`以外になる)まで、以下を繰り返す。

- `get_state()`で手番を確認する。
- **ユーザー側の手番**: `engine_hint(multipv=1)` で最善手を取得し、その手をそのまま
  `apply_move()` で指す。ユーザーとの対話は挟まない。
- **コンピュータ側の手番**: `engine_move()` を呼ぶ。

## 報告のタイミング

進行中は基本的に会話を挟まず黙々と指し進める。ただし以下のときだけ一言報告する。

- 王手がかかったとき
- 飛車・角・金・銀など主要な駒が捕られた/交換されたとき
- 対局が終了したとき(詰み・千日手・入玉宣言・投了・エンジンの投了/入玉宣言勝ち)。
  終局時は`board`をそのまま表示し、結果を短く要約する。

盤面を示すときは、ツールが返す`board`文字列をそのまま使う(自分で盤面を描き直さない)。
