# Multi-LLM Agents Orchestration

複数の LLM プロバイダー（Codex・Copilot・Gemini）にタスクを振り分け、計画・実装・レビュー・セキュリティ強化を自動で実行するオーケストレーションランタイム。
全ステップの判断・プロンプト・応答は JSON アーティファクトとして記録され、完全な再現性を保証する。

また、`.contexts/` はスタンドアロンのコンテキスト管理ツールとして単体でも利用できる。

## 概要

このリポジトリは独立した 2 つのツールで構成されている。

| ツール           | 役割                                                                                   |
| ---------------- | -------------------------------------------------------------------------------------- |
| **`collab/`**    | 複数の LLM にタスクを振り分けて実行するオーケストレーションランタイム                  |
| **`.contexts/`** | タスクの知識や判断をセッションをまたいで保持する SQLite ベースのコンテキスト管理ツール |

2 つは連携することで効果を発揮するが、それぞれ単体でも利用できる。

```
目標 (Markdown/JSON)
  → collab/run plan    → 構造化された計画
  → collab/run impl    → コード変更（git 経由で適用）
  → collab/run review  → レビュー結果と修正案
  → collab/run harden  → セキュリティ強化
```

---

## `collab/` — オーケストレーションランタイム

### 前提条件

- Python 3.13+
- 以下のいずれかの LLM CLI（認証済み）：
  - `codex`（OpenAI Codex）
  - `copilot`（GitHub Copilot CLI）
  - `gemini`（Google Gemini CLI）

### クイックスタート

**目標ファイルを作成する：**

```markdown
# 認証モジュールのリファクタリング

認証ヘルパーを AuthService クラスに集約し、後方互換性を維持する。
```

`goal.md` として保存して実行：

```bash
./collab/run plan --source /path/to/goal.md
./collab/run impl --source /path/to/goal.md
```

プロバイダーの選択・プロンプトの組み立て・ステップの実行・アーティファクトの保存はすべて自動で行われる。

### オプションフラグ

```bash
--strategy STRATEGY_ID    # 戦略を手動指定
--with-harden             # review と harden を 1 パスで実行
--dry-run                 # プロバイダーを呼び出さずに設定を検証
```

### 入力ファイルの形式

シンプルな Markdown か、細かく制御したい場合は JSON で記述する。

```json
{
  "summary": "認証モジュールのリファクタリング",
  "targets": { "path": "src/auth/" },
  "constraints": { "disallowed_paths": ["src/legacy/"] },
  "selectors": { "strategy": "COLLAB_IMPL_PATCH_FIRST" }
}
```

### フェーズと戦略

各フェーズには、用途別の複数ステップからなるワークフロー（戦略）が用意されている。

| フェーズ   | 使用可能な戦略                                                          | 用途                 |
| ---------- | ----------------------------------------------------------------------- | -------------------- |
| **plan**   | `QUESTIONS_ONLY`, `MINIMAL`, `FULL`, `THOROUGH`                         | 実装計画の生成       |
| **impl**   | `BATCH_SHOT`, `PATCH_FIRST`, `SPEC_PATCH`, `FILE_BY_FILE`, `SHIELD_FIX` | コード変更の適用     |
| **review** | `LITE`, `MODE_A`, `MODE_B`, `STANDARD`, `STRICT`                        | コードレビューと指摘 |
| **harden** | `LITE`, `STANDARD`, `FULL`                                              | セキュリティ強化     |

戦略名はすべて `COLLAB_{PHASE}_` プレフィックスが付く（例：`COLLAB_PLAN_FULL`）。

### プロバイダールーティング

ルーティングエンジンが各ステップに最適なプロバイダーを自動選択する：

1. **絞り込み** — セッション再開や JSON スキーマ対応など、必要な機能を持つ候補を抽出
2. **スコアリング** — コンテキスト適合度・コスト・信頼性などで候補を順位付け
3. **選択** — 最高スコアのプロバイダーを採用
4. **予算ガード** — 上限コストを超えた場合は実行を一時停止

