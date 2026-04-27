"""settings のテスト。

settings.json は ``mem.sync.enabled`` / ``mem.sync.postgres_url`` のみ永続化し、
ランタイム状態（last_synced_at など）は ``sync_state.json`` で管理する構成を検証する。
"""

import json
from pathlib import Path

import pytest

from devgear.mem.settings import _DEFAULT_EMBEDDING_MODEL, Settings


@pytest.fixture(autouse=True)
def _patch_default_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """各テストで ~/.devgear の代わりに一時ディレクトリを使う。"""
    import devgear.mem.settings as mod

    monkeypatch.setattr(mod, "_DEFAULT_DATA_DIR", tmp_path)


class TestSettingsDefaults:
    """デフォルト値のテスト"""

    def test_default_values(self) -> None:
        s = Settings()
        assert s.log_level == "info"
        assert s.embedding_model == _DEFAULT_EMBEDDING_MODEL
        assert s.search_half_life_days == 30.0
        assert s.chunk_max_length == 2000
        assert s.context_chunk_count == 30
        assert s.context_max_tokens == 1500
        assert s.context_hot_tokens == 400
        assert s.context_warm_tokens == 600
        assert s.excluded_projects == []

    def test_derived_properties(self, tmp_path: Path) -> None:
        s = Settings()
        assert s.data_path == tmp_path
        assert s.db_path == tmp_path / "mem.db"
        assert s.log_dir == tmp_path / "logs"
        assert s.settings_path == tmp_path / "settings.json"
        assert s.sync_state_path == tmp_path / "sync_state.json"


class TestSettingsSave:
    """永続化のテスト"""

    def test_save_creates_file(self, tmp_path: Path) -> None:
        s = Settings()
        s.save()
        assert (tmp_path / "settings.json").exists()

    def test_save_only_writes_sync_section(self, tmp_path: Path) -> None:
        """save() は mem.sync.enabled と mem.sync.postgres_url のみを書き出す。"""
        s = Settings()
        s.sync.enabled = True
        s.sync.postgres_url = "postgres://example"
        s.save()
        raw = json.loads((tmp_path / "settings.json").read_text())
        assert raw["mem"] == {"sync": {"enabled": True, "postgres_url": "postgres://example"}}

    def test_save_does_not_write_hardcoded_fields(self, tmp_path: Path) -> None:
        """save() はハードコード対象（log_level 等）を書き出さない。"""
        s = Settings()
        s.save()
        raw = json.loads((tmp_path / "settings.json").read_text())
        assert "log_level" not in raw["mem"]
        assert "chunk_max_length" not in raw["mem"]
        assert "embedding_model" not in raw["mem"]
        assert "last_compacted_at" not in raw["mem"]
        assert "compact" not in raw["mem"]
        assert "slim" not in raw["mem"]

    def test_save_preserves_other_plugin_sections(self, tmp_path: Path) -> None:
        """保存時に他プラグインのセクションを保持する"""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"flow": {"some_key": "some_value"}}))
        s = Settings()
        s.save()
        raw = json.loads(settings_file.read_text())
        assert raw["flow"]["some_key"] == "some_value"
        assert raw["mem"]["sync"]["enabled"] is False

    def test_save_reads_broken_existing_file_gracefully(self, tmp_path: Path) -> None:
        """既存ファイルが破損 JSON の場合、save() は空辞書から書き直す。"""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{{broken json")
        s = Settings()
        s.save()
        raw = json.loads(settings_file.read_text())
        assert "mem" in raw

    def test_save_reads_unreadable_existing_file_gracefully(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """既存ファイルの read_text が OSError を起こした場合、空辞書から書き直す。"""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}")

        call_count = {"n": 0}
        original_read_text = Path.read_text

        def _patched_read_text(self_path: Path, *args, **kwargs):  # type: ignore[override]
            if str(self_path) == str(settings_file) and call_count["n"] == 0:
                call_count["n"] += 1
                raise OSError("permission denied")
            return original_read_text(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _patched_read_text)

        s = Settings()
        s.save()
        raw = json.loads(settings_file.read_text())
        assert "mem" in raw


class TestSettingsLoad:
    """読み込みのテスト"""

    def test_load_reads_only_sync_enabled_and_url(self, tmp_path: Path) -> None:
        """settings.json から sync.enabled / sync.postgres_url のみ反映する。

        settings.json に旧フィールド（log_level 等）が残っていても無視し、
        ハードコード既定値が使用される。
        """
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "mem": {
                        "log_level": "debug",
                        "chunk_max_length": 9999,
                        "sync": {
                            "enabled": True,
                            "postgres_url": "postgres://example",
                            # settings.json に残っていても読まれない
                            "last_synced_at": 123.0,
                            "last_sync_success": True,
                        },
                    }
                }
            )
        )
        s = Settings.load(settings_path=path)
        # settings.json の設定値は無視され、ハードコード既定値
        assert s.log_level == "info"
        assert s.chunk_max_length == 2000
        # sync.enabled / postgres_url のみ反映
        assert s.sync.enabled is True
        assert s.sync.postgres_url == "postgres://example"
        # settings.json の last_synced_at は無視される（ランタイム状態のため）
        assert s.sync.last_synced_at == 0.0
        assert s.sync.last_sync_success is False

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent.json"
        s = Settings.load(settings_path=path)
        assert s.log_level == "info"
        assert s.sync.enabled is False

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text("not json{{{")
        s = Settings.load(settings_path=path)
        assert s.log_level == "info"
        assert s.sync.enabled is False

    def test_load_invalid_json_with_default_path(self, tmp_path: Path) -> None:
        (tmp_path / "settings.json").write_text("not json{{{")
        s = Settings.load()
        assert s.log_level == "info"
        assert s.sync.enabled is False

    def test_load_unknown_keys_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"mem": {"unknown_key": "val"}}))
        s = Settings.load(settings_path=path)
        assert not hasattr(s, "unknown_key")

    def test_load_default_creates_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """デフォルトパスで存在しない場合、ファイルを作成する"""
        import devgear.mem.settings as mod

        monkeypatch.setattr(mod, "_DEFAULT_DATA_DIR", tmp_path)
        Settings.load()
        assert (tmp_path / "settings.json").exists()

    def test_load_nonexistent_with_explicit_path_no_save(self, tmp_path: Path) -> None:
        """settings_path 指定時、存在しなければ save() しない"""
        path = tmp_path / "sub" / "settings.json"
        s = Settings.load(settings_path=path)
        assert not path.exists()
        assert s.log_level == "info"

    def test_load_sync_state_from_explicit_path(self, tmp_path: Path) -> None:
        """settings_path と同じディレクトリの sync_state.json があれば読み込む。"""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"mem": {"sync": {"enabled": True, "postgres_url": "u"}}}))
        (tmp_path / "sync_state.json").write_text(
            json.dumps(
                {
                    "last_synced_at": 42.0,
                    "last_sync_attempt_at": 41.0,
                    "last_sync_success": True,
                    "last_compacted_at": 100.0,
                }
            )
        )
        s = Settings.load(settings_path=settings_file)
        assert s.sync.last_synced_at == 42.0
        assert s.sync.last_sync_attempt_at == 41.0
        assert s.sync.last_sync_success is True
        assert s.last_compacted_at == 100.0

    def test_load_default_reads_sync_state(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """デフォルトパスで sync_state.json があれば自動で読み込む。"""
        import devgear.mem.settings as mod

        monkeypatch.setattr(mod, "_DEFAULT_DATA_DIR", tmp_path)
        (tmp_path / "sync_state.json").write_text(json.dumps({"last_compacted_at": 77.0}))

        s = Settings.load()
        assert s.last_compacted_at == 77.0

    def test_load_broken_sync_state_is_ignored(self, tmp_path: Path) -> None:
        """sync_state.json が壊れていてもクラッシュしない。"""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"mem": {"sync": {"enabled": False, "postgres_url": ""}}}))
        (tmp_path / "sync_state.json").write_text("{{broken")
        s = Settings.load(settings_path=settings_file)
        assert s.last_compacted_at == 0.0

    def test_load_non_dict_sync_state_is_ignored(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"mem": {"sync": {"enabled": True, "postgres_url": "u"}}}))
        (tmp_path / "sync_state.json").write_text("[]")
        s = Settings.load(settings_path=settings_file)
        assert s.last_compacted_at == 0.0


