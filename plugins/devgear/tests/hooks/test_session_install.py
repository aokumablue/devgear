"""session_install フックのテスト。"""

from __future__ import annotations

import json
import runpy
import subprocess
from contextlib import contextmanager
from pathlib import Path

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

    def test_returns_none_when_invalid_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        plugin_json = tmp_path / ".claude-plugin" / "plugin.json"
        plugin_json.parent.mkdir()
        plugin_json.write_text("not-json")

        result = session_install._get_plugin_version(tmp_path)
        assert result is None
        assert "plugin.json" in capsys.readouterr().err


class TestResolvePluginRoot:
    def test_returns_none_when_env_missing(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

        assert session_install._resolve_plugin_root() is None
        assert "CLAUDE_PLUGIN_ROOT" in capsys.readouterr().err

    def test_returns_none_when_plugin_json_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        monkeypatch.setattr(session_install, "_PLUGIN_ROOT", tmp_path)

        assert session_install._resolve_plugin_root() is None
        assert "不正なプラグインルート" in capsys.readouterr().err

    def test_returns_resolved_root_when_valid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        plugin_json = tmp_path / ".claude-plugin" / "plugin.json"
        plugin_json.parent.mkdir()
        plugin_json.write_text(json.dumps({"version": "1.0.0"}))
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        monkeypatch.setattr(session_install, "_PLUGIN_ROOT", tmp_path)

        assert session_install._resolve_plugin_root() == tmp_path.resolve()


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
        assert version_file.stat().st_mode & 0o777 == 0o600

    def test_creates_parent_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        devgear_dir = tmp_path / "nested" / ".devgear"
        version_file = devgear_dir / "plugin_installed_version"
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", devgear_dir)
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)

        session_install._write_installed_version("2.0.0")

        assert devgear_dir.exists()
        assert version_file.read_text() == "2.0.0\n"
        assert devgear_dir.stat().st_mode & 0o777 == 0o700