プロバイダーとモデルのプリセットは `collab/configs/user/` で管理する。

### 予算と承認ゲート

- **ソフトキャップ**：低コストなプロバイダーが優先されるよう順位を調整
- **ハードキャップ**：`STOP_AND_CONFIRM` を出力して実行を一時停止
- **再開方法**：`approval_continuation: approved` を含む再開用 JSON を作成して `./collab/run resume --source resume.json` を実行

### アーティファクト

実行ごとに完全な JSON 監査ログが生成される：

```
collab/artifacts/tasks/<task_id>/
  ├── requests/        # 入力リクエスト
  ├── routing/         # プロバイダー選択結果
  ├── prompts/         # 組み立て済みプロンプト
  ├── responses/       # プロバイダーからの生応答
  ├── normalized/      # 正規化済み出力
  ├── checkpoints/     # git 状態スナップショット
  ├── events.jsonl     # イベントログ
  └── manifests/       # 来歴マニフェスト
```

アーティファクトはプロジェクト固有のデータのため、`.gitignore` でリポジトリから除外される。

### 設定ファイル

```
collab/configs/user/
  ├── plan.json       # plan フェーズの戦略とモデルプリセット
  ├── impl.json       # impl フェーズの戦略
  ├── review.json     # review フェーズの戦略
  ├── harden.json     # harden フェーズの戦略
  └── providers.json  # デフォルトのプロバイダー設定
```

各設定ファイルは `$presets`（モデルの短縮名）と `strategies`（ステップの並び）を定義する。`default` キーがデフォルトプリセットとなる。

---

## `.contexts/` — コンテキスト管理ツール

**`collab/` とは独立して単体でも使える。** Claude・Codex・Gemini などあらゆるエージェントのコンテキスト永続化に利用できる。

### セットアップ

```bash
.contexts/run init
```

`.contexts/local/`（git 管理外）に SQLite データベースが作成される。

### 主なコマンド

```bash
# タスク開始時：コンテキストを取得
.contexts/run get-task-context --task-id <id> --include-project --format markdown

# 作業中：スナップショットを更新
.contexts/run update-task-context --task-id <id> --expected-revision 0 < payload.json

# 設計上の判断を記録
.contexts/run log-decision --key <key> --scope task/<id> < decision.json

# 過去の記録を検索（キーワード）
.contexts/run search-memory --query "キーワード" --limit 10

# 過去の記録を検索（意味検索・ハイブリッド — ベクター検索セットアップ済みの場合に使用可能）
.contexts/run search-memory --query "キーワード" --mode hybrid --limit 10

# メンテナンス
.contexts/run doctor          # 正常性チェック
.contexts/run render-context  # スコープの Markdown サマリーを生成
```

### ベクター検索（オプション）

`.contexts/` は標準で **FTS5 キーワード検索**を提供する。オプションとして**ベクター（意味）検索**レイヤーを追加でき、既存の DB やコマンドには一切影響しない。

| プロファイル | 必要環境 | 利用可能な検索モード |
| --- | --- | --- |
| **core**（標準） | Python 3.8+, SQLite | `fts` のみ |
| **vector-enabled** | Python 3.12, `sqlite-vec`, `fastembed` | `fts`, `semantic`, `hybrid`, `auto` |

#### vector-enabled プロファイルのセットアップ

`.contexts/run` はすべてのコマンドに対応した統一エントリーポイント。ベクター検索をセットアップすると自動的に使用される。

```bash
# 実行内容を確認（ディスク・時間の警告表示、変更なし）
.contexts/run setup-vector --dry-run

# ローカルにインストール（.contexts/ 隣に .venv-vector/ を作成）
.contexts/run setup-vector

# グローバルにインストール（複数リポジトリ間で依存を共有、1 プロジェクトあたり約 400 MB 節約）
.contexts/run setup-vector --global

# 任意のパスにインストール
.contexts/run setup-vector --venv-path /path/to/venv

# セットアップを確認
.contexts/run vector-doctor
```

注意事項：

