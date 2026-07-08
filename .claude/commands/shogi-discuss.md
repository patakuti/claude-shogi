---
description: 将棋をClaude対話モードで対局する(手ごとに一言添えてから指す)
argument-hint: [difficulty 1-5] [user_side black|white]
---

将棋の新しい対局を「Claude対話モード」で開始し、進行する。

## 開始時の確認

引数 `$ARGUMENTS` に難易度(1-5)と手番(black/white)が両方指定されていればそれを使う。
指定がなければ、対局を始める前にユーザーに尋ねる(勝手にデフォルト値を使わない)。

確認後、`new_game(difficulty, user_side, mode="discuss")` を呼ぶ。

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
   上書きし、**同じ`file_path`**で`Artifact`を再度呼んで同一URLへ再デプロイする。

## 対局の進め方

対局が終了する(`status`が`"playing"`以外になる)まで、以下を繰り返す。

- **ユーザー側の手番**: `engine_hint(multipv=3)` で候補手と評価値・読み筋を取得する。
  最有力候補を選び、「こう指そうと思う。理由は〜」と指し手と簡単な理由を一言添えて
  ユーザーに提示する。ユーザーからコメント・別の希望があればそれを踏まえて手を選び直し、
  特になければそのまま `apply_move()` で指す。
- **コンピュータ側の手番**: `engine_move()` を呼び、指した手と評価値を簡潔に報告する。

毎手、`board`をそのまま表示してから次の手に進む(自分で盤面を描き直さない)。

## 終局

詰み・千日手・入玉宣言・投了・エンジンの投了/入玉宣言勝ちのいずれかで対局が終了したら、
`board`を表示し、結果を要約して伝える。
