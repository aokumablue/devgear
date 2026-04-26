"""session_aliases モジュールのテスト。"""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from devgear.lib.session_aliases import (
    ALIAS_VERSION,
    AliasInfo,
    AliasListItem,
    cleanup_aliases,
    delete_alias,
    get_aliases_for_session,
    get_aliases_path,
    list_aliases,
    load_aliases,
    rename_alias,
    resolve_alias,
    resolve_session_alias,
    save_aliases,
    set_alias,
    update_alias_title,
)


@pytest.fixture
def mock_aliases_path(tmp_path):
    """エイリアスパスが一時ディレクトリを使うようにモックする。"""
    aliases_file = tmp_path / "session-aliases.json"
    with patch("devgear.lib.session_aliases.get_aliases_path", return_value=aliases_file):
        with patch("devgear.lib.session_aliases.get_claude_dir", return_value=tmp_path):
            yield aliases_file


class TestGetAliasesPath:
    """get_aliases_path 関数のテスト。"""

    def test_returns_path(self):
        path = get_aliases_path()
        assert path.name == "session-aliases.json"


class TestLoadAliases:
    """load_aliases 関数のテスト。"""

    def test_returns_default_when_no_file(self, mock_aliases_path):
        result = load_aliases()
        assert result["version"] == ALIAS_VERSION
        assert result["aliases"] == {}
        assert "metadata" in result

    def test_loads_existing_file(self, mock_aliases_path):
        data = {
            "version": "1.0",
            "aliases": {"test": {"sessionPath": "/path/to/session", "createdAt": "2024-01-01"}},
            "metadata": {"totalCount": 1, "lastUpdated": "2024-01-01"},
        }
        mock_aliases_path.write_text(json.dumps(data))

        result = load_aliases()
        assert "test" in result["aliases"]
        assert result["aliases"]["test"]["sessionPath"] == "/path/to/session"

    def test_returns_default_for_invalid_json(self, mock_aliases_path):
        mock_aliases_path.write_text("not valid json")

        result = load_aliases()
        assert result["version"] == ALIAS_VERSION
        assert result["aliases"] == {}

    def test_adds_missing_version(self, mock_aliases_path):
        data = {"aliases": {}}
        mock_aliases_path.write_text(json.dumps(data))

        result = load_aliases()
        assert result["version"] == ALIAS_VERSION

    def test_adds_missing_version_when_aliases_exist(self, mock_aliases_path):
        data = {
            "aliases": {"test": {"sessionPath": "/path", "createdAt": "2024-01-01"}},
            "metadata": {"totalCount": 1, "lastUpdated": "2024-01-01"},
        }
        mock_aliases_path.write_text(json.dumps(data))

        result = load_aliases()
        assert result["version"] == ALIAS_VERSION

    def test_adds_missing_metadata(self, mock_aliases_path):
        data = {"version": "1.0", "aliases": {"test": {"sessionPath": "/path"}}}
        mock_aliases_path.write_text(json.dumps(data))

        result = load_aliases()
        assert "metadata" in result

    def test_returns_default_for_empty_file(self, mock_aliases_path):
        mock_aliases_path.write_text("")

        result = load_aliases()
        assert result["version"] == ALIAS_VERSION
        assert result["aliases"] == {}


