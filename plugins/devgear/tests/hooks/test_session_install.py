"""session_install フックのテスト。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from devgear.hooks import session_install


class TestGetPluginVersion:
    def test_reads_version_from_plugin_json(self, tmp_path: Path) -> None:
        plugin_json = tmp_path / ".claude-plugin" / "plugin.json"
        plugin_json.parent.mkdir()
        plugin_json.write_text(json.dumps({"version": "1.2.3", "name": "devgear"}))

        assert session_install._get_plugin_version(tmp_path) == "1.2.3"

    def test_returns_none_when_version_missing_from_json(self, tmp_path: Path) -> None:
        plugin_json = tmp_path / ".claude-plugin" / "plugin.json"
        plugin_json.parent.mkdir()
        plugin_json.write_text(json.dumps({"name": "devgear"}))

        assert session_install._get_plugin_version(tmp_path) is None

    def test_returns_none_when_file_not_found(self, tmp_path: Path) -> None:
        assert session_install._get_plugin_version(tmp_path) is None

    def test_returns_none_when_invalid_json(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        plugin_json = tmp_path / ".claude-plugin" / "plugin.json"
        plugin_json.parent.mkdir()
        plugin_json.write_text("not-json")

        result = session_install._get_plugin_version(tmp_path)
        assert result is None
        assert "plugin.json" in capsys.readouterr().err


class TestGetInstalledVersion:
    def test_returns_none_when_file_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_install, "_VERSION_FILE", tmp_path / "plugin_installed_version")

        assert session_install._get_installed_version() is None

    def test_reads_version_from_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("0.0.2\n")
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)

        assert session_install._get_installed_version() == "0.0.2"

    def test_strips_whitespace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("  0.0.3  \n")
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)

        assert session_install._get_installed_version() == "0.0.3"


class TestWriteInstalledVersion:
    def test_creates_file_with_version(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        version_file = tmp_path / "plugin_installed_version"
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)

        session_install._write_installed_version("1.0.0")

        assert version_file.read_text() == "1.0.0\n"

    def test_creates_parent_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        devgear_dir = tmp_path / "nested" / ".devgear"
        version_file = devgear_dir / "plugin_installed_version"
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", devgear_dir)
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)

        session_install._write_installed_version("2.0.0")

        assert devgear_dir.exists()
        assert version_file.read_text() == "2.0.0\n"


class TestRun:
    def _setup_plugin_root(self, tmp_path: Path, version: str) -> Path:
        """plugin.json と install.sh を持つ偽プラグインルートを作成する。"""
        plugin_json = tmp_path / ".claude-plugin" / "plugin.json"
        plugin_json.parent.mkdir()
        plugin_json.write_text(json.dumps({"version": version}))
        install_sh = tmp_path / "install.sh"
        install_sh.write_text("#!/bin/bash\necho installed")
        return tmp_path

    def test_skips_when_no_claude_plugin_root(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

        result = json.loads(session_install.run(""))

        assert result["hookSpecificOutput"]["skipped"] is True
        assert result["hookSpecificOutput"]["reason"] == "CLAUDE_PLUGIN_ROOT not set"
        assert "CLAUDE_PLUGIN_ROOT" in capsys.readouterr().err

    def test_skips_when_plugin_json_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

        result = json.loads(session_install.run(""))

        assert result["hookSpecificOutput"]["skipped"] is True
        assert result["hookSpecificOutput"]["reason"] == "version not found"
        assert "バージョス" not in capsys.readouterr().err  # just check it ran without error

    def test_skips_when_version_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.2")
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("0.0.2\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)

        result = json.loads(session_install.run(""))

        assert result["hookSpecificOutput"]["skipped"] is True
        assert result["hookSpecificOutput"]["version"] == "0.0.2"

    def test_runs_install_when_no_version_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.2")
        version_file = tmp_path / "plugin_installed_version"
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        result = json.loads(session_install.run(""))

        assert result["hookSpecificOutput"]["skipped"] is False
        assert result["hookSpecificOutput"]["success"] is True
        assert result["hookSpecificOutput"]["version"] == "0.0.2"
        assert version_file.read_text() == "0.0.2\n"

    def test_runs_install_when_version_changed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.3")
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("0.0.2\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "install output"
        mock_result.stderr = "install stderr"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        result = json.loads(session_install.run(""))

        assert result["hookSpecificOutput"]["success"] is True
        assert result["hookSpecificOutput"]["version"] == "0.0.3"
        assert version_file.read_text() == "0.0.3\n"

    def test_does_not_write_version_on_install_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.3")
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("0.0.2\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "install failed"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        result = json.loads(session_install.run(""))

        assert result["hookSpecificOutput"]["success"] is False
        # バージョンファイルはまだ古いバージョンのまま（次回再試行）
        assert version_file.read_text() == "0.0.2\n"
        assert "失敗" in capsys.readouterr().err

    def test_does_not_write_version_on_subprocess_exception(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.3")
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("0.0.2\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)

        def raise_oserror(*_a: object, **_kw: object) -> None:
            raise OSError("install.sh not found")

        monkeypatch.setattr(subprocess, "run", raise_oserror)

        result = json.loads(session_install.run(""))

        assert result["hookSpecificOutput"]["success"] is False
        assert version_file.read_text() == "0.0.2\n"
        assert "実行に失敗" in capsys.readouterr().err

    def test_install_stdout_stderr_routed_to_stderr(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.2")
        version_file = tmp_path / "plugin_installed_version"
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "stdout from install"
        mock_result.stderr = "stderr from install"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        session_install.run("")

        captured = capsys.readouterr()
        assert "stdout from install" in captured.err
        assert "stderr from install" in captured.err


class TestMain:
    def test_returns_zero_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        assert session_install.main() == 0

    def test_returns_zero_on_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr(session_install, "run", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))

        assert session_install.main() == 0

    def test_reads_stdin_when_not_tty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

        assert session_install.main() == 0

    def test_main_block_via_runpy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import runpy
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("devgear.hooks.session_install", run_name="__main__")

        assert exc_info.value.code == 0
