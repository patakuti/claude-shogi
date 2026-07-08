# claude-shogi

Claude Code上で、将棋エンジン(やねうら王)を相手に対局できる環境。

## 概要

- 対局相手は常にコンピュータ(USIプロトコル対応の将棋エンジン)。
- ユーザー側の手をどう決めるかを、対局開始時に3つのモードから選択できる。
  - 自動モード / Claude対話モード / ユーザー対話モード
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

(実装中。フェーズ4完了後に記載予定)

## 使い方

(実装中。フェーズ5完了後にスラッシュコマンドの使い方を記載予定)

## ライセンス

本リポジトリのコードのライセンスはTBD。
同梱の評価関数(`engine/eval/nn.bin`)はtanuki-チームによる配布物でGPLv3
(`engine/eval/LICENSE-eval-gpl-3.0.txt`参照)。やねうら王本体もGPLv3。