class TestSaveAliases:
    """save_aliases 関数のテスト。"""

    def test_saves_aliases(self, mock_aliases_path):
        aliases = {
            "version": "1.0",
            "aliases": {"test": {"sessionPath": "/path", "createdAt": "2024-01-01"}},
        }

        result = save_aliases(aliases)
        assert result is True
        assert mock_aliases_path.exists()

        saved = json.loads(mock_aliases_path.read_text())
        assert "test" in saved["aliases"]
        assert saved["metadata"]["totalCount"] == 1

    def test_restores_backup_when_rename_fails(self, mock_aliases_path, monkeypatch):
        mock_aliases_path.write_text(
            json.dumps({"version": "1.0", "aliases": {"old": {"sessionPath": "/old", "createdAt": "2024-01-01"}}})
        )
        aliases = {
            "version": "1.0",
            "aliases": {"new": {"sessionPath": "/new", "createdAt": "2024-01-02"}},
        }

        monkeypatch.setattr("devgear.lib.session_aliases.platform.system", lambda: "Windows")

        def fake_rename(self, dest):  # noqa: ANN001
            raise OSError("boom")

        monkeypatch.setattr(Path, "rename", fake_rename)

        result = save_aliases(aliases)

        assert result is False
        saved = json.loads(mock_aliases_path.read_text())
        assert "old" in saved["aliases"]
        assert "new" not in saved["aliases"]

    def test_creates_parent_directory(self, tmp_path):
        nested_path = tmp_path / "nested" / "dir" / "session-aliases.json"
        with patch("devgear.lib.session_aliases.get_aliases_path", return_value=nested_path):
            with patch("devgear.lib.session_aliases.get_claude_dir", return_value=nested_path.parent):
                aliases = {"version": "1.0", "aliases": {}}
                result = save_aliases(aliases)
                assert result is True

    def test_returns_false_when_rename_fails(self, mock_aliases_path):
        aliases = {
            "version": "1.0",
            "aliases": {"test": {"sessionPath": "/path", "createdAt": "2024-01-01"}},
        }

        with patch("pathlib.Path.rename", side_effect=OSError("boom")):
            result = save_aliases(aliases)

        assert result is False

    def test_logs_restore_and_cleans_temp_when_rollback_restore_fails(self, mock_aliases_path, monkeypatch):
        mock_aliases_path.write_text(
            json.dumps({"version": "1.0", "aliases": {"old": {"sessionPath": "/old", "createdAt": "2024-01-01"}}})
        )
        aliases = {
            "version": "1.0",
            "aliases": {"new": {"sessionPath": "/new", "createdAt": "2024-01-02"}},
        }
        messages: list[str] = []
        backup_path = mock_aliases_path.with_suffix(".json.bak")
        temp_path = mock_aliases_path.with_suffix(".json.tmp")
        original_unlink = Path.unlink
        original_copy2 = shutil.copy2

        def fake_copy2(src, dst, *args, **kwargs):  # noqa: ANN001
            if Path(src) == backup_path and Path(dst) == mock_aliases_path:
                raise OSError("restore boom")
            return original_copy2(src, dst, *args, **kwargs)

        def fake_unlink(self, *args, **kwargs):  # noqa: ANN001
            if self == temp_path:
                raise OSError("cleanup boom")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr("devgear.lib.session_aliases.shutil.copy2", fake_copy2)
        monkeypatch.setattr(Path, "rename", lambda self, dest: (_ for _ in ()).throw(OSError("boom")))
        monkeypatch.setattr(Path, "unlink", fake_unlink)
        monkeypatch.setattr("devgear.lib.session_aliases.log", messages.append)

        result = save_aliases(aliases)

        assert result is False
        assert any("Failed to restore backup" in message for message in messages)


class TestResolveAlias:
    """resolve_alias 関数のテスト。"""

    def test_resolves_existing_alias(self, mock_aliases_path):
        data = {
            "version": "1.0",
            "aliases": {
                "myalias": {
                    "sessionPath": "/path/to/session",
                    "createdAt": "2024-01-01T00:00:00",
                    "title": "My Session",
                }
            },
        }
        mock_aliases_path.write_text(json.dumps(data))

        result = resolve_alias("myalias")
        assert result is not None
        assert isinstance(result, AliasInfo)
        assert result.alias == "myalias"
        assert result.session_path == "/path/to/session"
        assert result.title == "My Session"

    def test_returns_none_for_missing_alias(self, mock_aliases_path):
        mock_aliases_path.write_text(json.dumps({"version": "1.0", "aliases": {}}))

        result = resolve_alias("nonexistent")
        assert result is None

    def test_returns_none_for_invalid_alias_name(self, mock_aliases_path):
        result = resolve_alias("invalid!name")
        assert result is None

    def test_returns_none_for_empty_alias(self, mock_aliases_path):
        result = resolve_alias("")
        assert result is None


class TestSetAlias:
    """set_alias 関数のテスト。"""

    def test_creates_new_alias(self, mock_aliases_path):
        result = set_alias("newalias", "/path/to/session", "My Session")

        assert result.success is True
        assert result.is_new is True
        assert result.alias == "newalias"
        assert result.session_path == "/path/to/session"
        assert result.title == "My Session"

    def test_updates_existing_alias(self, mock_aliases_path):
        set_alias("existing", "/old/path")
        result = set_alias("existing", "/new/path", "Updated Title")

        assert result.success is True
        assert result.is_new is False
        assert result.session_path == "/new/path"

    def test_rejects_empty_alias(self, mock_aliases_path):
        result = set_alias("", "/path")
        assert result.success is False
        assert "cannot be empty" in result.error

    def test_rejects_empty_session_path(self, mock_aliases_path):
        result = set_alias("alias", "")
        assert result.success is False
        assert "cannot be empty" in result.error

    def test_rejects_long_alias(self, mock_aliases_path):
        result = set_alias("a" * 129, "/path")
        assert result.success is False
        assert "128 characters" in result.error

    def test_rejects_invalid_characters(self, mock_aliases_path):
        result = set_alias("invalid!name", "/path")
        assert result.success is False
        assert "letters, numbers" in result.error

    def test_returns_failure_when_save_fails(self, mock_aliases_path, monkeypatch):
        monkeypatch.setattr("devgear.lib.session_aliases.save_aliases", lambda aliases: False)

        result = set_alias("newalias", "/path")

        assert result.success is False
        assert "Failed to save alias" in result.error

    def test_rejects_reserved_names(self, mock_aliases_path):
        result = set_alias("list", "/path")
        assert result.success is False
        assert "reserved" in result.error