class TestSaveSyncState:
    """ランタイム状態の永続化テスト"""

    def test_save_sync_state_creates_file(self, tmp_path: Path) -> None:
        s = Settings()
        s.sync.last_synced_at = 111.0
        s.sync.last_sync_attempt_at = 110.0
        s.sync.last_sync_success = True
        s.last_compacted_at = 222.0
        s.save_sync_state()

        raw = json.loads((tmp_path / "sync_state.json").read_text())
        assert raw == {
            "last_synced_at": 111.0,
            "last_sync_attempt_at": 110.0,
            "last_sync_success": True,
            "last_compacted_at": 222.0,
        }

    def test_save_sync_state_does_not_touch_settings_json(self, tmp_path: Path) -> None:
        """save_sync_state() は settings.json を書き換えない。"""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"flow": {"a": 1}}))
        s = Settings()
        s.save_sync_state()
        # settings.json は変更されない
        assert json.loads(settings_file.read_text()) == {"flow": {"a": 1}}
        assert (tmp_path / "sync_state.json").exists()

    def test_sync_state_roundtrip(self, tmp_path: Path) -> None:
        """save_sync_state -> load で状態が復元される。"""
        settings_file = tmp_path / "settings.json"
        s = Settings()
        s.sync.enabled = True
        s.sync.postgres_url = "url"
        s.sync.last_synced_at = 1234567890.0
        s.last_compacted_at = 9999.0
        s.save()
        s.save_sync_state()

        loaded = Settings.load(settings_path=settings_file)
        assert loaded.sync.enabled is True
        assert loaded.sync.postgres_url == "url"
        assert loaded.sync.last_synced_at == 1234567890.0
        assert loaded.last_compacted_at == 9999.0


class TestAutoCompactSettings:
    """自動圧縮設定のテスト（ハードコード値）"""

    def test_auto_compact_defaults(self) -> None:
        s = Settings()
        assert s.auto_compact_enabled is True
        assert s.auto_compact_interval_days == 7
        assert s.last_compacted_at == 0.0

    def test_last_compacted_at_persisted_in_sync_state(self, tmp_path: Path) -> None:
        """last_compacted_at は sync_state.json に保存される。"""
        settings_file = tmp_path / "settings.json"
        s = Settings(last_compacted_at=1234567890.0)
        s.save()
        s.save_sync_state()

        loaded = Settings.load(settings_path=settings_file)
        assert loaded.last_compacted_at == 1234567890.0
        # auto_compact_enabled / interval_days はハードコード既定値
        assert loaded.auto_compact_enabled is True
        assert loaded.auto_compact_interval_days == 7
