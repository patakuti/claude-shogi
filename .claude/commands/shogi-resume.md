---
description: 保存済みの棋譜(KIF)を読み込んで対局を再開する
argument-hint: [KIFファイルパス(省略時はgames/内の最新ファイル)]
---

保存済みの対局を再開する。

## 手順

1. `$ARGUMENTS` にKIFファイルのパスが指定されていればそれを使う。
   省略時は `games/` ディレクトリ内で最も新しい`.kif`ファイルを探す
   (例: `ls -t games/*.kif | head -1`)。対象ファイルが見つからなければ、
   その旨をユーザーに伝えて終了する。
2. `load_kif(path)` を呼ぶ。
3. 戻り値の`board`を表示し、手番・直前の指し手をユーザーに伝える。
4. 戻り値の`board_svg`をHTMLに埋め込みスクラッチパッドディレクトリへ書き出し、`Artifact`ツールで
   公開する(`favicon`は`♟️`、`title`は「将棋対局」。手順の詳細は`/shogi-auto`の
   「GUI盤面の自動更新」節と同じ)。公開したURLをユーザーに一度だけ伝える。
5. 戻り値の`status`が`"playing"`でなければ(詰み・千日手・入玉宣言・投了などで
   既に終局している場合)、その旨を伝えて終了する。
6. `status`が`"playing"`なら、戻り値の`mode`フィールドを見て、対応するモードの
   進め方で対局を継続する(`new_game`は呼ばない。既に対局は読み込み済み)。
   以降の`apply_move()` / `engine_move()`のたびに、同じ`file_path`で`Artifact`を再デプロイして
   GUI盤面を更新し続ける。
   - `mode` が `"auto"` → `/shogi-auto` と同じ進め方(会話を挟まず自動で進める)
   - `mode` が `"discuss"` → `/shogi-discuss` と同じ進め方(一手ごとに提案してから指す)
   - `mode` が `"user"` → `/shogi-user` と同じ進め方(ユーザーの自然言語指示を待つ)
