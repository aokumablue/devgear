"""c-sessions ランタイムのテスト。"""

from __future__ import annotations

import runpy
import sys
from datetime import datetime

import pytest
from devgear.commands import session_commands as sc
from devgear.lib.session_aliases import AliasInfo, AliasListItem, DeleteAliasResult, SessionAliasInfo, SetAliasResult
from devgear.lib.session_manager import (
    ParsedSessionMetadata,
    SessionDetail,
    SessionListResult,
    SessionRecord,
    SessionStats,
    )


def _make_session_detail(*, stats: SessionStats | None = None, content: str | None = "# Session") -> SessionDetail:
    return SessionDetail(
        filename="2024-01-15-abc-session.tmp",
        short_id="abc12345",
        date="2024-01-15",
        datetime=datetime(2024, 1, 15),
        session_path="/tmp/sessions/2024-01-15-abc-session.tmp",
        has_content=True,
        size=100,
        modified_time=datetime(2024, 1, 15, 9, 5),
        created_time=datetime(2024, 1, 15, 9, 0),
        content=content,
        metadata=ParsedSessionMetadata(project="demo", branch="main", worktree="/workspace/demo"),
        stats=stats,
    )


def _make_session_record(*, short_id: str = "abc12345", filename: str = "2024-01-15-abc-session.tmp") -> SessionRecord:
    return SessionRecord(
        filename=filename,
        short_id=short_id,
        date="2024-01-15",
        datetime=datetime(2024, 1, 15),
        session_path=f"/tmp/sessions/{filename}",
        has_content=True,
        size=100,
        modified_time=datetime(2024, 1, 15, 9, 5),
        created_time=datetime(2024, 1, 15, 9, 0),
    )


def test_list_formats_sessions_with_aliases(monkeypatch, capsys) -> None:
    """一覧が既存ヘルパーを使って整形されること。"""

    sessions = [_make_session_record()]
    monkeypatch.setattr(sc, "get_all_sessions", lambda **kwargs: SessionListResult(sessions=sessions, total=1, offset=0, limit=20, has_more=False))
    monkeypatch.setattr(
        sc,
        "list_aliases",
        lambda: [AliasListItem(name="my-alias", session_path="/tmp/sessions/2024-01-15-abc-session.tmp", created_at=None, updated_at=None, title=None)],
    )
    monkeypatch.setattr(sc, "get_session_content", lambda path: "**Branch:** main\n**Worktree:** /workspace/demo")

    assert sc.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "Sessions (showing 1 of 1):" in out
    assert "abc12345" in out
    assert "main" in out
    assert "demo" in out
    assert "my-alias" in out


def test_load_resolves_alias_and_normalizes_full_path(monkeypatch, capsys) -> None:
    """load が alias とフルパスを両方処理できること。"""

    captured = {}

    def fake_get_session_by_id(session_id: str, include_content: bool = False):  # noqa: ANN001
        captured["session_id"] = session_id
        captured["include_content"] = include_content
        return _make_session_detail(
            stats=SessionStats(
                total_items=1,
                completed_items=1,
                in_progress_items=0,
                line_count=2,
                has_notes=False,
                has_context=False,
            )
        )

    monkeypatch.setattr(sc, "resolve_alias", lambda value: AliasInfo(alias="alias", session_path="/tmp/sessions/2024-01-15-abc-session.tmp", created_at="2024-01-15T00:00:00"))
    monkeypatch.setattr(sc, "get_session_by_id", fake_get_session_by_id)
    monkeypatch.setattr(sc, "get_aliases_for_session", lambda filename: [SessionAliasInfo(name="alias", created_at=None, title=None)])

    assert sc.main(["load", "alias"]) == 0
    out = capsys.readouterr().out
    assert captured["session_id"] == "2024-01-15-abc-session.tmp"
    assert captured["include_content"] is True
    assert "Session: 2024-01-15-abc-session.tmp" in out
    assert "Aliases: alias" in out


def test_alias_create_uses_session_filename_and_remove_reports_errors(monkeypatch, capsys) -> None:
    """alias create/remove がヘルパーの結果を反映すること。"""

    requested = {}

    def fake_get_session_by_id(session_id: str, include_content: bool = False):  # noqa: ANN001
        requested["session_id"] = session_id
        return _make_session_detail(stats=None, content=None)

    monkeypatch.setattr(sc, "get_session_by_id", fake_get_session_by_id)
    monkeypatch.setattr(sc, "set_alias", lambda alias, session_path, title=None: SetAliasResult(success=True, is_new=True, alias=alias, session_path=session_path, title=title))
    assert sc.main(["alias", "/tmp/sessions/2024-01-15-abc-session.tmp", "friendly"]) == 0
    out = capsys.readouterr().out
    assert requested["session_id"] == "2024-01-15-abc-session.tmp"
    assert "Alias created: friendly -> 2024-01-15-abc-session.tmp" in out

    monkeypatch.setattr(sc, "delete_alias", lambda alias: DeleteAliasResult(success=False, error="Alias not found", alias=alias))
    assert sc.main(["alias", "--remove", "missing"]) == 1
    out = capsys.readouterr().out
    assert "Error: Alias not found" in out