class TestListAliases:
    """list_aliases 関数のテスト。"""

    def test_lists_all_aliases(self, mock_aliases_path):
        set_alias("alias1", "/path1", "Title 1")
        set_alias("alias2", "/path2", "Title 2")

        result = list_aliases()
        assert len(result) == 2
        assert all(isinstance(a, AliasListItem) for a in result)

    def test_filters_by_search(self, mock_aliases_path):
        set_alias("alpha", "/path1")
        set_alias("beta", "/path2")

        result = list_aliases(search="alpha")
        assert len(result) == 1
        assert result[0].name == "alpha"

    def test_searches_in_title(self, mock_aliases_path):
        set_alias("alias1", "/path1", "Project Alpha")
        set_alias("alias2", "/path2", "Project Beta")

        result = list_aliases(search="beta")
        assert len(result) == 1
        assert result[0].title == "Project Beta"

    def test_limits_results(self, mock_aliases_path):
        set_alias("alias1", "/path1")
        set_alias("alias2", "/path2")
        set_alias("alias3", "/path3")

        result = list_aliases(limit=2)
        assert len(result) == 2

    def test_handles_invalid_timestamps(self, mock_aliases_path):
        data = {
            "version": "1.0",
            "aliases": {
                "alias1": {
                    "sessionPath": "/path1",
                    "createdAt": "bad",
                    "updatedAt": "also-bad",
                    "title": "Title",
                }
            },
        }
        mock_aliases_path.write_text(json.dumps(data))

        result = list_aliases()
        assert len(result) == 1
        assert result[0].name == "alias1"


class TestDeleteAlias:
    """delete_alias 関数のテスト。"""

    def test_deletes_existing_alias(self, mock_aliases_path):
        set_alias("todelete", "/path")

        result = delete_alias("todelete")
        assert result.success is True
        assert result.alias == "todelete"
        assert result.deleted_session_path == "/path"

        # 削除済みであることを確認
        assert resolve_alias("todelete") is None

    def test_fails_for_nonexistent_alias(self, mock_aliases_path):
        result = delete_alias("nonexistent")
        assert result.success is False
        assert "not found" in result.error

    def test_returns_failure_when_save_fails(self, mock_aliases_path, monkeypatch):
        set_alias("todelete", "/path")
        monkeypatch.setattr("devgear.lib.session_aliases.save_aliases", lambda aliases: False)

        result = delete_alias("todelete")

        assert result.success is False
        assert "Failed to delete alias" in result.error


class TestRenameAlias:
    """rename_alias 関数のテスト。"""

    def test_renames_alias(self, mock_aliases_path):
        set_alias("oldname", "/path", "My Session")

        result = rename_alias("oldname", "newname")
        assert result.success is True
        assert result.old_alias == "oldname"
        assert result.new_alias == "newname"

        # 旧名は存在しないはず
        assert resolve_alias("oldname") is None
        # 新名は存在するはず
        assert resolve_alias("newname") is not None

    def test_fails_for_nonexistent_old_alias(self, mock_aliases_path):
        result = rename_alias("nonexistent", "newname")
        assert result.success is False
        assert "not found" in result.error

    def test_fails_for_existing_new_alias(self, mock_aliases_path):
        set_alias("alias1", "/path1")
        set_alias("alias2", "/path2")

        result = rename_alias("alias1", "alias2")
        assert result.success is False
        assert "already exists" in result.error

    def test_validates_new_alias_name(self, mock_aliases_path):
        set_alias("oldname", "/path")

        result = rename_alias("oldname", "invalid!name")
        assert result.success is False

    def test_rejects_new_alias_edge_cases(self, mock_aliases_path):
        set_alias("oldname", "/path", "My Session")

        cases = [
            ("", "cannot be empty"),
            ("a" * 129, "cannot exceed 128 characters"),
            ("list", "reserved alias name"),
        ]

        for new_alias, expected in cases:
            result = rename_alias("oldname", new_alias)
            assert result.success is False
            assert expected in result.error

    def test_rolls_back_when_save_fails(self, mock_aliases_path, monkeypatch):
        data = {
            "version": ALIAS_VERSION,
            "aliases": {"oldname": {"sessionPath": "/path", "createdAt": "2024-01-01"}},
        }

        monkeypatch.setattr("devgear.lib.session_aliases.load_aliases", lambda: data)
        monkeypatch.setattr("devgear.lib.session_aliases.save_aliases", lambda aliases: False)

        result = rename_alias("oldname", "newname")

        assert result.success is False
        assert "rolled back" in result.error
        assert "oldname" in data["aliases"]
        assert "newname" not in data["aliases"]


