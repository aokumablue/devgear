"""session_manager モジュールの追加テスト。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from devgear.lib import session_manager as sm


def test_parse_session_filename_covers_datetime_mismatch_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """日付正規化チェックの分岐を通す。"""

    class FakeDateTime:
        def __call__(self, year: int, month: int, day: int):  # noqa: ANN001
            return SimpleNamespace(month=month + 1, day=day + 1)

    monkeypatch.setattr(sm, "datetime", FakeDateTime())

    assert sm.parse_session_filename("2024-01-15-abc-session.tmp") is None


def test_build_session_record_handles_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_build_session_record の stat 失敗を確認する。"""
    metadata = sm.SessionMetadata(
        filename="2024-01-15-abc-session.tmp",
        short_id="abc",
        date="2024-01-15",
        datetime=sm.datetime(2024, 1, 15),
    )
    session_file = tmp_path / "2024-01-15-abc-session.tmp"
    session_file.write_text("content", encoding="utf-8")

    monkeypatch.setattr(sm.Path, "stat", lambda self: (_ for _ in ()).throw(OSError("boom")), raising=False)

    assert sm._build_session_record(session_file, metadata) is None


def test_get_session_path_uses_sessions_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """get_session_path が sessions ディレクトリを使うこと。"""
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(sm, "get_sessions_dir", lambda: sessions_dir)

    assert sm.get_session_path("2024-01-15-abc-session.tmp") == sessions_dir / "2024-01-15-abc-session.tmp"


def test_get_session_candidates_covers_invalid_entries_and_dedupes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """候補取得のフィルタと重複排除を確認する。"""
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()

    (first_dir / "notes.txt").write_text("skip", encoding="utf-8")
    (first_dir / "2024-01-15-alpha-session.tmp").write_text("one", encoding="utf-8")
    (second_dir / "2024-01-15-alpha-session.tmp").write_text("two", encoding="utf-8")
    (second_dir / "bad.tmp").write_text("invalid", encoding="utf-8")

    monkeypatch.setattr(sm, "get_session_search_dirs", lambda: [first_dir, second_dir])

    candidates = sm._get_session_candidates(date="2024-01-15", search="alpha")
    assert [candidate.short_id for candidate in candidates] == ["alpha"]
    assert len(candidates) == 1


def test_get_session_candidates_skips_missing_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """存在しない候補ディレクトリは無視されること。"""
    missing = tmp_path / "missing"
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "2024-01-15-alpha-session.tmp").write_text("one", encoding="utf-8")

    monkeypatch.setattr(sm, "get_session_search_dirs", lambda: [missing, existing])

    candidates = sm._get_session_candidates()
    assert [candidate.short_id for candidate in candidates] == ["alpha"]


def test_get_session_candidates_ignores_directory_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """セッションディレクトリの読み取り失敗を無視する。"""
    blocked = tmp_path / "blocked"
    blocked.mkdir()

    monkeypatch.setattr(sm, "get_session_search_dirs", lambda: [blocked])
    monkeypatch.setattr(sm.Path, "iterdir", lambda self: (_ for _ in ()).throw(OSError("boom")), raising=False)

    assert sm._get_session_candidates() == []


def test_get_session_by_id_covers_filename_and_no_id_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ID 一致判定の filename / no-id 分岐を通す。"""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    monkeypatch.setattr(sm, "get_session_search_dirs", lambda: [sessions_dir])

    filename_match = sessions_dir / "2024-01-15-target-session.tmp"
    filename_match.write_text("# target", encoding="utf-8")
    no_id_match = sessions_dir / "2024-01-15-session.tmp"
    no_id_match.write_text("# no id", encoding="utf-8")

    assert sm.get_session_by_id("2024-01-15-target-session") is not None
    assert sm.get_session_by_id("2024-01-15") is not None


def test_get_session_by_id_rejects_non_string_and_blank() -> None:
    assert sm.get_session_by_id(None) is None
    assert sm.get_session_by_id("   ") is None


def test_get_session_by_id_skips_missing_dirs_and_iterdir_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "missing"
    blocked = tmp_path / "blocked"
    blocked.mkdir()

    monkeypatch.setattr(sm, "get_session_search_dirs", lambda: [missing, blocked])

    original_iterdir = sm.Path.iterdir

    def fake_iterdir(self):  # noqa: ANN001
        if self == blocked:
            raise OSError("boom")
        return original_iterdir(self)

    monkeypatch.setattr(sm.Path, "iterdir", fake_iterdir, raising=False)
    assert sm.get_session_by_id("alpha") is None


def test_get_session_by_id_skips_non_tmp_entries_and_failed_record_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    monkeypatch.setattr(sm, "get_session_search_dirs", lambda: [sessions_dir])

    (sessions_dir / "notes.md").write_text("skip", encoding="utf-8")
    (sessions_dir / "2024-01-15-alpha-session.tmp").write_text("# alpha", encoding="utf-8")

    monkeypatch.setattr(sm, "_build_session_record", lambda session_path, metadata: None)
    assert sm.get_session_by_id("alpha") is None


def test_get_session_stats_accepts_path_strings(tmp_path: Path) -> None:
    """パス文字列入力の分岐を通す。"""
    session_file = tmp_path / "session.tmp"
    session_file.write_text(
        """\
# Title
### 完了済み
- [x] Done
### 進行中
- [ ] Doing
### 次回セッションへの引継ぎ
Notes
### 読み込むコンテキスト
```
context
```
""",
        encoding="utf-8",
    )

    stats = sm.get_session_stats(str(session_file))
    assert stats.total_items == 2
    assert stats.has_notes is True
    assert stats.has_context is True


def test_get_session_size_and_mutating_io_helpers_cover_error_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """サイズ取得と CRUD ヘルパーのエラーパスを確認する。"""
    large_file = tmp_path / "large.tmp"
    large_file.write_bytes(b"x" * (1024 * 1024 + 1))
    assert sm.get_session_size(large_file).endswith("MB")

    session_file = tmp_path / "session.tmp"
    assert sm.write_session_content(session_file, "content") is True
    assert sm.append_session_content(session_file, " more") is True
    assert session_file.read_text(encoding="utf-8") == "content more"
    assert sm.delete_session(session_file) is True

    monkeypatch.setattr(sm.Path, "write_text", lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("boom")), raising=False)
    assert sm.write_session_content(tmp_path / "write-fail.tmp", "content") is False

    monkeypatch.setattr(sm, "open", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")), raising=False)
    assert sm.append_session_content(tmp_path / "append-fail.tmp", "content") is False

    monkeypatch.setattr(sm.Path, "exists", lambda self: True, raising=False)
    monkeypatch.setattr(sm.Path, "unlink", lambda self: (_ for _ in ()).throw(OSError("boom")), raising=False)
    assert sm.delete_session(tmp_path / "delete-fail.tmp") is False

    monkeypatch.setattr(sm.Path, "is_file", lambda self: (_ for _ in ()).throw(OSError("boom")), raising=False)
    assert sm.session_exists(tmp_path / "exists-fail.tmp") is False
