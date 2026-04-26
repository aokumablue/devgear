"""session_manager モジュールのテスト。"""

from __future__ import annotations

from datetime import datetime

from devgear.lib.session_manager import (
    ParsedSessionMetadata,
    SessionDetail,
    SessionListResult,
    SessionMetadata,
    SessionRecord,
    SessionStats,
    delete_session,
    get_all_sessions,
    get_session_by_id,
    get_session_size,
    get_session_stats,
    get_session_title,
    parse_session_filename,
    parse_session_metadata,
    session_exists,
    write_session_content,
)


class TestParseSessionFilename:
    """parse_session_filename のテスト。"""

    def test_parses_valid_filename_with_id(self):
        """ID 付きの有効なセッションファイル名を解析できること。"""
        result = parse_session_filename("2024-01-15-abc123-session.tmp")
        assert result is not None
        assert result.short_id == "abc123"
        assert result.date == "2024-01-15"
        assert result.datetime.year == 2024
        assert result.datetime.month == 1
        assert result.datetime.day == 15

    def test_parses_filename_without_id(self):
        """ID なしのファイル名は 'no-id' として解析すること。"""
        result = parse_session_filename("2024-01-15-session.tmp")
        assert result is not None
        assert result.short_id == "no-id"
        assert result.date == "2024-01-15"

    def test_parses_filename_with_complex_id(self):
        """複雑なセッション ID を含むファイル名を解析できること。"""
        result = parse_session_filename("2024-01-15-my_session-id-123-session.tmp")
        assert result is not None
        assert result.short_id == "my_session-id-123"

    def test_rejects_invalid_format(self):
        """無効な形式では None を返すこと。"""
        assert parse_session_filename("invalid.tmp") is None
        assert parse_session_filename("session.tmp") is None
        assert parse_session_filename("2024-01-15.tmp") is None

    def test_rejects_non_tmp_extension(self):
        """.tmp 以外の拡張子では None を返すこと。"""
        assert parse_session_filename("2024-01-15-abc123-session.json") is None

    def test_rejects_invalid_date(self):
        """無効な日付では None を返すこと。"""
        assert parse_session_filename("2024-13-15-abc-session.tmp") is None  # 無効な月
        assert parse_session_filename("2024-02-30-abc-session.tmp") is None  # 無効な日

    def test_handles_edge_cases(self):
        """境界ケースを扱えること。"""
        assert parse_session_filename("") is None
        assert parse_session_filename(None) is None  # type: ignore


class TestParseSessionMetadata:
    """parse_session_metadata のテスト。"""

    def test_parses_title(self):
        """Markdown 見出しからタイトルを解析すること。"""
        content = "# My Session Title\nContent here"
        result = parse_session_metadata(content)
        assert result.title == "My Session Title"

    def test_parses_date(self):
        """日付メタデータを解析すること。"""
        content = "# Title\n**Date:** 2024-01-15"
        result = parse_session_metadata(content)
        assert result.date == "2024-01-15"

    def test_parses_started_time(self):
        """開始時刻を解析すること。"""
        content = "**Started:** 10:30"
        result = parse_session_metadata(content)
        assert result.started == "10:30"

    def test_parses_last_updated(self):
        """最終更新時刻を解析すること。"""
        content = "**Last Updated:** 15:45"
        result = parse_session_metadata(content)
        assert result.last_updated == "15:45"

    def test_parses_project_info(self):
        """プロジェクト関連メタデータを解析すること。"""
        content = "**Project:** my-project\n**Branch:** feature-x\n**Worktree:** /path/to/worktree"
        result = parse_session_metadata(content)
        assert result.project == "my-project"
        assert result.branch == "feature-x"
        assert result.worktree == "/path/to/worktree"

    def test_parses_completed_items(self):
        """完了項目を解析すること。"""
        content = """### 完了済み
- [x] First task
- [x] Second task
"""
        result = parse_session_metadata(content)
        assert result.completed == ["First task", "Second task"]

    def test_parses_in_progress_items(self):
        """進行中項目を解析すること。"""
        content = """### 進行中
- [ ] Task one
- [ ] Task two
"""
        result = parse_session_metadata(content)
        assert result.in_progress == ["Task one", "Task two"]

    def test_parses_notes(self):
        """ノートセクションを解析すること。"""
        content = """### 次回セッションへの引継ぎ
Some important notes here
"""
        result = parse_session_metadata(content)
        assert result.notes == "Some important notes here"

    def test_parses_context(self):
        """コンテキストセクションを解析すること。"""
        content = """### 読み込むコンテキスト
```
context data here
```
"""
        result = parse_session_metadata(content)
        assert result.context == "context data here"

    def test_handles_empty_content(self):
        """空の内容を扱えること。"""
        result = parse_session_metadata("")
        assert result.title is None
        assert result.completed == []

    def test_handles_none_content(self):
        """None の内容を扱えること。"""
        result = parse_session_metadata(None)
        assert result.title is None