class TestRun:
    def _configure_plugin_root(self, monkeypatch: pytest.MonkeyPatch, plugin_root: Path) -> None:
        monkeypatch.setattr(session_install, "_PLUGIN_ROOT", plugin_root)

    def _setup_plugin_root(self, tmp_path: Path, version: str) -> Path:
        """plugin.json と install.sh を持つ偽プラグインルートを作成する。"""
        plugin_json = tmp_path / ".claude-plugin" / "plugin.json"
        plugin_json.parent.mkdir()
        plugin_json.write_text(json.dumps({"version": version}))
        install_sh = tmp_path / "install.sh"
        install_sh.write_text("#!/bin/bash\necho installed")
        return tmp_path

    def _assert_session_start_output(self, result: str) -> None:
        payload = json.loads(result)
        assert payload == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "",
            }
        }

    def test_skips_when_no_claude_plugin_root(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

        result = json.loads(session_install.run(""))

        assert result == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "",
            }
        }
        assert "CLAUDE_PLUGIN_ROOT" in capsys.readouterr().err

    def test_skips_when_plugin_json_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        monkeypatch.setattr(session_install, "_PLUGIN_ROOT", tmp_path)

        result = json.loads(session_install.run(""))

        assert result == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "",
            }
        }
        assert "不正なプラグインルート" in capsys.readouterr().err

    def test_skips_when_version_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.2")
        self._configure_plugin_root(monkeypatch, plugin_root)
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("0.0.2\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_LOCK_FILE", tmp_path / "install.lock")

        result = json.loads(session_install.run(""))

        assert result == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "",
            }
        }

    @pytest.mark.parametrize(
        ("current_version", "installed_version"),
        [
            ("0.0.2", "0.0.2\n"),
            ("1.2.3", "1.2.3\n"),
        ],
    )
    def test_version_matched_skips_install_table_driven(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        current_version: str,
        installed_version: str,
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, current_version)
        self._configure_plugin_root(monkeypatch, plugin_root)
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text(installed_version)
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_LOCK_FILE", tmp_path / "install.lock")

        monkeypatch.setattr(
            session_install,
            "run_text",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("install should not run")),
        )

        result = session_install.run("")
        self._assert_session_start_output(result)

    def test_lock_phase_recheck_skips_when_other_process_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.3")
        self._configure_plugin_root(monkeypatch, plugin_root)
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("0.0.2\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_LOCK_FILE", tmp_path / "install.lock")

        @contextmanager
        def fake_lock(_lock_file: Path):
            # precheck 後に別プロセスが install 済みにした状態を再現
            version_file.write_text("0.0.3\n")
            yield

        monkeypatch.setattr(session_install, "install_lock", fake_lock)
        monkeypatch.setattr(
            session_install,
            "run_text",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("install should not run")),
        )

        result = session_install.run("")
        self._assert_session_start_output(result)
        assert version_file.read_text() == "0.0.3\n"

    def test_runs_install_when_no_version_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.2")
        self._configure_plugin_root(monkeypatch, plugin_root)
        version_file = tmp_path / "plugin_installed_version"
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_LOCK_FILE", tmp_path / "install.lock")

        mock_result = subprocess.CompletedProcess(["bash", str(plugin_root / "install.sh")], 0, stdout="", stderr="")
        monkeypatch.setattr(session_install, "run_text", lambda *a, **kw: mock_result)

        result = json.loads(session_install.run(""))

        assert result == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "",
            }
        }
        assert version_file.read_text() == "0.0.2\n"
        assert version_file.stat().st_mode & 0o777 == 0o600
        assert tmp_path.stat().st_mode & 0o777 == 0o700

    def test_runs_install_when_version_changed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.3")
        self._configure_plugin_root(monkeypatch, plugin_root)
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("0.0.2\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_LOCK_FILE", tmp_path / "install.lock")

        mock_result = subprocess.CompletedProcess(
            ["bash", str(plugin_root / "install.sh")],
            0,
            stdout="install output",
            stderr="install stderr",
        )
        monkeypatch.setattr(session_install, "run_text", lambda *a, **kw: mock_result)

        result = json.loads(session_install.run(""))

        assert result == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "",
            }
        }
        assert version_file.read_text() == "0.0.3\n"

    def test_does_not_write_version_on_install_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.3")
        self._configure_plugin_root(monkeypatch, plugin_root)
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("0.0.2\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_LOCK_FILE", tmp_path / "install.lock")

        mock_result = subprocess.CompletedProcess(
            ["bash", str(plugin_root / "install.sh")],
            1,
            stdout="",
            stderr="install failed",
        )
        monkeypatch.setattr(session_install, "run_text", lambda *a, **kw: mock_result)

        result = json.loads(session_install.run(""))

        assert result == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "",
            }
        }
        assert version_file.read_text() == "0.0.2\n"
        assert "失敗" in capsys.readouterr().err

    def test_does_not_write_version_on_subprocess_exception(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.3")
        self._configure_plugin_root(monkeypatch, plugin_root)
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("0.0.2\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_LOCK_FILE", tmp_path / "install.lock")

        def raise_oserror(*_a: object, **_kw: object) -> subprocess.CompletedProcess[str]:
            raise OSError("install.sh not found")

        monkeypatch.setattr(session_install, "run_text", raise_oserror)

        result = json.loads(session_install.run(""))

        assert result == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "",
            }
        }
        assert version_file.read_text() == "0.0.2\n"
        assert "実行に失敗" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "run_text_behavior",
        [
            lambda _install_sh: subprocess.CompletedProcess(
                ["bash", str(_install_sh)],
                1,
                stdout="",
                stderr="install failed",
            ),
            lambda _install_sh: (_ for _ in ()).throw(OSError("install.sh not found")),
            lambda _install_sh: (_ for _ in ()).throw(subprocess.SubprocessError("exec error")),
        ],
    )
    def test_install_failures_do_not_write_version_table_driven(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        run_text_behavior,
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.3")
        self._configure_plugin_root(monkeypatch, plugin_root)
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("0.0.2\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_LOCK_FILE", tmp_path / "install.lock")
        monkeypatch.setattr(
            session_install,
            "run_text",
            lambda cmd, timeout: run_text_behavior(plugin_root / "install.sh"),
        )

        result = session_install.run("")

        self._assert_session_start_output(result)
        assert version_file.read_text() == "0.0.2\n"

    def test_install_stdout_stderr_routed_to_stderr(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.2")
        self._configure_plugin_root(monkeypatch, plugin_root)
        version_file = tmp_path / "plugin_installed_version"
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_LOCK_FILE", tmp_path / "install.lock")

        mock_result = subprocess.CompletedProcess(
            ["bash", str(plugin_root / "install.sh")],
            0,
            stdout="stdout from install",
            stderr="stderr from install",
        )
        monkeypatch.setattr(session_install, "run_text", lambda *a, **kw: mock_result)

        session_install.run("")

        captured = capsys.readouterr()
        assert "stdout from install" in captured.err
        assert "stderr from install" in captured.err

    def test_skips_install_when_install_sh_escapes_plugin_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        plugin_root = self._setup_plugin_root(tmp_path, "0.0.3")
        self._configure_plugin_root(monkeypatch, plugin_root)
        outside = tmp_path.parent / "outside.sh"
        outside.write_text("#!/bin/bash\necho outside", encoding="utf-8")
        (plugin_root / "install.sh").unlink()
        (plugin_root / "install.sh").symlink_to(outside)
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("0.0.2\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_LOCK_FILE", tmp_path / "install.lock")
        monkeypatch.setattr(session_install, "run_text", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not run")))

        result = json.loads(session_install.run(""))

        assert result == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "",
            }
        }
        assert "プラグインルート外" in capsys.readouterr().err


class TestShouldRepairVenvSymlink:
    def test_returns_false_when_shared_venv_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_install, "_VENV_DIR", tmp_path / "nonexistent")
        assert session_install._should_repair_venv_symlink(tmp_path) is False

    def test_returns_true_when_symlink_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        shared_venv = tmp_path / "shared_venv"
        shared_venv.mkdir()
        monkeypatch.setattr(session_install, "_VENV_DIR", shared_venv)
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        # .venv が存在しない
        assert session_install._should_repair_venv_symlink(plugin_root) is True

    def test_returns_false_when_correct_symlink_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        shared_venv = tmp_path / "shared_venv"
        shared_venv.mkdir()
        monkeypatch.setattr(session_install, "_VENV_DIR", shared_venv)
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        (plugin_root / ".venv").symlink_to(shared_venv, target_is_directory=True)
        assert session_install._should_repair_venv_symlink(plugin_root) is False

    def test_returns_true_when_symlink_points_elsewhere(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        shared_venv = tmp_path / "shared_venv"
        shared_venv.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        monkeypatch.setattr(session_install, "_VENV_DIR", shared_venv)
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        (plugin_root / ".venv").symlink_to(other, target_is_directory=True)
        assert session_install._should_repair_venv_symlink(plugin_root) is True

    def test_returns_true_when_real_directory_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        shared_venv = tmp_path / "shared_venv"
        shared_venv.mkdir()
        monkeypatch.setattr(session_install, "_VENV_DIR", shared_venv)
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        (plugin_root / ".venv").mkdir()  # 実体ディレクトリ
        assert session_install._should_repair_venv_symlink(plugin_root) is True


class TestRepairVenvSymlink:
    def test_creates_symlink_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        shared_venv = tmp_path / "shared_venv"
        shared_venv.mkdir()
        monkeypatch.setattr(session_install, "_VENV_DIR", shared_venv)
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()

        session_install._repair_venv_symlink(plugin_root)

        link = plugin_root / ".venv"
        assert link.is_symlink()
        assert link.resolve() == shared_venv.resolve()

    def test_replaces_broken_symlink(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        shared_venv = tmp_path / "shared_venv"
        shared_venv.mkdir()
        monkeypatch.setattr(session_install, "_VENV_DIR", shared_venv)
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        (plugin_root / ".venv").symlink_to(tmp_path / "nonexistent")  # 破損 symlink

        session_install._repair_venv_symlink(plugin_root)

        link = plugin_root / ".venv"
        assert link.is_symlink()
        assert link.resolve() == shared_venv.resolve()

    def test_does_not_touch_real_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        shared_venv = tmp_path / "shared_venv"
        shared_venv.mkdir()
        monkeypatch.setattr(session_install, "_VENV_DIR", shared_venv)
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        real_dir = plugin_root / ".venv"
        real_dir.mkdir()

        session_install._repair_venv_symlink(plugin_root)

        assert real_dir.is_dir() and not real_dir.is_symlink()
        assert "自動修復を中止" in capsys.readouterr().err


class TestRepairVenvSymlinkIntegration:
    """version 一致時の symlink 修復が run() を通じて動作することを確認する。"""

    def _setup_plugin_root(self, tmp_path: Path, version: str) -> Path:
        plugin_json = tmp_path / ".claude-plugin" / "plugin.json"
        plugin_json.parent.mkdir(parents=True)
        plugin_json.write_text(json.dumps({"version": version}))
        install_sh = tmp_path / "install.sh"
        install_sh.write_text("#!/bin/bash\necho installed")
        return tmp_path

    def test_run_repairs_missing_symlink_on_version_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shared_venv = tmp_path / "shared_venv"
        shared_venv.mkdir()
        plugin_root = self._setup_plugin_root(tmp_path / "plugin", "1.0.0")
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("1.0.0\n")

        monkeypatch.setattr(session_install, "_PLUGIN_ROOT", plugin_root)
        monkeypatch.setattr(session_install, "_VENV_DIR", shared_venv)
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_LOCK_FILE", tmp_path / "install.lock")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setattr(
            session_install,
            "run_text",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("install should not run")),
        )

        result = json.loads(session_install.run(""))

        assert result["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        link = plugin_root / ".venv"
        assert link.is_symlink()
        assert link.resolve() == shared_venv.resolve()

    def test_run_skips_repair_when_symlink_correct(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shared_venv = tmp_path / "shared_venv"
        shared_venv.mkdir()
        plugin_root = self._setup_plugin_root(tmp_path / "plugin", "1.0.0")
        (plugin_root / ".venv").symlink_to(shared_venv, target_is_directory=True)
        version_file = tmp_path / "plugin_installed_version"
        version_file.write_text("1.0.0\n")

        monkeypatch.setattr(session_install, "_PLUGIN_ROOT", plugin_root)
        monkeypatch.setattr(session_install, "_VENV_DIR", shared_venv)
        monkeypatch.setattr(session_install, "_VERSION_FILE", version_file)
        monkeypatch.setattr(session_install, "_DEVGEAR_DIR", tmp_path)
        monkeypatch.setattr(session_install, "_LOCK_FILE", tmp_path / "install.lock")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))

        mtime_before = (plugin_root / ".venv").lstat().st_mtime
        result = json.loads(session_install.run(""))

        assert result["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert (plugin_root / ".venv").lstat().st_mtime == mtime_before  # 変更されていない


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
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("devgear.hooks.session_install", run_name="__main__")

        assert exc_info.value.code == 0
