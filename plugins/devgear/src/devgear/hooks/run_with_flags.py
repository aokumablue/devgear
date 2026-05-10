#!/usr/bin/env python3
"""フラグに応じてフックの有効・無効を切り替えるランチャーです。

フック設定を見て、必要な場合だけターゲットスクリプトを実行します。
追加引数はターゲットへそのまま渡します。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from devgear.hooks.hook_common import MAX_STDIN_BYTES, write_stderr, write_stdout
from devgear.lib.hook_flags import is_hook_enabled

REPO_ROOT = Path(__file__).resolve().parents[3]

# 入力切り捨て時に config-protection をバイパスさせないためのガード対象 hook id 集合。
# 設定ファイル保護は truncated payload を見逃すとバイパスに悪用されうるため、
# run_with_flags 側でブロックする。
_TRUNCATION_GUARD_HOOK_IDS = frozenset({"pre:config-protection"})
_SESSION_START_HOOK_IDS = frozenset(
    {
        "session:start",
        "session:mem:context",
        "session:mem:record-project-profile",
    }
)


def read_raw_stdin_with_truncation(max_bytes: int = MAX_STDIN_BYTES) -> tuple[str, bool]:
    """標準入力を読み取り、切り捨ての有無を返します。

    Args:
        max_bytes: 読み取る最大バイト数です。

    Returns:
        読み取った文字列と、切り捨てが発生したかどうかのタプルを返します。

    Raises:
        例外は発生しません。
    """
    raw_bytes = sys.stdin.buffer.read(max_bytes + 1)
    truncated = len(raw_bytes) > max_bytes
    if truncated:
        raw_bytes = raw_bytes[:max_bytes]
    return raw_bytes.decode("utf-8", errors="replace"), truncated


def build_env() -> dict[str, str]:
    """サブプロセス用の環境変数を構築します。

    Returns:
        実行用に調整した環境変数の辞書を返します。

    Raises:
        例外は発生しません。
    """
    env = os.environ.copy()
    env.setdefault("CLAUDE_PLUGIN_ROOT", str(REPO_ROOT))

    pythonpath = env.get("PYTHONPATH")
    paths = [str(REPO_ROOT / "src")]
    if pythonpath:
        paths.append(pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _truncation_blocked_message(hook_id: str, max_bytes: int) -> str:
    """入力切り捨て時のブロック理由メッセージを生成する。

    Args:
        hook_id: 対象フック ID。
        max_bytes: 入力の最大バイト数。

    Returns:
        stderr に書き出すメッセージ。

    Raises:
        例外は発生しません。
    """
    return (
        f"BLOCKED: Hook input exceeded {max_bytes} bytes for {hook_id}. "
        "Refusing to bypass protection on a truncated payload. "
        "Retry with a smaller edit."
    )


def _session_start_fallback_output() -> str:
    """SessionStart の最低限の JSON 出力を返す。"""
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "",
            }
        }
    )


def resolve_target_command(target: str, args: list[str] | None = None) -> list[str]:
    """ターゲット指定から実行コマンドを解決します。

    Args:
        target: ターゲットのパスまたはモジュール名です。
        args: ターゲットへ渡す追加引数です。

    Returns:
        subprocess に渡すコマンドリストを返します。

    Raises:
        例外は発生しません。
    """
    args = list(args or [])
    candidate = Path(target)
    if not candidate.is_absolute():
        plugin_root = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", str(REPO_ROOT))).resolve()
        candidate = candidate if candidate.exists() else plugin_root / candidate
        try:
            if candidate.resolve().is_relative_to(plugin_root):
                if candidate.exists():
                    suffix = candidate.suffix.lower()
                    if suffix == ".py":
                        return [sys.executable, str(candidate), *args]
                    if suffix in {".sh", ".bash"}:
                        return ["bash", str(candidate), *args]
                    if os.name == "nt" and suffix in {".cmd", ".bat"}:
                        return ["cmd", "/c", str(candidate), *args]
                    if os.access(candidate, os.X_OK):
                        return [str(candidate), *args]
        except OSError:
            pass
    elif candidate.exists():
        suffix = candidate.suffix.lower()
        if suffix == ".py":
            return [sys.executable, str(candidate), *args]
        if suffix in {".sh", ".bash"}:
            return ["bash", str(candidate), *args]
        if os.name == "nt" and suffix in {".cmd", ".bat"}:
            return ["cmd", "/c", str(candidate), *args]
        if os.access(candidate, os.X_OK):
            return [str(candidate), *args]

    return [sys.executable, "-m", target, *args]


def main() -> int:
    """フックランチャーのメイン処理を実行します。

    Returns:
        ターゲットの終了コード、またはエラー時の 1 を返します。

    Args:
        引数はありません。

    Raises:
        例外は発生しません。
    """
    if len(sys.argv) < 3:
        raw, _truncated = read_raw_stdin_with_truncation()
        write_stdout(raw)
        return 0

    hook_id = sys.argv[1]
    target = sys.argv[2]
    profiles_csv = sys.argv[3] if len(sys.argv) > 3 else None
    target_args = sys.argv[4:] if len(sys.argv) > 4 else []

    if not is_hook_enabled(hook_id, profiles=profiles_csv):
        write_stdout(sys.stdin.read())
        return 0

    raw, truncated = read_raw_stdin_with_truncation()

    # 切り捨てが発生した状態で保護系フックへ渡すとバイパスに悪用されうるため、
    # run_with_flags 側でブロックする（該当フックに限定）。
    if truncated and hook_id in _TRUNCATION_GUARD_HOOK_IDS:
        write_stderr(_truncation_blocked_message(hook_id, MAX_STDIN_BYTES) + "\n")
        return 2

    try:
        result = subprocess.run(
            resolve_target_command(target, target_args),
            input=raw,
            text=True,
            capture_output=True,
            env=build_env(),
        )
    except OSError as err:
        write_stderr(f"[Hook] Error running {hook_id}: {err}\n")
        write_stdout(raw)
        return 1

    if result.stdout:
        write_stdout(result.stdout)
    elif hook_id in _SESSION_START_HOOK_IDS:
        write_stdout(_session_start_fallback_output())
    else:
        write_stdout(raw)

    if result.stderr:
        write_stderr(result.stderr)

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