- 初回実行時は埋め込みモデル約 90 MB を `~/.cache/huggingface/` にダウンロード
- 合計ディスク使用量：パッケージ約 400 MB + モデル約 90 MB
- 初期インデックス構築：1〜3 分程度
- FTS キーワード検索はセットアップなしで即時使用可能
- `--global` を使用するとリポジトリ間でパッケージを共有でき、ベクターインデックスはプロジェクトごとに保持

#### ベクター検索の使い方

セットアップ後は、すべての検索コマンドで同じ `.contexts/run` エントリーポイントを使用する：

```bash
# auto モード（ベクター利用可能ならハイブリッド、不可なら fts）
.contexts/run search-memory --query "なぜこの設計を選んだのか" --mode auto

# 意味検索（言語・表現に依存しない）
.contexts/run search-memory --query "認証の方針" --mode semantic

# ハイブリッド検索（FTS + 意味検索を順位融合）
.contexts/run search-memory --query "DB スキーマの決定" --mode hybrid

# 書き込み後にインデックスを差分更新
.contexts/run sync-vector-index
```

ベクター検索未セットアップの状態で `semantic` や `hybrid` を指定した場合は FTS にフォールバックし、レスポンスに `setup_hint` フィールドが追加される。

### 各エージェントでの使い方

#### Claude（CLAUDE.md / copilot-instructions.md）

プロジェクトルートに以下を記述すると、Claude がタスク開始時に自動でコンテキストを参照する：

```markdown
## コンテキスト管理

作業前に必ず実行：
`.contexts/run get-task-context --task-id <TASK_ID> --include-project --format markdown`

作業後に記録：
`.contexts/run update-task-context --task-id <TASK_ID> --expected-revision 0 < snapshot.json`
```

#### Codex（`.codex/instructions.md`）

```markdown
Before starting any task, retrieve context:
.contexts/run get-task-context --task-id <TASK_ID> --include-project

After completing work, save progress:
.contexts/run update-task-context --task-id <TASK_ID> --expected-revision 0 < snapshot.json
```

#### Gemini（`GEMINI.md`）

```markdown
On task start: `.contexts/run get-task-context --task-id <TASK_ID> --include-project --format markdown`
On task end: `.contexts/run update-task-context --task-id <TASK_ID> --expected-revision 0 < snapshot.json`
```

### エントリの種類

| 種類              | スコープ     | 用途                     |
| ----------------- | ------------ | ------------------------ |
| `project_profile` | project      | プロジェクトの目標・制約 |
| `task_snapshot`   | task/session | 現在の計画・進捗・障害   |
| `decision`        | 任意         | 設計上の判断とその根拠   |
| `episode`         | task         | フェーズごとの観察と教訓 |
| `procedural_rule` | 任意         | 再利用可能な手順ルール   |

### スコープの階層

```
project → branch → task → session
```

より具体的なスコープは上位スコープを継承する。`task`・`session` スコープのエントリは即時有効になり、`project`・`branch` スコープはオペレーターの承認が必要となる。

---

## プロジェクト構成

```
collab/                     # オーケストレーションランタイム（単体利用可）
  ├── run                   # CLI エントリーポイント
  ├── runtime/              # タスクランナー・ルーティング・プロバイダー・アーティファクト
  ├── configs/user/         # ユーザーが編集するフェーズ設定
  ├── schemas/              # JSON スキーマ
  ├── docs/                 # 設計ポリシードキュメント
  └── tests/                # ユニット・統合・stub-e2e・リグレッション

.contexts/                  # コンテキスト管理ツール（単体利用可）
  ├── run                   # 統一 CLI エントリーポイント（venv を自動検出し python3 にフォールバック）
  ├── runtime/
  │   └── vector/           # ベクター検索拡張（オプション）
  ├── sql/                  # マイグレーションスクリプト
  ├── schemas/              # エントリペイロードスキーマ
  └── local/                # git 管理外; DB・設定・vector_python_path

.venv-vector/               # git 管理外; setup-vector が作成するリポジトリローカル venv（オプション）
```

## ライセンス

MIT
