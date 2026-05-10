#!/usr/bin/env python3
"""
install.sh の自動実行を管理する SessionStart フック。

~/.devgear/plugin_installed_version のバージョンと plugin.json のバージョンを比較し、
差異がある場合のみ install.sh を実行して仮想環境を再構築する。
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

from devgear.hooks.hook_common import emit_session_start_output as _emit_session_start_output

_DEVGEAR_DIR = Path.home() / ".devgear"
_VERSION_FILE = _DEVGEAR_DIR / "plugin_installed_version"
_LOCK_FILE = _DEVGEAR_DIR / "install.lock"


def _session_start_output() -> str:
    """SessionStart 互換の hookSpecificOutput を返す。"""
    return _emit_session_start_output()


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
    except Exception as e:
        print(f"[SessionInstall] plugin.json の読み込みに失敗しました: {e}", file=sys.stderr)
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
    _DEVGEAR_DIR.mkdir(parents=True, exist_ok=True)
    _VERSION_FILE.write_text(version + "\n", encoding="utf-8")


def run(_raw_input: str) -> str:
    """install.sh の実行判定と実行を行い hookSpecificOutput の JSON を返す。

    Args:
        _raw_input: フックへの標準入力（未使用）。

    Returns:
        hookSpecificOutput を含む JSON 文字列。

    Raises:
        例外は発生しません。
    """
    plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root_env:
        print("[SessionInstall] CLAUDE_PLUGIN_ROOT が設定されていません。スキップします。", file=sys.stderr)
        return _session_start_output()

    plugin_root = Path(plugin_root_env)
    current_version = _get_plugin_version(plugin_root)

    if current_version is None:
        print("[SessionInstall] バージョンを取得できませんでした。スキップします。", file=sys.stderr)
        return _session_start_output()

    installed_version = _get_installed_version()

    if installed_version == current_version:
        print(f"[SessionInstall] 既にインストール済みです: {current_version}", file=sys.stderr)
        return _session_start_output()

    print(
        f"[SessionInstall] バージョン変更を検出しました: {installed_version!r} → {current_version!r}",
        file=sys.stderr,
    )

    install_sh = plugin_root / "install.sh"

    # 複数セッション同時起動時の .venv レース破壊を防ぐため flock で排他制御する。
    _DEVGEAR_DIR.mkdir(parents=True, exist_ok=True)
    try:
        lock_fp = open(_LOCK_FILE, "w")  # noqa: SIM115 - flock のため with 外で open
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX)
    except Exception as e:
        print(f"[SessionInstall] ロック取得失敗: {e}", file=sys.stderr)
        return _session_start_output()

    try:
        # ロック取得後に再チェック: 別プロセスが既に install 済みかもしれない
        if _get_installed_version() == current_version:
            print(f"[SessionInstall] 別プロセスがインストール済み: {current_version}", file=sys.stderr)
            return _session_start_output()

        try:
            result = subprocess.run(
                ["bash", str(install_sh)],
                text=True,
                capture_output=True,
            )
        except Exception as e:
            print(f"[SessionInstall] install.sh の実行に失敗しました: {e}", file=sys.stderr)
            return _session_start_output()

        if result.stdout:
            print(result.stdout, end="", file=sys.stderr)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)

        if result.returncode != 0:
            print(
                f"[SessionInstall] install.sh が失敗しました (exit {result.returncode})。次回再試行します。",
                file=sys.stderr,
            )
            return _session_start_output()

        _write_installed_version(current_version)
        print(f"[SessionInstall] インストール完了: {current_version}", file=sys.stderr)
        return _session_start_output()
    finally:
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)
        lock_fp.close()


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
        print(f"[SessionInstall] エラー: {err}", file=sys.stderr)
        print(_session_start_output(), end="")
        return 0


if __name__ == "__main__":
    sys.exit(main())
