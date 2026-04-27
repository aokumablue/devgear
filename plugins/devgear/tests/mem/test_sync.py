"""PostgreSQL 同期ロジックのテスト（モック使用）"""

from __future__ import annotations

import sqlite3
import struct
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from devgear.mem.database import (
    Adr,
    Database,
    EventLog,
    Instinct,
    InteractionLog,
    MemItemRun,
    MemoryChunk,
    ProjectProfile,
    Session,
)
from devgear.mem.sync import SyncResult, _sync_embeddings, should_sync, sync_check, sync_to_postgres


@pytest.fixture
def mock_settings(tmp_path):
    """テスト用の設定オブジェクト"""
    settings = MagicMock()
    settings.db_path = str(tmp_path / "sync.db")
    settings.sync.enabled = True
    settings.sync.postgres_url = "postgresql://testuser@localhost:5432/testdb"
    settings.sync.interval_hours = 168  # 7日 = 168時間
    settings.sync.last_synced_at = 0.0
    settings.sync.last_sync_attempt_at = 0.0
    settings.sync.last_sync_success = False
    return settings


@pytest.fixture
def mock_git_user(monkeypatch):
    """sync.py 内の get_git_user_name を固定値に差し替えるフィクスチャ"""
    monkeypatch.setattr("devgear.mem.sync.get_git_user_name", lambda: "test_user")
    return "test_user"


class TestShouldSync:
    """should_sync 関数のテスト"""

    def test_returns_false_when_disabled(self, mock_settings):
        mock_settings.sync.enabled = False
        assert should_sync(mock_settings) is False

    def test_returns_false_when_no_postgres_url(self, mock_settings):
        mock_settings.sync.postgres_url = ""
        assert should_sync(mock_settings) is False

    def test_returns_true_when_never_synced(self, mock_settings):
        mock_settings.sync.last_synced_at = 0.0
        assert should_sync(mock_settings) is True

    def test_returns_false_when_within_interval(self, mock_settings):
        import time

        # 24時間前に同期した（168時間=7日間隔なので未達）
        mock_settings.sync.last_synced_at = time.time() - 24 * 60 * 60
        assert should_sync(mock_settings) is False

    def test_returns_true_when_interval_exceeded(self, mock_settings):
        import time

        # 169時間前に同期した（168時間間隔を超過）
        mock_settings.sync.last_synced_at = time.time() - 169 * 60 * 60
        assert should_sync(mock_settings) is True

    def test_returns_false_during_retry_backoff(self, mock_settings):
        import time

        now = time.time()
        mock_settings.sync.last_synced_at = now - 169 * 60 * 60
        mock_settings.sync.last_sync_success = False
        mock_settings.sync.last_sync_attempt_at = now - 60

        assert should_sync(mock_settings) is False


class TestSyncToPostgres:
    """sync_to_postgres 関数のテスト"""

    def test_returns_success_when_disabled(self, mock_settings):
        mock_settings.sync.enabled = False
        result = sync_to_postgres(mock_settings)
        assert result.success is True
        assert result.chunks == 0

    def test_returns_error_when_no_postgres_url(self, mock_settings):
        mock_settings.sync.postgres_url = ""
        result = sync_to_postgres(mock_settings)
        assert result.success is False
        assert "postgres_url" in result.error

    def test_pg_connection_failure_ignores_save_state_errors(self, mock_settings, monkeypatch, mock_git_user):
        db = Database(mock_settings.db_path)

        class FakeSQLiteDb:
            def __init__(self, real_db: Database) -> None:
                self.conn = real_db.conn
                self._real_db = real_db
                self.closed = False

            def close(self) -> None:
                self.closed = True
                self._real_db.close()

        class FakePgDb:
            def __init__(self) -> None:
                self.closed = False

            def test_connection(self) -> bool:
                return False

            def close(self) -> None:
                self.closed = True

        sqlite_db = FakeSQLiteDb(db)
        pg_db = FakePgDb()
        monkeypatch.setattr("devgear.mem.sync.Database", lambda path: sqlite_db)
        monkeypatch.setattr("devgear.mem.sync.PgDatabase", lambda url: pg_db)
        monkeypatch.setattr(
            mock_settings,
            "save_sync_state",
            lambda: (_ for _ in ()).throw(RuntimeError("save failed")),
        )

        result = sync_to_postgres(mock_settings)

        assert result.success is False
        assert result.error == "PostgreSQL への接続に失敗しました"
        assert sqlite_db.closed is True
        assert pg_db.closed is True


