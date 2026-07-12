# claude-shogi

Claude Code上で、将棋エンジン(やねうら王)を相手に対局できる環境。

## 概要

- 対局相手は常にコンピュータ(USIプロトコル対応の将棋エンジン)。
- ユーザー側の手をどう決めるかを、対局開始時に4つのモードから選択できる。
  - 自動モード / Claude対話モード / ユーザー対話モード / Claude思考モード
- ルールの正しさ(合法手判定・詰み・千日手・入玉宣言勝ち等)はcshogiに委譲し、
  対局の強さはやねうら王(NNUE)が担当する。

詳細な要件・設計は `01_requirements.md` / `02_design.md`(Git管理外)を参照。

## セットアップ

### 前提パッケージ

```bash
sudo apt install build-essential git p7zip-full wget
```

### 将棋エンジンのビルド

```bash
scripts/setup_engine.sh
```

以下を生成する(いずれもGit管理外・`.gitignore`対象):

- `engine/YaneuraOu-by-gcc` … やねうら王本体(ソースからビルド、`TARGET_CPU=ZEN3`)
- `engine/eval/nn.bin` … NNUE評価関数「Háo」(tanuki-チーム配布, GPLv3。
  同ディレクトリに`LICENSE-eval-gpl-3.0.txt`を同梱)

スクリプト最後にUSI疎通確認(`usi`→`isready`→`go byoyomi`→`bestmove`)を自動実行する。

### MCPサーバー

`.mcp.json`にサーバー`shogi`として登録済み(Claude Codeが自動で`uv run --project mcp-server shogi-mcp`を起動する)。
提供するツール: `new_game` / `get_state` / `apply_move` / `engine_move` / `engine_hint` /
`save_kif` / `load_kif` / `resign` / `add_comment`(詳細は`02_design.md` §3, §12)、および
Claude思考モード用の解析ツール `analyze_position` / `verify_moves` / `simulate_line`
(同§11, §13, §14。エンジン不使用のcshogiベース自前実装で、詰み探索・詰めろ検出(王手中は
全回避手の個別検証)・自駒への当たり一覧(浮き駒の検出)・頓死チェック・
浅い探索(駒得+玉の安全度、反復深化で打ち切り時のノイズを排除)・読み筋の検証を行う)。

`apply_move`/`engine_move`の応答には毎回`attack_report`(ユーザー側/エンジン側
それぞれの駒への当たり一覧)を含む。`analyze_position`の呼び忘れがあっても、
放置すると取られる駒・タダ取りできる駒が毎手必ず目に入る(§14.2)。
`verify_moves`の各候補には`destination`(移動先/打ち込み先マスへの相手の利き数・
味方の紐数)と`own_attacked_after`(着手直後の自駒への当たり上位5件)、および
反復深化で完了した探索深さ`search_depth_completed`(0なら`material_change`は
`null`)も含む(§14.3, §14.4)。
`attacked_pieces`(および`attack_report`/`own_attacked_after`)の各駒には
`pawn_drop_risk`(相手の持ち駒の歩を打って当てられるか。二歩・盤端・打ち込み先の
空き状況を考慮)も含む。盤上の利きが0でも`pawn_drop_risk: true`なら見落とし
やすい脅威として扱う(§15.1)。`verify_moves`ツールは`node_limit`引数
(既定5万、範囲1,000〜300,000)を受け付け、合法手が多く読みが浅くなりがちな
複雑な局面で、呼び出し側が探索予算を増やして深い検証を要求できる(§15.2)。
`verify_moves`の各候補には`major_piece_trade`(この手、または読み筋のどこかで
飛・角〈成りを含む〉が捕られるかを示す真偽値。自分・相手どちらの大駒が
捕られる場合も対象)も含む。`search_depth_completed == 0`のときは読み筋側の
将来の大駒交換は検出できず、候補手自体の捕り駒のみで判定する。局面フェーズ
(序盤/中盤/終盤)の判定はツール側では行わない(§16.1)。
`analyze_position`の`major_piece_drop_threats`は、自陣3段目以内の紐なしマスへの
相手の飛・角の安全な打ち込みが、成り込みと組み合わさって王手・両取り・安全な
当たりに発展する脅威の一覧([{square, piece, patterns, example_move_usi}, ...]。
パターンA〜Dは王手/紐なし駒への当たり/移動先の安全性の組み合わせ)。王手中や
打ち込み自体が直接王手になる候補は対象外(§17.1)。

