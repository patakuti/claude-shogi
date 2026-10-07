# claude-shogi

Claude Code上で将棋を指すための環境。将棋エンジンのヒントを一切使わず、Claude自身が
局面解析ツールを頼りに考えて指す「Claude思考モード」を中心に据えている。

## 動機

将棋YouTuberそらさんの動画
[「政府に規制された最強AIと将棋を指したらヤバすぎた」](https://www.youtube.com/watch?v=SR-ZajubK6o)で、
指し手の符号だけをテキストで入力し、生成AI(Fable 5)と将棋を指す試みが紹介されていた。
将棋専用に訓練されたAIではないため終始強いということはあり得ないが、序盤は正確な指し回しを
見せ、そらさんを驚かせていた。

この動画を見て、合法手判定・詰み探索・候補手検証のような補助ツールをLLMに使わせれば、
やねうら王のような専用の将棋エンジンなしでも、それなりの強さを持たせられるのではないかと
考え、試しに作ってみたのがこのツールの動機。動画で指していたFable 5に加え、Sonnet 5でも
試している。

## 概要

- 2つの対局モードがある。
  - **Claude思考モード** (`/shogi-brain`): ユーザー側の手をClaude自身が、局面解析ツール
    (詰み探索・候補手検証・読み筋シミュレータ、いずれも将棋エンジン不使用の自前実装)だけを
    頼りに決める。対局相手側はやねうら王(NNUE)で、難易度をLv1〜5から選べる。
  - **CSA対局モード** (`/shogi-csa`): ユーザー側の手はユーザー本人が手元のCSA対応対局ソフト
    (ShogiGUI・将棋所等)から実際に指す。対局相手側はClaudeがClaude思考モードと
    同じロジックで指す(やねうら王も含め将棋エンジンは一切使わない)。上記の動機を最も
    直接的に検証できるモードで、後述の対局実績もこのモードで指したもの。
- ルールの正しさ(合法手判定・詰み・千日手・入玉宣言勝ち等)はcshogiに委譲する。

## 位置づけ

多くの将棋・チェス向けMCPサーバーは、将棋/チェスエンジンの評価値・最善手・読み筋をそのまま
LLMに渡し、LLMはそれを読み上げたり解説したりする設計になっている。

| ツール/記事 | 概要 |
|---|---|
| [shogi-mcp](https://github.com/azumausu/shogi-mcp) ([Glama](https://glama.ai/mcp/servers/@azumausu/shogi-mcp)) | USI将棋エンジンの解析結果(MultiPV)をLLMに橋渡しするブリッジ |
| [ClaudeCodeと将棋を指してみる(Qiita)](https://qiita.com/synchr0niciteen/items/2e2d4ff33ea9df5e35f9) | やねうら王+水匠の評価値・最善手・読み筋を自然言語で取得しながら対局する試み |
| [chess-mcp](https://github.com/turlockmike/chess-mcp) | Stockfishによる局面評価・盤面表示・定跡データベース検索を提供 |
| [mcp-chess](https://github.com/alexandreroman/mcp-chess) | 盤面画像生成・合法手チェックに加え、次の一手の提案自体をStockfish.online APIに委任 |
| [chessagine-mcp](https://github.com/jalpp/chessagine-mcp) | Stockfish/Leela/Maia等複数エンジン+定跡DB+Lichess連携で評価値・最善手を横断的に提供 |
| [games-dash](https://github.com/sandraschi/games-dash) | 100以上のゲーム+7エンジン(将棋はやねうら王)をMCP経由で統合するプラットフォーム |
| [将棋エンジンを作る〜(Zennスクラップ)](https://zenn.dev/sh11235/scraps/3456d57f674c73) | Claude Codeに将棋の対戦AIロジック自体を書かせた記録。専用エンジンによる補強なしでは「違和感のある手」を指し、既存の無料将棋サイトのAIにも及ばなかったとの結果 |

本ツールはこれらとは逆の方針を取る。`analyze_position`/`rank_moves`/`verify_moves`/`simulate_line`は
いずれも将棋エンジンを使わない自前実装で、返すのは詰み筋・危険手・材料損得といった「検証」情報のみ
(`rank_moves`は全合法手を自前の浅い探索で並べ、検証にかける候補の漏れを防ぐためのもの)。
評価値や最善手をエンジンから取得してClaudeにそのまま渡すことは、`/shogi-brain`・`/shogi-csa`の
どちらのモードでも意図的に避けている。指し手の決定はあくまでClaudeの大局観に委ねており、
「LLM自身がどこまで指せるか」を検証することが本ツールの目的のため。

上記の中では、Zennスクラップの「対戦AIを作る」試みが目的として最も近い(専用エンジンに
頼らずLLM/生成AIで対局ロジックを作る)。同スクラップでは専用エンジンによる補強なしのAIが
既存の無料将棋サイトのAIにも及ばなかったと報告されており、本ツールは局面解析ツール
(詰み探索・候補手検証・読み筋シミュレータ、いずれも将棋エンジン不使用)による補助を
与えることで、その差を縮められるか試している。

## 強さ

CSA対局モード(将棋エンジン不使用、Claudeが局面解析ツールのみで指す)で、
[ぴよ将棋 Web版](https://www.studiok-i.net/ps/)と対局した実績(9局)。ぴよ将棋自体はCSA対局に
対応していないため、CSA対局モードの画面とぴよ将棋の画面を並べ、双方の指し手を
ユーザーが手動で中継する形で対局を実現した。対局を重ねるごとに局面解析ツール自体も
改良しているため、対局順(日付順)で記載する。

**Sonnet 5**

| 日付 | 相手(ぴよ将棋) | レーティング目安 | 結果 |
|---|---|---|---|
| 07/17 | Lv1 ひよこ | R30 | ○ 勝ち |
| 07/17 | Lv10 ピヨ太 | R450 | ○ 勝ち |
| 07/18 | Lv20 ピヨ馬 | R1220 | ● 負け |
| 07/20 | Lv13 ひよか | R630 | ● 負け |

**Fable 5**

| 日付 | 相手(ぴよ将棋) | レーティング目安 | 結果 |
|---|---|---|---|
| 07/18 | Lv20 ピヨ馬 | R1220 | ● 負け |
| 07/18 | Lv15 ひよん | R780 | ● 負け |
| 07/18 | Lv10 ピヨ太 | R450 | ○ 勝ち |
| 07/19 | Lv13 ひよか | R630 | ○ 勝ち |
| 07/19 | Lv15 ひよん | R780 | △ 後手優勢のまま中断(操作ミス) |

Fable 5は序盤の2局(R1220・R780)を落とした後、ツールの改良とともにR450・R630に勝ち、
R780でも優勢のまま中断するところまで戦えるようになった。Sonnet 5は序盤にR30・R450に
勝ったものの、直近の対局ではR1220・R630に敗れている。対局数が少ないため、この結果だけ
からモデル間の強さの優劣を結論づけることはできないが、棋譜を見返した印象としては
Fable 5の方がおかしな指し手が少なかった。

### 棋譜サンプル

`samples/`に上記9局すべてのKIFファイルを同梱している。ShogiGUI・ShogiHome等の既存棋譜
ビューアでそのまま開けるほか、`/shogi-resume`で読み込んで対局を再開することもできる。

**Fable 5 vs Lv20 ピヨ馬(R1220)戦、81手目時点**(ShogiHomeによる事後解析のスクリーンショット)

![81手目時点でFable 5(後手)が評価値-2150の勝勢だったが、直後に評価値が反転した様子](samples/20260718_074548_claude-shogi-csa_Lv20%20ピヨ馬%28R1220%29_Claude%20Fable%205%28思考%29_turn81.png)

81手目の時点でFable 5(後手)は評価値-2150(後手勝勢)まで優位を築いていたが、直後の数手で
評価値が一気に先手側へ振れて大逆転を許し、最終的にこの一局を落とす結果になった。
画像下部の評価値グラフでも、80手台前半で評価値が反転しているのが確認できる。

## セットアップ

### 動作確認環境

Linux(Ubuntu)でのみ動作確認している。Windows/Macでは未検証(実機がないため確認できて
いない)。`/shogi-csa`(CSA対局モード)は将棋エンジンを一切使わず、依存パッケージ
(`cshogi`等)もクロスプラットフォーム対応のため動く可能性はある。

### 前提パッケージ

MCPサーバーの実行に共通して必要なもの。

- Python 3.12以上
- [uv](https://docs.astral.sh/uv/)

### 将棋エンジンのビルド(`/shogi-brain`を使う場合のみ)

`/shogi-brain`(Claude思考モード)の対局相手として使うやねうら王を用意する手順。
`/shogi-csa`(CSA対局モード)だけを使う場合、対局相手側もClaude自身が思考ロジックで
指すため将棋エンジンを一切使わず、この節はまるごと不要。

`scripts/setup_engine.sh`はソースからのgcc/makeビルド(`TARGET_CPU=ZEN3`)であり、
Linux専用。Windows/Macでは動かない。

Windowsではやねうら王公式配布のビルド済みバイナリ(NNUE版)を使えば動く可能性がある
(**未確認**)。使う場合は`engine/YaneuraOu-by-gcc`という固定パスをコードが参照する
(`mcp-server/src/shogi_mcp/server.py`の`ENGINE_PATH`)ため、バイナリをこのファイル名で
配置するか、コード側でパスを変更する必要がある。評価関数(`engine/eval/nn.bin`)も
別途用意が要る。

```bash
sudo apt install build-essential git p7zip-full wget
scripts/setup_engine.sh
```

以下を生成する:

- `engine/YaneuraOu-by-gcc` … やねうら王本体(ソースからビルド、`TARGET_CPU=ZEN3`)
- `engine/eval/nn.bin` … NNUE評価関数「Háo」(tanuki-チーム配布, GPLv3)。リポジトリには
  含まれず、スクリプトが配布元から取得して配置する。同ディレクトリに
  `LICENSE-eval-gpl-3.0.txt`も一緒に配置される

スクリプト最後にUSI疎通確認(`usi`→`isready`→`go byoyomi`→`bestmove`)を自動実行する。

### ネイティブ実装(任意)

浅い探索(`rank_moves`・`verify_moves`・`analyze_position`の材料点+玉の安全度の評価と探索)を
Cで高速化する任意のビルド。未実行でもPython実装で同じ結果が出る(速度のみ異なる)。gccが必要でLinux専用
(他OSは未検証)。

```bash
scripts/build_native.sh
```

`mcp-server/src/shogi_mcp/_native/libshogi_native.so`が生成される(Git管理外)。次を含む:

- 評価関数(`mcp-server/native/shogi_eval.c`)
- 盤面・合法手生成(`shogi_core.c`。cshogiと全合法手が一致することをperftと数万局面の比較で検証済み)
- 浅い探索(`shogi_search.c`。置換表・PVS・null move・LMR等。Python版の`_Searcher`と同じ
  アルゴリズムで、枝刈りを無効にした探索値がPython版と一致することをテストで検証済み)

ビルドしていない場合、MCPサーバーはstderrに警告を1行出してPython実装を使う。
`SHOGI_MCP_NATIVE=0`で明示的に無効化もできる。`rank_moves`(実戦391局面)の1手あたりの時間は、
深さ3で平均0.19秒(Python版1.7秒)、深さ4で平均0.67秒(同6.0秒)になる。上位3手だけ正確に読む既定の
`exact_n=3`では、129局面の深さ5が平均1.0秒(95%点3.4秒)、深さ6が平均4.4秒(95%点20秒)。

### MCPサーバー

`.mcp.json`にサーバー`shogi`として登録済み(Claude Codeが自動で`uv run --project mcp-server shogi-mcp`を起動する)。
提供するツールの詳細は後述の「提供ツール」を参照。

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

### 評価のずれの測定(任意、要エンジン)

`scripts/eval_gap.py`は、静的評価(`analysis.py`)とやねうら王(採点専用)の評価値との平均絶対
誤差を、段階別・玉が薄い局面・駒得差が大きい局面で集計する。評価に項目を足したとき、ずれが
縮むかの合否判定に使う(重みの自動調整には使わない)。評価の玉の危険度項(囲い・逃げ道・相手の
持ち駒、`analysis.EvalWeights`)は実装済みだが、測定で効果が確認できなかったため既定の重みは0。

```bash
cd mcp-server
uv run python ../scripts/eval_gap.py
```

`scripts/king_danger_report.py`は、KIFの各局面で`analyze_position`の`king_safety.own_king`/
`opponent_king`(玉への攻め駒と守り駒の枚数比較)を一覧する。`--referee`でやねうら王の評価値も
並べて表示する(表示のみ)。

### 探索の強さの測定(任意、要エンジン)

`scripts/measure_strength.py`は、`samples/`の棋譜でClaudeが指した局面について、`rank_moves`の
上位手をやねうら王(**採点専用**。対局の手の決定には使わない)の最善手・評価値と比べ、
一致率(top1/top3)と1位手の評価損(cp)を序盤・中盤・終盤別に集計する。
`engine/`のビルド(`scripts/setup_engine.sh`)が必要。

```bash
cd mcp-server
uv run python ../scripts/measure_strength.py --depths 1,2,3
```

### テスト

`mcp-server/tests/`にpytestを配置している。`test_usi_engine.py` / `test_server.py`は
`engine/YaneuraOu-by-gcc`のビルド(`scripts/setup_engine.sh`実行)を前提とし、未ビルドの場合は
自動的にスキップされる。

## 提供ツール

MCPサーバー(`shogi`)が提供するツールは大きく3種類。呼ばれ方も一律ではなく、毎手ほぼ
必ず呼ばれるものと、Claudeが局面に応じて必要と判断したときだけ呼ぶものがある。

- **対局進行**(毎手呼ばれる): `new_game` / `get_state` / `apply_move` / `engine_move` /
  `engine_hint` / `save_kif` / `load_kif` / `resign` / `add_comment`。`apply_move`/
  `engine_move`の応答には毎回`attack_report`(両者の駒への当たり一覧)を含み、放置すると
  取られる駒が毎手必ず目に入るようにしている。`get_state`/`apply_move`/`engine_move`/
  `wait_for_user_move`の`board`(盤面テキスト)と`legal_moves`(全合法手一覧)は、
  毎手の応答に無条件で含めると会話コンテキストを圧迫するため既定で省略される
  (`include_board`/`include_legal_moves`引数でオプトイン)。`new_game`/`load_kif`/
  `resign`のように1対局に1回だけ呼ばれるツールは従来どおり常に含む。
- **局面解析**(将棋エンジン不使用、cshogiベースの自前実装。Claude思考モードの中核):
  `analyze_position`(詰み筋・詰めろ・自駒への当たり・玉の安全度・大駒の両取り機会/
  捕獲確定〈トラップ〉などを解析)は毎手呼ばれ、その結果(詰み逃し防止・王手回避・
  当たり駒の確認等)はスラッシュコマンドの指示で毎手必須のチェック事項になっている。
  `rank_moves`(全合法手を駒得+玉の安全度ベースの浅い探索で評価し、上位の手を要約して返す。
  既定は深さ4・時間予算5秒で、全候補手を深さ1から順に読み、予算を超えたら完了した最後の深さの結果を返す。
  終盤の勝負所では`depth=5, time_limit=20`程度まで引き上げ可能〈実戦391局面での平均: ネイティブ実装あり(後述)で深さ3 約0.2秒・4 約0.7秒・5 約2.9秒(95%点12秒)。なしでは深さ2 0.55秒・3 1.7秒で、時間予算内に到達できる深さまでになる〉)も毎手呼ばれ、
  その上位手は`verify_moves`にかける候補へ必ず含める運用になっている(主観で候補を選ぶ段階での
  最善手の見落とし対策。序盤のように多数の手が同点で並ぶ局面ではこの強制を外す)。
  `verify_moves`(候補手ごとに合法性・材料損得・大駒交換・詰み回避・着手後の危険度・
  読み筋シミュレーション結果を検証)と`simulate_line`(読み筋を実際に進めて結果を確認)は、
  Claudeが検討中の候補手について局面ごとに必要と判断した回数だけ呼ぶ。これら候補手比較の
  生の応答は判断ロジックに必須で単純には削れないため、`/shogi-brain`・`/shogi-csa`とも
  手番決定自体をサブエージェント(fork)に委譲し、対局を進行するメインの会話には指した手と
  短い報告だけが残るようにしている(fork自体は常に非同期のため、体感としては1手ごとに
  ターンが区切れる)。
- **CSA対局モード専用**: `wait_for_user_move`(ユーザー本人の着手をポーリングで待つ。
  人間側の手番の間、着手を検知するまで繰り返し呼ばれる)。

局面解析の読みの深さは、将棋エンジンのように深くはない。`verify_moves`の`reply_pv_usi`/
`material_change`(駒得+玉の安全度ベースの浅い探索)は既定3手先まで(`depth`引数で
1〜4手に変更可)。取り合いが続く手順に限り、既定の探索ノード数上限(`node_limit`引数、
既定5万・範囲1,000〜30万)まで静止探索でさらに数手延長される。詰み探索(`mate_ply`引数、
既定5・範囲1〜21)は既定で5手詰めまでを検出する(21手詰めまで指定可能だが、局面によっては
数秒〜十数秒かかるため通常は必要な局面でだけ引き上げる運用)。この浅い読みを、hanging駒の
検出・詰めろ判定・両取り検出などの静的な盤面解析と組み合わせて補うことで、Claudeの大局観
だけに頼らない判断を可能にしている。

これら`node_limit`/`depth`/`mate_ply`は既定値のまま使うのが基本だが、王手中で合法手が
少ない局面や、相手の飛・角の利きが自玉の隣接マスに及んでいる(`mating_net_risk`)など
重要な判断が必要な場面では、Claude自身の判断で値を引き上げて再検証してよいという運用
ルールがスラッシュコマンドの指示に明記されている。ツール側の既定値そのものは変更しない
(必要な場面だけ呼び出し側が引き上げる設計)。

## 使い方

Claude Code上で以下のスラッシュコマンドを使う。難易度(1〜5)と手番(black/white)は
引数で指定できる(例: `/shogi-brain 3 black`)。省略した場合は対局開始前に確認される。

| コマンド | モード |
|---|---|
| `/shogi-brain [difficulty] [user_side]` | Claude思考モード。エンジンのヒントを使わず、Claude自身が解析ツール(詰み探索・候補手検証・読み筋シミュレータ)を頼りに考えて指す。 |
| `/shogi-csa [user_side]` | CSA対局モード。ユーザー側の手はユーザー本人が手元のCSA対応対局ソフトから実際に指し、対局相手側はClaudeが思考モードで指す(USIエンジン不使用)。 |
| `/shogi-resume [KIFパス]` | 保存済みの対局を再開する。パス省略時は`games/`内の最新KIFを使う。 |

### 難易度

`/shogi-brain`における対局相手(やねうら王)の強さ。`/shogi-csa`はUSIエンジンを使わないため、
この難易度設定は適用されない。

| Lv | 想定 | 設定 |
|---|---|---|
| 1 | 入門 | NodesLimit=1000, byoyomi 100ms |
| 2 | 初級 | NodesLimit=10000, byoyomi 300ms |
| 3 | 中級 | NodesLimit=100000, byoyomi 1000ms |
| 4 | 上級 | NodesLimit無制限, byoyomi 2000ms |
| 5 | 最強 | NodesLimit無制限, byoyomi 5000ms, Threads 8 |

体感の強さに応じて`mcp-server/src/shogi_mcp/presets.py`のノード数を調整できる。
Lv2(初級)でもかなり強く、Fable 5では歯が立たなかった実績がある。

### CSA対局モード

`/shogi-csa`は、ユーザー側の手をユーザー本人が手元のCSA対応対局ソフトから実際に指す
モード。対局相手側はClaudeが`/shogi-brain`と同じ思考ロジック(エンジンのヒント不使用)で
指す。MCPサーバー起動時、`127.0.0.1:4081`でCSA通信対局プロトコル(サブセット)を待受する
常時稼働のTCPサーバーも起動する(標準ライブラリの`socket`/`socketserver`のみで実装、
追加の外部依存なし)。

Linux上のShogiHomeで動作確認済み。ShogiGUI・将棋所等の他のCSA対応ソフトも原理上は
接続できるはずだが未確認(いずれもWindows専用)。

- 接続元は同一マシン上のCSA対応クライアントを想定し、待受は
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
- **Claudeのコメント**: Claude思考モードでは、着手の狙いや山場の所感が`apply_move`の
  `comment`引数 / `add_comment`ツール経由でコメント行に記録される。

記録済みの対局は `http://localhost:8765/replay` でブラウザ再生できる。対局の選択、
手数スライダー/前後ボタン(←→キー対応)での盤面送り、指し手ごとのコメント表示、
評価値グラフ(クリックで該当手へジャンプ)に対応する。対局セッションとは独立に
KIFファイルだけを読むため、対局中でも過去譜を再生できる。

### ツール呼び出しログ

思考用ツール(`rank_moves`・`verify_moves`・`analyze_position`・`simulate_line`・`apply_move`)の
呼び出しは、対局のKIFと同じ`games/`に`<KIF名>.toollog.jsonl`として1行1呼び出しで記録される
(Git管理外)。各行は時刻(`ts`)・手数(`ply`、呼び出し時点の指し手数)・`tool`・所要時間
(`elapsed_ms`)・引数(`args`、実効値)・結果の要約(`summary`)を持つ。たとえば`rank_moves`は
完了した深さ(`depth`)・時間で打ち切ったか(`time_limited`)・上位3手、`verify_moves`は候補ごとの
`search_depth_completed`・`search_truncated`、`apply_move`は指した手とコメントの先頭を残す。
実戦で探索の挙動とClaudeの選択を後から検証するためのもので、記録の失敗はツールの結果に
影響しない。`SHOGI_MCP_TOOLLOG=0`で無効化できる。

## このプロジェクトについて

このツールはすべてClaudeが設計し実装した。
人間はアイディアを提供した。
ただし、one shotの作品ではなく、人間がこだわりを持って調整した。

## ライセンス

GPLv3(`LICENSE`参照)。
`scripts/setup_engine.sh`が取得する評価関数(`engine/eval/nn.bin`、リポジトリには含まれず
セットアップ時に配布元から取得する)はtanuki-チームによる配布物でGPLv3
(取得時に同ディレクトリへ配置される`engine/eval/LICENSE-eval-gpl-3.0.txt`参照)。
やねうら王本体もGPLv3。