class TestSyncCheck:
    """sync_check 関数のテスト"""

    def test_skips_when_not_needed(self, mock_settings):
        import time

        mock_settings.sync.last_synced_at = time.time()  # 今同期した
        result = sync_check(mock_settings)
        assert result.success is True
        assert result.chunks == 0

    def test_skips_when_disabled(self, mock_settings):
        mock_settings.sync.enabled = False
        result = sync_check(mock_settings)
        assert result.success is True


class TestSyncResult:
    """SyncResult のテスト"""

    def test_default_values(self):
        result = SyncResult()
        assert result.chunks == 0
        assert result.sessions == 0
        assert result.instincts == 0
        assert result.adrs == 0
        assert result.events == 0
        assert result.success is True
        assert result.error is None

    def test_with_values(self):
        result = SyncResult(chunks=10, sessions=5, success=False, error="Test error")
        assert result.chunks == 10
        assert result.sessions == 5
        assert result.success is False
        assert result.error == "Test error"


class TestSyncToPostgresDetailed:
    """sync_to_postgres の詳細な分岐テスト"""

    def _seed_sync_rows(self, db: Database, *, include_synced_chunk: bool = False) -> dict[str, str]:
        session = Session(
            id="session-1",
            origin_user="sqlite-user",
            session_id="sess-1",
            project="proj",
            started_at_epoch=1700000000,
            chunk_count=0,
        )
        db.upsert_session(session)

        pending_chunk_id = db.store_chunk(
            MemoryChunk(
                id="chunk-1",
                origin_user="sqlite-user",
                session_id="sess-1",
                project="proj",
                chunk_index=0,
                content="content",
                tool_names=["Edit"],
                files_read=["src/app.py"],
                files_modified=["src/app.py"],
                user_prompt="prompt",
                created_at_epoch=1700000001,
            )
        )

        synced_chunk_id = ""
        if include_synced_chunk:
            synced_chunk_id = db.store_chunk(
                MemoryChunk(
                    id="chunk-2",
                    origin_user="sqlite-user",
                    session_id="sess-1",
                    project="proj",
                    chunk_index=1,
                    content="synced-content",
                    tool_names=["Read"],
                    files_read=["src/other.py"],
                    files_modified=[],
                    user_prompt="prompt-2",
                    created_at_epoch=1700000002,
                )
            )
            db.conn.execute(
                "UPDATE memory_chunks SET synced_at = ? WHERE id = ?",
                ("already-synced", synced_chunk_id),
            )

        db.upsert_instinct(
            Instinct(
                id="inst-1",
                instinct_id="inst-1",
                scope="project",
                confidence=0.8,
                content="content",
                created_at_epoch=1700000003,
                updated_at_epoch=1700000004,
                origin_user="sqlite-user",
                project_id="proj",
                trigger_text="when testing",
            )
        )
        db.upsert_adr(
            Adr(
                id="adr-1",
                project="proj",
                adr_number=1,
                title="title",
                status="accepted",
                content="content",
                created_at_epoch=1700000005,
                updated_at_epoch=1700000006,
                origin_user="sqlite-user",
            )
        )
        db.store_event_log(
            EventLog(
                id="event-1",
                event_type="notice",
                content="content",
                created_at_epoch=1700000007,
                origin_user="sqlite-user",
                project_id="proj",
            )
        )
        interaction_id = db.store_interaction_log(
            InteractionLog(
                id="interaction-1",
                origin_user="sqlite-user",
                session_id="sess-1",
                project="proj",
                user_prompt_full="do something",
                interaction_index=0,
                created_at_epoch=1700000008,
                user_prompt_hash="hash",
                ai_response_summary="summary",
                execution_outcome="success",
                tool_error_count=0,
            )
        )
        db.upsert_project_profile(
            ProjectProfile(
                id="profile-1",
                project="proj",
                detected_at_epoch=1700000009,
                last_updated_epoch=1700000010,
                origin_user="sqlite-user",
                project_path="/repo",
                languages=["python"],
                frameworks=["pytest"],
                primary_language="python",
                detection_confidence=0.9,
            )
        )
        db.store_mem_item_run(
            MemItemRun(
                id="run-1",
                session_id="sess-1",
                project="proj",
                skill_name="s-tdd",
                created_at_epoch=1700000011,
                origin_user="sqlite-user",
                skill_trigger="trigger",
                interaction_log_id=interaction_id,
            )
        )

        db.conn.commit()
        return {
            "pending_chunk_id": pending_chunk_id,
            "synced_chunk_id": synced_chunk_id,
            "session_id": "sess-1",
        }

    def test_dry_run_counts_only_unsynced_rows(self, mock_settings, monkeypatch, mock_git_user):
        db = Database(mock_settings.db_path)
        ids = self._seed_sync_rows(db, include_synced_chunk=True)

        class FakeSQLiteDb:
            def __init__(self, real_db: Database) -> None:
                self.conn = real_db.conn
                self._real_db = real_db
                self.closed = False

            def close(self) -> None:
                self.closed = True
                self._real_db.close()

        class FakePgDb:
            def __init__(self) -> None:
                self.closed = False

            def test_connection(self) -> bool:
                return True

            def close(self) -> None:
                self.closed = True

        sqlite_db = FakeSQLiteDb(db)
        pg_db = FakePgDb()
        monkeypatch.setattr("devgear.mem.sync.Database", lambda path: sqlite_db)
        monkeypatch.setattr("devgear.mem.sync.PgDatabase", lambda url: pg_db)

        result = sync_to_postgres(mock_settings, dry_run=True)

        assert result.success is True
        assert result.chunks == 1
        assert result.sessions == 1
        assert result.instincts == 1
        assert result.adrs == 1
        assert result.events == 1
        assert result.interaction_logs == 1
        assert result.project_profiles == 1
        assert result.skill_runs == 1
        assert sqlite_db.closed is True
        assert pg_db.closed is True
        assert mock_settings.sync.last_synced_at == 0.0

        conn = sqlite3.connect(mock_settings.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, synced_at FROM memory_chunks WHERE id IN (?, ?) ORDER BY chunk_index",
            (ids["pending_chunk_id"], ids["synced_chunk_id"]),
        ).fetchall()
        assert rows[0]["synced_at"] is None
        assert rows[1]["synced_at"] == "already-synced"
        conn.close()

    def test_full_sync_claims_rows_and_commits(self, mock_settings, monkeypatch, mock_git_user):
        db = Database(mock_settings.db_path)
        ids = self._seed_sync_rows(db)

        class FakeSQLiteDb:
            def __init__(self, real_db: Database) -> None:
                self.conn = real_db.conn
                self._real_db = real_db
                self.closed = False

            def close(self) -> None:
                self.closed = True
                self._real_db.close()

        class FakePgDb:
            def __init__(self) -> None:
                self.closed = False
                self.calls: list[tuple[str, object]] = []
                self.project_profiles = []
                self.skill_runs = []

            def test_connection(self) -> bool:
                return True

            def upsert_chunks_batch(self, chunks, origin_user):  # noqa: ANN001
                self.calls.append(("chunks", (origin_user, len(chunks))))
                return len(chunks)

            def upsert_sessions_batch(self, sessions, origin_user):  # noqa: ANN001
                self.calls.append(("sessions", (origin_user, len(sessions))))
                return len(sessions)

            def upsert_instincts_batch(self, instincts):  # noqa: ANN001
                self.calls.append(("instincts", instincts))
                return len(instincts)

            def upsert_adrs_batch(self, adrs):  # noqa: ANN001
                self.calls.append(("adrs", adrs))
                return len(adrs)

            def insert_event_logs_batch(self, events):  # noqa: ANN001
                self.calls.append(("events", events))
                return len(events)

            def upsert_interaction_logs_batch(self, logs):  # noqa: ANN001
                self.calls.append(("interaction_logs", logs))
                return len(logs)

            def upsert_project_profiles_batch(self, profiles):  # noqa: ANN001
                self.calls.append(("project_profiles", profiles))
                self.project_profiles = profiles
                return len(profiles)

            def upsert_mem_item_runs_batch(self, runs):  # noqa: ANN001
                self.calls.append(("skill_runs", runs))
                self.skill_runs = runs
                return len(runs)

            def close(self) -> None:
                self.closed = True

        sqlite_db = FakeSQLiteDb(db)
        pg_db = FakePgDb()
        monkeypatch.setattr("devgear.mem.sync.Database", lambda path: sqlite_db)
        monkeypatch.setattr("devgear.mem.sync.PgDatabase", lambda url: pg_db)
        monkeypatch.setattr("devgear.mem.sync._sync_embeddings", lambda sqlite_db, pg_db, chunks: len(chunks))
        monkeypatch.setattr("devgear.mem.sync.time.time", lambda: 9999)

        result = sync_to_postgres(mock_settings, dry_run=False)

        assert result.success is True
        assert result.chunks == 1
        assert result.sessions == 1
        assert result.instincts == 1
        assert result.adrs == 1
        assert result.events == 1
        assert result.interaction_logs == 1
        assert result.project_profiles == 1
        assert result.skill_runs == 1
        assert result.embeddings == 1
        assert sqlite_db.closed is True
        assert pg_db.closed is True
        assert mock_settings.sync.last_synced_at == 9999
        assert mock_settings.save_sync_state.called
        assert pg_db.calls[0] == ("chunks", ("test_user", 1))
        assert pg_db.calls[1] == ("sessions", ("test_user", 1))
        assert pg_db.project_profiles[0].origin_user == "test_user"
        assert pg_db.skill_runs[0].origin_user == "test_user"

        conn = sqlite3.connect(mock_settings.db_path)
        conn.row_factory = sqlite3.Row
        synced_rows = conn.execute(
            """
            SELECT synced_at
            FROM memory_chunks
            WHERE id = ? OR id = ?
            ORDER BY chunk_index
            """,
            (ids["pending_chunk_id"], ids["synced_chunk_id"] or ids["pending_chunk_id"]),
        ).fetchall()
        assert synced_rows[0]["synced_at"] is not None
        conn.close()

    def test_full_sync_without_chunks_uses_default_result(self, mock_settings, monkeypatch, mock_git_user):
        class FakePgDb:
            def __init__(self) -> None:
                self.closed = False
                self.calls: list[str] = []

            def test_connection(self) -> bool:
                return True

            def upsert_chunks_batch(self, chunks, origin_user):  # noqa: ANN001
                self.calls.append("chunks")
                return len(chunks)

            def upsert_sessions_batch(self, sessions, origin_user):  # noqa: ANN001
                self.calls.append("sessions")
                return len(sessions)

            def upsert_instincts_batch(self, instincts):  # noqa: ANN001
                self.calls.append("instincts")
                return len(instincts)

            def upsert_adrs_batch(self, adrs):  # noqa: ANN001
                self.calls.append("adrs")
                return len(adrs)

            def insert_event_logs_batch(self, events):  # noqa: ANN001
                self.calls.append("events")
                return len(events)

            def upsert_interaction_logs_batch(self, logs):  # noqa: ANN001
                self.calls.append("interaction_logs")
                return len(logs)

            def upsert_project_profiles_batch(self, profiles):  # noqa: ANN001
                self.calls.append("project_profiles")
                return len(profiles)

            def upsert_mem_item_runs_batch(self, runs):  # noqa: ANN001
                self.calls.append("skill_runs")
                return len(runs)

            def close(self) -> None:
                self.closed = True

        pg_db = FakePgDb()
        monkeypatch.setattr("devgear.mem.sync.PgDatabase", lambda url: pg_db)

        result = sync_to_postgres(mock_settings, dry_run=False)

        assert result.success is True
        assert result.chunks == 0
        assert result.sessions == 0
        assert result.embeddings == 0
        assert pg_db.closed is True
        assert pg_db.calls == []
        assert mock_settings.sync.last_synced_at > 0
        assert mock_settings.save_sync_state.called

    def test_failed_sync_rolls_back_synced_at(self, mock_settings, monkeypatch, mock_git_user):
        db = Database(mock_settings.db_path)
        ids = self._seed_sync_rows(db)

        class FakeSQLiteDb:
            def __init__(self, real_db: Database) -> None:
                self.conn = real_db.conn
                self._real_db = real_db
                self.closed = False

            def close(self) -> None:
                self.closed = True
                self._real_db.close()

        class FakePgDb:
            def __init__(self) -> None:
                self.closed = False

            def test_connection(self) -> bool:
                return True

            def upsert_chunks_batch(self, chunks, origin_user):  # noqa: ANN001
                raise RuntimeError("boom")

            def close(self) -> None:
                self.closed = True

        sqlite_db = FakeSQLiteDb(db)
        pg_db = FakePgDb()
        monkeypatch.setattr("devgear.mem.sync.Database", lambda path: sqlite_db)
        monkeypatch.setattr("devgear.mem.sync.PgDatabase", lambda url: pg_db)

        result = sync_to_postgres(mock_settings, dry_run=False)

        assert result.success is False
        assert "boom" in result.error
        assert sqlite_db.closed is True
        assert pg_db.closed is True
        assert mock_settings.sync.last_sync_success is False

        conn = sqlite3.connect(mock_settings.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT synced_at FROM memory_chunks WHERE id = ?",
            (ids["pending_chunk_id"],),
        ).fetchone()
        assert row["synced_at"] is None
        session_row = conn.execute(
            "SELECT synced_at FROM sessions WHERE session_id = ?",
            (ids["session_id"],),
        ).fetchone()
        assert session_row["synced_at"] is None
        conn.close()

    def test_failed_sync_ignores_save_state_errors(self, mock_settings, monkeypatch, mock_git_user):
        db = Database(mock_settings.db_path)
        self._seed_sync_rows(db)

        class FakeSQLiteDb:
            def __init__(self, real_db: Database) -> None:
                self.conn = real_db.conn
                self._real_db = real_db
                self.closed = False

            def close(self) -> None:
                self.closed = True
                self._real_db.close()

        class FakePgDb:
            def __init__(self) -> None:
                self.closed = False

            def test_connection(self) -> bool:
                return True

            def upsert_chunks_batch(self, chunks, origin_user):  # noqa: ANN001
                raise RuntimeError("boom")

            def close(self) -> None:
                self.closed = True

        sqlite_db = FakeSQLiteDb(db)
        pg_db = FakePgDb()
        monkeypatch.setattr("devgear.mem.sync.Database", lambda path: sqlite_db)
        monkeypatch.setattr("devgear.mem.sync.PgDatabase", lambda url: pg_db)
        monkeypatch.setattr(
            mock_settings,
            "save_sync_state",
            lambda: (_ for _ in ()).throw(RuntimeError("save failed")),
        )

        result = sync_to_postgres(mock_settings, dry_run=False)

        assert result.success is False
        assert "boom" in result.error
        assert sqlite_db.closed is True
        assert pg_db.closed is True
        assert mock_settings.sync.last_sync_success is False

    def test_pg_connection_failure(self, mock_settings, monkeypatch, mock_git_user):
        db = Database(mock_settings.db_path)

        class FakeSQLiteDb:
            def __init__(self, real_db: Database) -> None:
                self.conn = real_db.conn
                self._real_db = real_db
                self.closed = False

            def close(self) -> None:
                self.closed = True
                self._real_db.close()

        class FakePgDb:
            def __init__(self) -> None:
                self.closed = False

            def test_connection(self) -> bool:
                return False

            def close(self) -> None:
                self.closed = True

        sqlite_db = FakeSQLiteDb(db)
        pg_db = FakePgDb()
        monkeypatch.setattr("devgear.mem.sync.Database", lambda path: sqlite_db)
        monkeypatch.setattr("devgear.mem.sync.PgDatabase", lambda url: pg_db)

        result = sync_to_postgres(mock_settings, dry_run=False)

        assert result.success is False
        assert result.error == "PostgreSQL への接続に失敗しました"
        assert sqlite_db.closed is True
        assert pg_db.closed is True

    def test_sync_check_delegates_when_needed(self, mock_settings, monkeypatch):
        monkeypatch.setattr("devgear.mem.sync.should_sync", lambda settings: True)
        monkeypatch.setattr("devgear.mem.sync.sync_to_postgres", lambda settings, dry_run=False: SyncResult(chunks=3))

        result = sync_check(mock_settings)
        assert result.chunks == 3