MCPサーバー起動時、`http://localhost:8765/` でGUI盤面(SVG)を配信するHTTPサーバーも
常時待受する(標準ライブラリの`http.server`のみで実装、追加の外部依存なし)。ブラウザで
このURLを開いておけば、1秒間隔のポーリングで一手ごとに盤面が自動更新される。

対局は1手ごとに`games/YYYY-MM-DD_HHMMSS.kif`へ自動保存され、`load_kif`で再開できる。

手動での動作確認:

```bash
cd mcp-server
uv run pytest tests/ -v
```

### テスト

`mcp-server/tests/`にpytestを配置している。`test_usi_engine.py` / `test_server.py`は
`engine/YaneuraOu-by-gcc`のビルド(`scripts/setup_engine.sh`実行)を前提とし、未ビルドの場合は
自動的にスキップされる。

## 使い方

Claude Code上で以下のスラッシュコマンドを使う。難易度(1〜5)と手番(black/white)は
引数で指定できる(例: `/shogi-auto 3 black`)。省略した場合は対局開始前に確認される。

| コマンド | モード |
|---|---|
| `/shogi-auto [difficulty] [user_side]` | 自動モード。Claudeが会話を挟まずユーザー側の手も自動で決めて指す。終局や山場のみ報告。 |
| `/shogi-discuss [difficulty] [user_side]` | Claude対話モード。1手ごとに「こう指そうと思う、理由は〜」と提案してから指す。 |
| `/shogi-user [difficulty] [user_side]` | ユーザー対話モード。「7六歩」のような自然言語の指示を指し手に変換して指す。 |
| `/shogi-brain [difficulty] [user_side]` | Claude思考モード。エンジンのヒントを使わず、Claude自身が解析ツール(詰み探索・候補手検証・読み筋シミュレータ)を頼りに考えて指す。 |
| `/shogi-resume [KIFパス]` | 保存済みの対局を再開する。パス省略時は`games/`内の最新KIFを使う。 |

### 難易度

| Lv | 想定 | 設定 |
|---|---|---|
| 1 | 入門 | NodesLimit=1000, byoyomi 100ms |
| 2 | 初級 | NodesLimit=10000, byoyomi 300ms |
| 3 | 中級 | NodesLimit=100000, byoyomi 1000ms |
| 4 | 上級 | NodesLimit無制限, byoyomi 2000ms |
| 5 | 最強 | NodesLimit無制限, byoyomi 5000ms, Threads 8 |

体感の強さに応じて`mcp-server/src/shogi_mcp/presets.py`のノード数を調整できる。

### 対局の再開

対局は1手ごとに`games/YYYY-MM-DD_HHMMSS.kif`へ自動保存される。Claude Codeのセッションが
途切れても、`/shogi-resume`で直前の局面・難易度・手番・モードから対局を再開できる。

### 対局の振り返り(リプレイ)

対局中、KIFには指し手に加えて以下が記録される
(棋譜ファイル1つで完結し、ShogiGUI等の既存棋譜ビューアでもそのまま読める)。

- **対局者名**: 先手・後手が誰か(例: `先手：Claude(思考)` / `後手：やねうら王 Lv1`)を
  KIFヘッダーに記録。対局中のGUI盤面とリプレイ画面にも表示される。
- **エンジンの評価値**: `engine_move`のたびに`*eval cp:120 pv:...`形式のコメント行で自動記録
  (先手有利が正)。
- **Claudeのコメント**: Claude思考モード・Claude対話モードでは、着手の狙いや山場の所感が
  `apply_move`の`comment`引数 / `add_comment`ツール経由でコメント行に記録される。

記録済みの対局は `http://localhost:8765/replay` でブラウザ再生できる。対局の選択、
手数スライダー/前後ボタン(←→キー対応)での盤面送り、指し手ごとのコメント表示、
評価値グラフ(クリックで該当手へジャンプ)に対応する。対局セッションとは独立に
KIFファイルだけを読むため、対局中でも過去譜を再生できる。

## ライセンス

本リポジトリのコードのライセンスはTBD。
同梱の評価関数(`engine/eval/nn.bin`)はtanuki-チームによる配布物でGPLv3
(`engine/eval/LICENSE-eval-gpl-3.0.txt`参照)。やねうら王本体もGPLv3。