def test_remaining_helpers_and_entrypoint_paths(monkeypatch, capsys) -> None:
    """ヘルパー分岐と CLI の残りの経路をまとめて確認する。"""

    assert sc._normalize_session_target("  /tmp/one/two.tmp  ") == "two.tmp"
    assert sc._normalize_session_target("   ") == ""

    alias_map = sc._build_alias_map(
        [
            AliasListItem(name="first", session_path="/tmp/sessions/one.tmp", created_at=None, updated_at=None, title=None),
            AliasListItem(name="second", session_path="/tmp/sessions/two.tmp", created_at=None, updated_at=None, title=None),
        ]
    )
    assert alias_map["/tmp/sessions/one.tmp"] == "first"
    assert alias_map["one.tmp"] == "first"
    assert alias_map["two.tmp"] == "second"

    monkeypatch.setattr(sc, "list_aliases", lambda: [])
    monkeypatch.setattr(sc, "get_session_content", lambda path: "**Branch:** -\n**Worktree:** ")
    monkeypatch.setattr(sc, "parse_session_metadata", lambda content: ParsedSessionMetadata(project=None, branch=None, worktree=None))
    sc._print_session_list([_make_session_record(short_id="no-id")], total=1)
    out = capsys.readouterr().out
    assert "(none)" in out
    assert "Alias" in out

    monkeypatch.setattr(sc, "get_session_stats", lambda content: SessionStats(total_items=2, completed_items=1, in_progress_items=1, line_count=4, has_notes=False, has_context=False))
    sc._print_session_detail(_make_session_detail(stats=None, content=None))
    out = capsys.readouterr().out
    assert "Lines: 4" in out
    assert "Project: demo" in out

    monkeypatch.setattr(sc, "get_session_by_id", lambda session_id, include_content=False: None)
    assert sc._handle_load([]) == 1
    assert sc._handle_load(["missing"]) == 1
    out = capsys.readouterr().out
    assert "Usage: /c-sessions load <id|alias>" in out
    assert "Session not found: missing" in out

    assert sc._handle_alias([]) == 1
    assert sc._handle_alias(["--remove"]) == 1
    assert sc._handle_alias(["only-one"]) == 1
    monkeypatch.setattr(sc, "get_session_by_id", lambda session_id, include_content=False: None)
    assert sc._handle_alias(["missing", "friendly"]) == 1
    out = capsys.readouterr().out
    assert "Usage: /c-sessions alias <id> <name>" in out
    assert "Session not found: missing" in out

    monkeypatch.setattr(sc, "delete_alias", lambda alias: DeleteAliasResult(success=True, error=None, alias=alias))
    assert sc._handle_alias(["--remove", "friendly"]) == 0
    out = capsys.readouterr().out
    assert "Alias removed: friendly" in out

    monkeypatch.setattr(sc, "set_alias", lambda alias, session_path, title=None: SetAliasResult(success=False, is_new=False, alias=alias, session_path=session_path, title=title, error="boom"))
    monkeypatch.setattr(sc, "get_session_by_id", lambda session_id, include_content=False: _make_session_detail())
    assert sc._handle_alias(["missing", "friendly"]) == 1
    out = capsys.readouterr().out
    assert "Error: boom" in out

    monkeypatch.setattr(sc, "list_aliases", lambda: [])
    assert sc._handle_aliases() == 0
    out = capsys.readouterr().out
    assert "No aliases found." in out

    monkeypatch.setattr(
        sc,
        "list_aliases",
        lambda: [AliasListItem(name="alias", session_path="/tmp/sessions/alias.tmp", created_at=None, updated_at=None, title=None)],
    )
    assert sc._handle_aliases() == 0
    out = capsys.readouterr().out
    assert "Alias      Session Path" in out
    assert "alias" in out

    assert sc.main([]) == 0
    assert sc.main(["--help"]) == 0
    assert sc.main(["aliases"]) == 0
    assert sc.main(["unknown"]) == 1
    out = capsys.readouterr().out
    assert "Usage: /c-sessions [list|load|alias|aliases]" in out
    assert "Unknown command: unknown" in out


def test_session_commands_entrypoint_exits_zero(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["session_commands.py"])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("devgear.commands.session_commands", run_name="__main__")

    assert excinfo.value.code == 0
