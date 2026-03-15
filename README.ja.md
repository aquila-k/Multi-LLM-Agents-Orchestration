# Multi-LLM Agents Orchestration

複数の LLM プロバイダー（Codex・Copilot・Gemini）にタスクを振り分け、計画・実装・レビュー・セキュリティ強化を自動で実行するオーケストレーションランタイム。

| ツール                   | CLI                | 役割                                                                 |
| ------------------------ | ------------------ | -------------------------------------------------------------------- |
| **オーケストレーション** | `agentorch collab` | 複数の LLM にタスクを振り分けて plan / impl / review / harden を実行 |
| **コンテキスト管理**     | `agentorch ctx`    | タスクの知識・判断・スナップショットを SQLite DB で永続化            |
| **タスクレジストリ**     | `agentorch task`   | アクティブなタスク・プロバイダー参加・親子タスク階層を追跡           |

3 つは連携することで効果を発揮するが、それぞれ単体でも利用できる。

---

## インストール

### git から（現時点での推奨）

```bash
git clone https://github.com/aquila-k/Multi-LLM-Agents-Orchestration.git
cd Multi-LLM-Agents-Orchestration
pip install -e .

# ベクター検索も使う場合（オプション）
pip install -e ".[vector]"

# 確認
agentorch version
agentorch doctor
```

### uv を使う場合

```bash
uv pip install "git+https://github.com/aquila-k/Multi-LLM-Agents-Orchestration.git"
```

### 前提条件

- Python 3.11+
- 以下のいずれかの LLM CLI（認証済み）：
  - `codex`（OpenAI Codex）
  - `copilot`（GitHub Copilot CLI）
  - `gemini`（Google Gemini CLI）

---

## クイックスタート

### プロジェクトの初期化

```bash
cd your-project
agentorch init                # 全セットアップ: 設定・コンテキストDB・エージェント指示書
```

生成されるもの:

- `.agentorch/configs/` — オーケストレーション設定（編集可能）
- `.contexts/local/context.db` — コンテキストDB（gitignore 済み）
- `.claude/skills/`, `.agent/skills/`, `.github/instructions/` — 各エージェント用指示書
- `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` — エージェント指示セクション追記

個別に初期化することも可能:

```bash
agentorch collab init         # オーケストレーション設定 + Claude Code 指示書のみ
agentorch ctx init            # コンテキストDB + 全エージェント指示書のみ
```

### ワークフローの実行

```bash
agentorch collab plan   --source /path/to/goal.md
agentorch collab impl   --source /path/to/task.json
agentorch collab review --source /path/to/task.md
agentorch collab harden --source /path/to/task.md
```

### コンテキスト管理

```bash
# タスクを登録
TASK_ID=$(agentorch task create --summary "認証バグの修正" --provider claude)

# 過去の決定を検索
agentorch ctx search-memory --query "authentication" --limit 10

# 決定を記録
echo '{"decision": "JWT を使用", "reason": "ステートレス認証が必要", "semantic_hint": "JWT auth decision"}' \
  | agentorch ctx log-decision --key auth-method --scope task/$TASK_ID --stdin

# タスクコンテキストを取得
agentorch ctx get-task-context --task-id $TASK_ID --include-project
```

---

## `agentorch collab` — オーケストレーション

### 入力ファイルの形式

シンプルな Markdown か、細かく制御したい場合は JSON で記述:

```markdown
# 認証モジュールのリファクタリング

認証ヘルパーを AuthService クラスに集約し、後方互換性を維持する。
```

```json
{
  "summary": "認証モジュールのリファクタリング",
  "targets": { "path": "src/auth/" },
  "constraints": { "disallowed_paths": ["src/legacy/"] },
  "selectors": { "strategy": "COLLAB_IMPL_PATCH_FIRST" }
}
```

### オプションフラグ

```bash
--strategy STRATEGY_ID    # 戦略を手動指定
--with-harden             # review と harden を 1 パスで実行
--dry-run                 # プロバイダーを呼び出さずに設定を検証
```

### フェーズと戦略