class TestGetSessionStats:
    """get_session_stats のテスト。"""

    def test_calculates_stats_from_content(self):
        """セッション内容から統計を計算すること。"""
        content = """# Title
### 完了済み
- [x] Done 1
- [x] Done 2
### 進行中
- [ ] Pending 1
### 次回セッションへの引継ぎ
Some notes
### 読み込むコンテキスト
```
context
```
"""
        result = get_session_stats(content)
        assert result.total_items == 3
        assert result.completed_items == 2
        assert result.in_progress_items == 1
        assert result.has_notes is True
        assert result.has_context is True
        assert result.line_count > 0


class TestGetSessionTitle:
    """get_session_title のテスト。"""

    def test_returns_title_from_content(self, tmp_path):
        """セッション内容からタイトルを返すこと。"""
        session_file = tmp_path / "session.tmp"
        session_file.write_text("# My Session\nContent")

        result = get_session_title(session_file)
        assert result == "My Session"

    def test_returns_untitled_when_no_title(self, tmp_path):
        """タイトルがない場合は 'Untitled Session' を返すこと。"""
        session_file = tmp_path / "session.tmp"
        session_file.write_text("No heading here")

        result = get_session_title(session_file)
        assert result == "Untitled Session"


class TestGetSessionSize:
    """get_session_size のテスト。"""

    def test_formats_bytes(self, tmp_path):
        """バイト単位で整形すること。"""
        session_file = tmp_path / "session.tmp"
        session_file.write_text("x" * 100)

        result = get_session_size(session_file)
        assert result == "100 B"

    def test_formats_kilobytes(self, tmp_path):
        """キロバイト単位で整形すること。"""
        session_file = tmp_path / "session.tmp"
        session_file.write_text("x" * 2048)

        result = get_session_size(session_file)
        assert "KB" in result

    def test_handles_missing_file(self, tmp_path):
        """ファイルがない場合は '0 B' を返すこと。"""
        result = get_session_size(tmp_path / "nonexistent.tmp")
        assert result == "0 B"


class TestWriteSessionContent:
    """write_session_content のテスト。"""

    def test_writes_content(self, tmp_path):
        """内容をファイルへ書き込むこと。"""
        session_file = tmp_path / "session.tmp"
        result = write_session_content(session_file, "Test content")

        assert result is True
        assert session_file.read_text() == "Test content"

    def test_overwrites_existing(self, tmp_path):
        """既存内容を上書きすること。"""
        session_file = tmp_path / "session.tmp"
        session_file.write_text("Old content")

        write_session_content(session_file, "New content")

        assert session_file.read_text() == "New content"


class TestDeleteSession:
    """delete_session のテスト。"""

    def test_deletes_existing_file(self, tmp_path):
        """既存のセッションファイルを削除すること。"""
        session_file = tmp_path / "session.tmp"
        session_file.write_text("content")

        result = delete_session(session_file)

        assert result is True
        assert not session_file.exists()

    def test_returns_false_for_nonexistent(self, tmp_path):
        """存在しないファイルでは False を返すこと。"""
        result = delete_session(tmp_path / "nonexistent.tmp")
        assert result is False


class TestSessionExists:
    """session_exists のテスト。"""

    def test_returns_true_for_existing(self, tmp_path):
        """存在するファイルでは True を返すこと。"""
        session_file = tmp_path / "session.tmp"
        session_file.write_text("content")

        assert session_exists(session_file) is True

    def test_returns_false_for_nonexistent(self, tmp_path):
        """存在しないファイルでは False を返すこと。"""
        assert session_exists(tmp_path / "nonexistent.tmp") is False


class TestGetAllSessions:
    """get_all_sessions のテスト。"""

    def test_returns_empty_when_no_sessions(self, tmp_path, monkeypatch):
        """セッションがない場合は空リストを返すこと。"""
        monkeypatch.setattr(
            "devgear.lib.session_manager.get_session_search_dirs",
            lambda: [tmp_path],
        )
        tmp_path.mkdir(exist_ok=True)

        result = get_all_sessions()
        assert result.sessions == []
        assert result.total == 0

    def test_returns_sessions_sorted_by_modified_time(self, tmp_path, monkeypatch):
        """更新時刻順（新しい順）で返すこと。"""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        monkeypatch.setattr(
            "devgear.lib.session_manager.get_session_search_dirs",
            lambda: [sessions_dir],
        )

        # セッションファイルを作成
        (sessions_dir / "2024-01-15-old-session.tmp").write_text("old")
        (sessions_dir / "2024-01-16-new-session.tmp").write_text("new")

        result = get_all_sessions()
        assert len(result.sessions) == 2

    def test_filters_by_date(self, tmp_path, monkeypatch):
        """日付でセッションを絞り込むこと。"""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        monkeypatch.setattr(
            "devgear.lib.session_manager.get_session_search_dirs",
            lambda: [sessions_dir],
        )

        (sessions_dir / "2024-01-15-one-session.tmp").write_text("a")
        (sessions_dir / "2024-01-16-two-session.tmp").write_text("b")

        result = get_all_sessions(date="2024-01-15")
        assert len(result.sessions) == 1
        assert result.sessions[0].date == "2024-01-15"

    def test_filters_by_search(self, tmp_path, monkeypatch):
        """検索語でセッションを絞り込むこと。"""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        monkeypatch.setattr(
            "devgear.lib.session_manager.get_session_search_dirs",
            lambda: [sessions_dir],
        )

        (sessions_dir / "2024-01-15-target-session.tmp").write_text("a")
        (sessions_dir / "2024-01-16-other-session.tmp").write_text("b")

        result = get_all_sessions(search="target")
        assert len(result.sessions) == 1
        assert result.sessions[0].short_id == "target"

    def test_pagination(self, tmp_path, monkeypatch):
        """ページネーションをサポートすること。"""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        monkeypatch.setattr(
            "devgear.lib.session_manager.get_session_search_dirs",
            lambda: [sessions_dir],
        )

        for i in range(5):
            (sessions_dir / f"2024-01-{15 + i:02d}-s{i}-session.tmp").write_text(f"content{i}")

        result = get_all_sessions(limit=2, offset=1)
        assert len(result.sessions) == 2
        assert result.total == 5
        assert result.has_more is True


