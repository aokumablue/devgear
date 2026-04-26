"""pre_user_prompt フックのテスト。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from devgear.hooks import pre_user_prompt as hook
from devgear.mem.settings import SlimSettings


def _make_payload(prompt: str = "hello", session_id: str = "sess-test") -> str:
    """テスト用の UserPromptSubmit JSON ペイロードを生成する。"""
    return json.dumps({"prompt": prompt, "session_id": session_id})


class TestEvaluateSlimEnabled:
    """Slim 有効/無効のテスト"""

    def test_enabled_injects_skill_content(self, tmp_path) -> None:
        """settings.enabled=True のとき SKILL.md の内容を注入する。"""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("slim-content", encoding="utf-8")

        import unittest.mock as mock
        with mock.patch.object(hook, "_SKILL_PATH", skill_file):
            result = hook.evaluate(_make_payload(), settings=SlimSettings(enabled=True))

        data = json.loads(result)
        assert data["hookEventName"] == "UserPromptSubmit"
        assert data["additionalContext"] == "slim-content"

    def test_disabled_returns_empty(self) -> None:
        """settings.enabled=False は空文字列を返す。"""
        result = hook.evaluate(_make_payload(), settings=SlimSettings(enabled=False))
        assert result == ""

    def test_skill_not_found_returns_empty(self, tmp_path) -> None:
        """SKILL.md が存在しない場合は空文字列を返す。"""
        import unittest.mock as mock
        missing = tmp_path / "MISSING.md"
        with mock.patch.object(hook, "_SKILL_PATH", missing):
            result = hook.evaluate(_make_payload(), settings=SlimSettings(enabled=True))
        assert result == ""

    def test_skill_oserror_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SKILL.md の読み込みが OSError の場合は空文字列を返す。"""
        monkeypatch.setattr(
            hook,
            "_SKILL_PATH",
            SimpleNamespace(
                exists=lambda: True,
                read_text=lambda encoding="utf-8": (_ for _ in ()).throw(OSError("boom")),
            ),
        )
        result = hook.evaluate(_make_payload(), settings=SlimSettings(enabled=True))
        assert result == ""

    def test_invalid_json_returns_empty(self) -> None:
        """不正な JSON は空文字列を返す。"""
        result = hook.evaluate("not-json", settings=SlimSettings(enabled=True))
        assert result == ""

    def test_empty_input_returns_empty(self) -> None:
        """空文字列は空文字列を返す。"""
        result = hook.evaluate("", settings=SlimSettings(enabled=True))
        assert result == ""


class TestMain:
    """main() のテスト"""

    def test_main_returns_zero(self, monkeypatch) -> None:
        """main() は常に 0 を返す。"""
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(_make_payload()))
        assert hook.main() == 0


def test_load_slim_settings_falls_back_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []

    monkeypatch.setattr(hook.Settings, "load", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(hook, "write_stderr", messages.append)

    assert hook._load_slim_settings() == SlimSettings()
    assert any("settings load failed" in message for message in messages)


def test_load_skill_content_returns_empty_on_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hook,
        "_SKILL_PATH",
        SimpleNamespace(
            exists=lambda: True,
            read_text=lambda encoding="utf-8": (_ for _ in ()).throw(OSError("boom")),
        ),
    )

    assert hook._load_skill_content() == ""


def test_main_writes_output_and_handles_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout: list[str] = []
    stderr: list[str] = []

    monkeypatch.setattr(hook, "read_raw_stdin", lambda: _make_payload())
    monkeypatch.setattr(hook, "evaluate", lambda raw: "payload")
    monkeypatch.setattr(hook, "write_stdout", stdout.append)
    assert hook.main() == 0
    assert stdout == ["payload"]

    monkeypatch.setattr(hook, "evaluate", lambda raw: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(hook, "write_stderr", stderr.append)

    assert hook.main() == 0
    assert any("unexpected error" in message for message in stderr)
