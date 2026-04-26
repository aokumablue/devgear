"""SQLite データベース管理 (FTS5 trigram + sqlite-vec)"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from devgear.mem.logger import get as _get_logger

log = _get_logger("DB")


def generate_uuid() -> str:
    """UUID v4 を生成する"""
    return str(uuid.uuid4())


# --- データ型 ---


@dataclass
class MemoryChunk:
    session_id: str
    project: str
    chunk_index: int
    content: str
    tool_names: list[str]
    files_read: list[str]
    files_modified: list[str]
    user_prompt: str
    created_at_epoch: int
    id: str | None = None
    origin_user: str = ""

    # Phase 1: コンテキスト品質向上
    access_count: int = 0
    last_accessed_epoch: int | None = None

    # Phase 2: メモリ圧縮
    merged_generation: int = 0
    merged_into: str | None = None

    # Phase 3: 実行品質トラッキング
    execution_status: str = "unknown"  # 'success'|'partial'|'failure'|'unknown'
    tool_error: str | None = None  # エラーメッセージ先頭500文字
    ai_response_summary: str | None = None  # AI応答の要約（最大500文字）
    tool_sequence: list[str] = field(default_factory=list)  # 順序保持・重複ありリスト


@dataclass
class Session:
    session_id: str
    project: str
    started_at_epoch: int
    chunk_count: int = 0
    id: str | None = None
    origin_user: str = ""

    # git 状態（セッション開始時のスナップショット）
    branch: str | None = None
    commit_hash: str | None = None  # HEAD 先頭12文字
    uncommitted_count: int = 0
    ended_at_epoch: int | None = None
    project_profile_id: str | None = None  # project_profiles への参照


@dataclass
class Instinct:
    """インスティンクトデータ"""

    instinct_id: str
    scope: str
    confidence: float
    content: str
    created_at_epoch: int
    updated_at_epoch: int
    id: str | None = None
    origin_user: str = ""
    project_id: str | None = None
    trigger_text: str | None = None
    domain: str | None = None

    # 信頼度の根拠
    observation_count: int = 0
    confidence_reasons: list[dict] = field(default_factory=list)  # [{reason, weight}]
    source_interaction_ids: list[str] = field(default_factory=list)  # interaction_log IDs
    last_activated_epoch: int | None = None


@dataclass
class Adr:
    """ADR データ"""

    project: str
    adr_number: int
    title: str
    status: str
    content: str
    created_at_epoch: int
    updated_at_epoch: int
    id: str | None = None
    origin_user: str = ""


@dataclass
class EventLog:
    """汎用イベントログ"""

    event_type: str
    content: str
    created_at_epoch: int
    id: str | None = None
    origin_user: str = ""
    project_id: str | None = None


@dataclass
class InteractionLog:
    """ユーザー指示と AI 応答のペア記録（スキル自動生成の原料）"""

    session_id: str
    project: str
    user_prompt_full: str  # トランケートなし全文
    interaction_index: int  # セッション内通し番号
    created_at_epoch: int
    id: str | None = None
    origin_user: str = ""
    user_prompt_hash: str | None = None  # SHA256先頭16文字
    ai_response_summary: str | None = None  # 最大2000文字
    ai_response_tool_plan: str | None = None  # JSON配列（最大10件）
    chunk_id: str | None = None
    execution_outcome: str = "unknown"  # 'success'|'partial'|'failure'|'unknown'
    tool_error_count: int = 0


@dataclass
class ProjectProfile:
    """プロジェクトの技術スタック情報（instinct の scope 判定に使用）"""

    project: str
    detected_at_epoch: int
    last_updated_epoch: int
    id: str | None = None
    origin_user: str = ""
    project_path: str | None = None
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    primary_language: str | None = None
    test_command: str | None = None
    build_command: str | None = None
    scope_hint: str = "project"  # 'global'|'project'
    detection_confidence: float = 1.0


@dataclass
class MemItemRun:
    """メムサブシステムが観測したスキル・コマンド・エージェントの実行記録（ベストエフォート）"""

    session_id: str
    project: str
    skill_name: str
    created_at_epoch: int
    id: str | None = None
    origin_user: str = ""
    skill_trigger: str | None = None  # トリガープロンプト先頭200文字
    outcome: str = "unknown"  # 'success'|'partial'|'failure'|'unknown'
    tools_used: list[str] = field(default_factory=list)
    files_modified_count: int = 0
    duration_seconds: int | None = None
    interaction_log_id: str | None = None
    item_type: str = "skill"  # 'skill'|'command'|'agent'


# --- スキーマ ---

_SCHEMA_SQL = """\
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS memory_chunks (
  id TEXT PRIMARY KEY,
  origin_user TEXT NOT NULL DEFAULT '',
  session_id TEXT NOT NULL,
  project TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  tool_names TEXT,
  files_read TEXT,
  files_modified TEXT,
  user_prompt TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  created_at_epoch INTEGER NOT NULL,
  access_count INTEGER DEFAULT 0,
  last_accessed_epoch INTEGER,
  merged_generation INTEGER DEFAULT 0,
  merged_into TEXT REFERENCES memory_chunks(id),
  execution_status TEXT DEFAULT 'unknown',
  tool_error TEXT,
  ai_response_summary TEXT,
  tool_sequence TEXT DEFAULT '[]',
  synced_at TEXT,
  UNIQUE(session_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_session ON memory_chunks(session_id);
CREATE INDEX IF NOT EXISTS idx_chunks_project ON memory_chunks(project);
CREATE INDEX IF NOT EXISTS idx_chunks_epoch ON memory_chunks(created_at_epoch);
CREATE INDEX IF NOT EXISTS idx_chunks_origin ON memory_chunks(origin_user);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  origin_user TEXT NOT NULL DEFAULT '',
  session_id TEXT NOT NULL,
  project TEXT NOT NULL,
  started_at TEXT DEFAULT (datetime('now')),
  started_at_epoch INTEGER NOT NULL,
  chunk_count INTEGER DEFAULT 0,
  branch TEXT,
  commit_hash TEXT,
  uncommitted_count INTEGER DEFAULT 0,
  ended_at_epoch INTEGER,
  project_profile_id TEXT,
  synced_at TEXT,
  UNIQUE(session_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_origin ON sessions(origin_user);

-- インスティンクト
CREATE TABLE IF NOT EXISTS instincts (
  id TEXT PRIMARY KEY,
  origin_user TEXT NOT NULL DEFAULT '',
  instinct_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  project_id TEXT,
  trigger_text TEXT,
  confidence REAL NOT NULL,
  domain TEXT,
  content TEXT NOT NULL,
  created_at_epoch INTEGER NOT NULL,
  updated_at_epoch INTEGER NOT NULL,
  observation_count INTEGER DEFAULT 0,
  confidence_reasons TEXT DEFAULT '[]',
  source_interaction_ids TEXT DEFAULT '[]',
  last_activated_epoch INTEGER,
  synced_at TEXT,
  UNIQUE(origin_user, instinct_id, scope, project_id)
);

CREATE INDEX IF NOT EXISTS idx_instincts_user ON instincts(origin_user);
CREATE INDEX IF NOT EXISTS idx_instincts_scope ON instincts(scope);
CREATE INDEX IF NOT EXISTS idx_instincts_project ON instincts(project_id);

-- ADR
CREATE TABLE IF NOT EXISTS adrs (
  id TEXT PRIMARY KEY,
  origin_user TEXT NOT NULL DEFAULT '',
  project TEXT NOT NULL,
  adr_number INTEGER NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at_epoch INTEGER NOT NULL,
  updated_at_epoch INTEGER NOT NULL,
  synced_at TEXT,
  UNIQUE(origin_user, project, adr_number)
);

CREATE INDEX IF NOT EXISTS idx_adrs_user ON adrs(origin_user);
CREATE INDEX IF NOT EXISTS idx_adrs_project ON adrs(project);

-- 汎用イベントログ
CREATE TABLE IF NOT EXISTS event_logs (
  id TEXT PRIMARY KEY,
  origin_user TEXT NOT NULL DEFAULT '',
  event_type TEXT NOT NULL,
  project_id TEXT,
  content TEXT NOT NULL,
  created_at_epoch INTEGER NOT NULL,
  synced_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_type ON event_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_events_epoch ON event_logs(created_at_epoch);
CREATE INDEX IF NOT EXISTS idx_events_project ON event_logs(project_id);

-- ユーザー指示と AI 応答のペア記録（スキル自動生成の最重要原料）
CREATE TABLE IF NOT EXISTS interaction_logs (
  id TEXT PRIMARY KEY,
  origin_user TEXT NOT NULL DEFAULT '',
  session_id TEXT NOT NULL,
  project TEXT NOT NULL,
  user_prompt_full TEXT NOT NULL,
  user_prompt_hash TEXT,
  ai_response_summary TEXT,
  ai_response_tool_plan TEXT,
  chunk_id TEXT REFERENCES memory_chunks(id),
  execution_outcome TEXT DEFAULT 'unknown',
  tool_error_count INTEGER DEFAULT 0,
  interaction_index INTEGER NOT NULL,
  created_at_epoch INTEGER NOT NULL,
  synced_at TEXT,
  UNIQUE(session_id, interaction_index)
);

CREATE INDEX IF NOT EXISTS idx_ilog_session ON interaction_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_ilog_project ON interaction_logs(project);
CREATE INDEX IF NOT EXISTS idx_ilog_epoch ON interaction_logs(created_at_epoch);
CREATE INDEX IF NOT EXISTS idx_ilog_outcome ON interaction_logs(execution_outcome);
CREATE INDEX IF NOT EXISTS idx_ilog_hash ON interaction_logs(user_prompt_hash);

-- プロジェクトの技術スタック情報（instinct の scope 判定に使用）
CREATE TABLE IF NOT EXISTS project_profiles (
  id TEXT PRIMARY KEY,
  origin_user TEXT NOT NULL DEFAULT '',
  project TEXT NOT NULL,
  project_path TEXT,
  languages TEXT NOT NULL DEFAULT '[]',
  frameworks TEXT NOT NULL DEFAULT '[]',
  primary_language TEXT,
  test_command TEXT,
  build_command TEXT,
  scope_hint TEXT DEFAULT 'project',
  detected_at_epoch INTEGER NOT NULL,
  last_updated_epoch INTEGER NOT NULL,
  detection_confidence REAL DEFAULT 1.0,
  synced_at TEXT,
  UNIQUE(origin_user, project)
);

CREATE INDEX IF NOT EXISTS idx_proj_prof_user ON project_profiles(origin_user);
CREATE INDEX IF NOT EXISTS idx_proj_prof_lang ON project_profiles(primary_language);

-- アイテム実行記録（スキル・コマンド・エージェント、ベストエフォート観測）
CREATE TABLE IF NOT EXISTS mem_item_runs (
  id TEXT PRIMARY KEY,
  origin_user TEXT NOT NULL DEFAULT '',
  session_id TEXT NOT NULL,
  project TEXT NOT NULL,
  skill_name TEXT NOT NULL,
  skill_trigger TEXT,
  outcome TEXT DEFAULT 'unknown',
  tools_used TEXT DEFAULT '[]',
  files_modified_count INTEGER DEFAULT 0,
  duration_seconds INTEGER,
  interaction_log_id TEXT REFERENCES interaction_logs(id),
  created_at_epoch INTEGER NOT NULL,
  synced_at TEXT,
  item_type TEXT NOT NULL DEFAULT 'skill'
);

CREATE INDEX IF NOT EXISTS idx_mir_skill ON mem_item_runs(skill_name);
CREATE INDEX IF NOT EXISTS idx_mir_project ON mem_item_runs(project);
CREATE INDEX IF NOT EXISTS idx_mir_epoch ON mem_item_runs(created_at_epoch);
CREATE INDEX IF NOT EXISTS idx_mir_outcome ON mem_item_runs(outcome, created_at_epoch);
CREATE INDEX IF NOT EXISTS idx_mir_item_type ON mem_item_runs(item_type);
"""

# FTS5 と sqlite-vec は別途作成（拡張依存のため）
_FTS5_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts USING fts5(
  chunk_id UNINDEXED,
  content,
  user_prompt,
  tool_names,
  files_read,
  files_modified,
  ai_response_summary,
  tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON memory_chunks BEGIN
  INSERT INTO memory_chunks_fts(chunk_id, content, user_prompt, tool_names, files_read, files_modified, ai_response_summary)
  VALUES (new.id, new.content, new.user_prompt, new.tool_names, new.files_read, new.files_modified, new.ai_response_summary);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON memory_chunks BEGIN
  DELETE FROM memory_chunks_fts WHERE chunk_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON memory_chunks BEGIN
  UPDATE memory_chunks_fts
  SET content = new.content,
      user_prompt = new.user_prompt,
      tool_names = new.tool_names,
      files_read = new.files_read,
      files_modified = new.files_modified,
      ai_response_summary = new.ai_response_summary
  WHERE chunk_id = new.id;
END;
"""

_VEC_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_vec USING vec0(
  chunk_id TEXT PRIMARY KEY,
  embedding FLOAT[768]
);
"""

# --- マイグレーション ---

_MIGRATIONS: list[tuple[str, list[str]]] = []


def _make_prompt_hash(prompt: str) -> str:
    """プロンプトの SHA256 先頭16文字を返す（重複検出用）。"""
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


class Database:
    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._migrate()
        # Phase 0: パフォーマンス最適化 PRAGMA
        self.conn.execute("PRAGMA temp_store = MEMORY")
        self.conn.execute("PRAGMA mmap_size = 268435456")
        self.conn.execute("PRAGMA cache_size = -64000")

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(_SCHEMA_SQL)

        # FTS5 (SQLite 組み込み)
        try:
            cur.executescript(_FTS5_SQL)
        except sqlite3.OperationalError as e:
            log.warning("FTS5 初期化失敗（古い SQLite?）: %s", e)

        # sqlite-vec 拡張（オプショナル）
        try:
            import sqlite_vec  # type: ignore[import-untyped]

            sqlite_vec.load(self.conn)
            cur.executescript(_VEC_SQL)
        except ImportError:
            log.debug("sqlite-vec は利用できません（ベクトル検索は無効）")

        self.conn.commit()

    def _migrate(self) -> None:
        """マイグレーション管理テーブルを使い、未適用のみ実行する"""
        self.conn.execute("""
      CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at_epoch INTEGER NOT NULL
      )
    """)
        applied = {r[0] for r in self.conn.execute("SELECT version FROM schema_migrations").fetchall()}
        for version, sqls in _MIGRATIONS:
            if version not in applied:
                for sql in sqls:
                    self.conn.execute(sql)
                self.conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at_epoch) VALUES (?, ?)",
                    (version, int(time.time())),
                )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- セッション ---

    def upsert_session(self, session: Session) -> str:
        """セッションを挿入または更新し、id を返す。"""
        if not session.id:
            session.id = generate_uuid()

        cur = self.conn.execute(
            """INSERT INTO sessions
         (id, origin_user, session_id, project, started_at_epoch,
          branch, commit_hash, uncommitted_count)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(session_id) DO UPDATE SET
            chunk_count = chunk_count,
            synced_at = NULL
          RETURNING id""",
            (
                session.id,
                session.origin_user,
                session.session_id,
                session.project,
                session.started_at_epoch,
                session.branch,
                session.commit_hash,
                session.uncommitted_count,
            ),
        )
        row = cur.fetchone()
        self.conn.commit()
        return row["id"]

    def end_session(self, session_id: str) -> None:
        """セッション終了時刻を記録する。"""
        self.conn.execute(
            "UPDATE sessions SET ended_at_epoch = ?, synced_at = NULL WHERE session_id = ?",
            (int(time.time()), session_id),
        )
        self.conn.commit()

    # --- チャンク ---

    def store_chunk(self, chunk: MemoryChunk) -> str:
        """チャンクを保存し、生成された id を返す。セッションの chunk_count も同一トランザクションで更新。"""
        if not chunk.id:
            chunk.id = generate_uuid()

        cur = self.conn.execute(
            """INSERT INTO memory_chunks
         (id, origin_user, session_id, project, chunk_index, content,
          tool_names, files_read, files_modified,
          user_prompt, created_at_epoch,
          execution_status, tool_error, ai_response_summary, tool_sequence)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         RETURNING id""",
            (
                chunk.id,
                chunk.origin_user,
                chunk.session_id,
                chunk.project,
                chunk.chunk_index,
                chunk.content,
                json.dumps(chunk.tool_names, ensure_ascii=False),
                json.dumps(chunk.files_read, ensure_ascii=False),
                json.dumps(chunk.files_modified, ensure_ascii=False),
                chunk.user_prompt,
                chunk.created_at_epoch,
                chunk.execution_status,
                chunk.tool_error,
                chunk.ai_response_summary,
                json.dumps(chunk.tool_sequence, ensure_ascii=False),
            ),
        )
        row = cur.fetchone()
        self.conn.execute(
            "UPDATE sessions SET chunk_count = chunk_count + 1, synced_at = NULL WHERE session_id = ?",
            (chunk.session_id,),
        )
        self.conn.commit()
        return row["id"]

    def get_chunks_by_session(self, session_id: str) -> list[MemoryChunk]:
        rows = self.conn.execute(
            "SELECT * FROM memory_chunks WHERE session_id = ? ORDER BY chunk_index",
            (session_id,),
        ).fetchall()
        return [_row_to_chunk(r) for r in rows]

    def get_chunk_by_id(self, chunk_id: str) -> MemoryChunk | None:
        row = self.conn.execute("SELECT * FROM memory_chunks WHERE id = ?", (chunk_id,)).fetchone()
        return _row_to_chunk(row) if row else None

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> dict[str, MemoryChunk]:
        """複数チャンクを一括取得する（N+1 クエリ回避）。"""
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" * len(chunk_ids))
        rows = self.conn.execute(
            f"SELECT * FROM memory_chunks WHERE id IN ({placeholders})",
            chunk_ids,
        ).fetchall()
        return {r["id"]: _row_to_chunk(r) for r in rows}

    def get_next_chunk_index(self, session_id: str) -> int:
        row = self.conn.execute(
            "SELECT MAX(chunk_index) as mx FROM memory_chunks WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        mx = row["mx"]
        return (mx if mx is not None else -1) + 1

    def get_all_chunks(self) -> list[MemoryChunk]:
        """全チャンクを取得する（圧縮・プルーニング用）。"""
        rows = self.conn.execute("SELECT * FROM memory_chunks ORDER BY created_at_epoch").fetchall()
        return [_row_to_chunk(r) for r in rows]

    # --- FTS5 検索 ---

    def fts_search(self, query: str, limit: int = 40) -> list[tuple[str, float]]:
        """FTS5 trigram 検索。(chunk_id, rank) のリストを返す。"""
        try:
            rows = self.conn.execute(
                """SELECT chunk_id, rank
           FROM memory_chunks_fts
           WHERE memory_chunks_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
                (f'"{query}"', limit),
            ).fetchall()
            return [(r["chunk_id"], r["rank"]) for r in rows]
        except sqlite3.OperationalError as e:
            log.warning("FTS5 検索エラー: %s", e)
            return []

    # --- ベクトル検索 ---

    def store_embeddings(self, chunk_ids: list[str], embeddings: list[list[float]]) -> None:
        """エンべディングを一括保存する。"""
        for cid, emb in zip(chunk_ids, embeddings, strict=False):
            blob = struct.pack(f"{len(emb)}f", *emb)
            self.conn.execute(
                "INSERT OR REPLACE INTO memory_chunks_vec (chunk_id, embedding) VALUES (?, ?)",
                (cid, blob),
            )
        self.conn.commit()

    def vec_search(self, embedding: list[float], limit: int = 40) -> list[tuple[str, float]]:
        """sqlite-vec ベクトル検索。(chunk_id, distance) のリストを返す。"""
        try:
            blob = struct.pack(f"{len(embedding)}f", *embedding)
            rows = self.conn.execute(
                """SELECT chunk_id, distance
           FROM memory_chunks_vec
           WHERE embedding MATCH ?
           ORDER BY distance
           LIMIT ?""",
                (blob, limit),
            ).fetchall()
            return [(r["chunk_id"], r["distance"]) for r in rows]
        except Exception as e:
            log.warning("ベクトル検索エラー: %s", e)
            return []

    # --- アクセス追跡 ---

    def update_access(self, chunk_ids: list[str]) -> None:
        """検索でヒットしたチャンクのアクセス情報をバッチ更新する（ベストエフォート）"""
        if not chunk_ids:
            return
        unique_ids = list(dict.fromkeys(chunk_ids))  # 順序保持で重複排除
        now = int(time.time())
        try:
            self.conn.executemany(
                """UPDATE memory_chunks
              SET access_count = access_count + 1,
                 last_accessed_epoch = ?,
                 synced_at = NULL
              WHERE id = ?""",
                [(now, cid) for cid in unique_ids],
            )
            self.conn.commit()
        except Exception as e:
            log.debug("アクセスカウント更新スキップ: %s", e)

    # --- ユーティリティ ---

    def get_recent_chunks(self, limit: int = 50, project: str | None = None) -> list[MemoryChunk]:
        """最新のチャンクを取得する。コンテキスト注入用。"""
        if project:
            rows = self.conn.execute(
                "SELECT * FROM memory_chunks WHERE project = ? ORDER BY created_at_epoch DESC LIMIT ?",
                (project, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM memory_chunks ORDER BY created_at_epoch DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_chunk(r) for r in rows]

    # --- インスティンクト ---

    def upsert_instinct(self, instinct: Instinct) -> str:
        """インスティンクトを保存または更新し、id を返す。"""
        instinct_uuid = instinct.id or generate_uuid()
        self.conn.execute(
            """INSERT INTO instincts
         (id, origin_user, instinct_id, scope, project_id, trigger_text,
          confidence, domain, content, created_at_epoch, updated_at_epoch,
          observation_count, confidence_reasons, source_interaction_ids, last_activated_epoch)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(origin_user, instinct_id, scope, project_id) DO UPDATE SET
            trigger_text = excluded.trigger_text,
            confidence = excluded.confidence,
            domain = excluded.domain,
            content = excluded.content,
            updated_at_epoch = excluded.updated_at_epoch,
            observation_count = excluded.observation_count,
            confidence_reasons = excluded.confidence_reasons,
            source_interaction_ids = excluded.source_interaction_ids,
            last_activated_epoch = excluded.last_activated_epoch,
            synced_at = NULL""",
            (
                instinct_uuid,
                instinct.origin_user,
                instinct.instinct_id,
                instinct.scope,
                instinct.project_id,
                instinct.trigger_text,
                instinct.confidence,
                instinct.domain,
                instinct.content,
                instinct.created_at_epoch,
                instinct.updated_at_epoch,
                instinct.observation_count,
                json.dumps(instinct.confidence_reasons, ensure_ascii=False),
                json.dumps(instinct.source_interaction_ids, ensure_ascii=False),
                instinct.last_activated_epoch,
            ),
        )
        self.conn.commit()
        return instinct_uuid

    def get_instincts(self, scope: str | None = None, project_id: str | None = None) -> list[Instinct]:
        """インスティンクトを取得する。"""
        if scope and project_id:
            rows = self.conn.execute(
                "SELECT * FROM instincts WHERE scope = ? AND project_id = ?",
                (scope, project_id),
            ).fetchall()
        elif scope:
            rows = self.conn.execute("SELECT * FROM instincts WHERE scope = ?", (scope,)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM instincts").fetchall()
        return [_row_to_instinct(r) for r in rows]

    def get_all_instincts(self) -> list[Instinct]:
        """全インスティンクトを取得する（同期用）。"""
        rows = self.conn.execute("SELECT * FROM instincts ORDER BY created_at_epoch").fetchall()
        return [_row_to_instinct(r) for r in rows]

    # --- ADR ---

    def upsert_adr(self, adr: Adr) -> str:
        """ADR を保存または更新し、id を返す。"""
        adr_uuid = adr.id or generate_uuid()
        self.conn.execute(
            """INSERT INTO adrs
         (id, origin_user, project, adr_number, title, status, content,
          created_at_epoch, updated_at_epoch)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(origin_user, project, adr_number) DO UPDATE SET
            title = excluded.title,
            status = excluded.status,
            content = excluded.content,
            updated_at_epoch = excluded.updated_at_epoch,
            synced_at = NULL""",
            (
                adr_uuid,
                adr.origin_user,
                adr.project,
                adr.adr_number,
                adr.title,
                adr.status,
                adr.content,
                adr.created_at_epoch,
                adr.updated_at_epoch,
            ),
        )
        self.conn.commit()
        return adr_uuid

    def get_adrs(self, project: str | None = None) -> list[Adr]:
        """ADR を取得する。"""
        if project:
            rows = self.conn.execute(
                "SELECT * FROM adrs WHERE project = ? ORDER BY adr_number",
                (project,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM adrs ORDER BY project, adr_number").fetchall()
        return [_row_to_adr(r) for r in rows]

    def get_all_adrs(self) -> list[Adr]:
        """全 ADR を取得する（同期用）。"""
        rows = self.conn.execute("SELECT * FROM adrs ORDER BY created_at_epoch").fetchall()
        return [_row_to_adr(r) for r in rows]

    # --- イベントログ ---

    def store_event_log(self, event: EventLog) -> str:
        """イベントログを保存し、id を返す。"""
        event_uuid = event.id or generate_uuid()
        self.conn.execute(
            """INSERT OR IGNORE INTO event_logs
         (id, origin_user, event_type, project_id, content, created_at_epoch)
         VALUES (?, ?, ?, ?, ?, ?)""",
            (
                event_uuid,
                event.origin_user,
                event.event_type,
                event.project_id,
                event.content,
                event.created_at_epoch,
            ),
        )
        self.conn.commit()
        return event_uuid

    def get_event_logs(self, event_type: str | None = None, limit: int = 100) -> list[EventLog]:
        """イベントログを取得する。"""
        if event_type:
            rows = self.conn.execute(
                "SELECT * FROM event_logs WHERE event_type = ? ORDER BY created_at_epoch DESC LIMIT ?",
                (event_type, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM event_logs ORDER BY created_at_epoch DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_event_log(r) for r in rows]

    def get_all_event_logs(self) -> list[EventLog]:
        """全イベントログを取得する（同期用）。"""
        rows = self.conn.execute("SELECT * FROM event_logs ORDER BY created_at_epoch").fetchall()
        return [_row_to_event_log(r) for r in rows]

    # --- インタラクションログ ---

    def store_interaction_log(self, log_entry: InteractionLog) -> str:
        """インタラクションログを保存し、id を返す。"""
        log_uuid = log_entry.id or generate_uuid()
        prompt_hash = log_entry.user_prompt_hash or _make_prompt_hash(log_entry.user_prompt_full)
        self.conn.execute(
            """INSERT OR IGNORE INTO interaction_logs
         (id, origin_user, session_id, project,
          user_prompt_full, user_prompt_hash,
          ai_response_summary, ai_response_tool_plan,
          chunk_id, execution_outcome, tool_error_count,
          interaction_index, created_at_epoch)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                log_uuid,
                log_entry.origin_user,
                log_entry.session_id,
                log_entry.project,
                log_entry.user_prompt_full,
                prompt_hash,
                log_entry.ai_response_summary,
                log_entry.ai_response_tool_plan,
                log_entry.chunk_id,
                log_entry.execution_outcome,
                log_entry.tool_error_count,
                log_entry.interaction_index,
                log_entry.created_at_epoch,
            ),
        )
        self.conn.commit()
        return log_uuid

    def get_interaction_logs(
        self,
        session_id: str | None = None,
        project: str | None = None,
        limit: int = 100,
    ) -> list[InteractionLog]:
        """インタラクションログを取得する。"""
        if session_id:
            rows = self.conn.execute(
                "SELECT * FROM interaction_logs WHERE session_id = ? ORDER BY interaction_index",
                (session_id,),
            ).fetchall()
        elif project:
            rows = self.conn.execute(
                "SELECT * FROM interaction_logs WHERE project = ? ORDER BY created_at_epoch DESC LIMIT ?",
                (project, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM interaction_logs ORDER BY created_at_epoch DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_interaction_log(r) for r in rows]

    def get_all_interaction_logs(self) -> list[InteractionLog]:
        """全インタラクションログを取得する（同期用）。"""
        rows = self.conn.execute(
            "SELECT * FROM interaction_logs ORDER BY created_at_epoch"
        ).fetchall()
        return [_row_to_interaction_log(r) for r in rows]

    def get_next_interaction_index(self, session_id: str) -> int:
        """セッション内の次の interaction_index を返す。"""
        row = self.conn.execute(
            "SELECT MAX(interaction_index) as mx FROM interaction_logs WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        mx = row["mx"]
        return (mx if mx is not None else -1) + 1

    # --- プロジェクトプロファイル ---

    def upsert_project_profile(self, profile: ProjectProfile) -> str:
        """プロジェクトプロファイルを保存または更新し、id を返す。"""
        profile_uuid = profile.id or generate_uuid()
        self.conn.execute(
            """INSERT INTO project_profiles
         (id, origin_user, project, project_path,
          languages, frameworks, primary_language,
          test_command, build_command, scope_hint,
          detected_at_epoch, last_updated_epoch, detection_confidence)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(origin_user, project) DO UPDATE SET
            project_path = excluded.project_path,
            languages = excluded.languages,
            frameworks = excluded.frameworks,
            primary_language = excluded.primary_language,
            test_command = excluded.test_command,
            build_command = excluded.build_command,
            scope_hint = excluded.scope_hint,
            last_updated_epoch = excluded.last_updated_epoch,
            detection_confidence = excluded.detection_confidence,
            synced_at = NULL""",
            (
                profile_uuid,
                profile.origin_user,
                profile.project,
                profile.project_path,
                json.dumps(profile.languages, ensure_ascii=False),
                json.dumps(profile.frameworks, ensure_ascii=False),
                profile.primary_language,
                profile.test_command,
                profile.build_command,
                profile.scope_hint,
                profile.detected_at_epoch,
                profile.last_updated_epoch,
                profile.detection_confidence,
            ),
        )
        self.conn.commit()
        return profile_uuid

    def get_project_profile(self, project: str, origin_user: str = "") -> ProjectProfile | None:
        """プロジェクトプロファイルを取得する。"""
        if origin_user:
            row = self.conn.execute(
                "SELECT * FROM project_profiles WHERE project = ? AND origin_user = ?",
                (project, origin_user),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM project_profiles WHERE project = ? ORDER BY last_updated_epoch DESC LIMIT 1",
                (project,),
            ).fetchone()
        return _row_to_project_profile(row) if row else None

    def get_all_project_profiles(self) -> list[ProjectProfile]:
        """全プロジェクトプロファイルを取得する（同期用）。"""
        rows = self.conn.execute(
            "SELECT * FROM project_profiles ORDER BY last_updated_epoch"
        ).fetchall()
        return [_row_to_project_profile(r) for r in rows]

    # --- スキル実行記録 ---

    def store_mem_item_run(self, run: MemItemRun) -> str:
        """アイテム実行記録を保存し、id を返す。"""
        run_uuid = run.id or generate_uuid()
        self.conn.execute(
            """INSERT INTO mem_item_runs
         (id, origin_user, session_id, project,
          skill_name, skill_trigger, outcome,
          tools_used, files_modified_count, duration_seconds,
          interaction_log_id, created_at_epoch, item_type)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_uuid,
                run.origin_user,
                run.session_id,
                run.project,
                run.skill_name,
                run.skill_trigger,
                run.outcome,
                json.dumps(run.tools_used, ensure_ascii=False),
                run.files_modified_count,
                run.duration_seconds,
                run.interaction_log_id,
                run.created_at_epoch,
                run.item_type,
            ),
        )
        self.conn.commit()
        return run_uuid

    def get_skill_run_stats(
        self,
        skill_name: str | None = None,
        project: str | None = None,
        limit: int = 100,
    ) -> list[MemItemRun]:
        """スキル実行記録を取得する。"""
        conditions = []
        params: list = []
        if skill_name:
            conditions.append("skill_name = ?")
            params.append(skill_name)
        if project:
            conditions.append("project = ?")
            params.append(project)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM mem_item_runs {where} ORDER BY created_at_epoch DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_mem_item_run(r) for r in rows]

    def get_all_mem_item_runs(self) -> list[MemItemRun]:
        """全アイテム実行記録を取得する（同期用）。"""
        rows = self.conn.execute(
            "SELECT * FROM mem_item_runs ORDER BY created_at_epoch"
        ).fetchall()
        return [_row_to_mem_item_run(r) for r in rows]


# --- row 変換ヘルパー ---


def _row_to_chunk(row: sqlite3.Row) -> MemoryChunk:
    keys = row.keys()
    return MemoryChunk(
        id=row["id"],
        origin_user=row["origin_user"] if "origin_user" in keys else "",
        session_id=row["session_id"],
        project=row["project"],
        chunk_index=row["chunk_index"],
        content=row["content"],
        tool_names=_parse_json_list(row["tool_names"]),
        files_read=_parse_json_list(row["files_read"]),
        files_modified=_parse_json_list(row["files_modified"]),
        user_prompt=row["user_prompt"] or "",
        created_at_epoch=row["created_at_epoch"],
        access_count=row["access_count"] if "access_count" in keys else 0,
        last_accessed_epoch=row["last_accessed_epoch"] if "last_accessed_epoch" in keys else None,
        merged_generation=row["merged_generation"] if "merged_generation" in keys else 0,
        merged_into=row["merged_into"] if "merged_into" in keys else None,
        execution_status=row["execution_status"] if "execution_status" in keys else "unknown",
        tool_error=row["tool_error"] if "tool_error" in keys else None,
        ai_response_summary=row["ai_response_summary"] if "ai_response_summary" in keys else None,
        tool_sequence=_parse_json_list(row["tool_sequence"]) if "tool_sequence" in keys else [],
    )


def _parse_json_list(val: str | None) -> list[str]:
    if not val:
        return []
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError) as e:
        log.debug("JSON パース失敗（list）: %r → %s", val[:50] if val else val, e)
        return []


def _parse_json_dict_list(val: str | None) -> list[dict]:
    if not val:
        return []
    try:
        result = json.loads(val)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _row_to_instinct(row: sqlite3.Row) -> Instinct:
    keys = row.keys()
    return Instinct(
        id=row["id"],
        origin_user=row["origin_user"],
        instinct_id=row["instinct_id"],
        scope=row["scope"],
        project_id=row["project_id"],
        trigger_text=row["trigger_text"],
        confidence=row["confidence"],
        domain=row["domain"],
        content=row["content"],
        created_at_epoch=row["created_at_epoch"],
        updated_at_epoch=row["updated_at_epoch"],
        observation_count=row["observation_count"] if "observation_count" in keys else 0,
        confidence_reasons=_parse_json_dict_list(row["confidence_reasons"]) if "confidence_reasons" in keys else [],
        source_interaction_ids=_parse_json_list(row["source_interaction_ids"]) if "source_interaction_ids" in keys else [],
        last_activated_epoch=row["last_activated_epoch"] if "last_activated_epoch" in keys else None,
    )


def _row_to_adr(row: sqlite3.Row) -> Adr:
    return Adr(
        id=row["id"],
        origin_user=row["origin_user"],
        project=row["project"],
        adr_number=row["adr_number"],
        title=row["title"],
        status=row["status"],
        content=row["content"],
        created_at_epoch=row["created_at_epoch"],
        updated_at_epoch=row["updated_at_epoch"],
    )


def _row_to_event_log(row: sqlite3.Row) -> EventLog:
    return EventLog(
        id=row["id"],
        origin_user=row["origin_user"],
        event_type=row["event_type"],
        project_id=row["project_id"],
        content=row["content"],
        created_at_epoch=row["created_at_epoch"],
    )


def _row_to_interaction_log(row: sqlite3.Row) -> InteractionLog:
    return InteractionLog(
        id=row["id"],
        origin_user=row["origin_user"],
        session_id=row["session_id"],
        project=row["project"],
        user_prompt_full=row["user_prompt_full"],
        user_prompt_hash=row["user_prompt_hash"],
        ai_response_summary=row["ai_response_summary"],
        ai_response_tool_plan=row["ai_response_tool_plan"],
        chunk_id=row["chunk_id"],
        execution_outcome=row["execution_outcome"],
        tool_error_count=row["tool_error_count"],
        interaction_index=row["interaction_index"],
        created_at_epoch=row["created_at_epoch"],
    )


def _row_to_project_profile(row: sqlite3.Row) -> ProjectProfile:
    return ProjectProfile(
        id=row["id"],
        origin_user=row["origin_user"],
        project=row["project"],
        project_path=row["project_path"],
        languages=_parse_json_list(row["languages"]),
        frameworks=_parse_json_list(row["frameworks"]),
        primary_language=row["primary_language"],
        test_command=row["test_command"],
        build_command=row["build_command"],
        scope_hint=row["scope_hint"],
        detected_at_epoch=row["detected_at_epoch"],
        last_updated_epoch=row["last_updated_epoch"],
        detection_confidence=row["detection_confidence"],
    )


def _row_to_mem_item_run(row: sqlite3.Row) -> MemItemRun:
    keys = row.keys()
    return MemItemRun(
        id=row["id"],
        origin_user=row["origin_user"],
        session_id=row["session_id"],
        project=row["project"],
        skill_name=row["skill_name"],
        skill_trigger=row["skill_trigger"],
        outcome=row["outcome"],
        tools_used=_parse_json_list(row["tools_used"]),
        files_modified_count=row["files_modified_count"],
        duration_seconds=row["duration_seconds"],
        interaction_log_id=row["interaction_log_id"],
        created_at_epoch=row["created_at_epoch"],
        item_type=row["item_type"] if "item_type" in keys else "skill",
    )