class TestGetSessionById:
    """get_session_by_id のテスト。"""

    def test_finds_session_by_short_id(self, tmp_path, monkeypatch):
        """短縮 ID でセッションを見つけること。"""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        monkeypatch.setattr(
            "devgear.lib.session_manager.get_session_search_dirs",
            lambda: [sessions_dir],
        )

        (sessions_dir / "2024-01-15-target-session.tmp").write_text("# Test Session")

        result = get_session_by_id("target")
        assert result is not None
        assert result.short_id == "target"

    def test_returns_none_when_not_found(self, tmp_path, monkeypatch):
        """セッションが見つからない場合は None を返すこと。"""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        monkeypatch.setattr(
            "devgear.lib.session_manager.get_session_search_dirs",
            lambda: [sessions_dir],
        )

        result = get_session_by_id("nonexistent")
        assert result is None

    def test_includes_content_when_requested(self, tmp_path, monkeypatch):
        """include_content=True のとき内容を含めること。"""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        monkeypatch.setattr(
            "devgear.lib.session_manager.get_session_search_dirs",
            lambda: [sessions_dir],
        )

        (sessions_dir / "2024-01-15-test-session.tmp").write_text("# My Title\nContent")

        result = get_session_by_id("test", include_content=True)
        assert result is not None
        assert result.content is not None
        assert result.metadata is not None
        assert result.metadata.title == "My Title"


class TestDataclasses:
    """データクラス構造のテスト。"""

    def test_session_metadata_attributes(self):
        """SessionMetadata が期待する属性を持つこと。"""
        meta = SessionMetadata(
            filename="2024-01-15-test-session.tmp",
            short_id="test",
            date="2024-01-15",
            datetime=datetime(2024, 1, 15),
        )
        assert meta.filename == "2024-01-15-test-session.tmp"
        assert meta.short_id == "test"

    def test_session_record_attributes(self):
        """SessionRecord が期待する属性を持つこと。"""
        record = SessionRecord(
            filename="test.tmp",
            short_id="test",
            date="2024-01-15",
            datetime=datetime(2024, 1, 15),
            session_path="/path/to/session",
            has_content=True,
            size=100,
            modified_time=datetime.now(),
            created_time=datetime.now(),
        )
        assert record.filename == "test.tmp"
        assert record.has_content is True

    def test_parsed_session_metadata_defaults(self):
        """ParsedSessionMetadata が既定値を持つこと。"""
        meta = ParsedSessionMetadata()
        assert meta.title is None
        assert meta.completed == []
        assert meta.in_progress == []
        assert meta.notes == ""

    def test_session_stats_attributes(self):
        """SessionStats が期待する属性を持つこと。"""
        stats = SessionStats(
            total_items=5,
            completed_items=3,
            in_progress_items=2,
            line_count=100,
            has_notes=True,
            has_context=False,
        )
        assert stats.total_items == 5
        assert stats.completed_items == 3

    def test_session_list_result_attributes(self):
        """SessionListResult が期待する属性を持つこと。"""
        result = SessionListResult(
            sessions=[],
            total=0,
            offset=0,
            limit=50,
            has_more=False,
        )
        assert result.sessions == []
        assert result.total == 0

    def test_session_detail_attributes(self):
        """SessionDetail が期待する属性を持つこと。"""
        detail = SessionDetail(
            filename="test.tmp",
            short_id="test",
            date="2024-01-15",
            datetime=datetime(2024, 1, 15),
            session_path="/path",
            has_content=True,
            size=100,
            modified_time=datetime.now(),
            created_time=datetime.now(),
        )
        assert detail.content is None
        assert detail.metadata is None
        assert detail.stats is None