class TestResolveSessionAlias:
    """resolve_session_alias 関数のテスト。"""

    def test_resolves_alias(self, mock_aliases_path):
        set_alias("myalias", "/path/to/session")

        result = resolve_session_alias("myalias")
        assert result == "/path/to/session"

    def test_returns_input_for_non_alias(self, mock_aliases_path):
        result = resolve_session_alias("some-session-id")
        assert result == "some-session-id"


class TestUpdateAliasTitle:
    """update_alias_title 関数のテスト。"""

    def test_updates_title(self, mock_aliases_path):
        set_alias("myalias", "/path")

        result = update_alias_title("myalias", "New Title")
        assert result.success is True
        assert result.title == "New Title"

        resolved = resolve_alias("myalias")
        assert resolved.title == "New Title"

    def test_clears_title_with_none(self, mock_aliases_path):
        set_alias("myalias", "/path", "Old Title")

        result = update_alias_title("myalias", None)
        assert result.success is True
        assert result.title is None

    def test_fails_for_nonexistent_alias(self, mock_aliases_path):
        result = update_alias_title("nonexistent", "Title")
        assert result.success is False
        assert "not found" in result.error

    def test_rejects_non_string_title(self, mock_aliases_path):
        result = update_alias_title("myalias", 123)  # type: ignore[arg-type]
        assert result.success is False
        assert "must be a string or null" in result.error

    def test_returns_error_when_save_fails(self, mock_aliases_path, monkeypatch):
        data = {
            "version": ALIAS_VERSION,
            "aliases": {"myalias": {"sessionPath": "/path", "createdAt": "2024-01-01"}},
        }

        monkeypatch.setattr("devgear.lib.session_aliases.load_aliases", lambda: data)
        monkeypatch.setattr("devgear.lib.session_aliases.save_aliases", lambda aliases: False)

        result = update_alias_title("myalias", "Updated")

        assert result.success is False
        assert "Failed to update alias title" in result.error


class TestGetAliasesForSession:
    """get_aliases_for_session 関数のテスト。"""

    def test_finds_aliases_for_session(self, mock_aliases_path):
        set_alias("alias1", "/path/session1")
        set_alias("alias2", "/path/session1")
        set_alias("alias3", "/path/session2")

        result = get_aliases_for_session("/path/session1")
        assert len(result) == 2
        names = {a.name for a in result}
        assert "alias1" in names
        assert "alias2" in names

    def test_returns_empty_for_no_matches(self, mock_aliases_path):
        set_alias("alias1", "/path/session1")

        result = get_aliases_for_session("/path/other")
        assert result == []


class TestCleanupAliases:
    """cleanup_aliases 関数のテスト。"""

    def test_removes_invalid_aliases(self, mock_aliases_path):
        set_alias("valid", "/path/exists")
        set_alias("invalid", "/path/missing")

        def session_exists(path: str) -> bool:
            return path == "/path/exists"

        result = cleanup_aliases(session_exists)
        assert result.success is True
        assert result.removed == 1
        assert len(result.removed_aliases) == 1

        # 有効なエイリアスは残るはず
        assert resolve_alias("valid") is not None
        # 無効なエイリアスは削除されるはず
        assert resolve_alias("invalid") is None

    def test_returns_error_for_non_callable(self, mock_aliases_path):
        result = cleanup_aliases("not a function")
        assert result.success is False
        assert "must be a function" in result.error

    def test_returns_error_when_save_after_cleanup_fails(self, mock_aliases_path, monkeypatch):
        data = {
            "version": ALIAS_VERSION,
            "aliases": {
                "valid": {"sessionPath": "/path/exists", "createdAt": "2024-01-01"},
                "invalid": {"sessionPath": "/path/missing", "createdAt": "2024-01-01"},
            },
        }

        monkeypatch.setattr("devgear.lib.session_aliases.load_aliases", lambda: data)
        monkeypatch.setattr("devgear.lib.session_aliases.save_aliases", lambda aliases: False)

        def session_exists(path: str) -> bool:
            return path == "/path/exists"

        result = cleanup_aliases(session_exists)

        assert result.success is False
        assert result.removed == 1
        assert "Failed to save after cleanup" in result.error