class TestSyncEmbeddings:
    """_sync_embeddings のテスト"""

    def test_handles_empty_and_error_paths(self, monkeypatch):
        class FakePgDb:
            def upsert_embeddings_batch(self, embeddings):  # noqa: ANN001
                return len(embeddings)

        class FakeConn:
            def execute(self, sql: str, params=None):  # noqa: ANN001
                raise RuntimeError("boom")

        class FakeSQLiteDb:
            def __init__(self) -> None:
                self.conn = FakeConn()

        assert _sync_embeddings(FakeSQLiteDb(), FakePgDb(), []) == 0
        assert _sync_embeddings(FakeSQLiteDb(), FakePgDb(), [MemoryChunk("s", "p", 0, "c", [], [], [], "", 1, id="c1")]) == 0

    def test_returns_zero_when_no_embeddings_are_found(self):
        class FakePgDb:
            def upsert_embeddings_batch(self, embeddings):  # noqa: ANN001
                return len(embeddings)

        class FakeConn:
            def execute(self, sql: str, params=None):  # noqa: ANN001
                return SimpleNamespace(fetchall=lambda: [])

        class FakeSQLiteDb:
            def __init__(self) -> None:
                self.conn = FakeConn()

        assert _sync_embeddings(
            FakeSQLiteDb(),
            FakePgDb(),
            [MemoryChunk("s", "p", 0, "c", [], [], [], "", 1, id="c1")],
        ) == 0

    def test_decodes_embeddings_when_available(self):
        class FakePgDb:
            def __init__(self) -> None:
                self.embeddings = None

            def upsert_embeddings_batch(self, embeddings):  # noqa: ANN001
                self.embeddings = embeddings
                return len(embeddings)

        class FakeConn:
            def execute(self, sql: str, params=None):  # noqa: ANN001
                return SimpleNamespace(fetchall=lambda: [("c1", struct.pack("2f", 0.1, 0.2))])

        class FakeSQLiteDb:
            def __init__(self) -> None:
                self.conn = FakeConn()

        pg = FakePgDb()
        count = _sync_embeddings(FakeSQLiteDb(), pg, [MemoryChunk("s", "p", 0, "c", [], [], [], "", 1, id="c1")])
        assert count == 1
        assert pg.embeddings[0][0] == "c1"
        assert pg.embeddings[0][1][0] == pytest.approx(0.1)
        assert pg.embeddings[0][1][1] == pytest.approx(0.2)


class TestSyncHelpers:
    """内部ヘルパーの分岐テスト"""

    def test_count_pending_rows_returns_zero_for_empty_table(self, tmp_path):
        db = Database(tmp_path / "empty-sync.db")
        from devgear.mem.sync import _count_pending_rows

        assert _count_pending_rows(db.conn, "memory_chunks") == 0
        db.close()

    def test_count_pending_embeddings_handles_empty_and_operational_error(self):
        from devgear.mem.sync import _count_pending_embeddings

        class EmptyConn:
            def execute(self, sql: str, params=None):  # noqa: ANN001
                raise sqlite3.OperationalError("no vec table")

        class OkConn:
            def execute(self, sql: str, params=None):  # noqa: ANN001
                return SimpleNamespace(fetchone=lambda: (0,))

        assert _count_pending_embeddings(OkConn(), []) == 0
        assert _count_pending_embeddings(EmptyConn(), ["c1"]) == 0
