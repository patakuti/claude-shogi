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
`save_kif` / `load_kif` / `resign`(詳細は`02_design.md` §3)、およびClaude思考モード用の
解析ツール `analyze_position` / `verify_moves` / `simulate_line`(同§11。エンジン不使用の
cshogiベース自前実装で、詰み探索・頓死チェック・浅い駒得探索・読み筋の検証を行う)。

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

## ライセンス

本リポジトリのコードのライセンスはTBD。
同梱の評価関数(`engine/eval/nn.bin`)はtanuki-チームによる配布物でGPLv3
(`engine/eval/LICENSE-eval-gpl-3.0.txt`参照)。やねうら王本体もGPLv3。
