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
CSA対局モード(`mode="csa"`)専用のツール`wait_for_user_move`(同§26.4。CSA対応
クライアント経由でユーザー本人が指すのを待つ。長時間ブロックする設計は避け、
短時間(既定8秒)ポーリングして未着手なら`{"status": "waiting", "move_number":
..., "turn": ...}`を返す。`move_number`/`turn`により、`waiting`が連続しても
手数が変化していなければ取りこぼしではないと判断でき、別途`get_state`を呼ぶ
必要がない、§27.3)もある。

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
やすい脅威として扱う(§15.1)。
同じく各駒には`king_only_defense`(紐が1つ以上あり、かつその全てが自玉で
あるか)も含む。実際に取り返すと玉自身が危険な位置に出る特殊なケースであり、
`hanging`(紐なし)と同様に実質的な無防備として扱うべきだが、玉が動いた後の
実際の安全性までは判定しない(§19.1)。`verify_moves`ツールは`node_limit`引数
(既定5万、範囲1,000〜300,000)を受け付け、合法手が多く読みが浅くなりがちな
複雑な局面で、呼び出し側が探索予算を増やして深い検証を要求できる(§15.2)。
`verify_moves`の各候補には`major_piece_trade`(この手、または読み筋のどこかで
飛・角〈成りを含む〉が捕られるかを示す真偽値。自分・相手どちらの大駒が
捕られる場合も対象)も含む。`search_depth_completed == 0`のときは読み筋側の
将来の大駒交換は検出できず、候補手自体の捕り駒のみで判定する。局面フェーズ
(序盤/中盤/終盤)の判定はツール側では行わない(§16.1)。
`analyze_position`の`major_piece_drop_threats`は、自陣3段目以内の紐なしマスへの
相手の飛・角の安全な打ち込み、または盤上に既にある相手の未成りの飛・角の自陣
3段目以内への前進が、成り込みと組み合わさって王手・両取り・安全な当たりに
発展する脅威の一覧([{square, piece, source, patterns, example_move_usi}, ...]。
パターンA〜Dは王手/紐なし駒への当たり/移動先の安全性の組み合わせ)。`source`は
打ち込み由来なら`"drop"`(`square`は打ち込み先)、盤上の駒の前進由来なら
`"board"`(`square`はその駒の現在地)。既に成っている駒(龍・馬)は`"board"`の
対象外。王手中や打ち込み自体が直接王手になる候補は対象外(§17.1、盤上前進版は
§21.1)。
`analyze_position`の`trapped_major_pieces`は、盤上に既にある相手の飛・角
(成りを含む: 龍・馬)のうち、合法な移動先の全てに手番側の利きが及んでいて
安全に逃げられない駒の一覧([{square, piece, legal_move_count, attackers}, ...]。
合法な移動先が一つもない〈完全に動けない〉駒も`legal_move_count: 0`で含む。
`attackers`はその駒へ現在実際に利いている手番側の駒数で、0は退避不可だが
まだ当たっていない、1以上は既に当たっており無償捕獲できる可能性が高い
ことを示す〈§20.3〉)。打ち込み(持ち駒からの新規配置)は対象外、静的な
利き数のみの判定でピンや取り合いの最終損得は考慮しない。王手中は空リスト
(§18.1)。
`verify_moves`の各候補には、その手をpushした直後(応手を読む前)の局面に
対する`major_piece_drop_threats_after`/`trapped_major_pieces_after`も含む
(この手を指す側=自分視点、攻撃側=自分。`own_attacked_after`と同様、`is_mate`の
候補には付けない)。前者が非空はこの手が新たな大駒打ち込み・前進の脅威を
自ら生むことを、後者が非空は相手の飛・角を捕獲確定に追い込めることを示し、
候補手を比較する段階でより早く判断材料を得られる(§20.2)。さらに
`own_trapped_major_pieces_after`(攻守逆転: 攻撃側=相手、防御側=自分)も含み、
非空ならこの手の直後に自分の飛・角が捕獲確定になっていることを示す
(新規の判定アルゴリズムは追加せず、`trapped_major_pieces`の`color`引数を
逆向きに呼ぶのみ。§21.2)。
`verify_moves`の各候補には`own_king_shelter_after`(自玉に隣接する自分の
金・銀〈金と同格の成駒を含む〉の数を、`immediately_after`〈着手直後〉/
`after_pv`〈読み筋`reply_pv_usi`を最後まで適用した後〉の2値で返す)も含む。
`search_depth_completed == 0`のとき`after_pv`は`null`
(`material_change`と同じ制約)。`is_mate`の候補には付けない(§22.2)。
`verify_moves`ツールは`mate_ply`引数(既定5、範囲1〜21。上限は実測で確定)も
受け付け、`allows_mate`判定の詰み探索の深さを呼び出し側が指定できる。既定値は
変更せず、王手中で合法手が少ない局面など重要な判断の前だけ深く指定する
(`node_limit`と同じ考え方。§22.3)。
`analyze_position`は`king_safety`(手番側視点の玉の安全度の要約:
`own_shelter_count`〈自玉に隣接する自分の金・銀の数〉と`opponent_hand_value`
〈相手の持ち駒の合計価値〉)も返す。王手中でも他のフィールドと異なり空に
ならず、通常どおり計算される(§22.4)。
`analyze_position`は`major_piece_fork_opportunities`(手番側の持ち駒にある
飛・角の打ち込み、または盤上の未成りの飛・角の移動が、王手も成りも伴わない
単純な両取りになる機会の一覧([{square, piece, source, targets,
example_move_usi}, ...]。`targets`は両取りされる相手の駒〈2件以上、玉は
含まない〉)も返す。王手を伴う両取りは`allows_mate`/`check_evasions`の範疇、
成り込みを伴う打ち込みは`major_piece_drop_threats`の範疇であり、本フィールドは
両者と重複しない「単純な両取り」のみを対象とする。紐が1つでもあればその駒は
対象から外れる(ピン・取り合いの最終損得は考慮しない)。王手中は空リスト
(§24.1)。
`verify_moves`の各候補には`own_attacked_after_pv`(読み筋`reply_pv_usi`を
最後まで適用した局面に対する`attacked_pieces`〈この手を指す側視点〉の上位5件)
も含む。`own_attacked_after`〈着手直後、応手を読む前〉には現れない、読み筋の
途中で自分の駒に新たに生じる当たりを検出できる。`search_depth_completed == 0`
のときは`null`(`material_change`と同じ制約)。`is_mate`の候補には付けない
(§24.2)。
`verify_moves`の各候補には`mate_threat_after_pv`(読み筋を最後まで適用した
局面に対する詰めろ判定。`{found, within_ply, first_move_usi}`、詰めろなしは
`null`)も含む。「読み筋の最後で自分が何もしなければ、相手から詰みがあるか」の
早期警告。`reply_pv_usi`は材料点+玉の安全度ベースの浅い探索の結果であり、
実際の相手の指し手と一致するとは限らない(`material_change`と同じ制約)。
`mate_ply`引数をそのまま流用する。`search_depth_completed == 0`のときは
`null`。`is_mate`の候補には付けない。既知の限界: 読み筋の総手数の偶奇に
よっては読み筋終端の手番がこの手を指した側に戻っていないことがあり
(反復深化の打ち切りや静止探索での追加の取り合いにより発生しうる、実戦
局面で確認済み)、その場合は逆方向の判定になってしまうため`null`を返す
(見逃しうる、§24.3)。
`major_piece_fork_opportunities`は`include_checks`引数(既定`False`)を
受け付ける。既定では従来どおり王手を伴う手を除外するが、`True`のとき
その除外のみを外し、王手を伴う両取りも対象に含める。王手を伴う場合、
玉への当たり(王手そのもの)を1駒分の当たりとして数え、玉以外の当たりが
1つ以上あれば両取りとして採用する(玉以外2駒以上を要求する非王手時とは
必要数が異なる。`allows_mate`は強制詰みのみを検出するため、「詰みには
至らないが王手と両取りが同時に成立し駒得される」パターンを拾うための
調整、§25.1)。
`verify_moves`の各候補には`opponent_fork_threats_after`(この手をpushした
直後〈応手を読む前、`major_piece_drop_threats_after`と同じ時点〉の局面に
対する`major_piece_fork_opportunities`〈相手視点、`include_checks=True`〉)
も含む。非空なら、この手を指した直後に相手の飛・角が王手を伴う両取りを
成立させられることを示す(材料点変化が良くても原則避けるべき候補)。
既知の限界は両取り検出そのものと同じ(動かした駒自身の利き以外による
当たりは対象外、紐が1つでもあれば対象から外れる)。`is_mate`の候補には
付けない(§25.1)。
`analyze_position`は`major_piece_attacked_squares`(手番側から見て相手の
飛・角〈成りを含む: 龍・馬〉が現在利いている升目の一覧、
`[{square, piece, attacker_square}, ...]`)も返す。走り利きのみが対象で、
龍・馬の隣接8方向への追加の1マス利きは含まない。盤端または最初の駒
(遮蔽物、自分の駒でも相手の駒でもそこで利きは止まる)までの全マスを
収集し、遮蔽物の升目自体は含む。候補手を自分で挙げる前に、盤面全体で
どこが大駒の利き筋に入っているかを俯瞰するための事前の危険地図であり、
候補手ごとの安全性は`destination`/`own_attacked_after`で別途確認が必要
(ピン・取り合いの最終損得は判定しない)。`king_safety`と同じ理由で王手中
でも通常どおり計算される(§25.3)。
同じ升目・同じ脅威を防げる候補が複数あるとき、盤上の金・銀・桂を動かす
手より持ち駒(特に歩)を打つ手を優先して検討する運用ルールを
`shogi-brain.md`に追記した(盤上の駒を動かす手は元の升目の利きを手放し、
より貴重な駒を最前線に置いて繰り返し狙われる形にしてしまうため。新規の
機械判定は追加せず、運用ルールのみ、§25.2)。
`major_piece_fork_opportunities`は飛・角に加え、手番側の持ち駒にある
銀・金・桂・香の**打ち込み**も対象に含む(盤上の移動は対象外、既存の
`major_piece_drop_threats`/`own_attacked_after`との重複を避けるための
意図的なスコープ限定)。`piece`フィールドで銀・金・桂・香・飛・角のいずれかを
区別できる。両取り判定の紐の扱いも拡張し、紐の内訳が自玉のみ
(`king_only_defense`、§19.1と同じ考え方)の場合は実質的に紐なしとして
両取り対象に含める(既存の飛・角判定にも影響するが、既存pytestで期待値の
不変を確認済み、§27.1)。
`analyze_position`の`king_safety`は`mating_net_risk`(相手の飛・角〈成りを
含む〉の利き筋が自玉の隣接マスに及んでいるかを示す真偽値)も返す。既存の
`major_piece_attacked_squares`と`king_safety`の組み合わせのみで判定し、
新規の探索ロジックは追加しない。静的な利き筋の交差判定のみで、実際に
詰み網が完成しているか(合駒・玉の逃げ場の有無)までは判定しない早期警告
であり、`true`のときは王手中でなくても`verify_moves`の`mate_ply`を既定より
大きく指定して再検証することが望ましい(§27.2)。
`verify_moves`の各候補には`own_trapped_major_pieces_after_pv`(読み筋
`reply_pv_usi`を最後まで適用した局面に対する`trapped_major_pieces`。
`own_trapped_major_pieces_after`〈着手直後〉と同じ攻守の向き)も含む。
非空ならば読み筋の最後で自分の飛・角(成りを含む)が捕獲確定(トラップ)に
なっていることを示す(例: 相手の合駒で退路が塞がれた後、相手玉が接近して
逃げ場を失う)。`own_trapped_major_pieces_after`(着手直後、応手を読む前)には
現れない、読み筋の途中で生じるトラップを検出できる。新規の判定アルゴリズムは
追加せず、`trapped_major_pieces`をPV終端の局面でもう一度呼ぶのみ。
`trapped_major_pieces`の`color`引数によるpush_passの自動切り替え(§20.1)
により、読み筋の総手数の偶奇(PV終端の手番)に関わらず計算される
(`mate_threat_after_pv`のような手番パリティによる`null`化は不要)。既知の
限界: `trapped_major_pieces`は王手中の局面では空リストを返す設計のため、
PV終端が王手のまま途切れている場合はトラップを見逃すことがある
(`own_trapped_major_pieces_after`と同じ制約)。`search_depth_completed == 0`の
ときは`null`(`material_change`と同じ制約)。`is_mate`の候補には付けない
(§28.1)。
`new_game`は`model_name`引数(既定は空文字)を受け付ける。手の決定主体が
Claude自身のモード(自動/対話/Claude思考)でのみ、対局者名にモデル名を
合成する(例: `model_name="Sonnet 5"` かつ思考モード →
「Claude Sonnet 5(思考)」)。KIFヘッダー・GUI盤面・リプレイ画面いずれも
`player_names`から導出される既存の表示にそのまま乗る。モデル名はMCPサーバー
側では自動判別できないため、各スラッシュコマンドがシステムプロンプトに
記載された自分のモデル名を自己申告する。ユーザー対話モード(`user`)は
対象外(§23)。

MCPサーバー起動時、`http://localhost:8765/` でGUI盤面(SVG)を配信するHTTPサーバーも
常時待受する(標準ライブラリの`http.server`のみで実装、追加の外部依存なし)。ブラウザで
このURLを開いておけば、1秒間隔のポーリングで一手ごとに盤面が自動更新される。
同様に`127.0.0.1:4081`でCSA通信対局プロトコルのTCPサーバーも常時待受する
(`/shogi-csa`専用。詳細は後述の「CSA対局モード」節を参照)。

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
引数で指定できる(例: `/shogi-brain 3 black`)。省略した場合は対局開始前に確認される。

| コマンド | モード |
|---|---|
| `/shogi-brain [difficulty] [user_side]` | Claude思考モード。エンジンのヒントを使わず、Claude自身が解析ツール(詰み探索・候補手検証・読み筋シミュレータ)を頼りに考えて指す。 |
| `/shogi-csa [user_side]` | CSA対局モード。ユーザー側の手はユーザー本人が手元のCSA対応対局ソフトから実際に指し、対局相手側はClaudeが思考モードで指す(USIエンジン不使用)。 |
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
`/shogi-csa`はUSIエンジンを使わないため、この難易度設定は適用されない。

### CSA対局モード

`/shogi-csa`は、ユーザー側の手をユーザー本人が手元のCSA対応対局ソフト(ShogiGUI・将棋所等)
から実際に指すモード。対局相手側はClaudeが`/shogi-brain`と同じ思考ロジック(エンジンの
ヒント不使用)で指す。MCPサーバー起動時、`127.0.0.1:4081`でCSA通信対局プロトコル
(サブセット)を待受する常時稼働のTCPサーバーも起動する(標準ライブラリの
`socket`/`socketserver`のみで実装、追加の外部依存なし)。

- 接続元は同一マシン上のCSA対応クライアント(Wine経由のShogiGUI等)を想定し、待受は
  `127.0.0.1`のみに限定する(LAN内の別マシンからの接続は非対応)。
- ログイン認証は行わない(ローカル専用ツールのため、任意のユーザー名・パスワードで接続可)。
  同時に1接続のみサポートする。
- 持ち時間切れの検出・強制はサーバー側では行わない(Claude側の思考時間が読めないため。
  接続先クライアントに申告する持ち時間は余裕を持った値にしている)。
- 対局中にクライアントが切断しても対局セッション自体は維持され(KIF自動保存済み)、
  再接続すれば続きから対局できる。

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