| フェーズ   | 使用可能な戦略                                                          | 用途                 |
| ---------- | ----------------------------------------------------------------------- | -------------------- |
| **plan**   | `QUESTIONS_ONLY`, `MINIMAL`, `FULL`, `THOROUGH`                         | 実装計画の生成       |
| **impl**   | `BATCH_SHOT`, `PATCH_FIRST`, `SPEC_PATCH`, `FILE_BY_FILE`, `SHIELD_FIX` | コード変更の適用     |
| **review** | `LITE`, `MODE_A`, `MODE_B`, `STANDARD`, `STRICT`                        | コードレビューと指摘 |
| **harden** | `LITE`, `STANDARD`, `FULL`                                              | セキュリティ強化     |

戦略名はすべて `COLLAB_{PHASE}_` プレフィックスが付く（例：`COLLAB_PLAN_FULL`）。

### 予算と承認ゲート

- **ソフトキャップ**: 低コストなプロバイダーが優先されるよう順位を調整
- **ハードキャップ**: `STOP_AND_CONFIRM` を出力して実行を一時停止
- **再開**: `agentorch collab resume --source resume.json`

### アーティファクト

```
.agentorch/artifacts/tasks/<task_id>/
  ├── requests/        # 入力リクエスト
  ├── routing/         # プロバイダー選択結果
  ├── prompts/         # 組み立て済みプロンプト
  ├── responses/       # プロバイダーからの生応答
  ├── normalized/      # 正規化済み出力
  ├── events.jsonl     # イベントログ
  └── manifests/       # 来歴マニフェスト
```

---

## `agentorch ctx` — コンテキスト管理

SQLite ベースの永続記憶。あらゆるエージェントで利用可能。

### 主なコマンド

```bash
agentorch ctx get-task-context --task-id <id> --include-project
echo '<snapshot>' | agentorch ctx update-task-context --task-id <id> --expected-revision 0 --stdin
echo '<decision>' | agentorch ctx log-decision --key <key> --scope task/<id> --stdin
agentorch ctx search-memory --query "キーワード" --limit 10
agentorch ctx search-memory --query "なぜこの設計にしたか" --mode hybrid
agentorch ctx doctor
```

### ベクター検索（オプション）

FTS5 キーワード検索は標準で利用可能。ベクター検索はオプション:

```bash
pip install -e ".[vector]"           # ベクター依存をインストール
agentorch ctx setup-vector           # ベクターインデックスを構築
agentorch ctx vector-doctor          # セットアップを確認
```

---

## `agentorch task` — タスクレジストリ

エージェントとセッションをまたいでタスクを追跡:

```bash
TASK_ID=$(agentorch task create --summary "認証のリファクタリング" --provider claude)
agentorch task current                                    # 現在のアクティブタスク
agentorch task create --summary "計画" --parent $TASK_ID  # 子タスク
agentorch task list --status active                       # タスク一覧
agentorch task status $TASK_ID --set completed            # 完了マーク
agentorch task check                                      # stale タスク検出
```

---

## エージェント指示書

`agentorch init` が各エージェント用の指示書を自動生成:

| エージェント | 生成ファイル                                                                       |
| ------------ | ---------------------------------------------------------------------------------- |
| Claude Code  | `.claude/skills/agentorch-{collab,ctx}/`, `.claude/rules/`, `CLAUDE.md` セクション |
| Codex        | `.agent/skills/agentorch-ctx/`, `AGENTS.md` セクション                             |
| Copilot      | `.github/instructions/agentorch-ctx.instructions.md`                               |
| Gemini       | `GEMINI.md` セクション                                                             |

オーケストレーション (`collab`) は Claude Code 専用。コンテキスト管理 (`ctx`) は全エージェント共通。

---

## プロジェクト構成

```
agentorch_ctx/              # Python パッケージ（pip でインストール）
  ├── __main__.py           # CLI: agentorch version|doctor|init|collab|ctx|task
  ├── runtime/              # タスクランナー・ルーティング・プロバイダー
  ├── contexts/             # コンテキスト管理ランタイム
  ├── task_registry/        # タスク追跡データベース
  ├── configs/              # 内部デフォルト + ユーザー設定テンプレート
  ├── templates/            # エージェント指示テンプレート（init で生成）
  └── tests/                # テスト

.agentorch/                 # `agentorch init` で作成（プロジェクト固有）
  ├── configs/              # ユーザー編集可能な設定
  └── artifacts/            # タスクアーティファクト（gitignore 済み）

.contexts/                  # `agentorch ctx init` で作成（プロジェクト固有）
  ├── run                   # 後方互換 wrapper
  └── local/                # gitignore 済み: DB・設定
```

## ライセンス

MIT
