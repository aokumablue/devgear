#!/usr/bin/env python3
"""
install.sh の自動実行を管理する SessionStart フック。

~/.devgear/plugin_installed_version のバージョンと plugin.json のバージョンを比較し、
差異がある場合のみ install.sh を実行して仮想環境を再構築する。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from devgear.hooks._install_lock import install_lock
from devgear.hooks.hook_common import emit_session_start_output as _emit_session_start_output
from devgear.lib.sanitize import sanitize_log_value
from devgear.lib.subprocess_utils import run_text

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_DEVGEAR_DIR = Path.home() / ".devgear"
_VERSION_FILE = _DEVGEAR_DIR / "plugin_installed_version"
_LOCK_FILE = _DEVGEAR_DIR / "install.lock"


def _session_start_output() -> str:
    """SessionStart 互換の hookSpecificOutput を返す。"""
    return _emit_session_start_output()


def _sanitize_exception(exc: BaseException) -> str:
    """例外メッセージをログ出力向けにサニタイズする。"""
    return sanitize_log_value(str(exc))


def _resolve_plugin_root() -> Path | None:
    """CLAUDE_PLUGIN_ROOT を検証してプラグインルートを返す。"""
    plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root_env:
        print("[SessionInstall] CLAUDE_PLUGIN_ROOT が設定されていません。スキップします。", file=sys.stderr)
        return None

    plugin_root = Path(plugin_root_env).resolve()
    if plugin_root != _PLUGIN_ROOT:
        print(
            f"[SessionInstall] 不正なプラグインルートです: {sanitize_log_value(plugin_root_env)}",
            file=sys.stderr,
        )
        return None

    plugin_json = plugin_root / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        print(
            f"[SessionInstall] 不正なプラグインルートです: {sanitize_log_value(plugin_root_env)}",
            file=sys.stderr,
        )
        return None
    return plugin_root


def _get_plugin_version(plugin_root: Path) -> str | None:
    """plugin.json からプラグインバージョンを読み取る。

    Args:
        plugin_root: プラグインルートディレクトリのパス。

    Returns:
        バージョン文字列。取得できない場合は None。

    Raises:
        例外は発生しません。
    """
    plugin_json = plugin_root / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(plugin_json.read_text(encoding="utf-8"))
        return data.get("version")
    except (json.JSONDecodeError, OSError, AttributeError, TypeError) as e:
        print(f"[SessionInstall] plugin.json の読み込みに失敗しました: {_sanitize_exception(e)}", file=sys.stderr)
        return None


def _get_installed_version() -> str | None:
    """~/.devgear/plugin_installed_version からインストール済みバージョンを読み取る。

    Args:
        引数はありません。

    Returns:
        インストール済みバージョン文字列。ファイルが存在しない場合は None。

    Raises:
        例外は発生しません。
    """
    if not _VERSION_FILE.exists():
        return None
    return _VERSION_FILE.read_text(encoding="utf-8").strip()


def _write_installed_version(version: str) -> None:
    """バージョンを ~/.devgear/plugin_installed_version に書き込む。

    Args:
        version: 書き込むバージョン文字列。

    Returns:
        None: 値を返しません。

    Raises:
        例外は発生しません。
    """
    _DEVGEAR_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(_DEVGEAR_DIR, 0o700)
    _VERSION_FILE.write_text(version + "\n", encoding="utf-8")
    os.chmod(_VERSION_FILE, 0o600)


def _precheck_install_target() -> tuple[Path, str] | None:
    """事前チェックを行い、install 実行対象を返す。"""
    plugin_root = _resolve_plugin_root()
    if plugin_root is None:
        return None

    current_version = _get_plugin_version(plugin_root)
    if current_version is None:
        print("[SessionInstall] バージョンを取得できませんでした。スキップします。", file=sys.stderr)
        return None

    installed_version = _get_installed_version()
    if installed_version == current_version:
        print(f"[SessionInstall] 既にインストール済みです: {sanitize_log_value(current_version)}", file=sys.stderr)
        return None

    print(
        "[SessionInstall] バージョン変更を検出しました: "
        f"{sanitize_log_value(repr(installed_version))} → {sanitize_log_value(repr(current_version))}",
        file=sys.stderr,
    )

    install_sh = (plugin_root / "install.sh").resolve()
    if not install_sh.is_file() or not install_sh.is_relative_to(plugin_root):
        print("[SessionInstall] install.sh がプラグインルート外です。スキップします。", file=sys.stderr)
        return None

    return install_sh, current_version


def _lock_phase_should_skip(current_version: str) -> bool:
    """ロック取得後の再チェックを行い、処理スキップ要否を返す。"""
    try:
        installed_version = _get_installed_version()
    except OSError as e:
        print(
            f"[SessionInstall] インストール済みバージョンの読み込みに失敗しました: {_sanitize_exception(e)}",
            file=sys.stderr,
        )
        return True

    if installed_version == current_version:
        print(f"[SessionInstall] 別プロセスがインストール済み: {sanitize_log_value(current_version)}", file=sys.stderr)
        return True

    return False


def _run_install(install_sh: Path) -> subprocess.CompletedProcess[str] | None:
    """install.sh を実行し、失敗時はログを出して None を返す。"""
    try:
        return run_text(["bash", str(install_sh)], timeout=1800)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[SessionInstall] install.sh の実行に失敗しました: {_sanitize_exception(e)}", file=sys.stderr)
        return None


def _handle_install_result(result: subprocess.CompletedProcess[str], current_version: str) -> None:
    """install 実行結果を出力し、成功時のみバージョンを書き戻す。"""
    if result.stdout:
        print(sanitize_log_value(result.stdout, max_len=4000), file=sys.stderr)
    if result.stderr:
        print(sanitize_log_value(result.stderr, max_len=4000), file=sys.stderr)

    if result.returncode != 0:
        print(
            f"[SessionInstall] install.sh が失敗しました (exit {result.returncode})。次回再試行します。",
            file=sys.stderr,
        )
        return

    try:
        _write_installed_version(current_version)
    except OSError as e:
        print(
            f"[SessionInstall] インストール済みバージョンの保存に失敗しました: {_sanitize_exception(e)}",
            file=sys.stderr,
        )
        return

    print(f"[SessionInstall] インストール完了: {sanitize_log_value(current_version)}", file=sys.stderr)


def run(_raw_input: str) -> str:
    """install.sh の実行判定と実行を行い hookSpecificOutput の JSON を返す。

    Args:
        _raw_input: フックへの標準入力（未使用）。

    Returns:
        hookSpecificOutput を含む JSON 文字列。

    Raises:
        例外は発生しません。
    """
    prechecked = _precheck_install_target()
    if prechecked is None:
        return _session_start_output()

    install_sh, current_version = prechecked

    # 複数セッション同時起動時の .venv レース破壊を防ぐため flock で排他制御する。
    _DEVGEAR_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(_DEVGEAR_DIR, 0o700)

    try:
        with install_lock(_LOCK_FILE):
            if _lock_phase_should_skip(current_version):
                return _session_start_output()

            result = _run_install(install_sh)
            if result is None:
                return _session_start_output()

            _handle_install_result(result, current_version)
            return _session_start_output()
    except OSError as e:
        print(f"[SessionInstall] ロック取得失敗: {_sanitize_exception(e)}", file=sys.stderr)
        return _session_start_output()


def main() -> int:
    """スクリプトとして実行されたときのエントリポイント。

    Args:
        引数はありません。

    Returns:
        終了コード（常に 0 — 失敗してもセッションをブロックしない）。

    Raises:
        例外は発生しません。
    """
    try:
        raw = "" if sys.stdin.isatty() else sys.stdin.read()
        output = run(raw)
        print(output, end="")
        return 0
    except Exception as err:
        print(f"[SessionInstall] エラー: {_sanitize_exception(err)}", file=sys.stderr)
        print(_session_start_output(), end="")
        return 0


if __name__ == "__main__":
    sys.exit(main())
