"""team: CLI ハンドラ (team-context / team-session-init) のテスト。"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

import devgear.mem.search as search_mod
from devgear.mem import cli as cli_module
from devgear.mem.settings import Settings, SyncSettings, TeamSettings


class _FakePg:
    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected
        self.closed = False

    def test_connection(self) -> bool:
        return self.connected

    def close(self) -> None:
        self.closed = True


def _settings(*, sync_enabled: bool = True, url: str = "postgres://x") -> Settings:
    s = Settings()
    s.sync = SyncSettings(enabled=sync_enabled, postgres_url=url)
    s.team = TeamSettings(enabled=True, max_tokens=1000, chunk_limit=5, exclude_self=True)
    return s


def test_team_context_skipped_when_sync_disabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    called = {"ok": False}

    def _fake_build(*a, **kw):  # noqa: ANN001, ANN002, ANN003
        called["ok"] = True
        return "<team-context>X</team-context>"

    monkeypatch.setattr("devgear.mem.team_context.build_team_context", _fake_build)
    assert cli_module._handle_team_context(_settings(sync_enabled=False), {"cwd": "/p/proj"}) == ""
    assert capsys.readouterr().out == ""
    assert called["ok"] is False


def test_team_context_skipped_when_url_empty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli_module._handle_team_context(_settings(url=""), {"cwd": "/p/proj"}) == ""
    assert capsys.readouterr().out == ""


def test_team_context_skipped_when_team_disabled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    s = _settings()
    s.team = TeamSettings(enabled=False)
    assert cli_module._handle_team_context(s, {"cwd": "/p/proj"}) == ""
    assert capsys.readouterr().out == ""


def test_team_context_silent_on_connection_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli_module, "get_git_user_name", lambda: "me")
    monkeypatch.setattr(
        "devgear.mem.pg_database.PgDatabase",
        lambda url: _FakePg(connected=False),
    )
    assert cli_module._handle_team_context(_settings(), {"cwd": "/p/proj"}) == ""
    assert capsys.readouterr().out == ""


def test_team_context_prints_additional_context(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pg_instance = _FakePg(connected=True)
    monkeypatch.setattr(cli_module, "get_git_user_name", lambda: "me")
    monkeypatch.setattr(
        "devgear.mem.pg_database.PgDatabase", lambda url: pg_instance
    )

    captured_kwargs: dict = {}

    def _fake_build(pg, *, query, exclude_origin_user, settings, mode, embedding_model=None):  # noqa: ANN001
        captured_kwargs.update(
            {
                "query": query,
                "exclude": exclude_origin_user,
                "mode": mode,
                "embedding_model": embedding_model,
            }
        )
        return "<team-context>hello</team-context>"

    monkeypatch.setattr("devgear.mem.team_context.build_team_context", _fake_build)

    result = cli_module._handle_team_context(_settings(), {"cwd": "/home/u/x-picflow"})

    assert "<team-context>" in result
    assert capsys.readouterr().out == ""
    assert captured_kwargs["query"] == "x-picflow"
    assert captured_kwargs["exclude"] == "me"
    assert captured_kwargs["mode"] == "fts"
    assert pg_instance.closed is True


def test_team_context_respects_excluded_projects(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = _settings()
    s.excluded_projects = ["x-picflow"]
    assert cli_module._handle_team_context(s, {"cwd": "/home/u/x-picflow"}) == ""
    assert capsys.readouterr().out == ""


def test_team_session_init_requires_retrospective_prompt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    called = {"ok": False}
    monkeypatch.setattr(
        "devgear.mem.pg_database.PgDatabase",
        lambda url: (_ for _ in ()).throw(AssertionError("should not reach PG")),
    )
    monkeypatch.setattr(
        "devgear.mem.team_context.build_team_context",
        lambda *a, **kw: called.__setitem__("ok", True) or "",  # noqa: ANN001
    )

    cli_module._handle_team_session_init(
        _settings(), {"cwd": "/p/proj", "prompt": "新機能を追加してください"}
    )

    assert capsys.readouterr().out == ""
    assert called["ok"] is False


def test_team_session_init_fires_on_retrospective_keyword(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pg_instance = _FakePg(connected=True)
    monkeypatch.setattr(cli_module, "get_git_user_name", lambda: "me")
    monkeypatch.setattr(
        "devgear.mem.pg_database.PgDatabase", lambda url: pg_instance
    )

    captured: dict = {}

    def _fake_build(pg, *, query, exclude_origin_user, settings, mode, embedding_model=None):  # noqa: ANN001
        captured.update(
            {
                "query": query,
                "exclude": exclude_origin_user,
                "mode": mode,
                "embedding_model": embedding_model,
            }
        )
        return "<team-context>history</team-context>"

    monkeypatch.setattr("devgear.mem.team_context.build_team_context", _fake_build)

    cli_module._handle_team_session_init(
        _settings(), {"cwd": "/home/u/x-picflow", "prompt": "前回どう直した？"}
    )

    assert capsys.readouterr().out.strip().startswith('{"hookEventName"')
    assert captured["mode"] == "hybrid"
    assert captured["exclude"] == "me"
    assert "前回どう直した？" in captured["query"]
    assert "x-picflow" in captured["query"]
    assert captured["embedding_model"]  # settings のモデル名が渡る


def test_team_session_init_silent_on_empty_prompt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli_module._handle_team_session_init(_settings(), {"cwd": "/p/proj", "prompt": ""})
    assert capsys.readouterr().out == ""


def test_team_session_init_respects_exclude_self_false(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    s = _settings()
    s.team = TeamSettings(enabled=True, exclude_self=False)
    pg_instance = _FakePg(connected=True)
    monkeypatch.setattr(cli_module, "get_git_user_name", lambda: "me")
    monkeypatch.setattr(
        "devgear.mem.pg_database.PgDatabase", lambda url: pg_instance
    )

    captured: dict = {}

    def _fake_build(pg, *, query, exclude_origin_user, settings, mode, embedding_model=None):  # noqa: ANN001
        captured["exclude"] = exclude_origin_user
        return "<team-context>x</team-context>"

    monkeypatch.setattr("devgear.mem.team_context.build_team_context", _fake_build)
    cli_module._handle_team_session_init(
        s, {"cwd": "/home/u/x-picflow", "prompt": "前回の話"}
    )
    assert captured["exclude"] == ""


def test_team_context_and_session_init_failure_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings()
    monkeypatch.setattr(cli_module, "get_git_user_name", lambda: "me")
    monkeypatch.setattr(search_mod, "should_inject_memory", lambda prompt: True)

    assert cli_module._handle_team_context(settings, {"cwd": "/"}) == ""
    assert capsys.readouterr().out == ""

    fake_pg = ModuleType("devgear.mem.pg_database")
    fake_team = ModuleType("devgear.mem.team_context")
    monkeypatch.setitem(sys.modules, "devgear.mem.pg_database", fake_pg)
    monkeypatch.setitem(sys.modules, "devgear.mem.team_context", fake_team)

    assert cli_module._handle_team_context(settings, {"cwd": "/home/u/x-picflow"}) == ""
    assert capsys.readouterr().out == ""

    fake_pg.PgDatabase = lambda url: SimpleNamespace(
        test_connection=lambda: False,
        close=lambda: None,
    )
    fake_team.build_team_context = lambda *args, **kwargs: None
    assert cli_module._handle_team_context(settings, {"cwd": "/home/u/x-picflow"}) == ""
    assert capsys.readouterr().out == ""

    fake_pg.PgDatabase = lambda url: SimpleNamespace(
        test_connection=lambda: True,
        close=lambda: None,
    )
    fake_team.build_team_context = lambda *args, **kwargs: None
    assert cli_module._handle_team_session_init(
        settings, {"cwd": "/home/u/x-picflow", "prompt": "前回の話"}
    ) is None
    assert capsys.readouterr().out == ""

    fake_pg.PgDatabase = lambda url: SimpleNamespace(
        test_connection=lambda: True,
        close=lambda: None,
    )
    fake_team.build_team_context = lambda *args, **kwargs: None
    assert cli_module._handle_team_session_init(
        settings, {"cwd": "/home/u/x-picflow", "prompt": "前回の話"}
    ) is None
    assert capsys.readouterr().out == ""
